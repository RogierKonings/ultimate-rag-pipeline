//! HTTP client for the embedding service.
//!
//! This module provides an async HTTP client that communicates with
//! an OpenAI-compatible embedding service to generate vector embeddings.

use std::time::Duration;

use futures::future::join_all;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tracing::{debug, instrument, warn};

use super::EmbeddingConfig;
use crate::error::{RetrievalError, Result};

/// Request body for the OpenAI-compatible embeddings API.
#[derive(Debug, Serialize)]
struct EmbeddingRequest {
    /// Input texts to embed.
    input: Vec<String>,
    /// Model identifier.
    model: String,
}

/// Response from the OpenAI-compatible embeddings API.
#[derive(Debug, Deserialize)]
struct EmbeddingResponse {
    /// Embedding data for each input.
    data: Vec<EmbeddingData>,
    /// Model used for generation.
    #[allow(dead_code)]
    model: String,
    /// Token usage statistics.
    #[allow(dead_code)]
    usage: Usage,
}

/// Individual embedding data from the API response.
#[derive(Debug, Deserialize)]
struct EmbeddingData {
    /// The embedding vector.
    embedding: Vec<f32>,
    /// Index of the input text this embedding corresponds to.
    index: usize,
}

/// Token usage statistics from the API response.
#[derive(Debug, Deserialize)]
struct Usage {
    /// Number of tokens in the input prompts.
    #[allow(dead_code)]
    prompt_tokens: usize,
    /// Total tokens used.
    #[allow(dead_code)]
    total_tokens: usize,
}

/// HTTP client for generating embeddings via the embedding service.
///
/// The client supports:
/// - Single text embedding
/// - Batch text embedding with automatic batching
/// - Query embedding with optional instruction prefix
/// - Retry logic with exponential backoff
///
/// # Example
///
/// ```no_run
/// use rag_retrieval::embedding::{EmbeddingClient, EmbeddingConfig};
///
/// #[tokio::main]
/// async fn main() -> Result<(), Box<dyn std::error::Error>> {
///     let config = EmbeddingConfig::default();
///     let client = EmbeddingClient::new(config)?;
///
///     // Embed a query
///     let embedding = client.embed_query("What is machine learning?").await?;
///     println!("Query embedding: {} dimensions", embedding.len());
///
///     Ok(())
/// }
/// ```
#[derive(Debug, Clone)]
pub struct EmbeddingClient {
    /// HTTP client for making requests.
    client: Client,
    /// Configuration for the embedding service.
    config: EmbeddingConfig,
}

impl EmbeddingClient {
    /// Create a new embedding client with the given configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the HTTP client cannot be created.
    pub fn new(config: EmbeddingConfig) -> Result<Self> {
        let client = Client::builder()
            .timeout(config.timeout())
            .build()
            .map_err(|e| RetrievalError::config(format!("Failed to create HTTP client: {e}")))?;

        Ok(Self { client, config })
    }

    /// Create a new embedding client from environment variables.
    ///
    /// # Errors
    ///
    /// Returns an error if the HTTP client cannot be created.
    pub fn from_env() -> Result<Self> {
        Self::new(EmbeddingConfig::from_env())
    }

    /// Get the configuration.
    #[must_use]
    pub const fn config(&self) -> &EmbeddingConfig {
        &self.config
    }

    /// Embed a single text.
    ///
    /// # Arguments
    ///
    /// * `text` - The text to embed
    ///
    /// # Errors
    ///
    /// Returns an error if the embedding request fails.
    #[instrument(skip(self, text), fields(text_len = text.len()))]
    pub async fn embed_text(&self, text: &str) -> Result<Vec<f32>> {
        let texts = vec![text.to_string()];
        let mut embeddings = self.embed_texts(&texts).await?;

        embeddings.pop().ok_or_else(|| {
            RetrievalError::embedding("No embedding returned for single text")
        })
    }

    /// Embed multiple texts.
    ///
    /// Texts are automatically batched according to the configured batch size.
    /// Multiple batches are processed in parallel.
    ///
    /// # Arguments
    ///
    /// * `texts` - The texts to embed
    ///
    /// # Errors
    ///
    /// Returns an error if any embedding request fails.
    #[instrument(skip(self, texts), fields(num_texts = texts.len()))]
    pub async fn embed_texts(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }

        // Split into batches
        let batches: Vec<Vec<String>> = texts
            .chunks(self.config.batch_size)
            .map(<[String]>::to_vec)
            .collect();

        debug!(
            num_batches = batches.len(),
            batch_size = self.config.batch_size,
            "Processing embedding batches"
        );

        // Process batches in parallel
        let batch_results: Vec<Result<Vec<Vec<f32>>>> = join_all(
            batches
                .iter()
                .map(|batch| self.embed_batch(batch))
        )
        .await;

        // Collect results, preserving order
        let mut all_embeddings = Vec::with_capacity(texts.len());
        for result in batch_results {
            let batch_embeddings = result?;
            all_embeddings.extend(batch_embeddings);
        }

        Ok(all_embeddings)
    }

    /// Embed a query with optional instruction prefix.
    ///
    /// If an instruction prefix is configured (e.g., for BGE models),
    /// it will be prepended to the query.
    ///
    /// # Arguments
    ///
    /// * `query` - The query text to embed
    ///
    /// # Errors
    ///
    /// Returns an error if the embedding request fails.
    #[instrument(skip(self, query), fields(query_len = query.len()))]
    pub async fn embed_query(&self, query: &str) -> Result<Vec<f32>> {
        let text = self
            .config
            .instruction_prefix
            .as_ref()
            .map_or_else(|| query.to_string(), |prefix| format!("{prefix}{query}"));

        self.embed_text(&text).await
    }

    /// Embed a batch of texts (internal method).
    async fn embed_batch(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        let mut last_error = None;
        let mut attempt = 0;

        while attempt <= self.config.max_retries {
            match self.make_request(texts).await {
                Ok(response) => {
                    return self.process_response(response, texts.len());
                }
                Err(e) => {
                    last_error = Some(e);
                    attempt += 1;

                    if attempt <= self.config.max_retries {
                        let backoff = calculate_backoff(attempt);
                        warn!(
                            attempt,
                            max_retries = self.config.max_retries,
                            backoff_ms = backoff.as_millis(),
                            "Embedding request failed, retrying"
                        );
                        tokio::time::sleep(backoff).await;
                    }
                }
            }
        }

        Err(last_error.unwrap_or_else(|| {
            RetrievalError::embedding("Embedding request failed with no error")
        }))
    }

    /// Make a single embedding request.
    async fn make_request(&self, texts: &[String]) -> Result<EmbeddingResponse> {
        let request = EmbeddingRequest {
            input: texts.to_vec(),
            model: self.config.model.clone(),
        };

        let response = self
            .client
            .post(self.config.embeddings_endpoint())
            .json(&request)
            .send()
            .await
            .map_err(|e| {
                if e.is_timeout() {
                    RetrievalError::timeout(format!(
                        "Embedding request timed out after {}ms",
                        self.config.timeout_ms
                    ))
                } else if e.is_connect() {
                    RetrievalError::embedding(format!(
                        "Failed to connect to embedding service at {}: {e}",
                        self.config.url
                    ))
                } else {
                    RetrievalError::embedding(format!("Embedding request failed: {e}"))
                }
            })?;

        let status = response.status();
        if !status.is_success() {
            let error_text = response.text().await.unwrap_or_else(|_| "Unknown error".to_string());
            return Err(RetrievalError::embedding(format!(
                "Embedding service returned {status}: {error_text}"
            )));
        }

        response.json::<EmbeddingResponse>().await.map_err(|e| {
            RetrievalError::embedding(format!("Failed to parse embedding response: {e}"))
        })
    }

    /// Process the embedding response, sorting by index.
    fn process_response(
        &self,
        response: EmbeddingResponse,
        expected_count: usize,
    ) -> Result<Vec<Vec<f32>>> {
        if response.data.len() != expected_count {
            return Err(RetrievalError::embedding(format!(
                "Expected {expected_count} embeddings, got {}",
                response.data.len()
            )));
        }

        // Sort by index to maintain input order
        let mut data = response.data;
        data.sort_by_key(|d| d.index);

        // Validate dimensions
        for (i, embedding_data) in data.iter().enumerate() {
            if embedding_data.embedding.len() != self.config.dimensions {
                return Err(RetrievalError::embedding(format!(
                    "Embedding {} has {} dimensions, expected {}",
                    i,
                    embedding_data.embedding.len(),
                    self.config.dimensions
                )));
            }
        }

        Ok(data.into_iter().map(|d| d.embedding).collect())
    }
}

/// Calculate exponential backoff with jitter.
///
/// Uses the formula: `min(base_ms * 2^attempt, max_ms)` with +/- 25% jitter
#[allow(
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss,
    clippy::cast_possible_wrap
)]
fn calculate_backoff(attempt: u32) -> Duration {
    const BASE_MS: u64 = 100;
    const MAX_MS: u64 = 5000;

    let base_backoff = BASE_MS.saturating_mul(1 << attempt.min(10));
    let capped_backoff = base_backoff.min(MAX_MS);

    // Add +/- 25% jitter
    let jitter_range = capped_backoff / 4;
    let jitter = if jitter_range > 0 {
        // Simple pseudo-random jitter based on attempt and time
        let seed = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_nanos() as u64);
        (seed % (jitter_range * 2)) as i64 - jitter_range as i64
    } else {
        0
    };

    let final_ms = (capped_backoff as i64 + jitter).max(BASE_MS as i64) as u64;
    Duration::from_millis(final_ms)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_client_creation() {
        let config = EmbeddingConfig::default();
        let client = EmbeddingClient::new(config);
        assert!(client.is_ok());
    }

    #[test]
    fn test_client_config() {
        let config = EmbeddingConfig::new()
            .with_url("http://test:8080")
            .with_model("test-model");
        let client = EmbeddingClient::new(config).unwrap();

        assert_eq!(client.config().url, "http://test:8080");
        assert_eq!(client.config().model, "test-model");
    }

    #[test]
    fn test_backoff_calculation() {
        // First retry: ~200ms (100 * 2^1)
        let backoff1 = calculate_backoff(1);
        assert!(backoff1.as_millis() >= 100);
        assert!(backoff1.as_millis() <= 300);

        // Second retry: ~400ms (100 * 2^2)
        let backoff2 = calculate_backoff(2);
        assert!(backoff2.as_millis() >= 200);
        assert!(backoff2.as_millis() <= 600);

        // Should cap at MAX_MS
        let backoff_high = calculate_backoff(20);
        assert!(backoff_high.as_millis() <= 6250); // MAX_MS + 25% jitter
    }

    #[test]
    fn test_process_response_success() {
        let config = EmbeddingConfig::new().with_dimensions(3);
        let client = EmbeddingClient::new(config).unwrap();

        let response = EmbeddingResponse {
            data: vec![
                EmbeddingData {
                    embedding: vec![0.1, 0.2, 0.3],
                    index: 1,
                },
                EmbeddingData {
                    embedding: vec![0.4, 0.5, 0.6],
                    index: 0,
                },
            ],
            model: "test".to_string(),
            usage: Usage {
                prompt_tokens: 10,
                total_tokens: 10,
            },
        };

        let result = client.process_response(response, 2).unwrap();

        // Should be sorted by index
        assert_eq!(result.len(), 2);
        assert_eq!(result[0], vec![0.4, 0.5, 0.6]);
        assert_eq!(result[1], vec![0.1, 0.2, 0.3]);
    }

    #[test]
    fn test_process_response_wrong_count() {
        let config = EmbeddingConfig::new().with_dimensions(3);
        let client = EmbeddingClient::new(config).unwrap();

        let response = EmbeddingResponse {
            data: vec![EmbeddingData {
                embedding: vec![0.1, 0.2, 0.3],
                index: 0,
            }],
            model: "test".to_string(),
            usage: Usage {
                prompt_tokens: 10,
                total_tokens: 10,
            },
        };

        let result = client.process_response(response, 2);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Expected 2"));
    }

    #[test]
    fn test_process_response_wrong_dimensions() {
        let config = EmbeddingConfig::new().with_dimensions(5);
        let client = EmbeddingClient::new(config).unwrap();

        let response = EmbeddingResponse {
            data: vec![EmbeddingData {
                embedding: vec![0.1, 0.2, 0.3],
                index: 0,
            }],
            model: "test".to_string(),
            usage: Usage {
                prompt_tokens: 10,
                total_tokens: 10,
            },
        };

        let result = client.process_response(response, 1);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("dimensions"));
    }

    #[tokio::test]
    async fn test_embed_texts_empty() {
        let config = EmbeddingConfig::default();
        let client = EmbeddingClient::new(config).unwrap();

        let result = client.embed_texts(&[]).await.unwrap();
        assert!(result.is_empty());
    }

    #[test]
    fn test_embedding_request_serialization() {
        let request = EmbeddingRequest {
            input: vec!["hello".to_string(), "world".to_string()],
            model: "test-model".to_string(),
        };

        let json = serde_json::to_string(&request).unwrap();
        assert!(json.contains("\"input\""));
        assert!(json.contains("\"model\""));
        assert!(json.contains("hello"));
        assert!(json.contains("world"));
    }
}

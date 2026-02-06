//! HTTP client for embedding service.
//!
//! This module provides an HTTP client that communicates with the embedding
//! service using the OpenAI-compatible API format.

use super::config::EmbeddingClientConfig;
use crate::error::{Error, Result};
use rag_config::{build_http_client_with_timeout, RetryPolicy};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tracing::instrument;

/// Response from the embedding service.
#[derive(Debug, Deserialize)]
struct EmbeddingResponse {
    data: Vec<EmbeddingData>,
    usage: Option<Usage>,
}

/// Individual embedding data in the response.
#[derive(Debug, Deserialize)]
struct EmbeddingData {
    embedding: Vec<f32>,
    index: usize,
}

/// Token usage information.
#[derive(Debug, Deserialize)]
struct Usage {
    total_tokens: u32,
}

/// Request to the embedding service.
#[derive(Debug, Serialize)]
struct EmbeddingRequest<'a> {
    input: &'a [String],
    model: &'a str,
}

/// HTTP client for the embedding service.
///
/// This client communicates with an OpenAI-compatible embedding API
/// and includes retry logic with exponential backoff.
pub struct EmbeddingClient {
    client: Client,
    config: EmbeddingClientConfig,
}

impl EmbeddingClient {
    /// Create a new embedding client with the given configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the HTTP client fails to build.
    pub fn new(config: EmbeddingClientConfig) -> Result<Self> {
        let client = build_http_client_with_timeout(config.timeout())
            .map_err(Error::Embedding)?;

        Ok(Self { client, config })
    }

    /// Embed a batch of texts.
    ///
    /// Returns a tuple of (embeddings, token_count).
    ///
    /// # Arguments
    ///
    /// * `texts` - The texts to embed.
    ///
    /// # Errors
    ///
    /// Returns an error if the embedding request fails after all retries.
    #[instrument(skip(self, texts), fields(batch_size = texts.len()))]
    pub async fn embed_batch(&self, texts: &[String]) -> Result<(Vec<Vec<f32>>, u32)> {
        if texts.is_empty() {
            return Ok((vec![], 0));
        }

        let retry_policy = RetryPolicy::new(
            self.config.max_retries,
            self.config.retry_delay().as_millis() as u64,
            30_000,
        );

        retry_policy
            .execute(
                || self.send_request(texts),
                |e: &Error| Self::is_retryable(e),
            )
            .await
    }

    /// Send the actual HTTP request to the embedding service.
    async fn send_request(&self, texts: &[String]) -> Result<(Vec<Vec<f32>>, u32)> {
        let request = EmbeddingRequest {
            input: texts,
            model: &self.config.model,
        };

        let response = self
            .client
            .post(self.config.embeddings_url())
            .json(&request)
            .send()
            .await?;

        let status = response.status();
        if !status.is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(Error::Embedding(format!(
                "Embedding service returned {status}: {body}"
            )));
        }

        let response: EmbeddingResponse = response.json().await?;

        // Sort by index to ensure correct order
        let mut embeddings: Vec<_> = response.data.into_iter().collect();
        embeddings.sort_by_key(|e| e.index);

        let embeddings = embeddings.into_iter().map(|e| e.embedding).collect();
        let token_count = response.usage.map_or(0, |u| u.total_tokens);

        Ok((embeddings, token_count))
    }

    /// Check if an error is retryable.
    fn is_retryable(error: &Error) -> bool {
        match error {
            Error::Http(e) => {
                e.is_timeout() || e.is_connect() || e.status().is_some_and(|s| s.is_server_error())
            }
            Error::Embedding(msg) => {
                // Check for 5xx status codes in error message
                msg.contains("500")
                    || msg.contains("501")
                    || msg.contains("502")
                    || msg.contains("503")
                    || msg.contains("504")
                    || msg.contains("505")
                    || msg.contains("506")
                    || msg.contains("507")
                    || msg.contains("508")
                    || msg.contains("509")
                    || msg.contains("510")
                    || msg.contains("511")
            }
            _ => false,
        }
    }

    /// Perform a health check by embedding a simple text.
    ///
    /// Returns `true` if the embedding service is healthy, `false` otherwise.
    ///
    /// # Errors
    ///
    /// This method does not return errors; failures are mapped to `false`.
    pub async fn health_check(&self) -> Result<bool> {
        match self.embed_batch(&["health check".to_string()]).await {
            Ok(_) => Ok(true),
            Err(_) => Ok(false),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    async fn setup_mock_server() -> MockServer {
        MockServer::start().await
    }

    #[tokio::test]
    async fn test_embed_batch_success() {
        let mock_server = setup_mock_server().await;

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "data": [
                    {"embedding": [0.1, 0.2, 0.3], "index": 0},
                    {"embedding": [0.4, 0.5, 0.6], "index": 1}
                ],
                "usage": {"total_tokens": 10}
            })))
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(&mock_server.uri());
        let client = EmbeddingClient::new(config).unwrap();

        let texts = vec!["hello".to_string(), "world".to_string()];
        let (embeddings, tokens) = client.embed_batch(&texts).await.unwrap();

        assert_eq!(embeddings.len(), 2);
        assert_eq!(embeddings[0], vec![0.1, 0.2, 0.3]);
        assert_eq!(embeddings[1], vec![0.4, 0.5, 0.6]);
        assert_eq!(tokens, 10);
    }

    #[tokio::test]
    async fn test_embed_batch_empty() {
        let config = EmbeddingClientConfig::new("http://localhost:9999");
        let client = EmbeddingClient::new(config).unwrap();

        let (embeddings, tokens) = client.embed_batch(&[]).await.unwrap();
        assert!(embeddings.is_empty());
        assert_eq!(tokens, 0);
    }

    #[tokio::test]
    async fn test_embed_batch_server_error_retries() {
        let mock_server = setup_mock_server().await;

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(500).set_body_string("Internal Server Error"))
            .expect(2) // Should retry once (initial + 1 retry with max_retries=1)
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(&mock_server.uri())
            .with_max_retries(1)
            .with_retry_delay_ms(10); // Fast for tests
        let client = EmbeddingClient::new(config).unwrap();

        let result = client.embed_batch(&["test".to_string()]).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_embed_batch_client_error_no_retry() {
        let mock_server = setup_mock_server().await;

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(400).set_body_string("Bad Request"))
            .expect(1) // Should NOT retry on 4xx
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(&mock_server.uri()).with_max_retries(3);
        let client = EmbeddingClient::new(config).unwrap();

        let result = client.embed_batch(&["test".to_string()]).await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_embed_batch_reorders_by_index() {
        let mock_server = setup_mock_server().await;

        // Return embeddings out of order
        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "data": [
                    {"embedding": [0.4, 0.5, 0.6], "index": 1},
                    {"embedding": [0.7, 0.8, 0.9], "index": 2},
                    {"embedding": [0.1, 0.2, 0.3], "index": 0}
                ],
                "usage": {"total_tokens": 15}
            })))
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(&mock_server.uri());
        let client = EmbeddingClient::new(config).unwrap();

        let texts = vec!["a".to_string(), "b".to_string(), "c".to_string()];
        let (embeddings, tokens) = client.embed_batch(&texts).await.unwrap();

        assert_eq!(embeddings.len(), 3);
        // Should be sorted by index
        assert_eq!(embeddings[0], vec![0.1, 0.2, 0.3]);
        assert_eq!(embeddings[1], vec![0.4, 0.5, 0.6]);
        assert_eq!(embeddings[2], vec![0.7, 0.8, 0.9]);
        assert_eq!(tokens, 15);
    }

    #[tokio::test]
    async fn test_embed_batch_no_usage() {
        let mock_server = setup_mock_server().await;

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "data": [
                    {"embedding": [0.1, 0.2, 0.3], "index": 0}
                ]
            })))
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(&mock_server.uri());
        let client = EmbeddingClient::new(config).unwrap();

        let texts = vec!["hello".to_string()];
        let (embeddings, tokens) = client.embed_batch(&texts).await.unwrap();

        assert_eq!(embeddings.len(), 1);
        assert_eq!(tokens, 0); // No usage provided, defaults to 0
    }

    #[tokio::test]
    async fn test_health_check_success() {
        let mock_server = setup_mock_server().await;

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({
                "data": [
                    {"embedding": [0.1, 0.2, 0.3], "index": 0}
                ]
            })))
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(&mock_server.uri());
        let client = EmbeddingClient::new(config).unwrap();

        let healthy = client.health_check().await.unwrap();
        assert!(healthy);
    }

    #[tokio::test]
    async fn test_health_check_failure() {
        let mock_server = setup_mock_server().await;

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(500).set_body_string("Server Error"))
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(&mock_server.uri()).with_max_retries(0); // No retries for faster test
        let client = EmbeddingClient::new(config).unwrap();

        let healthy = client.health_check().await.unwrap();
        assert!(!healthy);
    }

    #[test]
    fn test_is_retryable_server_errors() {
        // Embedding error with 500 status
        let err =
            Error::Embedding("Embedding service returned 500 Internal Server Error".to_string());
        assert!(EmbeddingClient::is_retryable(&err));

        // Embedding error with 502 status
        let err = Error::Embedding("Embedding service returned 502 Bad Gateway".to_string());
        assert!(EmbeddingClient::is_retryable(&err));

        // Embedding error with 400 status (not retryable)
        let err = Error::Embedding("Embedding service returned 400 Bad Request".to_string());
        assert!(!EmbeddingClient::is_retryable(&err));
    }
}

//! HTTP client for the reranker service.
//!
//! This module provides an async HTTP client that communicates with
//! the LLM Gateway's rerank endpoint to perform cross-encoder reranking.

use std::time::Instant;

use rag_config::build_http_client_with_timeout;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tracing::{debug, instrument};
use uuid::Uuid;

use super::RerankerConfig;
use crate::error::{Result, RetrievalError};

/// Request body for the Cohere-compatible rerank API.
#[derive(Debug, Serialize)]
struct RerankRequest {
    /// Model identifier.
    model: String,
    /// Search query.
    query: String,
    /// Documents to rerank.
    documents: Vec<String>,
    /// Whether to return document text in response.
    return_documents: bool,
}

/// Response from the rerank API.
#[derive(Debug, Deserialize)]
struct ApiRerankResponse {
    /// Reranked results.
    results: Vec<ApiRerankResult>,
}

/// Individual result from the rerank API.
#[derive(Debug, Deserialize)]
struct ApiRerankResult {
    /// Index of the document in the original input.
    index: usize,
    /// Relevance score from the cross-encoder.
    relevance_score: f32,
    /// Document text (if `return_documents` was true).
    /// Not currently used but included for API compatibility.
    #[serde(default)]
    #[allow(dead_code)]
    document: Option<ApiDocumentResult>,
}

/// Document text wrapper in the API response.
#[derive(Debug, Deserialize)]
#[allow(dead_code)]
struct ApiDocumentResult {
    /// The document text.
    text: String,
}

/// Single reranked result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RerankResult {
    /// ID of the document.
    pub document_id: Uuid,
    /// Original index in the input list.
    pub index: usize,
    /// Relevance score from cross-encoder (higher is more relevant).
    pub relevance_score: f32,
    /// Document text (if `return_documents` was true).
    pub document: Option<String>,
}

/// Response from reranking operation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RerankResponse {
    /// Reranked results sorted by relevance score descending.
    pub results: Vec<RerankResult>,
    /// Model used for reranking.
    pub model: String,
    /// Processing time in milliseconds.
    pub processing_time_ms: u64,
}

/// HTTP client for cross-encoder reranking via the LLM Gateway.
///
/// The client supports:
/// - Batch processing for large document sets
/// - Retry logic with exponential backoff
/// - Query and document truncation for token limits
/// - Score threshold filtering
///
/// # Example
///
/// ```no_run
/// use rag_retrieval::reranking::{RerankerClient, RerankerConfig};
/// use uuid::Uuid;
///
/// #[tokio::main]
/// async fn main() -> Result<(), Box<dyn std::error::Error>> {
///     let config = RerankerConfig::default();
///     let client = RerankerClient::new(config)?;
///
///     let query = "What is machine learning?";
///     let documents = vec!["ML is AI subset.".to_string()];
///     let ids = vec![Uuid::new_v4()];
///
///     let response = client.rerank(query, &documents, &ids).await?;
///     println!("Top result score: {}", response.results[0].relevance_score);
///
///     Ok(())
/// }
/// ```
#[derive(Debug, Clone)]
pub struct RerankerClient {
    /// HTTP client for making requests.
    client: Client,
    /// Configuration for the reranker service.
    config: RerankerConfig,
}

impl RerankerClient {
    /// Create a new reranker client with the given configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the HTTP client cannot be created.
    pub fn new(config: RerankerConfig) -> Result<Self> {
        let client =
            build_http_client_with_timeout(config.timeout()).map_err(RetrievalError::config)?;

        Ok(Self { client, config })
    }

    /// Create a new reranker client from environment variables.
    ///
    /// # Errors
    ///
    /// Returns an error if the HTTP client cannot be created.
    pub fn from_env() -> Result<Self> {
        Self::new(RerankerConfig::from_env())
    }

    /// Get the configuration.
    #[must_use]
    pub const fn config(&self) -> &RerankerConfig {
        &self.config
    }

    /// Rerank documents by relevance to a query.
    ///
    /// This is a convenience method that calls `rerank_with_options` with
    /// default options (no `top_k` limit, no document text in response).
    ///
    /// # Arguments
    ///
    /// * `query` - The search query
    /// * `documents` - Document texts to rerank
    /// * `document_ids` - Corresponding document IDs (must match documents length)
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - `documents` and `document_ids` have different lengths
    /// - Too many documents are provided
    /// - The rerank request fails after retries
    #[instrument(skip(self, query, documents, document_ids), fields(
        query_len = query.len(),
        num_documents = documents.len()
    ))]
    pub async fn rerank(
        &self,
        query: &str,
        documents: &[String],
        document_ids: &[Uuid],
    ) -> Result<RerankResponse> {
        self.rerank_with_options(query, documents, document_ids, None, false)
            .await
    }

    /// Rerank documents with options.
    ///
    /// # Arguments
    ///
    /// * `query` - The search query
    /// * `documents` - Document texts to rerank
    /// * `document_ids` - Corresponding document IDs (must match documents length)
    /// * `top_k` - Optional limit on number of results to return
    /// * `return_documents` - Whether to include document text in results
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - `documents` and `document_ids` have different lengths
    /// - Too many documents are provided
    /// - The rerank request fails after retries
    #[instrument(skip(self, query, documents, document_ids), fields(
        query_len = query.len(),
        num_documents = documents.len(),
        top_k = ?top_k,
        return_documents = return_documents
    ))]
    pub async fn rerank_with_options(
        &self,
        query: &str,
        documents: &[String],
        document_ids: &[Uuid],
        top_k: Option<usize>,
        return_documents: bool,
    ) -> Result<RerankResponse> {
        let start_time = Instant::now();

        // Validation
        if documents.len() != document_ids.len() {
            return Err(RetrievalError::invalid_request(format!(
                "documents and document_ids must have same length: {} vs {}",
                documents.len(),
                document_ids.len()
            )));
        }

        if documents.len() > self.config.max_documents {
            return Err(RetrievalError::invalid_request(format!(
                "Too many documents: {} > {}",
                documents.len(),
                self.config.max_documents
            )));
        }

        // Empty input
        if documents.is_empty() {
            return Ok(RerankResponse {
                results: Vec::new(),
                model: self.config.model.clone(),
                processing_time_ms: 0,
            });
        }

        // Truncate query and documents
        let truncated_query = truncate(query, self.config.max_query_chars());
        let truncated_docs: Vec<String> = documents
            .iter()
            .map(|doc| truncate(doc, self.config.max_document_chars()))
            .collect();

        // Process in batches if needed
        let mut all_scores: Vec<f32> = Vec::with_capacity(documents.len());

        for batch_start in (0..truncated_docs.len()).step_by(self.config.max_batch_size) {
            let batch_end = (batch_start + self.config.max_batch_size).min(truncated_docs.len());
            let batch_docs = &truncated_docs[batch_start..batch_end];

            debug!(
                batch_start,
                batch_end,
                batch_size = batch_docs.len(),
                "Processing rerank batch"
            );

            let batch_scores = self
                .rerank_batch(&truncated_query, batch_docs, return_documents)
                .await?;
            all_scores.extend(batch_scores);
        }

        // Build results with original indices
        let mut results: Vec<RerankResult> = all_scores
            .into_iter()
            .enumerate()
            .filter(|(_, score)| *score >= self.config.score_threshold)
            .map(|(idx, score)| RerankResult {
                document_id: document_ids[idx],
                index: idx,
                relevance_score: score,
                document: if return_documents {
                    Some(documents[idx].clone())
                } else {
                    None
                },
            })
            .collect();

        // Sort by relevance score descending
        results.sort_by(|a, b| {
            b.relevance_score
                .partial_cmp(&a.relevance_score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        // Apply top_k limit
        if let Some(k) = top_k {
            results.truncate(k);
        }

        #[allow(clippy::cast_possible_truncation)]
        let processing_time_ms = start_time.elapsed().as_millis() as u64;

        Ok(RerankResponse {
            results,
            model: self.config.model.clone(),
            processing_time_ms,
        })
    }

    /// Rerank a single batch with retry logic.
    async fn rerank_batch(
        &self,
        query: &str,
        documents: &[String],
        return_documents: bool,
    ) -> Result<Vec<f32>> {
        let retry_policy = rag_config::RetryPolicy::new(
            self.config.max_retries,
            self.config.retry_min_wait_ms,
            self.config.retry_max_wait_ms,
        );
        let doc_count = documents.len();

        retry_policy
            .execute(
                || async {
                    let response = self
                        .make_request(query, documents, return_documents)
                        .await?;
                    self.process_response(response, doc_count)
                },
                |e: &RetrievalError| {
                    let msg = e.to_string();
                    msg.contains("timed out")
                        || msg.contains("connect")
                        || msg.contains("500")
                        || msg.contains("502")
                        || msg.contains("503")
                        || msg.contains("504")
                },
            )
            .await
    }

    /// Make a single rerank request.
    async fn make_request(
        &self,
        query: &str,
        documents: &[String],
        return_documents: bool,
    ) -> Result<ApiRerankResponse> {
        let request = RerankRequest {
            model: self.config.model.clone(),
            query: query.to_string(),
            documents: documents.to_vec(),
            return_documents,
        };

        let response = self
            .client
            .post(self.config.rerank_endpoint_url())
            .json(&request)
            .send()
            .await
            .map_err(|e| {
                if e.is_timeout() {
                    RetrievalError::timeout(format!(
                        "Rerank request timed out after {}ms",
                        self.config.timeout_ms
                    ))
                } else if e.is_connect() {
                    RetrievalError::reranking(format!(
                        "Failed to connect to reranker service at {}: {e}",
                        self.config.gateway_url
                    ))
                } else {
                    RetrievalError::reranking(format!("Rerank request failed: {e}"))
                }
            })?;

        let status = response.status();
        if !status.is_success() {
            let error_text = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(RetrievalError::reranking(format!(
                "Reranker service returned {status}: {error_text}"
            )));
        }

        response
            .json::<ApiRerankResponse>()
            .await
            .map_err(|e| RetrievalError::reranking(format!("Failed to parse rerank response: {e}")))
    }

    /// Process the API response, extracting scores in input order.
    #[allow(clippy::unused_self)]
    fn process_response(
        &self,
        response: ApiRerankResponse,
        expected_count: usize,
    ) -> Result<Vec<f32>> {
        if response.results.len() != expected_count {
            return Err(RetrievalError::reranking(format!(
                "Expected {expected_count} rerank results, got {}",
                response.results.len()
            )));
        }

        // Build scores array, maintaining original order
        let mut scores = vec![0.0_f32; expected_count];
        for result in response.results {
            if result.index >= expected_count {
                return Err(RetrievalError::reranking(format!(
                    "Invalid result index {} for {} documents",
                    result.index, expected_count
                )));
            }
            scores[result.index] = result.relevance_score;
        }

        Ok(scores)
    }

    /// Check if the reranker service is healthy.
    ///
    /// Performs a simple rerank call to verify connectivity.
    ///
    /// # Errors
    ///
    /// This method always returns `Ok`. Network errors result in `Ok(false)`.
    pub async fn health_check(&self) -> Result<bool> {
        match self
            .rerank_batch("test", &["test document".to_string()], false)
            .await
        {
            Ok(_) => Ok(true),
            Err(_) => Ok(false),
        }
    }
}

/// Truncate text to a maximum length.
fn truncate(text: &str, max_chars: usize) -> String {
    if text.len() <= max_chars {
        text.to_string()
    } else {
        text.chars().take(max_chars).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_client_creation() {
        let config = RerankerConfig::default();
        let client = RerankerClient::new(config);
        assert!(client.is_ok());
    }

    #[test]
    fn test_client_config() {
        let config = RerankerConfig::new()
            .with_gateway_url("http://test:8004")
            .with_model("test-model");
        let client = RerankerClient::new(config).unwrap();

        assert_eq!(client.config().gateway_url, "http://test:8004");
        assert_eq!(client.config().model, "test-model");
    }

    #[test]
    fn test_truncate() {
        // No truncation needed
        assert_eq!(truncate("hello", 10), "hello");

        // Truncation needed
        assert_eq!(truncate("hello world", 5), "hello");

        // Empty string
        assert_eq!(truncate("", 5), "");

        // Unicode handling
        assert_eq!(truncate("hello world", 7), "hello w");
    }

    #[test]
    fn test_rerank_result_serialization() {
        let result = RerankResult {
            document_id: Uuid::nil(),
            index: 0,
            relevance_score: 0.95,
            document: Some("test document".to_string()),
        };

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("document_id"));
        assert!(json.contains("relevance_score"));
        assert!(json.contains("0.95"));
        assert!(json.contains("test document"));

        let deserialized: RerankResult = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.document_id, Uuid::nil());
        assert!((deserialized.relevance_score - 0.95).abs() < f32::EPSILON);
        assert_eq!(deserialized.document, Some("test document".to_string()));
    }

    #[test]
    fn test_rerank_response_serialization() {
        let response = RerankResponse {
            results: vec![RerankResult {
                document_id: Uuid::nil(),
                index: 0,
                relevance_score: 0.9,
                document: None,
            }],
            model: "test-model".to_string(),
            processing_time_ms: 150,
        };

        let json = serde_json::to_string(&response).unwrap();
        assert!(json.contains("results"));
        assert!(json.contains("model"));
        assert!(json.contains("processing_time_ms"));

        let deserialized: RerankResponse = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.results.len(), 1);
        assert_eq!(deserialized.model, "test-model");
        assert_eq!(deserialized.processing_time_ms, 150);
    }

    #[test]
    fn test_backoff_from_retry_policy() {
        let policy = rag_config::RetryPolicy::new(5, 100, 5000);

        // First retry: ~100ms base
        let b0 = policy.backoff_duration(0);
        assert!(b0.as_millis() >= 75);
        assert!(b0.as_millis() <= 125);

        // Second retry: ~200ms (100 * 2^1)
        let b1 = policy.backoff_duration(1);
        assert!(b1.as_millis() >= 150);
        assert!(b1.as_millis() <= 250);

        // Should cap at max_wait_ms
        let b_high = policy.backoff_duration(20);
        assert!(b_high.as_millis() <= 6250); // max_ms + 25% jitter
    }

    #[test]
    fn test_process_response_success() {
        let config = RerankerConfig::default();
        let client = RerankerClient::new(config).unwrap();

        let response = ApiRerankResponse {
            results: vec![
                ApiRerankResult {
                    index: 1,
                    relevance_score: 0.8,
                    document: None,
                },
                ApiRerankResult {
                    index: 0,
                    relevance_score: 0.9,
                    document: None,
                },
            ],
        };

        let scores = client.process_response(response, 2).unwrap();

        // Scores should be in input order (by index)
        assert_eq!(scores.len(), 2);
        assert!((scores[0] - 0.9).abs() < f32::EPSILON);
        assert!((scores[1] - 0.8).abs() < f32::EPSILON);
    }

    #[test]
    fn test_process_response_wrong_count() {
        let config = RerankerConfig::default();
        let client = RerankerClient::new(config).unwrap();

        let response = ApiRerankResponse {
            results: vec![ApiRerankResult {
                index: 0,
                relevance_score: 0.9,
                document: None,
            }],
        };

        let result = client.process_response(response, 2);
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("Expected 2"));
    }

    #[test]
    fn test_process_response_invalid_index() {
        let config = RerankerConfig::default();
        let client = RerankerClient::new(config).unwrap();

        let response = ApiRerankResponse {
            results: vec![ApiRerankResult {
                index: 5, // Invalid index
                relevance_score: 0.9,
                document: None,
            }],
        };

        let result = client.process_response(response, 1);
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Invalid result index"));
    }

    #[tokio::test]
    async fn test_rerank_empty_documents() {
        let config = RerankerConfig::default();
        let client = RerankerClient::new(config).unwrap();

        let result = client.rerank("test query", &[], &[]).await.unwrap();

        assert!(result.results.is_empty());
        assert_eq!(result.model, "BAAI/bge-reranker-v2-m3");
        assert_eq!(result.processing_time_ms, 0);
    }

    #[tokio::test]
    async fn test_rerank_mismatched_lengths() {
        let config = RerankerConfig::default();
        let client = RerankerClient::new(config).unwrap();

        let documents = vec!["doc1".to_string(), "doc2".to_string()];
        let ids = vec![Uuid::new_v4()]; // Only one ID

        let result = client.rerank("test", &documents, &ids).await;
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("same length"));
    }

    #[tokio::test]
    async fn test_rerank_too_many_documents() {
        let config = RerankerConfig::new().with_max_documents(2);
        let client = RerankerClient::new(config).unwrap();

        let documents = vec!["doc1".to_string(), "doc2".to_string(), "doc3".to_string()];
        let ids: Vec<Uuid> = (0..3).map(|_| Uuid::new_v4()).collect();

        let result = client.rerank("test", &documents, &ids).await;
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("Too many documents"));
    }

    #[test]
    fn test_rerank_request_serialization() {
        let request = RerankRequest {
            model: "test-model".to_string(),
            query: "test query".to_string(),
            documents: vec!["doc1".to_string(), "doc2".to_string()],
            return_documents: false,
        };

        let json = serde_json::to_string(&request).unwrap();
        assert!(json.contains("\"model\""));
        assert!(json.contains("\"query\""));
        assert!(json.contains("\"documents\""));
        assert!(json.contains("\"return_documents\""));
        assert!(json.contains("test-model"));
        assert!(json.contains("test query"));
        assert!(json.contains("doc1"));
        assert!(json.contains("doc2"));
    }
}

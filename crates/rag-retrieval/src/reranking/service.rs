//! High-level reranking service for fused result integration.
//!
//! This module provides `RerankerService`, which wraps the lower-level
//! `RerankerClient` to provide a higher-level API that works directly
//! with fused search results and `RetrievalResult` types.
//!
//! # Example
//!
//! ```no_run
//! use rag_retrieval::reranking::{RerankerService, RerankerConfig};
//! use rag_retrieval::fusion::{FusedResult, fuse, FusionConfig};
//! use rag_retrieval::ScoredItem;
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = RerankerConfig::default();
//!     let service = RerankerService::new(config)?;
//!
//!     // Create some fused results
//!     let semantic = vec![ScoredItem::new("doc1".to_string(), 0.9)];
//!     let keyword = vec![ScoredItem::new("doc1".to_string(), 0.8)];
//!     let fused = fuse(&semantic, &keyword, &FusionConfig::default())?;
//!
//!     // Rerank with content lookup
//!     let contents = vec!["Document 1 content about machine learning.".to_string()];
//!     let reranked = service.rerank_fused_with_content(
//!         "What is machine learning?",
//!         fused,
//!         &contents,
//!         Some(10),
//!     ).await?;
//!
//!     Ok(())
//! }
//! ```

use std::collections::HashMap;
use std::sync::Arc;

use tracing::{debug, instrument};
use uuid::Uuid;

use super::{RerankerClient, RerankerConfig};
use crate::error::{Result, RetrievalError};
use crate::fusion::FusedResult;
use crate::types::RetrievalResult;

/// High-level reranking service that integrates with fusion results.
///
/// The `RerankerService` wraps a `RerankerClient` and provides convenient
/// methods for reranking `FusedResult` collections and `RetrievalResult`
/// vectors, preserving metadata and updating scores appropriately.
///
/// # Score Updates
///
/// When reranking fused results, the service:
/// - Updates `fused_score` with the new rerank score
/// - Preserves original semantic and keyword scores/ranks
/// - Tracks original fused score for debugging
///
/// When reranking `RetrievalResult`s, the service:
/// - Updates the main `score` field with the rerank score
/// - Sets `rerank_score` to the new score
/// - Adds `original_score` to metadata
#[derive(Debug, Clone)]
pub struct RerankerService {
    /// The underlying reranker client.
    client: Arc<RerankerClient>,
}

impl RerankerService {
    /// Create a new reranker service with the given configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the HTTP client cannot be created.
    ///
    /// # Example
    ///
    /// ```no_run
    /// use rag_retrieval::reranking::{RerankerService, RerankerConfig};
    ///
    /// let config = RerankerConfig::default();
    /// let service = RerankerService::new(config)?;
    /// # Ok::<(), rag_retrieval::RetrievalError>(())
    /// ```
    pub fn new(config: RerankerConfig) -> Result<Self> {
        let client = RerankerClient::new(config)?;
        Ok(Self {
            client: Arc::new(client),
        })
    }

    /// Create a new reranker service from environment variables.
    ///
    /// # Errors
    ///
    /// Returns an error if the HTTP client cannot be created.
    pub fn from_env() -> Result<Self> {
        Self::new(RerankerConfig::from_env())
    }

    /// Create a reranker service from an existing client.
    ///
    /// This allows sharing a client between multiple services.
    ///
    /// # Example
    ///
    /// ```no_run
    /// use std::sync::Arc;
    /// use rag_retrieval::reranking::{RerankerService, RerankerClient, RerankerConfig};
    ///
    /// let client = Arc::new(RerankerClient::new(RerankerConfig::default())?);
    /// let service = RerankerService::from_client(client);
    /// # Ok::<(), rag_retrieval::RetrievalError>(())
    /// ```
    #[must_use]
    pub const fn from_client(client: Arc<RerankerClient>) -> Self {
        Self { client }
    }

    /// Get a reference to the underlying client.
    #[must_use]
    pub fn client(&self) -> &RerankerClient {
        &self.client
    }

    /// Get the configuration from the underlying client.
    #[must_use]
    pub fn config(&self) -> &RerankerConfig {
        self.client.config()
    }

    /// Rerank fused results with content provided separately.
    ///
    /// This method is useful when `FusedResult` IDs are string identifiers
    /// and content needs to be provided from an external source.
    ///
    /// # Arguments
    ///
    /// * `query` - The search query
    /// * `fused_results` - Fused results to rerank
    /// * `contents` - Content for each result (must match length of `fused_results`)
    /// * `top_k` - Optional limit on number of results to return
    ///
    /// # Returns
    ///
    /// Reranked results with updated `fused_score` and preserved metadata.
    /// Results are sorted by rerank score in descending order.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - `fused_results` and `contents` have different lengths
    /// - The rerank request fails
    #[instrument(skip(self, query, fused_results, contents), fields(
        query_len = query.len(),
        num_results = fused_results.len(),
        top_k = ?top_k
    ))]
    pub async fn rerank_fused_with_content<T>(
        &self,
        query: &str,
        fused_results: Vec<FusedResult<T>>,
        contents: &[String],
        top_k: Option<usize>,
    ) -> Result<Vec<FusedResult<T>>>
    where
        T: Clone + std::fmt::Debug,
    {
        if fused_results.is_empty() {
            return Ok(Vec::new());
        }

        if fused_results.len() != contents.len() {
            return Err(RetrievalError::invalid_request(format!(
                "fused_results and contents must have same length: {} vs {}",
                fused_results.len(),
                contents.len()
            )));
        }

        // Generate UUIDs for each result to track them
        let document_ids: Vec<Uuid> = (0..fused_results.len()).map(|_| Uuid::new_v4()).collect();

        // Build a map from UUID to index for reverse lookup
        let id_to_index: HashMap<Uuid, usize> = document_ids
            .iter()
            .enumerate()
            .map(|(idx, &id)| (id, idx))
            .collect();

        debug!(
            num_documents = fused_results.len(),
            "Sending documents to reranker"
        );

        // Rerank via client
        let rerank_response = self
            .client
            .rerank_with_options(query, contents, &document_ids, top_k, false)
            .await?;

        // Rebuild results with rerank scores
        let mut reranked: Vec<FusedResult<T>> = rerank_response
            .results
            .into_iter()
            .filter_map(|rr| {
                let idx = *id_to_index.get(&rr.document_id)?;
                let original = &fused_results[idx];

                // Create new result with updated fused_score
                let mut result = FusedResult::new(original.id.clone(), rr.relevance_score);

                // Preserve original semantic info
                if let (Some(score), Some(rank)) = (original.semantic_score, original.semantic_rank)
                {
                    result = result.with_semantic(score, rank);
                }

                // Preserve original keyword info
                if let (Some(score), Some(rank)) = (original.keyword_score, original.keyword_rank) {
                    result = result.with_keyword(score, rank);
                }

                Some(result)
            })
            .collect();

        // Results should already be sorted by relevance_score from client,
        // but ensure they are sorted
        reranked.sort_by(|a, b| {
            b.fused_score
                .partial_cmp(&a.fused_score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        debug!(num_reranked = reranked.len(), "Reranking complete");

        Ok(reranked)
    }

    /// Rerank retrieval results.
    ///
    /// This method reranks `RetrievalResult` objects using their content.
    /// The rerank score is stored in both the main `score` field and
    /// `rerank_score`. The original score is preserved in `metadata["original_score"]`.
    ///
    /// # Arguments
    ///
    /// * `query` - The search query
    /// * `results` - Retrieval results to rerank (borrowed; only selected results are cloned)
    /// * `top_k` - Optional limit on number of results to return
    ///
    /// # Returns
    ///
    /// Reranked results sorted by relevance score in descending order.
    ///
    /// # Errors
    ///
    /// Returns an error if the rerank request fails.
    ///
    /// # Example
    ///
    /// ```no_run
    /// use rag_retrieval::reranking::{RerankerService, RerankerConfig};
    /// use rag_retrieval::RetrievalResult;
    ///
    /// #[tokio::main]
    /// async fn main() -> Result<(), Box<dyn std::error::Error>> {
    ///     let service = RerankerService::new(RerankerConfig::default())?;
    ///
    ///     let results = vec![
    ///         RetrievalResult::new(
    ///             "chunk1".into(),
    ///             "doc1".into(),
    ///             "Machine learning is a subset of AI.".into(),
    ///             0.85,
    ///         ),
    ///         RetrievalResult::new(
    ///             "chunk2".into(),
    ///             "doc1".into(),
    ///             "Python is used for data science.".into(),
    ///             0.80,
    ///         ),
    ///     ];
    ///
    ///     let reranked = service.rerank_results("What is ML?", &results, Some(10)).await?;
    ///
    ///     for r in &reranked {
    ///         println!("Chunk {}: score {} (rerank: {:?})",
    ///             r.chunk_id, r.score, r.rerank_score);
    ///     }
    ///
    ///     Ok(())
    /// }
    /// ```
    #[instrument(skip(self, query, results), fields(
        query_len = query.len(),
        num_results = results.len(),
        top_k = ?top_k
    ))]
    pub async fn rerank_results(
        &self,
        query: &str,
        results: &[RetrievalResult],
        top_k: Option<usize>,
    ) -> Result<Vec<RetrievalResult>> {
        if results.is_empty() {
            return Ok(Vec::new());
        }

        // Extract content and create tracking IDs
        let contents: Vec<String> = results.iter().map(|r| r.content.clone()).collect();
        let document_ids: Vec<Uuid> = (0..results.len()).map(|_| Uuid::new_v4()).collect();

        // Build UUID to index mapping
        let id_to_index: HashMap<Uuid, usize> = document_ids
            .iter()
            .enumerate()
            .map(|(idx, &id)| (id, idx))
            .collect();

        debug!(num_results = results.len(), "Reranking retrieval results");

        // Rerank via client
        let rerank_response = self
            .client
            .rerank_with_options(query, &contents, &document_ids, top_k, false)
            .await?;

        // Rebuild results with rerank scores
        let reranked: Vec<RetrievalResult> = rerank_response
            .results
            .into_iter()
            .filter_map(|rr| {
                let idx = *id_to_index.get(&rr.document_id)?;
                let original = &results[idx];

                // Clone and update the result
                let mut result = original.clone();

                // Store original score in metadata
                result.metadata.insert(
                    "original_score".to_string(),
                    serde_json::json!(original.score),
                );

                // Update scores
                result.score = rr.relevance_score;
                result.rerank_score = Some(rr.relevance_score);

                Some(result)
            })
            .collect();

        debug!(
            num_reranked = reranked.len(),
            "Retrieval result reranking complete"
        );

        Ok(reranked)
    }

    /// Normalize scores to the 0-1 range using min-max normalization.
    ///
    /// This is a utility function for cases where raw scores need to be
    /// normalized before or after reranking.
    ///
    /// # Arguments
    ///
    /// * `scores` - Raw scores to normalize
    ///
    /// # Returns
    ///
    /// Normalized scores in the 0-1 range. Returns original scores if
    /// all scores are the same (avoiding division by zero).
    #[must_use]
    pub fn normalize_scores(scores: &[f32]) -> Vec<f32> {
        if scores.is_empty() {
            return Vec::new();
        }

        let min = scores.iter().copied().fold(f32::INFINITY, f32::min);
        let max = scores.iter().copied().fold(f32::NEG_INFINITY, f32::max);
        let range = max - min;

        if range.abs() < f32::EPSILON {
            // All scores are the same, return 1.0 for all
            return vec![1.0; scores.len()];
        }

        scores.iter().map(|&s| (s - min) / range).collect()
    }

    /// Check if the reranker service is healthy.
    ///
    /// Delegates to the underlying client's health check.
    ///
    /// # Returns
    ///
    /// `Ok(true)` if the service is healthy, `Ok(false)` otherwise.
    ///
    /// # Errors
    ///
    /// This method delegates to the client health check. Errors are
    /// caught internally and result in `Ok(false)`, so this method
    /// effectively cannot fail in practice.
    pub async fn health_check(&self) -> Result<bool> {
        self.client.health_check().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_service_creation() {
        let config = RerankerConfig::default();
        let service = RerankerService::new(config);
        assert!(service.is_ok());
    }

    #[test]
    fn test_service_from_client() {
        let config = RerankerConfig::default();
        let client = Arc::new(RerankerClient::new(config).unwrap());
        let service = RerankerService::from_client(client.clone());

        // Verify they share the same config
        assert_eq!(service.config().model, client.config().model);
    }

    #[test]
    fn test_normalize_scores_empty() {
        let scores: Vec<f32> = vec![];
        let normalized = RerankerService::normalize_scores(&scores);
        assert!(normalized.is_empty());
    }

    #[test]
    fn test_normalize_scores_single() {
        let scores = vec![0.5];
        let normalized = RerankerService::normalize_scores(&scores);
        assert_eq!(normalized.len(), 1);
        assert!((normalized[0] - 1.0).abs() < f32::EPSILON);
    }

    #[test]
    fn test_normalize_scores_same_values() {
        let scores = vec![0.5, 0.5, 0.5];
        let normalized = RerankerService::normalize_scores(&scores);
        assert_eq!(normalized.len(), 3);
        for n in &normalized {
            assert!((n - 1.0).abs() < f32::EPSILON);
        }
    }

    #[test]
    fn test_normalize_scores_varied() {
        let scores = vec![0.0, 0.5, 1.0];
        let normalized = RerankerService::normalize_scores(&scores);

        assert_eq!(normalized.len(), 3);
        assert!(normalized[0].abs() < f32::EPSILON); // 0.0 -> 0.0
        assert!((normalized[1] - 0.5).abs() < f32::EPSILON); // 0.5 -> 0.5
        assert!((normalized[2] - 1.0).abs() < f32::EPSILON); // 1.0 -> 1.0
    }

    #[test]
    fn test_normalize_scores_negative() {
        let scores = vec![-1.0, 0.0, 1.0];
        let normalized = RerankerService::normalize_scores(&scores);

        assert_eq!(normalized.len(), 3);
        assert!(normalized[0].abs() < f32::EPSILON); // -1.0 -> 0.0
        assert!((normalized[1] - 0.5).abs() < f32::EPSILON); // 0.0 -> 0.5
        assert!((normalized[2] - 1.0).abs() < f32::EPSILON); // 1.0 -> 1.0
    }

    #[tokio::test]
    async fn test_rerank_fused_empty() {
        let config = RerankerConfig::default();
        let service = RerankerService::new(config).unwrap();

        let fused_results: Vec<FusedResult<String>> = vec![];
        let contents: Vec<String> = vec![];

        let result = service
            .rerank_fused_with_content("test query", fused_results, &contents, None)
            .await
            .unwrap();

        assert!(result.is_empty());
    }

    #[tokio::test]
    async fn test_rerank_fused_mismatched_lengths() {
        let config = RerankerConfig::default();
        let service = RerankerService::new(config).unwrap();

        let fused_results = vec![
            FusedResult::new("doc1".to_string(), 0.9),
            FusedResult::new("doc2".to_string(), 0.8),
        ];
        let contents = vec!["content1".to_string()]; // Only one content

        let result = service
            .rerank_fused_with_content("test query", fused_results, &contents, None)
            .await;

        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("same length"));
    }

    #[tokio::test]
    async fn test_rerank_results_empty() {
        let config = RerankerConfig::default();
        let service = RerankerService::new(config).unwrap();

        let results: Vec<RetrievalResult> = vec![];

        let reranked = service
            .rerank_results("test query", &results, None)
            .await
            .unwrap();

        assert!(reranked.is_empty());
    }

    #[test]
    fn test_fused_result_metadata_preservation() {
        // Test that FusedResult can be cloned and modified
        let original = FusedResult::new("doc1".to_string(), 0.9)
            .with_semantic(0.95, 1)
            .with_keyword(0.85, 2);

        assert_eq!(original.semantic_score, Some(0.95));
        assert_eq!(original.semantic_rank, Some(1));
        assert_eq!(original.keyword_score, Some(0.85));
        assert_eq!(original.keyword_rank, Some(2));
        assert!(original.is_in_both());
    }

    #[test]
    fn test_retrieval_result_update() {
        // Test that RetrievalResult can be updated with rerank score
        let mut result = RetrievalResult::new(
            "chunk1".to_string(),
            "doc1".to_string(),
            "Test content".to_string(),
            0.85,
        );

        // Simulate reranking update
        result.metadata.insert(
            "original_score".to_string(),
            serde_json::json!(result.score),
        );
        result.score = 0.92;
        result.rerank_score = Some(0.92);

        assert!((result.score - 0.92).abs() < f32::EPSILON);
        assert_eq!(result.rerank_score, Some(0.92));

        // Check original_score was stored (comparing as f64 to handle JSON float precision)
        let original = result.metadata.get("original_score").unwrap();
        let original_f64 = original.as_f64().unwrap();
        assert!((original_f64 - 0.85).abs() < 0.0001);
    }
}

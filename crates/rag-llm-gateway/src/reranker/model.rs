//! Reranker model using fastembed's ONNX-based cross-encoder.
//!
//! This module provides document reranking via fastembed's `TextRerank`,
//! which uses ONNX Runtime for cross-encoder inference. The model takes
//! query-document pairs and produces relevance scores.

use std::sync::Mutex;
use std::time::Instant;

use fastembed::{RerankInitOptions, TextRerank};
use tracing::{info, instrument};

use crate::config::RerankerConfig;
use crate::error::{GatewayError, Result};

use super::types::{RerankRequest, RerankResponse, RerankUsage, ScoredDocument};

/// Map a config model name to a fastembed `RerankerModel` enum variant.
///
/// Supports the following model identifiers:
/// - `BAAI/bge-reranker-base` or `bge-reranker-base`
/// - `BAAI/bge-reranker-v2-m3` or `bge-reranker-v2-m3`
/// - `jinaai/jina-reranker-v1-turbo-en` or `jina-reranker-v1-turbo-en`
/// - `jinaai/jina-reranker-v2-base-multilingual` or `jina-reranker-v2-base-multilingual`
fn resolve_reranker_model(model_name: &str) -> Result<fastembed::RerankerModel> {
    // Try parsing directly first (fastembed supports model_code matching)
    if let Ok(m) = model_name.parse::<fastembed::RerankerModel>() {
        return Ok(m);
    }

    // Fallback: match on known short names / aliases
    let lower = model_name.to_lowercase();
    if lower.contains("bge-reranker-v2-m3") {
        Ok(fastembed::RerankerModel::BGERerankerV2M3)
    } else if lower.contains("bge-reranker-base") {
        Ok(fastembed::RerankerModel::BGERerankerBase)
    } else if lower.contains("jina-reranker-v1-turbo") {
        Ok(fastembed::RerankerModel::JINARerankerV1TurboEn)
    } else if lower.contains("jina-reranker-v2-base") {
        Ok(fastembed::RerankerModel::JINARerankerV2BaseMultiligual)
    } else {
        Err(GatewayError::Config(format!(
            "Unknown reranker model: {model_name}. Supported models: \
             BAAI/bge-reranker-base, BAAI/bge-reranker-v2-m3 (via rozgo/bge-reranker-v2-m3), \
             jinaai/jina-reranker-v1-turbo-en, jinaai/jina-reranker-v2-base-multilingual"
        )))
    }
}

/// Reranker model wrapper.
///
/// Uses fastembed's `TextRerank` for cross-encoder inference. The model takes
/// query-document pairs and produces relevance scores. Thread-safe via interior
/// `Mutex` (same pattern as `EmbeddingModelWrapper`).
pub struct RerankerModel {
    inner: Mutex<TextRerank>,
    config: RerankerConfig,
    model_id: String,
}

impl RerankerModel {
    /// Load the reranker model.
    ///
    /// Downloads the ONNX model from `HuggingFace` (or uses cache) and initializes
    /// the cross-encoder session. This is a **blocking** operation; call from
    /// `spawn_blocking` or a blocking context.
    ///
    /// # Errors
    ///
    /// Returns `GatewayError::Reranker` if:
    /// - The model name cannot be resolved to a supported model
    /// - The model cannot be downloaded or loaded
    #[instrument(skip_all, fields(model = %config.model))]
    pub fn load(config: &RerankerConfig) -> Result<Self> {
        info!("Loading reranker model: {}", config.model);

        let start = Instant::now();

        let fastembed_model = resolve_reranker_model(&config.model)?;
        let model_id = fastembed_model.to_string();

        let init_options =
            RerankInitOptions::new(fastembed_model).with_show_download_progress(true);

        let text_rerank = TextRerank::try_new(init_options).map_err(|e| {
            GatewayError::Reranker(format!(
                "Failed to load reranker model '{}': {e}",
                config.model
            ))
        })?;

        let elapsed = start.elapsed();
        info!(
            "Reranker model loaded in {:.2}s: {}",
            elapsed.as_secs_f64(),
            model_id
        );

        Ok(Self {
            inner: Mutex::new(text_rerank),
            config: config.clone(),
            model_id,
        })
    }

    /// Get the model identifier.
    #[must_use]
    pub fn model_id(&self) -> &str {
        &self.model_id
    }

    /// Rerank documents for a query.
    ///
    /// Takes a query and a list of documents, returning documents sorted by
    /// relevance score in descending order. The actual ONNX inference runs
    /// synchronously under a mutex lock; call from `spawn_blocking` to avoid
    /// blocking the async runtime.
    ///
    /// # Errors
    ///
    /// Returns `GatewayError::Reranker` if model inference fails.
    #[instrument(skip(self, request), fields(num_docs = request.documents.len()))]
    pub fn rerank(&self, request: &RerankRequest) -> Result<RerankResponse> {
        let start = Instant::now();

        // Build &str slices for fastembed. The rerank method is generic over
        // S: AsRef<str>; we use &str for both query and documents.
        let doc_refs: Vec<&str> = request.documents.iter().map(String::as_str).collect();

        // Run cross-encoder inference under lock.
        let fastembed_results = self
            .inner
            .lock()
            .map_err(|e| GatewayError::Reranker(format!("Mutex poisoned: {e}")))?
            .rerank(
                request.query.as_str(),
                doc_refs.as_slice(),
                request.return_documents,
                Some(self.config.max_batch_size),
            )
            .map_err(|e| GatewayError::Reranker(format!("Reranking failed: {e}")))?;

        // Convert fastembed results to our response type
        let mut results: Vec<ScoredDocument> = fastembed_results
            .into_iter()
            .map(|r| ScoredDocument {
                index: r.index,
                score: r.score,
                document: r.document,
                doc_id: request
                    .doc_ids
                    .as_ref()
                    .and_then(|ids| ids.get(r.index).cloned()),
            })
            .collect();

        // Results from fastembed are already sorted descending by score,
        // but apply our additional filters.

        // Apply min_score filter
        if let Some(min_score) = request.min_score {
            results.retain(|r| r.score >= min_score);
        }

        // Apply top_k limit
        if let Some(top_k) = request.top_k {
            results.truncate(top_k);
        }

        let elapsed = start.elapsed();

        // Estimate token count (rough approximation)
        let total_tokens: usize = request
            .documents
            .iter()
            .map(|d| request.query.split_whitespace().count() + d.split_whitespace().count())
            .sum();

        Ok(RerankResponse {
            model: self.model_id.clone(),
            results,
            usage: RerankUsage {
                prompt_tokens: total_tokens,
                total_tokens,
            },
            processing_time_ms: elapsed.as_secs_f64() * 1000.0,
        })
    }
}

impl std::fmt::Debug for RerankerModel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RerankerModel")
            .field("model_id", &self.model_id)
            .field("max_batch_size", &self.config.max_batch_size)
            .field("max_sequence_length", &self.config.max_sequence_length)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_resolve_reranker_model_bge_base() {
        let result = resolve_reranker_model("BAAI/bge-reranker-base");
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), fastembed::RerankerModel::BGERerankerBase);
    }

    #[test]
    fn test_resolve_reranker_model_bge_v2_m3() {
        // The fastembed model code for BGERerankerV2M3 is "rozgo/bge-reranker-v2-m3"
        let result = resolve_reranker_model("rozgo/bge-reranker-v2-m3");
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), fastembed::RerankerModel::BGERerankerV2M3);
    }

    #[test]
    fn test_resolve_reranker_model_bge_v2_m3_baai_alias() {
        // Users commonly use the BAAI/ prefix
        let result = resolve_reranker_model("BAAI/bge-reranker-v2-m3");
        assert!(result.is_ok());
        assert_eq!(result.unwrap(), fastembed::RerankerModel::BGERerankerV2M3);
    }

    #[test]
    fn test_resolve_reranker_model_jina_turbo() {
        let result = resolve_reranker_model("jinaai/jina-reranker-v1-turbo-en");
        assert!(result.is_ok());
        assert_eq!(
            result.unwrap(),
            fastembed::RerankerModel::JINARerankerV1TurboEn
        );
    }

    #[test]
    fn test_resolve_reranker_model_unknown() {
        let result = resolve_reranker_model("unknown/model");
        assert!(result.is_err());
    }

    #[test]
    fn test_rerank_request_deserialization() {
        let json = r#"{
            "query": "What is RAG?",
            "documents": ["RAG is retrieval augmented generation", "Another document"],
            "top_k": 5
        }"#;

        let request: RerankRequest = serde_json::from_str(json).unwrap();
        assert_eq!(request.query, "What is RAG?");
        assert_eq!(request.documents.len(), 2);
        assert_eq!(request.top_k, Some(5));
        assert!(request.return_documents); // default true
    }

    #[test]
    fn test_scored_document_serialization() {
        let doc = ScoredDocument {
            index: 0,
            score: 0.95,
            document: Some("Test document".into()),
            doc_id: Some("doc-1".into()),
        };

        let json = serde_json::to_string(&doc).unwrap();
        assert!(json.contains("\"score\":0.95"));
        assert!(json.contains("\"index\":0"));
    }

    #[test]
    fn test_rerank_response_serialization() {
        let response = RerankResponse {
            model: "test-model".into(),
            results: vec![ScoredDocument {
                index: 0,
                score: 0.9,
                document: None,
                doc_id: None,
            }],
            usage: RerankUsage {
                prompt_tokens: 100,
                total_tokens: 100,
            },
            processing_time_ms: 50.5,
        };

        let json = serde_json::to_string(&response).unwrap();
        assert!(json.contains("\"model\":\"test-model\""));
        assert!(json.contains("\"processing_time_ms\":50.5"));
    }
}

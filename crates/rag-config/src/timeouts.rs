//! Timeout configuration following the RAG pipeline timeout cascade.
//!
//! ```text
//! RAG E2E (30s)
//! ├── Retrieval Total (15s)
//! │   ├── Embedding (5s)
//! │   ├── Qdrant (3s) ──┐
//! │   ├── OpenSearch (3s)├── Parallel
//! │   └── Reranker (8s)
//! └── LLM (25s)
//! ```

use serde::{Deserialize, Serialize};
use std::time::Duration;
use validator::Validate;

/// Timeout configuration for the retrieval service.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
#[allow(clippy::struct_field_names)] // _ms suffix indicates units
pub struct RetrievalTimeouts {
    /// Embedding request timeout (ms)
    #[validate(range(min = 100, max = 30000))]
    #[serde(default = "default_embedding_timeout")]
    pub embedding_ms: u64,

    /// Qdrant query timeout (ms)
    #[validate(range(min = 100, max = 30000))]
    #[serde(default = "default_qdrant_timeout")]
    pub qdrant_ms: u64,

    /// `OpenSearch` query timeout (ms)
    #[validate(range(min = 100, max = 30000))]
    #[serde(default = "default_opensearch_timeout")]
    pub opensearch_ms: u64,

    /// Reranker batch timeout (ms)
    #[validate(range(min = 100, max = 30000))]
    #[serde(default = "default_reranker_timeout")]
    pub reranker_ms: u64,

    /// Total retrieval timeout (ms)
    #[validate(range(min = 1000, max = 60000))]
    #[serde(default = "default_retrieval_total_timeout")]
    pub total_ms: u64,
}

const fn default_embedding_timeout() -> u64 {
    5000
}

const fn default_qdrant_timeout() -> u64 {
    3000
}

const fn default_opensearch_timeout() -> u64 {
    3000
}

const fn default_reranker_timeout() -> u64 {
    8000
}

const fn default_retrieval_total_timeout() -> u64 {
    15000
}

impl Default for RetrievalTimeouts {
    fn default() -> Self {
        Self {
            embedding_ms: default_embedding_timeout(),
            qdrant_ms: default_qdrant_timeout(),
            opensearch_ms: default_opensearch_timeout(),
            reranker_ms: default_reranker_timeout(),
            total_ms: default_retrieval_total_timeout(),
        }
    }
}

impl RetrievalTimeouts {
    /// Get embedding timeout as Duration.
    #[must_use]
    pub const fn embedding(&self) -> Duration {
        Duration::from_millis(self.embedding_ms)
    }

    /// Get Qdrant timeout as Duration.
    #[must_use]
    pub const fn qdrant(&self) -> Duration {
        Duration::from_millis(self.qdrant_ms)
    }

    /// Get `OpenSearch` timeout as Duration.
    #[must_use]
    pub const fn opensearch(&self) -> Duration {
        Duration::from_millis(self.opensearch_ms)
    }

    /// Get reranker timeout as Duration.
    #[must_use]
    pub const fn reranker(&self) -> Duration {
        Duration::from_millis(self.reranker_ms)
    }

    /// Get total timeout as Duration.
    #[must_use]
    pub const fn total(&self) -> Duration {
        Duration::from_millis(self.total_ms)
    }

    /// Validate timeout cascade (inner < outer).
    ///
    /// # Errors
    ///
    /// Returns an error if the timeout cascade is invalid.
    pub fn validate_cascade(&self) -> Result<(), String> {
        // Individual operations must complete within total timeout
        if self.embedding_ms >= self.total_ms {
            return Err(format!(
                "Embedding timeout ({}) must be less than total ({})",
                self.embedding_ms, self.total_ms
            ));
        }
        if self.reranker_ms >= self.total_ms {
            return Err(format!(
                "Reranker timeout ({}) must be less than total ({})",
                self.reranker_ms, self.total_ms
            ));
        }

        // Qdrant and OpenSearch are parallel, so they can overlap
        // but both must be less than total
        let search_max = self.qdrant_ms.max(self.opensearch_ms);
        if search_max >= self.total_ms {
            return Err(format!(
                "Search timeout ({}) must be less than total ({})",
                search_max, self.total_ms
            ));
        }

        Ok(())
    }
}

/// Timeout configuration for the orchestrator service.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
#[allow(clippy::struct_field_names)] // _ms suffix indicates units
pub struct OrchestratorTimeouts {
    /// Retrieval service call timeout (ms)
    #[validate(range(min = 1000, max = 60000))]
    #[serde(default = "default_orchestrator_retrieval_timeout")]
    pub retrieval_ms: u64,

    /// LLM generation timeout (ms)
    #[validate(range(min = 1000, max = 120_000))]
    #[serde(default = "default_llm_timeout")]
    pub llm_ms: u64,

    /// Total RAG pipeline timeout (ms)
    #[validate(range(min = 5000, max = 180_000))]
    #[serde(default = "default_rag_total_timeout")]
    pub total_ms: u64,
}

const fn default_orchestrator_retrieval_timeout() -> u64 {
    20000
}

const fn default_llm_timeout() -> u64 {
    25000
}

const fn default_rag_total_timeout() -> u64 {
    30000
}

impl Default for OrchestratorTimeouts {
    fn default() -> Self {
        Self {
            retrieval_ms: default_orchestrator_retrieval_timeout(),
            llm_ms: default_llm_timeout(),
            total_ms: default_rag_total_timeout(),
        }
    }
}

impl OrchestratorTimeouts {
    /// Get retrieval timeout as Duration.
    #[must_use]
    pub const fn retrieval(&self) -> Duration {
        Duration::from_millis(self.retrieval_ms)
    }

    /// Get LLM timeout as Duration.
    #[must_use]
    pub const fn llm(&self) -> Duration {
        Duration::from_millis(self.llm_ms)
    }

    /// Get total timeout as Duration.
    #[must_use]
    pub const fn total(&self) -> Duration {
        Duration::from_millis(self.total_ms)
    }

    /// Validate timeout cascade.
    ///
    /// # Errors
    ///
    /// Returns an error if the timeout cascade is invalid.
    pub fn validate_cascade(&self) -> Result<(), String> {
        if self.retrieval_ms >= self.total_ms {
            return Err(format!(
                "Retrieval timeout ({}) must be less than total ({})",
                self.retrieval_ms, self.total_ms
            ));
        }
        // LLM can technically be longer since it's the main operation
        // but shouldn't exceed total
        if self.llm_ms > self.total_ms {
            return Err(format!(
                "LLM timeout ({}) must not exceed total ({})",
                self.llm_ms, self.total_ms
            ));
        }
        Ok(())
    }
}

/// Timeout configuration for the ingestion service.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
#[allow(clippy::struct_field_names)] // _ms suffix indicates units
pub struct IngestionTimeouts {
    /// Document parsing timeout (ms)
    #[validate(range(min = 1000, max = 300_000))]
    #[serde(default = "default_parsing_timeout")]
    pub parsing_ms: u64,

    /// Embedding batch timeout (ms)
    #[validate(range(min = 1000, max = 60_000))]
    #[serde(default = "default_ingestion_embedding_timeout")]
    pub embedding_ms: u64,

    /// Qdrant upsert timeout (ms)
    #[validate(range(min = 1000, max = 60_000))]
    #[serde(default = "default_qdrant_upsert_timeout")]
    pub qdrant_upsert_ms: u64,

    /// `OpenSearch` index timeout (ms)
    #[validate(range(min = 1000, max = 60_000))]
    #[serde(default = "default_opensearch_index_timeout")]
    pub opensearch_index_ms: u64,

    /// Total document processing timeout (ms)
    #[validate(range(min = 10_000, max = 600_000))]
    #[serde(default = "default_document_timeout")]
    pub document_total_ms: u64,
}

const fn default_parsing_timeout() -> u64 {
    60000
}

const fn default_ingestion_embedding_timeout() -> u64 {
    30000
}

const fn default_qdrant_upsert_timeout() -> u64 {
    10000
}

const fn default_opensearch_index_timeout() -> u64 {
    10000
}

const fn default_document_timeout() -> u64 {
    300_000
}

impl Default for IngestionTimeouts {
    fn default() -> Self {
        Self {
            parsing_ms: default_parsing_timeout(),
            embedding_ms: default_ingestion_embedding_timeout(),
            qdrant_upsert_ms: default_qdrant_upsert_timeout(),
            opensearch_index_ms: default_opensearch_index_timeout(),
            document_total_ms: default_document_timeout(),
        }
    }
}

impl IngestionTimeouts {
    /// Get parsing timeout as Duration.
    #[must_use]
    pub const fn parsing(&self) -> Duration {
        Duration::from_millis(self.parsing_ms)
    }

    /// Get embedding timeout as Duration.
    #[must_use]
    pub const fn embedding(&self) -> Duration {
        Duration::from_millis(self.embedding_ms)
    }

    /// Get Qdrant upsert timeout as Duration.
    #[must_use]
    pub const fn qdrant_upsert(&self) -> Duration {
        Duration::from_millis(self.qdrant_upsert_ms)
    }

    /// Get `OpenSearch` index timeout as Duration.
    #[must_use]
    pub const fn opensearch_index(&self) -> Duration {
        Duration::from_millis(self.opensearch_index_ms)
    }

    /// Get total document timeout as Duration.
    #[must_use]
    pub const fn document_total(&self) -> Duration {
        Duration::from_millis(self.document_total_ms)
    }
}

/// Combined timeout configuration.
#[derive(Debug, Clone, Serialize, Deserialize, Validate, Default)]
pub struct TimeoutConfig {
    /// Retrieval service timeouts
    #[serde(default)]
    #[validate(nested)]
    pub retrieval: RetrievalTimeouts,

    /// Orchestrator service timeouts
    #[serde(default)]
    #[validate(nested)]
    pub orchestrator: OrchestratorTimeouts,

    /// Ingestion service timeouts
    #[serde(default)]
    #[validate(nested)]
    pub ingestion: IngestionTimeouts,
}

impl TimeoutConfig {
    /// Validate all timeout cascades.
    ///
    /// # Errors
    ///
    /// Returns an error if any timeout cascade is invalid.
    pub fn validate_all_cascades(&self) -> Result<(), String> {
        self.retrieval.validate_cascade()?;
        self.orchestrator.validate_cascade()?;
        // Ingestion doesn't have a strict cascade but we could add validation
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_retrieval_timeouts_default() {
        let timeouts = RetrievalTimeouts::default();
        assert_eq!(timeouts.embedding_ms, 5000);
        assert_eq!(timeouts.qdrant_ms, 3000);
        assert_eq!(timeouts.total_ms, 15000);
    }

    #[test]
    fn test_retrieval_timeouts_duration() {
        let timeouts = RetrievalTimeouts::default();
        assert_eq!(timeouts.embedding(), Duration::from_millis(5000));
        assert_eq!(timeouts.total(), Duration::from_millis(15000));
    }

    #[test]
    fn test_retrieval_cascade_valid() {
        let timeouts = RetrievalTimeouts::default();
        assert!(timeouts.validate_cascade().is_ok());
    }

    #[test]
    fn test_retrieval_cascade_invalid() {
        let timeouts = RetrievalTimeouts {
            embedding_ms: 20000, // Too long
            ..Default::default()
        };
        assert!(timeouts.validate_cascade().is_err());
    }

    #[test]
    fn test_orchestrator_cascade_valid() {
        let timeouts = OrchestratorTimeouts::default();
        assert!(timeouts.validate_cascade().is_ok());
    }

    #[test]
    fn test_timeout_config_validate_all() {
        let config = TimeoutConfig::default();
        assert!(config.validate_all_cascades().is_ok());
    }
}

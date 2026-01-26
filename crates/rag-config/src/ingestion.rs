//! Ingestion service configuration.

use crate::common::{
    DatabaseConfig, EmbeddingConfig, OpenSearchConfig, QdrantConfig, RedisConfig, ServiceConfig,
    StorageConfig,
};
use crate::timeouts::IngestionTimeouts;
use serde::{Deserialize, Serialize};
use validator::Validate;

/// Full configuration for the ingestion service.
#[derive(Debug, Clone, Deserialize, Validate)]
pub struct IngestionConfig {
    /// Base service configuration
    #[serde(flatten)]
    #[validate(nested)]
    pub service: ServiceConfig,

    /// Database configuration
    #[validate(nested)]
    pub database: DatabaseConfig,

    /// Qdrant vector store configuration
    #[serde(default)]
    #[validate(nested)]
    pub qdrant: QdrantConfig,

    /// OpenSearch configuration
    #[serde(default)]
    #[validate(nested)]
    pub opensearch: OpenSearchConfig,

    /// Redis configuration (for Celery and caching)
    #[validate(nested)]
    pub redis: RedisConfig,

    /// Object storage configuration
    #[validate(nested)]
    pub storage: StorageConfig,

    /// Embedding service configuration
    #[serde(default)]
    #[validate(nested)]
    pub embedding: EmbeddingConfig,

    /// Timeout configuration
    #[serde(default)]
    #[validate(nested)]
    pub timeouts: IngestionTimeouts,

    /// Chunking configuration
    #[serde(default)]
    #[validate(nested)]
    pub chunking: ChunkingConfig,

    /// Worker configuration
    #[serde(default)]
    #[validate(nested)]
    pub worker: WorkerConfig,

    /// Feature flags
    #[serde(default)]
    pub features: IngestionFeatures,
}

/// Chunking configuration.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
pub struct ChunkingConfig {
    /// Target chunk size in tokens
    #[validate(range(min = 100, max = 4096))]
    #[serde(default = "default_target_tokens")]
    pub target_tokens: u32,

    /// Maximum chunk size in tokens
    #[validate(range(min = 100, max = 8192))]
    #[serde(default = "default_max_tokens")]
    pub max_tokens: u32,

    /// Overlap between chunks in tokens
    #[validate(range(max = 500))]
    #[serde(default = "default_overlap_tokens")]
    pub overlap_tokens: u32,

    /// Default chunking strategy
    #[serde(default)]
    pub default_strategy: ChunkingStrategy,

    /// Separators for recursive chunking (in order of preference)
    #[serde(default = "default_separators")]
    pub separators: Vec<String>,
}

/// Chunking strategy enum.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum ChunkingStrategy {
    /// Recursive character-based splitting
    #[default]
    Recursive,
    /// Semantic sentence-based splitting
    Semantic,
    /// Document structure-aware splitting
    Hierarchical,
}

const fn default_target_tokens() -> u32 {
    300
}

const fn default_max_tokens() -> u32 {
    512
}

const fn default_overlap_tokens() -> u32 {
    50
}

fn default_separators() -> Vec<String> {
    vec![
        "\n\n".to_string(),
        "\n".to_string(),
        ". ".to_string(),
        " ".to_string(),
    ]
}

impl Default for ChunkingConfig {
    fn default() -> Self {
        Self {
            target_tokens: default_target_tokens(),
            max_tokens: default_max_tokens(),
            overlap_tokens: default_overlap_tokens(),
            default_strategy: ChunkingStrategy::default(),
            separators: default_separators(),
        }
    }
}

/// Worker (Celery) configuration.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
pub struct WorkerConfig {
    /// Number of concurrent workers
    #[validate(range(min = 1, max = 32))]
    #[serde(default = "default_concurrency")]
    pub concurrency: u32,

    /// Task prefetch count
    #[validate(range(min = 1, max = 16))]
    #[serde(default = "default_prefetch")]
    pub prefetch: u32,

    /// Task soft time limit in seconds
    #[validate(range(min = 60, max = 7200))]
    #[serde(default = "default_soft_time_limit")]
    pub soft_time_limit_secs: u32,

    /// Task hard time limit in seconds
    #[validate(range(min = 120, max = 14400))]
    #[serde(default = "default_hard_time_limit")]
    pub hard_time_limit_secs: u32,

    /// Maximum retries for failed tasks
    #[validate(range(max = 10))]
    #[serde(default = "default_max_retries")]
    pub max_retries: u32,

    /// Retry delay in seconds (exponential backoff base)
    #[validate(range(min = 1, max = 300))]
    #[serde(default = "default_retry_delay")]
    pub retry_delay_secs: u32,
}

const fn default_concurrency() -> u32 {
    4
}

const fn default_prefetch() -> u32 {
    4
}

const fn default_soft_time_limit() -> u32 {
    300
}

const fn default_hard_time_limit() -> u32 {
    600
}

const fn default_max_retries() -> u32 {
    3
}

const fn default_retry_delay() -> u32 {
    60
}

impl Default for WorkerConfig {
    fn default() -> Self {
        Self {
            concurrency: default_concurrency(),
            prefetch: default_prefetch(),
            soft_time_limit_secs: default_soft_time_limit(),
            hard_time_limit_secs: default_hard_time_limit(),
            max_retries: default_max_retries(),
            retry_delay_secs: default_retry_delay(),
        }
    }
}

/// Feature flags for the ingestion service.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct IngestionFeatures {
    /// Enable PII detection
    #[serde(default = "default_true")]
    pub pii_detection_enabled: bool,

    /// Enable deduplication by content hash
    #[serde(default = "default_true")]
    pub deduplication_enabled: bool,

    /// Enable embedding caching
    #[serde(default = "default_true")]
    pub embedding_cache_enabled: bool,

    /// Enable metrics collection
    #[serde(default = "default_true")]
    pub metrics_enabled: bool,

    /// Enable OpenTelemetry tracing
    #[serde(default)]
    pub tracing_enabled: bool,
}

const fn default_true() -> bool {
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_chunking_config_default() {
        let config = ChunkingConfig::default();
        assert_eq!(config.target_tokens, 300);
        assert_eq!(config.max_tokens, 512);
        assert_eq!(config.overlap_tokens, 50);
        assert_eq!(config.default_strategy, ChunkingStrategy::Recursive);
    }

    #[test]
    fn test_worker_config_default() {
        let config = WorkerConfig::default();
        assert_eq!(config.concurrency, 4);
        assert_eq!(config.max_retries, 3);
    }

    #[test]
    fn test_separators_default() {
        let config = ChunkingConfig::default();
        assert_eq!(config.separators.len(), 4);
        assert_eq!(config.separators[0], "\n\n");
    }
}

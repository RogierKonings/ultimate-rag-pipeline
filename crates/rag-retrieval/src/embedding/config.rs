//! Configuration for the embedding client.
//!
//! This module provides configuration structures for the embedding
//! HTTP client that calls the embedding service.

use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Configuration for the embedding client.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingConfig {
    /// URL of the embedding service.
    #[serde(default = "default_url")]
    pub url: String,

    /// Model name to use for embeddings.
    #[serde(default = "default_model")]
    pub model: String,

    /// Expected embedding dimensions.
    #[serde(default = "default_dimensions")]
    pub dimensions: usize,

    /// Maximum number of texts per batch request.
    #[serde(default = "default_batch_size")]
    pub batch_size: usize,

    /// Request timeout in milliseconds.
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,

    /// Maximum number of retry attempts.
    #[serde(default = "default_max_retries")]
    pub max_retries: u32,

    /// Optional instruction prefix for query embeddings.
    /// For BGE models, use: "Represent this sentence for searching relevant passages: "
    #[serde(default)]
    pub instruction_prefix: Option<String>,
}

fn default_url() -> String {
    "http://localhost:8080".into()
}

fn default_model() -> String {
    "bge-small-en-v1.5".into()
}

const fn default_dimensions() -> usize {
    384
}

const fn default_batch_size() -> usize {
    32
}

const fn default_timeout_ms() -> u64 {
    5000
}

const fn default_max_retries() -> u32 {
    2
}

impl Default for EmbeddingConfig {
    fn default() -> Self {
        Self {
            url: default_url(),
            model: default_model(),
            dimensions: default_dimensions(),
            batch_size: default_batch_size(),
            timeout_ms: default_timeout_ms(),
            max_retries: default_max_retries(),
            instruction_prefix: None,
        }
    }
}

impl EmbeddingConfig {
    /// Create a new embedding config with defaults.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the embedding service URL.
    #[must_use]
    pub fn with_url(mut self, url: impl Into<String>) -> Self {
        self.url = url.into();
        self
    }

    /// Set the model name.
    #[must_use]
    pub fn with_model(mut self, model: impl Into<String>) -> Self {
        self.model = model.into();
        self
    }

    /// Set the expected embedding dimensions.
    #[must_use]
    pub const fn with_dimensions(mut self, dimensions: usize) -> Self {
        self.dimensions = dimensions;
        self
    }

    /// Set the batch size for multi-text requests.
    #[must_use]
    pub const fn with_batch_size(mut self, batch_size: usize) -> Self {
        self.batch_size = batch_size;
        self
    }

    /// Set the timeout in milliseconds.
    #[must_use]
    pub const fn with_timeout_ms(mut self, timeout_ms: u64) -> Self {
        self.timeout_ms = timeout_ms;
        self
    }

    /// Set the timeout.
    #[must_use]
    #[allow(clippy::cast_possible_truncation, clippy::missing_const_for_fn)]
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout_ms = timeout.as_millis() as u64;
        self
    }

    /// Set the maximum number of retries.
    #[must_use]
    pub const fn with_max_retries(mut self, max_retries: u32) -> Self {
        self.max_retries = max_retries;
        self
    }

    /// Set the instruction prefix for query embeddings.
    #[must_use]
    pub fn with_instruction_prefix(mut self, prefix: impl Into<String>) -> Self {
        self.instruction_prefix = Some(prefix.into());
        self
    }

    /// Set the instruction prefix for BGE-style models.
    /// Uses the standard BGE prefix: "Represent this sentence for searching relevant passages: "
    #[must_use]
    pub fn with_bge_prefix(self) -> Self {
        self.with_instruction_prefix("Represent this sentence for searching relevant passages: ")
    }

    /// Get the timeout as a Duration.
    #[must_use]
    pub const fn timeout(&self) -> Duration {
        Duration::from_millis(self.timeout_ms)
    }

    /// Get the embeddings API endpoint URL.
    #[must_use]
    pub fn embeddings_endpoint(&self) -> String {
        format!("{}/v1/embeddings", self.url.trim_end_matches('/'))
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `EMBEDDING_SERVICE_URL`: Service URL (default: `http://localhost:8080`)
    /// - `EMBEDDING_MODEL`: Model name (default: `bge-small-en-v1.5`)
    /// - `EMBEDDING_DIMENSIONS`: Vector dimensions (default: 384)
    /// - `EMBEDDING_BATCH_SIZE`: Batch size (default: 32)
    /// - `EMBEDDING_TIMEOUT_MS`: Timeout in milliseconds (default: 5000)
    /// - `EMBEDDING_MAX_RETRIES`: Max retry attempts (default: 2)
    /// - `EMBEDDING_INSTRUCTION_PREFIX`: Optional instruction prefix for queries
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(url) = std::env::var("EMBEDDING_SERVICE_URL") {
            config.url = url;
        }

        if let Ok(model) = std::env::var("EMBEDDING_MODEL") {
            config.model = model;
        }

        if let Ok(dimensions) = std::env::var("EMBEDDING_DIMENSIONS") {
            if let Ok(d) = dimensions.parse() {
                config.dimensions = d;
            }
        }

        if let Ok(batch_size) = std::env::var("EMBEDDING_BATCH_SIZE") {
            if let Ok(b) = batch_size.parse() {
                config.batch_size = b;
            }
        }

        if let Ok(timeout) = std::env::var("EMBEDDING_TIMEOUT_MS") {
            if let Ok(t) = timeout.parse() {
                config.timeout_ms = t;
            }
        }

        if let Ok(retries) = std::env::var("EMBEDDING_MAX_RETRIES") {
            if let Ok(r) = retries.parse() {
                config.max_retries = r;
            }
        }

        if let Ok(prefix) = std::env::var("EMBEDDING_INSTRUCTION_PREFIX") {
            config.instruction_prefix = Some(prefix);
        }

        config
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = EmbeddingConfig::default();
        assert_eq!(config.url, "http://localhost:8080");
        assert_eq!(config.model, "bge-small-en-v1.5");
        assert_eq!(config.dimensions, 384);
        assert_eq!(config.batch_size, 32);
        assert_eq!(config.timeout_ms, 5000);
        assert_eq!(config.max_retries, 2);
        assert!(config.instruction_prefix.is_none());
    }

    #[test]
    fn test_config_builder() {
        let config = EmbeddingConfig::new()
            .with_url("http://embedding:8080")
            .with_model("bge-large-en")
            .with_dimensions(1024)
            .with_batch_size(16)
            .with_timeout(Duration::from_secs(10))
            .with_max_retries(3)
            .with_instruction_prefix("Query: ");

        assert_eq!(config.url, "http://embedding:8080");
        assert_eq!(config.model, "bge-large-en");
        assert_eq!(config.dimensions, 1024);
        assert_eq!(config.batch_size, 16);
        assert_eq!(config.timeout_ms, 10_000);
        assert_eq!(config.max_retries, 3);
        assert_eq!(config.instruction_prefix, Some("Query: ".to_string()));
    }

    #[test]
    fn test_bge_prefix() {
        let config = EmbeddingConfig::new().with_bge_prefix();
        assert_eq!(
            config.instruction_prefix,
            Some("Represent this sentence for searching relevant passages: ".to_string())
        );
    }

    #[test]
    fn test_embeddings_endpoint() {
        let config = EmbeddingConfig::new().with_url("http://embedding:8080");
        assert_eq!(
            config.embeddings_endpoint(),
            "http://embedding:8080/v1/embeddings"
        );

        // Test with trailing slash
        let config = EmbeddingConfig::new().with_url("http://embedding:8080/");
        assert_eq!(
            config.embeddings_endpoint(),
            "http://embedding:8080/v1/embeddings"
        );
    }

    #[test]
    fn test_timeout_conversion() {
        let config = EmbeddingConfig::new().with_timeout_ms(3000);
        assert_eq!(config.timeout(), Duration::from_millis(3000));

        let config = EmbeddingConfig::new().with_timeout(Duration::from_secs(5));
        assert_eq!(config.timeout_ms, 5000);
    }

    #[test]
    fn test_config_serialization() {
        let config = EmbeddingConfig::new()
            .with_url("http://embedding:8080")
            .with_instruction_prefix("Prefix: ");

        let json = serde_json::to_string(&config).unwrap();
        assert!(json.contains("embedding:8080"));
        assert!(json.contains("Prefix: "));

        let deserialized: EmbeddingConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.url, "http://embedding:8080");
        assert_eq!(
            deserialized.instruction_prefix,
            Some("Prefix: ".to_string())
        );
    }
}

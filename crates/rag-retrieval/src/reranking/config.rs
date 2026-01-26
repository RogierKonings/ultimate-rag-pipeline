//! Configuration for the reranker client.
//!
//! This module provides configuration structures for the reranker
//! HTTP client that calls the LLM Gateway's rerank endpoint.

use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Configuration for the reranker client.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RerankerConfig {
    /// Model name for reranking.
    #[serde(default = "default_model")]
    pub model: String,

    /// URL of the LLM Gateway.
    #[serde(default = "default_gateway_url")]
    pub gateway_url: String,

    /// Rerank API endpoint path.
    #[serde(default = "default_rerank_endpoint")]
    pub rerank_endpoint: String,

    /// Maximum number of documents per batch.
    #[serde(default = "default_max_batch_size")]
    pub max_batch_size: usize,

    /// Maximum number of documents to rerank.
    #[serde(default = "default_max_documents")]
    pub max_documents: usize,

    /// Maximum query length in tokens (approximate).
    #[serde(default = "default_max_query_length")]
    pub max_query_length: usize,

    /// Maximum document length in tokens (approximate).
    #[serde(default = "default_max_document_length")]
    pub max_document_length: usize,

    /// Request timeout in milliseconds.
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,

    /// Minimum score threshold for results.
    #[serde(default = "default_score_threshold")]
    pub score_threshold: f32,

    /// Maximum number of retry attempts.
    #[serde(default = "default_max_retries")]
    pub max_retries: u32,

    /// Minimum retry wait time in milliseconds.
    #[serde(default = "default_retry_min_wait_ms")]
    pub retry_min_wait_ms: u64,

    /// Maximum retry wait time in milliseconds.
    #[serde(default = "default_retry_max_wait_ms")]
    pub retry_max_wait_ms: u64,
}

fn default_model() -> String {
    "BAAI/bge-reranker-v2-m3".into()
}

fn default_gateway_url() -> String {
    "http://localhost:8004".into()
}

fn default_rerank_endpoint() -> String {
    "/v1/rerank".into()
}

const fn default_max_batch_size() -> usize {
    32
}

const fn default_max_documents() -> usize {
    100
}

const fn default_max_query_length() -> usize {
    512
}

const fn default_max_document_length() -> usize {
    512
}

const fn default_timeout_ms() -> u64 {
    30_000
}

const fn default_score_threshold() -> f32 {
    0.0
}

const fn default_max_retries() -> u32 {
    3
}

const fn default_retry_min_wait_ms() -> u64 {
    1000
}

const fn default_retry_max_wait_ms() -> u64 {
    10_000
}

impl Default for RerankerConfig {
    fn default() -> Self {
        Self {
            model: default_model(),
            gateway_url: default_gateway_url(),
            rerank_endpoint: default_rerank_endpoint(),
            max_batch_size: default_max_batch_size(),
            max_documents: default_max_documents(),
            max_query_length: default_max_query_length(),
            max_document_length: default_max_document_length(),
            timeout_ms: default_timeout_ms(),
            score_threshold: default_score_threshold(),
            max_retries: default_max_retries(),
            retry_min_wait_ms: default_retry_min_wait_ms(),
            retry_max_wait_ms: default_retry_max_wait_ms(),
        }
    }
}

impl RerankerConfig {
    /// Create a new reranker config with defaults.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the reranker model name.
    #[must_use]
    pub fn with_model(mut self, model: impl Into<String>) -> Self {
        self.model = model.into();
        self
    }

    /// Set the LLM Gateway URL.
    #[must_use]
    pub fn with_gateway_url(mut self, url: impl Into<String>) -> Self {
        self.gateway_url = url.into();
        self
    }

    /// Set the rerank endpoint path.
    #[must_use]
    pub fn with_rerank_endpoint(mut self, endpoint: impl Into<String>) -> Self {
        self.rerank_endpoint = endpoint.into();
        self
    }

    /// Set the maximum batch size.
    #[must_use]
    pub const fn with_max_batch_size(mut self, size: usize) -> Self {
        self.max_batch_size = size;
        self
    }

    /// Set the maximum number of documents.
    #[must_use]
    pub const fn with_max_documents(mut self, max: usize) -> Self {
        self.max_documents = max;
        self
    }

    /// Set the maximum query length in tokens.
    #[must_use]
    pub const fn with_max_query_length(mut self, length: usize) -> Self {
        self.max_query_length = length;
        self
    }

    /// Set the maximum document length in tokens.
    #[must_use]
    pub const fn with_max_document_length(mut self, length: usize) -> Self {
        self.max_document_length = length;
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

    /// Set the minimum score threshold.
    #[must_use]
    pub const fn with_score_threshold(mut self, threshold: f32) -> Self {
        self.score_threshold = threshold;
        self
    }

    /// Set the maximum number of retries.
    #[must_use]
    pub const fn with_max_retries(mut self, retries: u32) -> Self {
        self.max_retries = retries;
        self
    }

    /// Set the minimum retry wait time in milliseconds.
    #[must_use]
    pub const fn with_retry_min_wait_ms(mut self, min_wait_ms: u64) -> Self {
        self.retry_min_wait_ms = min_wait_ms;
        self
    }

    /// Set the maximum retry wait time in milliseconds.
    #[must_use]
    pub const fn with_retry_max_wait_ms(mut self, max_wait_ms: u64) -> Self {
        self.retry_max_wait_ms = max_wait_ms;
        self
    }

    /// Get the timeout as a Duration.
    #[must_use]
    pub const fn timeout(&self) -> Duration {
        Duration::from_millis(self.timeout_ms)
    }

    /// Get the full rerank API endpoint URL.
    #[must_use]
    pub fn rerank_endpoint_url(&self) -> String {
        format!(
            "{}{}",
            self.gateway_url.trim_end_matches('/'),
            self.rerank_endpoint
        )
    }

    /// Get the maximum characters for query truncation.
    ///
    /// Uses approximate conversion: 4 characters per token.
    #[must_use]
    pub const fn max_query_chars(&self) -> usize {
        self.max_query_length * 4
    }

    /// Get the maximum characters for document truncation.
    ///
    /// Uses approximate conversion: 4 characters per token.
    #[must_use]
    pub const fn max_document_chars(&self) -> usize {
        self.max_document_length * 4
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `RERANKER_MODEL`: Model name (default: `BAAI/bge-reranker-v2-m3`)
    /// - `RERANKER_GATEWAY_URL`: LLM Gateway URL (default: `http://localhost:8004`)
    /// - `RERANKER_ENDPOINT`: Rerank endpoint path (default: `/v1/rerank`)
    /// - `RERANKER_MAX_BATCH_SIZE`: Max batch size (default: 32)
    /// - `RERANKER_MAX_DOCUMENTS`: Max documents (default: 100)
    /// - `RERANKER_MAX_QUERY_LENGTH`: Max query tokens (default: 512)
    /// - `RERANKER_MAX_DOCUMENT_LENGTH`: Max document tokens (default: 512)
    /// - `RERANKER_TIMEOUT_MS`: Timeout in milliseconds (default: 30000)
    /// - `RERANKER_SCORE_THRESHOLD`: Score threshold (default: 0.0)
    /// - `RERANKER_MAX_RETRIES`: Max retries (default: 3)
    /// - `RERANKER_RETRY_MIN_WAIT_MS`: Min retry wait (default: 1000)
    /// - `RERANKER_RETRY_MAX_WAIT_MS`: Max retry wait (default: 10000)
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(model) = std::env::var("RERANKER_MODEL") {
            config.model = model;
        }

        if let Ok(url) = std::env::var("RERANKER_GATEWAY_URL") {
            config.gateway_url = url;
        }

        if let Ok(endpoint) = std::env::var("RERANKER_ENDPOINT") {
            config.rerank_endpoint = endpoint;
        }

        if let Ok(size) = std::env::var("RERANKER_MAX_BATCH_SIZE") {
            if let Ok(s) = size.parse() {
                config.max_batch_size = s;
            }
        }

        if let Ok(max) = std::env::var("RERANKER_MAX_DOCUMENTS") {
            if let Ok(m) = max.parse() {
                config.max_documents = m;
            }
        }

        if let Ok(length) = std::env::var("RERANKER_MAX_QUERY_LENGTH") {
            if let Ok(l) = length.parse() {
                config.max_query_length = l;
            }
        }

        if let Ok(length) = std::env::var("RERANKER_MAX_DOCUMENT_LENGTH") {
            if let Ok(l) = length.parse() {
                config.max_document_length = l;
            }
        }

        if let Ok(timeout) = std::env::var("RERANKER_TIMEOUT_MS") {
            if let Ok(t) = timeout.parse() {
                config.timeout_ms = t;
            }
        }

        if let Ok(threshold) = std::env::var("RERANKER_SCORE_THRESHOLD") {
            if let Ok(t) = threshold.parse() {
                config.score_threshold = t;
            }
        }

        if let Ok(retries) = std::env::var("RERANKER_MAX_RETRIES") {
            if let Ok(r) = retries.parse() {
                config.max_retries = r;
            }
        }

        if let Ok(min_wait) = std::env::var("RERANKER_RETRY_MIN_WAIT_MS") {
            if let Ok(m) = min_wait.parse() {
                config.retry_min_wait_ms = m;
            }
        }

        if let Ok(max_wait) = std::env::var("RERANKER_RETRY_MAX_WAIT_MS") {
            if let Ok(m) = max_wait.parse() {
                config.retry_max_wait_ms = m;
            }
        }

        config
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_reranker_config_default() {
        let config = RerankerConfig::default();
        assert_eq!(config.model, "BAAI/bge-reranker-v2-m3");
        assert_eq!(config.gateway_url, "http://localhost:8004");
        assert_eq!(config.rerank_endpoint, "/v1/rerank");
        assert_eq!(config.max_batch_size, 32);
        assert_eq!(config.max_documents, 100);
        assert_eq!(config.max_query_length, 512);
        assert_eq!(config.max_document_length, 512);
        assert_eq!(config.timeout_ms, 30_000);
        assert!((config.score_threshold - 0.0).abs() < f32::EPSILON);
        assert_eq!(config.max_retries, 3);
        assert_eq!(config.retry_min_wait_ms, 1000);
        assert_eq!(config.retry_max_wait_ms, 10_000);
    }

    #[test]
    fn test_config_builder() {
        let config = RerankerConfig::new()
            .with_model("custom-model")
            .with_gateway_url("http://gateway:9000")
            .with_rerank_endpoint("/api/rerank")
            .with_max_batch_size(16)
            .with_max_documents(50)
            .with_max_query_length(256)
            .with_max_document_length(1024)
            .with_timeout(Duration::from_secs(60))
            .with_score_threshold(0.5)
            .with_max_retries(5)
            .with_retry_min_wait_ms(500)
            .with_retry_max_wait_ms(5000);

        assert_eq!(config.model, "custom-model");
        assert_eq!(config.gateway_url, "http://gateway:9000");
        assert_eq!(config.rerank_endpoint, "/api/rerank");
        assert_eq!(config.max_batch_size, 16);
        assert_eq!(config.max_documents, 50);
        assert_eq!(config.max_query_length, 256);
        assert_eq!(config.max_document_length, 1024);
        assert_eq!(config.timeout_ms, 60_000);
        assert!((config.score_threshold - 0.5).abs() < f32::EPSILON);
        assert_eq!(config.max_retries, 5);
        assert_eq!(config.retry_min_wait_ms, 500);
        assert_eq!(config.retry_max_wait_ms, 5000);
    }

    #[test]
    fn test_rerank_endpoint_url() {
        let config = RerankerConfig::new().with_gateway_url("http://gateway:8004");
        assert_eq!(
            config.rerank_endpoint_url(),
            "http://gateway:8004/v1/rerank"
        );

        // Test with trailing slash
        let config = RerankerConfig::new().with_gateway_url("http://gateway:8004/");
        assert_eq!(
            config.rerank_endpoint_url(),
            "http://gateway:8004/v1/rerank"
        );
    }

    #[test]
    fn test_max_chars_calculation() {
        let config = RerankerConfig::new()
            .with_max_query_length(512)
            .with_max_document_length(256);

        assert_eq!(config.max_query_chars(), 2048);
        assert_eq!(config.max_document_chars(), 1024);
    }

    #[test]
    fn test_timeout_conversion() {
        let config = RerankerConfig::new().with_timeout_ms(15_000);
        assert_eq!(config.timeout(), Duration::from_millis(15_000));

        let config = RerankerConfig::new().with_timeout(Duration::from_secs(20));
        assert_eq!(config.timeout_ms, 20_000);
    }

    #[test]
    fn test_config_serialization() {
        let config = RerankerConfig::new()
            .with_model("test-model")
            .with_score_threshold(0.3);

        let json = serde_json::to_string(&config).unwrap();
        assert!(json.contains("test-model"));
        assert!(json.contains("0.3"));

        let deserialized: RerankerConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.model, "test-model");
        assert!((deserialized.score_threshold - 0.3).abs() < f32::EPSILON);
    }
}

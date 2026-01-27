//! Configuration for the embedding client.
//!
//! This module provides configuration structures for the embedding
//! HTTP client that calls the embedding service.

use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Configuration for the embedding client.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingClientConfig {
    /// Base URL of the embedding service (e.g., "http://localhost:8080").
    #[serde(default = "default_url")]
    pub url: String,

    /// API endpoint for embeddings (default: "/v1/embeddings").
    #[serde(default = "default_endpoint")]
    pub endpoint: String,

    /// Model name to use (default: "all-MiniLM-L6-v2").
    #[serde(default = "default_model")]
    pub model: String,

    /// Request timeout in milliseconds (default: 30000).
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,

    /// Maximum number of retry attempts (default: 3).
    #[serde(default = "default_max_retries")]
    pub max_retries: u32,

    /// Base delay between retries in milliseconds (default: 1000).
    #[serde(default = "default_retry_delay_ms")]
    pub retry_delay_ms: u64,
}

fn default_url() -> String {
    "http://localhost:8080".into()
}

fn default_endpoint() -> String {
    "/v1/embeddings".into()
}

fn default_model() -> String {
    "all-MiniLM-L6-v2".into()
}

const fn default_timeout_ms() -> u64 {
    30_000
}

const fn default_max_retries() -> u32 {
    3
}

const fn default_retry_delay_ms() -> u64 {
    1000
}

impl Default for EmbeddingClientConfig {
    fn default() -> Self {
        Self {
            url: default_url(),
            endpoint: default_endpoint(),
            model: default_model(),
            timeout_ms: default_timeout_ms(),
            max_retries: default_max_retries(),
            retry_delay_ms: default_retry_delay_ms(),
        }
    }
}

impl EmbeddingClientConfig {
    /// Create a new configuration with the given URL.
    #[must_use]
    pub fn new(url: impl Into<String>) -> Self {
        Self {
            url: url.into(),
            ..Self::default()
        }
    }

    /// Set the API endpoint.
    #[must_use]
    pub fn with_endpoint(mut self, endpoint: impl Into<String>) -> Self {
        self.endpoint = endpoint.into();
        self
    }

    /// Set the model name.
    #[must_use]
    pub fn with_model(mut self, model: impl Into<String>) -> Self {
        self.model = model.into();
        self
    }

    /// Set the request timeout in milliseconds.
    #[must_use]
    pub const fn with_timeout_ms(mut self, timeout_ms: u64) -> Self {
        self.timeout_ms = timeout_ms;
        self
    }

    /// Set the request timeout.
    #[must_use]
    #[allow(clippy::cast_possible_truncation, clippy::missing_const_for_fn)]
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout_ms = timeout.as_millis() as u64;
        self
    }

    /// Set the maximum retry attempts.
    #[must_use]
    pub const fn with_max_retries(mut self, max_retries: u32) -> Self {
        self.max_retries = max_retries;
        self
    }

    /// Set the retry delay in milliseconds.
    #[must_use]
    pub const fn with_retry_delay_ms(mut self, retry_delay_ms: u64) -> Self {
        self.retry_delay_ms = retry_delay_ms;
        self
    }

    /// Set the retry delay.
    #[must_use]
    #[allow(clippy::cast_possible_truncation, clippy::missing_const_for_fn)]
    pub fn with_retry_delay(mut self, retry_delay: Duration) -> Self {
        self.retry_delay_ms = retry_delay.as_millis() as u64;
        self
    }

    /// Get the timeout as a Duration.
    #[must_use]
    pub const fn timeout(&self) -> Duration {
        Duration::from_millis(self.timeout_ms)
    }

    /// Get the retry delay as a Duration.
    #[must_use]
    pub const fn retry_delay(&self) -> Duration {
        Duration::from_millis(self.retry_delay_ms)
    }

    /// Get the full URL for the embeddings endpoint.
    #[must_use]
    pub fn embeddings_url(&self) -> String {
        format!("{}{}", self.url.trim_end_matches('/'), self.endpoint)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_defaults() {
        let config = EmbeddingClientConfig::default();
        assert_eq!(config.url, "http://localhost:8080");
        assert_eq!(config.endpoint, "/v1/embeddings");
        assert_eq!(config.model, "all-MiniLM-L6-v2");
        assert_eq!(config.timeout_ms, 30_000);
        assert_eq!(config.max_retries, 3);
        assert_eq!(config.retry_delay_ms, 1000);
    }

    #[test]
    fn test_config_new() {
        let config = EmbeddingClientConfig::new("http://embed:8080");
        assert_eq!(config.url, "http://embed:8080");
        assert_eq!(config.endpoint, "/v1/embeddings");
        assert_eq!(config.model, "all-MiniLM-L6-v2");
    }

    #[test]
    fn test_config_builder() {
        let config = EmbeddingClientConfig::new("http://embed:8080")
            .with_model("custom-model")
            .with_timeout(Duration::from_secs(60))
            .with_max_retries(5)
            .with_retry_delay(Duration::from_secs(2));

        assert_eq!(config.url, "http://embed:8080");
        assert_eq!(config.model, "custom-model");
        assert_eq!(config.timeout_ms, 60_000);
        assert_eq!(config.max_retries, 5);
        assert_eq!(config.retry_delay_ms, 2000);
    }

    #[test]
    fn test_embeddings_url() {
        let config = EmbeddingClientConfig::new("http://localhost:8080");
        assert_eq!(
            config.embeddings_url(),
            "http://localhost:8080/v1/embeddings"
        );

        // With trailing slash
        let config = EmbeddingClientConfig::new("http://localhost:8080/");
        assert_eq!(
            config.embeddings_url(),
            "http://localhost:8080/v1/embeddings"
        );
    }

    #[test]
    fn test_timeout_conversion() {
        let config = EmbeddingClientConfig::default().with_timeout_ms(5000);
        assert_eq!(config.timeout(), Duration::from_millis(5000));

        let config = EmbeddingClientConfig::default().with_timeout(Duration::from_secs(10));
        assert_eq!(config.timeout_ms, 10_000);
    }

    #[test]
    fn test_retry_delay_conversion() {
        let config = EmbeddingClientConfig::default().with_retry_delay_ms(2000);
        assert_eq!(config.retry_delay(), Duration::from_millis(2000));

        let config = EmbeddingClientConfig::default().with_retry_delay(Duration::from_secs(3));
        assert_eq!(config.retry_delay_ms, 3000);
    }

    #[test]
    fn test_custom_endpoint() {
        let config = EmbeddingClientConfig::new("http://localhost:8080")
            .with_endpoint("/api/embed");
        assert_eq!(config.embeddings_url(), "http://localhost:8080/api/embed");
    }

    #[test]
    fn test_config_serialization() {
        let config = EmbeddingClientConfig::new("http://embedding:8080")
            .with_model("custom-model")
            .with_timeout_ms(10_000);

        let json = serde_json::to_string(&config).unwrap();
        assert!(json.contains("embedding:8080"));
        assert!(json.contains("custom-model"));
        assert!(json.contains("10000"));

        let deserialized: EmbeddingClientConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.url, "http://embedding:8080");
        assert_eq!(deserialized.model, "custom-model");
        assert_eq!(deserialized.timeout_ms, 10_000);
    }

    #[test]
    fn test_config_deserialization_with_defaults() {
        let json = r#"{"url": "http://custom:9000"}"#;
        let config: EmbeddingClientConfig = serde_json::from_str(json).unwrap();

        assert_eq!(config.url, "http://custom:9000");
        // Defaults should be applied
        assert_eq!(config.endpoint, "/v1/embeddings");
        assert_eq!(config.model, "all-MiniLM-L6-v2");
        assert_eq!(config.timeout_ms, 30_000);
        assert_eq!(config.max_retries, 3);
        assert_eq!(config.retry_delay_ms, 1000);
    }
}

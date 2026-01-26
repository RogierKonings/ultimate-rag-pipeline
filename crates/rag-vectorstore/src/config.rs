//! Vector store configuration.

use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Vector store configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VectorStoreConfig {
    /// Qdrant server URL.
    pub url: String,

    /// API key for authentication (optional).
    pub api_key: Option<String>,

    /// Connection timeout.
    #[serde(default = "default_connect_timeout")]
    #[serde(with = "humantime_serde")]
    pub connect_timeout: Duration,

    /// Request timeout.
    #[serde(default = "default_timeout")]
    #[serde(with = "humantime_serde")]
    pub timeout: Duration,

    /// Default collection name.
    pub default_collection: Option<String>,

    /// HNSW index parameters.
    #[serde(default)]
    pub hnsw_config: HnswConfig,
}

fn default_connect_timeout() -> Duration {
    Duration::from_secs(5)
}

fn default_timeout() -> Duration {
    Duration::from_secs(30)
}

/// HNSW index configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HnswConfig {
    /// Number of edges per node in the HNSW graph.
    #[serde(default = "default_m")]
    pub m: u64,

    /// Number of neighbors to consider during index construction.
    #[serde(default = "default_ef_construct")]
    pub ef_construct: u64,
}

fn default_m() -> u64 {
    16
}

fn default_ef_construct() -> u64 {
    100
}

impl Default for HnswConfig {
    fn default() -> Self {
        Self {
            m: default_m(),
            ef_construct: default_ef_construct(),
        }
    }
}

impl Default for VectorStoreConfig {
    fn default() -> Self {
        Self {
            url: "http://localhost:6333".into(),
            api_key: None,
            connect_timeout: default_connect_timeout(),
            timeout: default_timeout(),
            default_collection: None,
            hnsw_config: HnswConfig::default(),
        }
    }
}

impl VectorStoreConfig {
    /// Create a new config with URL.
    #[must_use]
    pub fn new(url: impl Into<String>) -> Self {
        Self {
            url: url.into(),
            ..Default::default()
        }
    }

    /// Set the API key.
    #[must_use]
    pub fn with_api_key(mut self, key: impl Into<String>) -> Self {
        self.api_key = Some(key.into());
        self
    }

    /// Set the default collection.
    #[must_use]
    pub fn with_default_collection(mut self, collection: impl Into<String>) -> Self {
        self.default_collection = Some(collection.into());
        self
    }

    /// Set the timeout.
    #[must_use]
    pub const fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `QDRANT_URL`: Server URL
    /// - `QDRANT_API_KEY`: API key
    /// - `QDRANT_COLLECTION`: Default collection
    /// - `QDRANT_TIMEOUT_SECS`: Request timeout in seconds
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(url) = std::env::var("QDRANT_URL") {
            config.url = url;
        }

        if let Ok(key) = std::env::var("QDRANT_API_KEY") {
            config.api_key = Some(key);
        }

        if let Ok(collection) = std::env::var("QDRANT_COLLECTION") {
            config.default_collection = Some(collection);
        }

        if let Ok(timeout) = std::env::var("QDRANT_TIMEOUT_SECS") {
            if let Ok(secs) = timeout.parse::<u64>() {
                config.timeout = Duration::from_secs(secs);
            }
        }

        config
    }
}

/// Serde module for humantime duration parsing.
mod humantime_serde {
    use serde::{Deserialize, Deserializer, Serializer};
    use std::time::Duration;

    pub fn serialize<S>(duration: &Duration, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_u64(duration.as_secs())
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Duration, D::Error>
    where
        D: Deserializer<'de>,
    {
        let secs = u64::deserialize(deserializer)?;
        Ok(Duration::from_secs(secs))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = VectorStoreConfig::default();
        assert_eq!(config.url, "http://localhost:6333");
        assert_eq!(config.hnsw_config.m, 16);
        assert_eq!(config.hnsw_config.ef_construct, 100);
    }

    #[test]
    fn test_config_builder() {
        let config = VectorStoreConfig::new("http://qdrant:6333")
            .with_api_key("secret")
            .with_default_collection("documents");

        assert_eq!(config.url, "http://qdrant:6333");
        assert_eq!(config.api_key, Some("secret".into()));
        assert_eq!(config.default_collection, Some("documents".into()));
    }
}

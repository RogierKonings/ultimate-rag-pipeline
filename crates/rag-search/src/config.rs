//! Search configuration.

use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Search client configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchConfig {
    /// OpenSearch URL (e.g., "http://localhost:9200").
    pub url: String,

    /// Username for authentication (optional).
    pub username: Option<String>,

    /// Password for authentication (optional).
    pub password: Option<String>,

    /// Request timeout.
    #[serde(default = "default_timeout")]
    #[serde(with = "duration_secs")]
    pub timeout: Duration,

    /// Default index name.
    #[serde(default = "default_index")]
    pub default_index: String,

    /// Disable certificate verification (for development).
    #[serde(default)]
    pub danger_accept_invalid_certs: bool,

    /// Number of shards for new indices.
    #[serde(default = "default_shards")]
    pub number_of_shards: u32,

    /// Number of replicas for new indices.
    #[serde(default = "default_replicas")]
    pub number_of_replicas: u32,
}

fn default_index() -> String {
    "documents".to_string()
}

fn default_shards() -> u32 {
    1
}

fn default_replicas() -> u32 {
    0
}

fn default_timeout() -> Duration {
    Duration::from_secs(30)
}

impl Default for SearchConfig {
    fn default() -> Self {
        Self {
            url: "http://localhost:9200".into(),
            username: None,
            password: None,
            timeout: default_timeout(),
            default_index: default_index(),
            danger_accept_invalid_certs: false,
            number_of_shards: default_shards(),
            number_of_replicas: default_replicas(),
        }
    }
}

impl SearchConfig {
    /// Create a new config with URL.
    #[must_use]
    pub fn new(url: impl Into<String>) -> Self {
        Self {
            url: url.into(),
            ..Default::default()
        }
    }

    /// Set authentication credentials.
    #[must_use]
    pub fn with_credentials(
        mut self,
        username: impl Into<String>,
        password: impl Into<String>,
    ) -> Self {
        self.username = Some(username.into());
        self.password = Some(password.into());
        self
    }

    /// Set the default index.
    #[must_use]
    pub fn with_default_index(mut self, index: impl Into<String>) -> Self {
        self.default_index = index.into();
        self
    }

    /// Set the timeout.
    #[must_use]
    pub const fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    /// Disable certificate verification (development only).
    #[must_use]
    pub const fn danger_accept_invalid_certs(mut self) -> Self {
        self.danger_accept_invalid_certs = true;
        self
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `OPENSEARCH_URL`: Server URL
    /// - `OPENSEARCH_USERNAME`: Username
    /// - `OPENSEARCH_PASSWORD`: Password
    /// - `OPENSEARCH_INDEX`: Default index
    /// - `OPENSEARCH_TIMEOUT_SECS`: Request timeout in seconds
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(url) = std::env::var("OPENSEARCH_URL") {
            config.url = url;
        }

        if let Ok(username) = std::env::var("OPENSEARCH_USERNAME") {
            config.username = Some(username);
        }

        if let Ok(password) = std::env::var("OPENSEARCH_PASSWORD") {
            config.password = Some(password);
        }

        if let Ok(index) = std::env::var("OPENSEARCH_INDEX") {
            config.default_index = index;
        }

        if let Ok(timeout) = std::env::var("OPENSEARCH_TIMEOUT_SECS") {
            if let Ok(secs) = timeout.parse::<u64>() {
                config.timeout = Duration::from_secs(secs);
            }
        }

        config
    }
}

/// Serde module for duration in seconds.
mod duration_secs {
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
        let config = SearchConfig::default();
        assert_eq!(config.url, "http://localhost:9200");
        assert!(config.username.is_none());
    }

    #[test]
    fn test_config_builder() {
        let config = SearchConfig::new("http://opensearch:9200")
            .with_credentials("admin", "admin")
            .with_default_index("documents");

        assert_eq!(config.url, "http://opensearch:9200");
        assert_eq!(config.username, Some("admin".into()));
        assert_eq!(config.default_index, "documents");
    }
}

//! Cache configuration.

use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Configuration for the cache client.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CacheConfig {
    /// Redis connection URL
    #[serde(default = "default_url")]
    pub url: String,

    /// Connection pool size
    #[serde(default = "default_pool_size")]
    pub pool_size: u32,

    /// Connection timeout in milliseconds
    #[serde(default = "default_connect_timeout")]
    pub connect_timeout_ms: u64,

    /// Command timeout in milliseconds
    #[serde(default = "default_command_timeout")]
    pub command_timeout_ms: u64,

    /// Default TTL for cache entries in seconds
    #[serde(default = "default_ttl")]
    pub default_ttl_secs: u64,

    /// TTL for embedding cache in seconds (7 days)
    #[serde(default = "default_embedding_ttl")]
    pub embedding_ttl_secs: u64,

    /// TTL for query cache in seconds (5 minutes)
    #[serde(default = "default_query_ttl")]
    pub query_ttl_secs: u64,

    /// Key prefix for all cache entries
    #[serde(default = "default_prefix")]
    pub key_prefix: String,
}

fn default_url() -> String {
    "redis://127.0.0.1:6379".to_string()
}

const fn default_pool_size() -> u32 {
    5
}

const fn default_connect_timeout() -> u64 {
    5000
}

const fn default_command_timeout() -> u64 {
    5000
}

const fn default_ttl() -> u64 {
    3600 // 1 hour
}

const fn default_embedding_ttl() -> u64 {
    604_800 // 7 days
}

const fn default_query_ttl() -> u64 {
    300 // 5 minutes
}

fn default_prefix() -> String {
    String::new()
}

impl Default for CacheConfig {
    fn default() -> Self {
        Self {
            url: default_url(),
            pool_size: default_pool_size(),
            connect_timeout_ms: default_connect_timeout(),
            command_timeout_ms: default_command_timeout(),
            default_ttl_secs: default_ttl(),
            embedding_ttl_secs: default_embedding_ttl(),
            query_ttl_secs: default_query_ttl(),
            key_prefix: default_prefix(),
        }
    }
}

impl CacheConfig {
    /// Create a new config from a Redis URL.
    #[must_use]
    pub fn new(url: impl Into<String>) -> Self {
        Self {
            url: url.into(),
            ..Default::default()
        }
    }

    /// Get the connection timeout as a Duration.
    #[must_use]
    pub const fn connect_timeout(&self) -> Duration {
        Duration::from_millis(self.connect_timeout_ms)
    }

    /// Get the command timeout as a Duration.
    #[must_use]
    pub const fn command_timeout(&self) -> Duration {
        Duration::from_millis(self.command_timeout_ms)
    }

    /// Get the default TTL as a Duration.
    #[must_use]
    pub const fn default_ttl(&self) -> Duration {
        Duration::from_secs(self.default_ttl_secs)
    }

    /// Get the embedding TTL as a Duration.
    #[must_use]
    pub const fn embedding_ttl(&self) -> Duration {
        Duration::from_secs(self.embedding_ttl_secs)
    }

    /// Get the query TTL as a Duration.
    #[must_use]
    pub const fn query_ttl(&self) -> Duration {
        Duration::from_secs(self.query_ttl_secs)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = CacheConfig::default();
        assert_eq!(config.url, "redis://127.0.0.1:6379");
        assert_eq!(config.pool_size, 5);
        assert_eq!(config.embedding_ttl_secs, 604_800);
    }

    #[test]
    fn test_durations() {
        let config = CacheConfig::default();
        assert_eq!(config.connect_timeout(), Duration::from_millis(5000));
        assert_eq!(config.embedding_ttl(), Duration::from_secs(604_800));
    }
}

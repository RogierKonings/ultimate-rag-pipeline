//! Common configuration types shared across services.

use secrecy::{ExposeSecret, Secret};
use serde::{Deserialize, Serialize};
use std::fmt;
use url::Url;
use validator::Validate;

/// Log level configuration.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum LogLevel {
    /// Trace level (most verbose)
    Trace,
    /// Debug level
    Debug,
    /// Info level (default)
    #[default]
    Info,
    /// Warning level
    Warn,
    /// Error level (least verbose)
    Error,
}

impl fmt::Display for LogLevel {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Trace => write!(f, "trace"),
            Self::Debug => write!(f, "debug"),
            Self::Info => write!(f, "info"),
            Self::Warn => write!(f, "warn"),
            Self::Error => write!(f, "error"),
        }
    }
}

impl From<LogLevel> for tracing::Level {
    fn from(level: LogLevel) -> Self {
        match level {
            LogLevel::Trace => Self::TRACE,
            LogLevel::Debug => Self::DEBUG,
            LogLevel::Info => Self::INFO,
            LogLevel::Warn => Self::WARN,
            LogLevel::Error => Self::ERROR,
        }
    }
}

/// Base service configuration shared by all services.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
pub struct ServiceConfig {
    /// Service host address
    #[serde(default = "default_host")]
    pub host: String,

    /// Service port
    #[validate(range(min = 1, max = 65535))]
    #[serde(default = "default_port")]
    pub port: u16,

    /// Enable debug mode
    #[serde(default)]
    pub debug: bool,

    /// Log level
    #[serde(default)]
    pub log_level: LogLevel,

    /// Service name for tracing
    #[serde(default = "default_service_name")]
    pub service_name: String,

    /// Environment (dev, staging, prod)
    #[serde(default = "default_environment")]
    pub environment: String,
}

fn default_host() -> String {
    "0.0.0.0".to_string()
}

const fn default_port() -> u16 {
    8000
}

fn default_service_name() -> String {
    "rag-service".to_string()
}

fn default_environment() -> String {
    "development".to_string()
}

impl Default for ServiceConfig {
    fn default() -> Self {
        Self {
            host: default_host(),
            port: default_port(),
            debug: false,
            log_level: LogLevel::default(),
            service_name: default_service_name(),
            environment: default_environment(),
        }
    }
}

/// Database configuration.
#[derive(Clone, Deserialize, Validate)]
pub struct DatabaseConfig {
    /// `PostgreSQL` connection URL
    #[serde(alias = "database_url")]
    url: Secret<String>,

    /// Maximum connections in the pool
    #[validate(range(min = 1, max = 100))]
    #[serde(default = "default_max_connections")]
    pub max_connections: u32,

    /// Minimum connections to keep open
    #[validate(range(min = 0, max = 50))]
    #[serde(default = "default_min_connections")]
    pub min_connections: u32,

    /// Connection timeout in seconds
    #[validate(range(min = 1, max = 60))]
    #[serde(default = "default_connect_timeout")]
    pub connect_timeout_secs: u32,

    /// Idle connection timeout in seconds
    #[validate(range(min = 60, max = 3600))]
    #[serde(default = "default_idle_timeout")]
    pub idle_timeout_secs: u32,

    /// Enable statement caching
    #[serde(default = "default_true")]
    pub statement_cache_enabled: bool,
}

const fn default_max_connections() -> u32 {
    10
}

const fn default_min_connections() -> u32 {
    1
}

const fn default_connect_timeout() -> u32 {
    5
}

const fn default_idle_timeout() -> u32 {
    300
}

const fn default_true() -> bool {
    true
}

impl DatabaseConfig {
    /// Get the database URL (exposes secret).
    #[must_use]
    pub fn url(&self) -> &str {
        self.url.expose_secret()
    }

    /// Parse and return the URL (exposes secret).
    ///
    /// # Errors
    ///
    /// Returns an error if the URL is invalid.
    pub fn parsed_url(&self) -> Result<Url, url::ParseError> {
        Url::parse(self.url.expose_secret())
    }
}

impl fmt::Debug for DatabaseConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("DatabaseConfig")
            .field("url", &"[REDACTED]")
            .field("max_connections", &self.max_connections)
            .field("min_connections", &self.min_connections)
            .field("connect_timeout_secs", &self.connect_timeout_secs)
            .field("idle_timeout_secs", &self.idle_timeout_secs)
            .field("statement_cache_enabled", &self.statement_cache_enabled)
            .finish()
    }
}

/// Redis configuration.
#[derive(Clone, Deserialize, Validate)]
pub struct RedisConfig {
    /// Redis connection URL
    #[serde(alias = "redis_url")]
    url: Secret<String>,

    /// Maximum connections in the pool
    #[validate(range(min = 1, max = 100))]
    #[serde(default = "default_redis_pool_size")]
    pub pool_size: u32,

    /// Connection timeout in milliseconds
    #[validate(range(min = 100, max = 30000))]
    #[serde(default = "default_redis_timeout")]
    pub connect_timeout_ms: u32,

    /// Command timeout in milliseconds
    #[validate(range(min = 100, max = 30000))]
    #[serde(default = "default_redis_timeout")]
    pub command_timeout_ms: u32,
}

const fn default_redis_pool_size() -> u32 {
    5
}

const fn default_redis_timeout() -> u32 {
    5000
}

impl RedisConfig {
    /// Get the Redis URL (exposes secret).
    #[must_use]
    pub fn url(&self) -> &str {
        self.url.expose_secret()
    }
}

impl fmt::Debug for RedisConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("RedisConfig")
            .field("url", &"[REDACTED]")
            .field("pool_size", &self.pool_size)
            .field("connect_timeout_ms", &self.connect_timeout_ms)
            .field("command_timeout_ms", &self.command_timeout_ms)
            .finish()
    }
}

/// Qdrant vector store configuration.
#[derive(Debug, Clone, Deserialize, Validate)]
pub struct QdrantConfig {
    /// Qdrant server URL
    #[serde(alias = "qdrant_url", default = "default_qdrant_url")]
    pub url: String,

    /// API key (optional)
    #[serde(default)]
    api_key: Option<Secret<String>>,

    /// Default collection name
    #[serde(default = "default_collection")]
    pub collection: String,

    /// Connection timeout in milliseconds
    #[validate(range(min = 100, max = 30000))]
    #[serde(default = "default_qdrant_timeout")]
    pub timeout_ms: u32,

    /// Number of retries for failed operations
    #[validate(range(max = 5))]
    #[serde(default = "default_retries")]
    pub retries: u32,
}

fn default_qdrant_url() -> String {
    "http://localhost:6333".to_string()
}

fn default_collection() -> String {
    "documents".to_string()
}

const fn default_qdrant_timeout() -> u32 {
    3000
}

const fn default_retries() -> u32 {
    2
}

impl Default for QdrantConfig {
    fn default() -> Self {
        Self {
            url: default_qdrant_url(),
            api_key: None,
            collection: default_collection(),
            timeout_ms: default_qdrant_timeout(),
            retries: default_retries(),
        }
    }
}

impl QdrantConfig {
    /// Get the API key if configured (exposes secret).
    #[must_use]
    pub fn api_key(&self) -> Option<&str> {
        self.api_key.as_ref().map(|s| s.expose_secret().as_str())
    }
}

/// `OpenSearch` configuration.
#[derive(Clone, Deserialize, Validate)]
pub struct OpenSearchConfig {
    /// `OpenSearch` server URL
    #[serde(alias = "opensearch_url", default = "default_opensearch_url")]
    pub url: String,

    /// Username for authentication
    #[serde(default)]
    username: Option<Secret<String>>,

    /// Password for authentication
    #[serde(default)]
    password: Option<Secret<String>>,

    /// Default index name
    #[serde(default = "default_index")]
    pub index: String,

    /// Connection timeout in milliseconds
    #[validate(range(min = 100, max = 30000))]
    #[serde(default = "default_opensearch_timeout")]
    pub timeout_ms: u32,
}

fn default_opensearch_url() -> String {
    "http://localhost:9200".to_string()
}

fn default_index() -> String {
    "documents".to_string()
}

const fn default_opensearch_timeout() -> u32 {
    3000
}

impl Default for OpenSearchConfig {
    fn default() -> Self {
        Self {
            url: default_opensearch_url(),
            username: None,
            password: None,
            index: default_index(),
            timeout_ms: default_opensearch_timeout(),
        }
    }
}

impl OpenSearchConfig {
    /// Get the username if configured (exposes secret).
    #[must_use]
    pub fn username(&self) -> Option<&str> {
        self.username.as_ref().map(|s| s.expose_secret().as_str())
    }

    /// Get the password if configured (exposes secret).
    #[must_use]
    pub fn password(&self) -> Option<&str> {
        self.password.as_ref().map(|s| s.expose_secret().as_str())
    }
}

impl fmt::Debug for OpenSearchConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("OpenSearchConfig")
            .field("url", &self.url)
            .field("username", &self.username.as_ref().map(|_| "[REDACTED]"))
            .field("password", &self.password.as_ref().map(|_| "[REDACTED]"))
            .field("index", &self.index)
            .field("timeout_ms", &self.timeout_ms)
            .finish()
    }
}

/// MinIO/S3 storage configuration.
#[derive(Clone, Deserialize, Validate)]
pub struct StorageConfig {
    /// S3/MinIO endpoint URL
    #[serde(alias = "minio_url")]
    pub url: String,

    /// Access key
    access_key: Secret<String>,

    /// Secret key
    secret_key: Secret<String>,

    /// Default bucket name
    #[serde(default = "default_bucket")]
    pub bucket: String,

    /// AWS region (for S3)
    #[serde(default = "default_region")]
    pub region: String,

    /// Use path-style addressing (required for `MinIO`)
    #[serde(default = "default_true")]
    pub path_style: bool,
}

fn default_bucket() -> String {
    "rag-documents".to_string()
}

fn default_region() -> String {
    "us-east-1".to_string()
}

impl StorageConfig {
    /// Get the access key (exposes secret).
    #[must_use]
    pub fn access_key(&self) -> &str {
        self.access_key.expose_secret()
    }

    /// Get the secret key (exposes secret).
    #[must_use]
    pub fn secret_key(&self) -> &str {
        self.secret_key.expose_secret()
    }
}

impl fmt::Debug for StorageConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("StorageConfig")
            .field("url", &self.url)
            .field("access_key", &"[REDACTED]")
            .field("secret_key", &"[REDACTED]")
            .field("bucket", &self.bucket)
            .field("region", &self.region)
            .field("path_style", &self.path_style)
            .finish()
    }
}

/// Embedding service configuration.
#[derive(Debug, Clone, Deserialize, Validate)]
pub struct EmbeddingConfig {
    /// Embedding service URL
    pub url: String,

    /// Model name
    #[serde(default = "default_embedding_model")]
    pub model: String,

    /// Embedding dimensions
    #[validate(range(min = 1, max = 4096))]
    #[serde(default = "default_embedding_dimensions")]
    pub dimensions: u32,

    /// Batch size for embedding requests
    #[validate(range(min = 1, max = 64))]
    #[serde(default = "default_batch_size")]
    pub batch_size: u32,

    /// Request timeout in milliseconds
    #[validate(range(min = 1000, max = 60000))]
    #[serde(default = "default_embedding_timeout")]
    pub timeout_ms: u32,
}

fn default_embedding_model() -> String {
    "all-MiniLM-L6-v2".to_string()
}

const fn default_embedding_dimensions() -> u32 {
    384
}

const fn default_batch_size() -> u32 {
    32
}

const fn default_embedding_timeout() -> u32 {
    5000
}

impl Default for EmbeddingConfig {
    fn default() -> Self {
        Self {
            url: "http://localhost:8080".to_string(),
            model: default_embedding_model(),
            dimensions: default_embedding_dimensions(),
            batch_size: default_batch_size(),
            timeout_ms: default_embedding_timeout(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_log_level_display() {
        assert_eq!(LogLevel::Info.to_string(), "info");
        assert_eq!(LogLevel::Debug.to_string(), "debug");
    }

    #[test]
    fn test_service_config_default() {
        let config = ServiceConfig::default();
        assert_eq!(config.host, "0.0.0.0");
        assert_eq!(config.port, 8000);
        assert!(!config.debug);
    }

    #[test]
    fn test_embedding_config_default() {
        let config = EmbeddingConfig::default();
        assert_eq!(config.dimensions, 384);
        assert_eq!(config.batch_size, 32);
    }

    #[test]
    fn test_database_config_debug_redacts_url() {
        let json = r#"{"url": "postgresql://user:pass@localhost/db"}"#;
        let config: DatabaseConfig = serde_json::from_str(json).unwrap();
        let debug_str = format!("{config:?}");
        assert!(debug_str.contains("[REDACTED]"));
        assert!(!debug_str.contains("pass"));
    }
}

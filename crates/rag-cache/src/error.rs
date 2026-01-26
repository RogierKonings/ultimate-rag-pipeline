//! Cache error types.

use thiserror::Error;

/// Result type for cache operations.
pub type Result<T> = std::result::Result<T, CacheError>;

/// Errors that can occur during cache operations.
#[derive(Error, Debug)]
pub enum CacheError {
    /// Connection to Redis failed
    #[error("Connection error: {0}")]
    Connection(String),

    /// Redis command failed
    #[error("Redis error: {0}")]
    Redis(#[from] redis::RedisError),

    /// Serialization/deserialization failed
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    /// Key not found
    #[error("Key not found: {0}")]
    NotFound(String),

    /// Invalid key format
    #[error("Invalid key format: {0}")]
    InvalidKey(String),

    /// Operation timed out
    #[error("Operation timed out after {0}ms")]
    Timeout(u64),

    /// Pool exhausted
    #[error("Connection pool exhausted")]
    PoolExhausted,
}

impl CacheError {
    /// Check if this error is retriable.
    #[must_use]
    pub const fn is_retriable(&self) -> bool {
        matches!(
            self,
            Self::Connection(_) | Self::Timeout(_) | Self::PoolExhausted
        )
    }

    /// Create a connection error.
    pub fn connection(msg: impl Into<String>) -> Self {
        Self::Connection(msg.into())
    }

    /// Create a not found error.
    pub fn not_found(key: impl Into<String>) -> Self {
        Self::NotFound(key.into())
    }
}

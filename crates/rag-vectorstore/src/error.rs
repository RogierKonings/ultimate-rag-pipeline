//! Error types for vector store operations.

use thiserror::Error;

/// Result type for vector store operations.
pub type Result<T> = std::result::Result<T, VectorStoreError>;

/// Vector store operation errors.
#[derive(Debug, Error)]
pub enum VectorStoreError {
    /// Collection not found.
    #[error("Collection not found: {0}")]
    CollectionNotFound(String),

    /// Collection already exists.
    #[error("Collection already exists: {0}")]
    CollectionExists(String),

    /// Point not found.
    #[error("Point not found: {0}")]
    PointNotFound(String),

    /// Invalid vector dimension.
    #[error("Invalid vector dimension: expected {expected}, got {actual}")]
    DimensionMismatch { expected: usize, actual: usize },

    /// Connection error.
    #[error("Connection error: {0}")]
    Connection(String),

    /// Qdrant API error.
    #[error("Qdrant error: {0}")]
    Qdrant(String),

    /// Configuration error.
    #[error("Configuration error: {0}")]
    Config(String),

    /// Timeout error.
    #[error("Operation timed out")]
    Timeout,

    /// Serialization error.
    #[error("Serialization error: {0}")]
    Serialization(String),
}

impl From<anyhow::Error> for VectorStoreError {
    fn from(err: anyhow::Error) -> Self {
        Self::Qdrant(err.to_string())
    }
}

impl From<serde_json::Error> for VectorStoreError {
    fn from(err: serde_json::Error) -> Self {
        Self::Serialization(err.to_string())
    }
}

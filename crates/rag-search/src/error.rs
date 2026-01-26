//! Error types for search operations.

use thiserror::Error;

/// Result type for search operations.
pub type Result<T> = std::result::Result<T, SearchError>;

/// Search operation errors.
#[derive(Debug, Error)]
pub enum SearchError {
    /// Index operation error.
    #[error("Index error: {0}")]
    Index(String),

    /// Index not found.
    #[error("Index not found: {0}")]
    IndexNotFound(String),

    /// Index already exists.
    #[error("Index already exists: {0}")]
    IndexExists(String),

    /// Document not found.
    #[error("Document not found: {index}/{id}")]
    DocumentNotFound { index: String, id: String },

    /// Connection error.
    #[error("Connection error: {0}")]
    Connection(String),

    /// OpenSearch error.
    #[error("OpenSearch error: {0}")]
    OpenSearch(String),

    /// Configuration error.
    #[error("Configuration error: {0}")]
    Config(String),

    /// Serialization error.
    #[error("Serialization error: {0}")]
    Serialization(String),

    /// Query error.
    #[error("Query error: {0}")]
    Query(String),

    /// Timeout error.
    #[error("Operation timed out")]
    Timeout,
}

impl From<opensearch::Error> for SearchError {
    fn from(err: opensearch::Error) -> Self {
        Self::OpenSearch(err.to_string())
    }
}

impl From<serde_json::Error> for SearchError {
    fn from(err: serde_json::Error) -> Self {
        Self::Serialization(err.to_string())
    }
}

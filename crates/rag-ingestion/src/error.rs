//! Error types for the ingestion crate.

use thiserror::Error;

/// Errors that can occur during ingestion operations.
#[derive(Debug, Error)]
pub enum Error {
    /// Failed to parse document content.
    #[error("Parse error: {0}")]
    Parse(String),

    /// Failed to chunk document.
    #[error("Chunking error: {0}")]
    Chunking(String),

    /// Invalid configuration provided.
    #[error("Configuration error: {0}")]
    Config(String),

    /// IO error during file operations.
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    /// Serialization/deserialization error.
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    /// Embedding service error.
    #[error("Embedding error: {0}")]
    Embedding(String),

    /// HTTP request error.
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),

    /// Vector store (Qdrant) error.
    #[error("Vector store error: {0}")]
    VectorStore(String),

    /// Search store (OpenSearch) error.
    #[error("Search store error: {0}")]
    SearchStore(String),

    /// Database (PostgreSQL) error.
    #[error("Database error: {0}")]
    Database(String),

    /// Index coordination error.
    #[error("Indexing error: {0}")]
    Indexing(String),

    /// Connector error.
    #[error("Connector error: {0}")]
    Connector(String),

    /// Storage (S3/MinIO) error.
    #[error("Storage error: {0}")]
    Storage(String),

    /// Resource not found.
    #[error("Not found: {0}")]
    NotFound(String),

    /// Operation timeout.
    #[error("Timeout: {0}")]
    Timeout(String),
}

impl From<rag_vectorstore::VectorStoreError> for Error {
    fn from(e: rag_vectorstore::VectorStoreError) -> Self {
        Error::VectorStore(e.to_string())
    }
}

impl From<rag_search::SearchError> for Error {
    fn from(e: rag_search::SearchError) -> Self {
        Error::SearchStore(e.to_string())
    }
}

impl From<rag_database::DatabaseError> for Error {
    fn from(e: rag_database::DatabaseError) -> Self {
        Error::Database(e.to_string())
    }
}

/// Result type alias for ingestion operations.
pub type Result<T> = std::result::Result<T, Error>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_error_display() {
        let err = Error::Embedding("connection refused".to_string());
        assert_eq!(err.to_string(), "Embedding error: connection refused");
    }

    #[test]
    fn test_error_from_io() {
        let io_err = std::io::Error::new(std::io::ErrorKind::NotFound, "file not found");
        let err: Error = io_err.into();
        assert!(matches!(err, Error::Io(_)));
    }

    #[test]
    fn test_vectorstore_error_display() {
        let err = Error::VectorStore("connection failed".to_string());
        assert_eq!(err.to_string(), "Vector store error: connection failed");
    }

    #[test]
    fn test_searchstore_error_display() {
        let err = Error::SearchStore("index not found".to_string());
        assert_eq!(err.to_string(), "Search store error: index not found");
    }

    #[test]
    fn test_database_error_display() {
        let err = Error::Database("connection pool exhausted".to_string());
        assert_eq!(err.to_string(), "Database error: connection pool exhausted");
    }

    #[test]
    fn test_notfound_error_display() {
        let err = Error::NotFound("document abc123".to_string());
        assert_eq!(err.to_string(), "Not found: document abc123");
    }

    #[test]
    fn test_timeout_error_display() {
        let err = Error::Timeout("embedding request exceeded 5s".to_string());
        assert_eq!(err.to_string(), "Timeout: embedding request exceeded 5s");
    }

    #[test]
    fn test_connector_error_display() {
        let err = Error::Connector("S3 bucket not accessible".to_string());
        assert_eq!(err.to_string(), "Connector error: S3 bucket not accessible");
    }

    #[test]
    fn test_storage_error_display() {
        let err = Error::Storage("upload failed".to_string());
        assert_eq!(err.to_string(), "Storage error: upload failed");
    }

    #[test]
    fn test_indexing_error_display() {
        let err = Error::Indexing("coordination failure".to_string());
        assert_eq!(err.to_string(), "Indexing error: coordination failure");
    }
}

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
}

/// Result type alias for ingestion operations.
pub type Result<T> = std::result::Result<T, Error>;

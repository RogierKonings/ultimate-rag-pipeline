//! Error types for embedding operations.

use thiserror::Error;

/// Result type for embedding operations.
pub type Result<T> = std::result::Result<T, EmbeddingError>;

/// Errors that can occur during embedding operations.
#[derive(Debug, Error)]
pub enum EmbeddingError {
    /// Model loading failed.
    #[error("Failed to load model: {0}")]
    ModelLoad(String),

    /// Embedding generation failed.
    #[error("Embedding generation failed: {0}")]
    Inference(String),

    /// Invalid input provided.
    #[error("Invalid input: {0}")]
    InvalidInput(String),

    /// Model not ready (still loading).
    #[error("Model not ready: {0}")]
    NotReady(String),

    /// Configuration error.
    #[error("Configuration error: {0}")]
    Config(String),
}

impl EmbeddingError {
    /// Create a model load error.
    pub fn model_load(msg: impl Into<String>) -> Self {
        Self::ModelLoad(msg.into())
    }

    /// Create an inference error.
    pub fn inference(msg: impl Into<String>) -> Self {
        Self::Inference(msg.into())
    }

    /// Create an invalid input error.
    pub fn invalid_input(msg: impl Into<String>) -> Self {
        Self::InvalidInput(msg.into())
    }

    /// Create a not ready error.
    pub fn not_ready(msg: impl Into<String>) -> Self {
        Self::NotReady(msg.into())
    }

    /// Create a config error.
    pub fn config(msg: impl Into<String>) -> Self {
        Self::Config(msg.into())
    }

    /// Check if this is a client error (4xx equivalent).
    #[must_use]
    pub const fn is_client_error(&self) -> bool {
        matches!(self, Self::InvalidInput(_))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_error_creation() {
        let err = EmbeddingError::model_load("test error");
        assert!(err.to_string().contains("Failed to load model"));
        assert!(err.to_string().contains("test error"));
    }

    #[test]
    fn test_is_client_error() {
        assert!(EmbeddingError::invalid_input("test").is_client_error());
        assert!(!EmbeddingError::model_load("test").is_client_error());
        assert!(!EmbeddingError::inference("test").is_client_error());
    }
}

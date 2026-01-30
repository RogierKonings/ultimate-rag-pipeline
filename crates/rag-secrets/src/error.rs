//! Error types for secrets management.

use thiserror::Error;

/// Result type for secrets operations.
pub type Result<T> = std::result::Result<T, SecretsError>;

/// Secrets management errors.
#[derive(Debug, Error)]
pub enum SecretsError {
    /// Secret not found.
    #[error("Secret not found: {0}")]
    NotFound(String),

    /// Secret value is invalid.
    #[error("Invalid secret value: {0}")]
    InvalidValue(String),

    /// Authentication error.
    #[error("Authentication failed: {0}")]
    AuthError(String),

    /// Connection error.
    #[error("Connection error: {0}")]
    ConnectionError(String),

    /// Configuration error.
    #[error("Configuration error: {0}")]
    ConfigError(String),

    /// HTTP request error.
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),

    /// JSON parsing error.
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),

    /// Base64 decoding error.
    #[error("Base64 decode error: {0}")]
    Base64(#[from] base64::DecodeError),

    /// Kubernetes API error.
    #[cfg(feature = "kubernetes")]
    #[error("Kubernetes error: {0}")]
    Kubernetes(#[from] kube::Error),

    /// All providers in chain failed.
    #[error("All providers failed to retrieve secret: {0}")]
    AllProvidersFailed(String),
}

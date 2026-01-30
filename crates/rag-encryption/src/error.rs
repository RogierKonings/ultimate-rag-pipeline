//! Encryption error types.

use thiserror::Error;

/// Result type for encryption operations.
pub type Result<T> = std::result::Result<T, EncryptionError>;

/// Errors that can occur during encryption operations.
#[derive(Debug, Error)]
pub enum EncryptionError {
    /// Key not found.
    #[error("Key not found: {0}")]
    KeyNotFound(String),

    /// Invalid key format or length.
    #[error("Invalid key: {0}")]
    InvalidKey(String),

    /// Encryption operation failed.
    #[error("Encryption failed: {0}")]
    EncryptionFailed(String),

    /// Decryption operation failed.
    #[error("Decryption failed: {0}")]
    DecryptionFailed(String),

    /// Invalid ciphertext format.
    #[error("Invalid ciphertext: {0}")]
    InvalidCiphertext(String),

    /// Key derivation failed.
    #[error("Key derivation failed: {0}")]
    KeyDerivationFailed(String),

    /// Configuration error.
    #[error("Configuration error: {0}")]
    ConfigError(String),

    /// Base64 decode error.
    #[error("Base64 decode error: {0}")]
    Base64Error(#[from] base64::DecodeError),

    /// Key version mismatch.
    #[error("Key version mismatch: expected {expected}, got {actual}")]
    KeyVersionMismatch { expected: u32, actual: u32 },

    /// Nonce generation failed.
    #[error("Failed to generate nonce")]
    NonceGenerationFailed,

    /// Secrets provider error.
    #[cfg(feature = "secrets-integration")]
    #[error("Secrets error: {0}")]
    SecretsError(#[from] rag_secrets::SecretsError),
}

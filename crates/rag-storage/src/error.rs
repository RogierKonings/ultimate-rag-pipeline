//! Error types for storage operations.

use thiserror::Error;

/// Result type for storage operations.
pub type Result<T> = std::result::Result<T, StorageError>;

/// Storage operation errors.
#[derive(Debug, Error)]
pub enum StorageError {
    /// Bucket not found.
    #[error("Bucket not found: {0}")]
    BucketNotFound(String),

    /// Object not found.
    #[error("Object not found: {bucket}/{key}")]
    ObjectNotFound { bucket: String, key: String },

    /// Access denied.
    #[error("Access denied: {0}")]
    AccessDenied(String),

    /// Invalid configuration.
    #[error("Configuration error: {0}")]
    Config(String),

    /// SDK error.
    #[error("S3 error: {0}")]
    S3(String),

    /// IO error.
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    /// Presigned URL error.
    #[error("Failed to generate presigned URL: {0}")]
    PresignedUrl(String),
}

impl<E> From<aws_sdk_s3::error::SdkError<E>> for StorageError
where
    E: std::fmt::Debug,
{
    fn from(err: aws_sdk_s3::error::SdkError<E>) -> Self {
        Self::S3(format!("{err:?}"))
    }
}

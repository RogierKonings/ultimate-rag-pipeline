//! Error types for tenant configuration.

use thiserror::Error;
use uuid::Uuid;

/// Result type for tenant operations.
pub type Result<T> = std::result::Result<T, TenantError>;

/// Tenant configuration errors.
#[derive(Debug, Error)]
pub enum TenantError {
    /// Tenant not found.
    #[error("Tenant not found: {0}")]
    NotFound(Uuid),

    /// Tenant configuration not found.
    #[error("Configuration not found for tenant: {0}")]
    ConfigNotFound(Uuid),

    /// Invalid isolation mode.
    #[error("Invalid isolation mode: {0}")]
    InvalidIsolationMode(String),

    /// Database error.
    #[error("Database error: {0}")]
    Database(String),

    /// Cache error.
    #[error("Cache error: {0}")]
    Cache(String),

    /// Serialization error.
    #[error("Serialization error: {0}")]
    Serialization(String),
}

impl From<rag_database::DatabaseError> for TenantError {
    fn from(err: rag_database::DatabaseError) -> Self {
        Self::Database(err.to_string())
    }
}

impl From<serde_json::Error> for TenantError {
    fn from(err: serde_json::Error) -> Self {
        Self::Serialization(err.to_string())
    }
}

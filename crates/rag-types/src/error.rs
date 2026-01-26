//! Error types for the RAG pipeline.
//!
//! This module defines a unified error type used throughout the pipeline,
//! with specific variants for different failure modes.

use thiserror::Error;

/// Result type alias using the pipeline error type.
pub type Result<T> = std::result::Result<T, Error>;

/// Unified error type for the RAG pipeline.
#[derive(Error, Debug)]
pub enum Error {
    // ─────────────────────────────────────────────────────────────────────────
    // Validation errors
    // ─────────────────────────────────────────────────────────────────────────
    /// Input validation failed
    #[error("Validation error: {message}")]
    Validation {
        /// Description of what failed validation
        message: String,
        /// Field that failed validation, if applicable
        field: Option<String>,
    },

    /// Resource not found
    #[error("{resource_type} not found: {id}")]
    NotFound {
        /// Type of resource (e.g., "Document", "Chunk")
        resource_type: String,
        /// ID that was not found
        id: String,
    },

    /// Resource already exists
    #[error("{resource_type} already exists: {id}")]
    AlreadyExists {
        /// Type of resource
        resource_type: String,
        /// Existing ID
        id: String,
    },

    // ─────────────────────────────────────────────────────────────────────────
    // Authorization errors
    // ─────────────────────────────────────────────────────────────────────────
    /// Authentication required but not provided
    #[error("Authentication required")]
    Unauthenticated,

    /// Authenticated but not authorized for this action
    #[error("Access denied: {reason}")]
    Unauthorized {
        /// Reason for denial
        reason: String,
    },

    /// Tenant access violation
    #[error("Tenant isolation violation: cannot access tenant {tenant_id}")]
    TenantViolation {
        /// Tenant that was attempted to be accessed
        tenant_id: String,
    },

    // ─────────────────────────────────────────────────────────────────────────
    // Infrastructure errors
    // ─────────────────────────────────────────────────────────────────────────
    /// Database operation failed
    #[error("Database error: {message}")]
    Database {
        /// Error description
        message: String,
        /// Underlying error, if available
        #[source]
        source: Option<Box<dyn std::error::Error + Send + Sync>>,
    },

    /// Redis/cache operation failed
    #[error("Cache error: {message}")]
    Cache {
        /// Error description
        message: String,
        /// Underlying error
        #[source]
        source: Option<Box<dyn std::error::Error + Send + Sync>>,
    },

    /// Vector store (Qdrant) operation failed
    #[error("Vector store error: {message}")]
    VectorStore {
        /// Error description
        message: String,
        /// Underlying error
        #[source]
        source: Option<Box<dyn std::error::Error + Send + Sync>>,
    },

    /// Search engine (OpenSearch) operation failed
    #[error("Search error: {message}")]
    Search {
        /// Error description
        message: String,
        /// Underlying error
        #[source]
        source: Option<Box<dyn std::error::Error + Send + Sync>>,
    },

    /// Object storage (S3/MinIO) operation failed
    #[error("Storage error: {message}")]
    Storage {
        /// Error description
        message: String,
        /// Underlying error
        #[source]
        source: Option<Box<dyn std::error::Error + Send + Sync>>,
    },

    // ─────────────────────────────────────────────────────────────────────────
    // External service errors
    // ─────────────────────────────────────────────────────────────────────────
    /// Embedding service failed
    #[error("Embedding service error: {message}")]
    EmbeddingService {
        /// Error description
        message: String,
        /// Underlying error
        #[source]
        source: Option<Box<dyn std::error::Error + Send + Sync>>,
    },

    /// Reranker service failed
    #[error("Reranker service error: {message}")]
    RerankerService {
        /// Error description
        message: String,
        /// Underlying error
        #[source]
        source: Option<Box<dyn std::error::Error + Send + Sync>>,
    },

    /// LLM gateway failed
    #[error("LLM service error: {message}")]
    LlmService {
        /// Error description
        message: String,
        /// Underlying error
        #[source]
        source: Option<Box<dyn std::error::Error + Send + Sync>>,
    },

    // ─────────────────────────────────────────────────────────────────────────
    // Processing errors
    // ─────────────────────────────────────────────────────────────────────────
    /// Document parsing failed
    #[error("Parse error for {document_type}: {message}")]
    Parse {
        /// Type of document being parsed
        document_type: String,
        /// Error description
        message: String,
    },

    /// Chunking operation failed
    #[error("Chunking error: {message}")]
    Chunking {
        /// Error description
        message: String,
    },

    /// Configuration error
    #[error("Configuration error: {message}")]
    Configuration {
        /// Error description
        message: String,
    },

    // ─────────────────────────────────────────────────────────────────────────
    // Operational errors
    // ─────────────────────────────────────────────────────────────────────────
    /// Operation timed out
    #[error("Operation timed out after {timeout_ms}ms: {operation}")]
    Timeout {
        /// Name of the operation
        operation: String,
        /// Timeout duration in milliseconds
        timeout_ms: u64,
    },

    /// Rate limit exceeded
    #[error("Rate limit exceeded: {message}")]
    RateLimited {
        /// Error description
        message: String,
        /// When the rate limit resets (seconds from now)
        retry_after_secs: Option<u64>,
    },

    /// Service is degraded
    #[error("Service degraded: {message}")]
    Degraded {
        /// Description of degradation
        message: String,
        /// Which components are affected
        affected_components: Vec<String>,
    },

    // ─────────────────────────────────────────────────────────────────────────
    // Generic errors
    // ─────────────────────────────────────────────────────────────────────────
    /// Internal error (should not happen)
    #[error("Internal error: {message}")]
    Internal {
        /// Error description
        message: String,
    },

    /// Serialization/deserialization error
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    /// IO error
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
}

impl Error {
    /// Create a validation error.
    pub fn validation(message: impl Into<String>) -> Self {
        Self::Validation {
            message: message.into(),
            field: None,
        }
    }

    /// Create a validation error with a field name.
    pub fn validation_field(message: impl Into<String>, field: impl Into<String>) -> Self {
        Self::Validation {
            message: message.into(),
            field: Some(field.into()),
        }
    }

    /// Create a not found error.
    pub fn not_found(resource_type: impl Into<String>, id: impl Into<String>) -> Self {
        Self::NotFound {
            resource_type: resource_type.into(),
            id: id.into(),
        }
    }

    /// Create a database error.
    pub fn database(message: impl Into<String>) -> Self {
        Self::Database {
            message: message.into(),
            source: None,
        }
    }

    /// Create a database error with a source.
    pub fn database_with_source(
        message: impl Into<String>,
        source: impl std::error::Error + Send + Sync + 'static,
    ) -> Self {
        Self::Database {
            message: message.into(),
            source: Some(Box::new(source)),
        }
    }

    /// Create a cache error.
    pub fn cache(message: impl Into<String>) -> Self {
        Self::Cache {
            message: message.into(),
            source: None,
        }
    }

    /// Create a cache error with a source.
    pub fn cache_with_source(
        message: impl Into<String>,
        source: impl std::error::Error + Send + Sync + 'static,
    ) -> Self {
        Self::Cache {
            message: message.into(),
            source: Some(Box::new(source)),
        }
    }

    /// Create a timeout error.
    pub fn timeout(operation: impl Into<String>, timeout_ms: u64) -> Self {
        Self::Timeout {
            operation: operation.into(),
            timeout_ms,
        }
    }

    /// Create an internal error.
    pub fn internal(message: impl Into<String>) -> Self {
        Self::Internal {
            message: message.into(),
        }
    }

    /// Check if this is a retriable error.
    #[must_use]
    pub const fn is_retriable(&self) -> bool {
        matches!(
            self,
            Self::Timeout { .. }
                | Self::RateLimited { .. }
                | Self::Cache { .. }
                | Self::VectorStore { .. }
                | Self::Search { .. }
                | Self::EmbeddingService { .. }
                | Self::RerankerService { .. }
        )
    }

    /// Check if this is a client error (4xx equivalent).
    #[must_use]
    pub const fn is_client_error(&self) -> bool {
        matches!(
            self,
            Self::Validation { .. }
                | Self::NotFound { .. }
                | Self::AlreadyExists { .. }
                | Self::Unauthenticated
                | Self::Unauthorized { .. }
                | Self::TenantViolation { .. }
        )
    }

    /// Check if this is a server error (5xx equivalent).
    #[must_use]
    pub const fn is_server_error(&self) -> bool {
        !self.is_client_error()
    }

    /// Get an error code suitable for API responses.
    #[must_use]
    pub const fn error_code(&self) -> &'static str {
        match self {
            Self::Validation { .. } => "VALIDATION_ERROR",
            Self::NotFound { .. } => "NOT_FOUND",
            Self::AlreadyExists { .. } => "ALREADY_EXISTS",
            Self::Unauthenticated => "UNAUTHENTICATED",
            Self::Unauthorized { .. } => "UNAUTHORIZED",
            Self::TenantViolation { .. } => "TENANT_VIOLATION",
            Self::Database { .. } => "DATABASE_ERROR",
            Self::Cache { .. } => "CACHE_ERROR",
            Self::VectorStore { .. } => "VECTOR_STORE_ERROR",
            Self::Search { .. } => "SEARCH_ERROR",
            Self::Storage { .. } => "STORAGE_ERROR",
            Self::EmbeddingService { .. } => "EMBEDDING_SERVICE_ERROR",
            Self::RerankerService { .. } => "RERANKER_SERVICE_ERROR",
            Self::LlmService { .. } => "LLM_SERVICE_ERROR",
            Self::Parse { .. } => "PARSE_ERROR",
            Self::Chunking { .. } => "CHUNKING_ERROR",
            Self::Configuration { .. } => "CONFIGURATION_ERROR",
            Self::Timeout { .. } => "TIMEOUT",
            Self::RateLimited { .. } => "RATE_LIMITED",
            Self::Degraded { .. } => "SERVICE_DEGRADED",
            Self::Internal { .. } => "INTERNAL_ERROR",
            Self::Serialization(_) => "SERIALIZATION_ERROR",
            Self::Io(_) => "IO_ERROR",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validation_error() {
        let err = Error::validation("Invalid input");
        assert!(err.is_client_error());
        assert!(!err.is_retriable());
        assert_eq!(err.error_code(), "VALIDATION_ERROR");
    }

    #[test]
    fn test_not_found_error() {
        let err = Error::not_found("Document", "doc-123");
        assert!(matches!(err, Error::NotFound { .. }));
        assert_eq!(err.to_string(), "Document not found: doc-123");
    }

    #[test]
    fn test_timeout_is_retriable() {
        let err = Error::timeout("embedding", 5000);
        assert!(err.is_retriable());
        assert!(err.is_server_error());
    }

    #[test]
    fn test_error_code() {
        assert_eq!(Error::Unauthenticated.error_code(), "UNAUTHENTICATED");
        assert_eq!(Error::internal("oops").error_code(), "INTERNAL_ERROR");
    }
}

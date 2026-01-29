//! API error handling for the ingestion service.

use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};

use crate::error::Error as IngestionError;

/// API error that can be converted to an HTTP response.
#[derive(Debug, Clone)]
pub struct ApiError {
    /// HTTP status code.
    pub status: StatusCode,
    /// Human-readable error message.
    pub message: String,
    /// Error code for programmatic handling.
    pub code: String,
    /// Optional details for debugging.
    pub details: Option<serde_json::Value>,
}

impl ApiError {
    /// Create a new API error.
    #[must_use]
    pub fn new(status: StatusCode, code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            status,
            code: code.into(),
            message: message.into(),
            details: None,
        }
    }

    /// Add details to the error.
    #[must_use]
    pub fn with_details(mut self, details: serde_json::Value) -> Self {
        self.details = Some(details);
        self
    }

    /// Create a bad request error (400).
    #[must_use]
    pub fn bad_request(message: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, "BAD_REQUEST", message)
    }

    /// Create a validation error (400).
    #[must_use]
    pub fn validation(message: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, "VALIDATION_ERROR", message)
    }

    /// Create a forbidden error (403).
    #[must_use]
    pub fn forbidden(message: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, "FORBIDDEN", message)
    }

    /// Create a not found error (404).
    #[must_use]
    pub fn not_found(message: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, "NOT_FOUND", message)
    }

    /// Create an internal server error (500).
    #[must_use]
    pub fn internal(message: impl Into<String>) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", message)
    }

    /// Create a service unavailable error (503).
    #[must_use]
    pub fn service_unavailable(message: impl Into<String>) -> Self {
        Self::new(
            StatusCode::SERVICE_UNAVAILABLE,
            "SERVICE_UNAVAILABLE",
            message,
        )
    }
}

/// JSON error response body.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorResponse {
    /// The error details.
    pub error: ErrorBody,
}

/// Error body within the response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorBody {
    /// Error code for programmatic handling.
    pub code: String,
    /// Human-readable error message.
    pub message: String,
    /// Optional additional details.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<serde_json::Value>,
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let body = ErrorResponse {
            error: ErrorBody {
                code: self.code,
                message: self.message,
                details: self.details,
            },
        };
        (self.status, Json(body)).into_response()
    }
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {} ({})", self.code, self.message, self.status)
    }
}

impl std::error::Error for ApiError {}

impl From<IngestionError> for ApiError {
    fn from(err: IngestionError) -> Self {
        match &err {
            IngestionError::NotFound(msg) => Self::not_found(msg),
            IngestionError::Config(msg) => Self::bad_request(msg),
            IngestionError::Timeout(_) => Self::service_unavailable(err.to_string()),
            // All other errors map to internal server error
            IngestionError::Parse(_)
            | IngestionError::Embedding(_)
            | IngestionError::Chunking(_)
            | IngestionError::VectorStore(_)
            | IngestionError::SearchStore(_)
            | IngestionError::Database(_)
            | IngestionError::Storage(_)
            | IngestionError::Io(_)
            | IngestionError::Serialization(_)
            | IngestionError::Http(_)
            | IngestionError::Indexing(_)
            | IngestionError::Connector(_) => Self::internal(err.to_string()),
        }
    }
}

/// Result type for API operations.
pub type ApiResult<T> = Result<T, ApiError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_api_error_creation() {
        let err = ApiError::bad_request("Invalid query parameter");
        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(err.code, "BAD_REQUEST");
    }

    #[test]
    fn test_api_error_with_details() {
        let err = ApiError::validation("Field validation failed")
            .with_details(serde_json::json!({"field": "query"}));
        assert!(err.details.is_some());
    }

    #[test]
    fn test_api_error_into_response() {
        let err = ApiError::not_found("Resource not found");
        let response = err.into_response();
        assert_eq!(response.status(), StatusCode::NOT_FOUND);
    }

    #[test]
    fn test_api_error_display() {
        let err = ApiError::internal("Something went wrong");
        let display = err.to_string();
        assert!(display.contains("INTERNAL_ERROR"));
    }

    #[test]
    fn test_bad_request_error() {
        let err = ApiError::bad_request("Invalid input");
        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(err.code, "BAD_REQUEST");
    }

    #[test]
    fn test_not_found_error() {
        let err = ApiError::not_found("Job not found");
        assert_eq!(err.status, StatusCode::NOT_FOUND);
        assert_eq!(err.code, "NOT_FOUND");
    }

    #[test]
    fn test_forbidden_error() {
        let err = ApiError::forbidden("Access denied");
        assert_eq!(err.status, StatusCode::FORBIDDEN);
        assert_eq!(err.code, "FORBIDDEN");
    }
}

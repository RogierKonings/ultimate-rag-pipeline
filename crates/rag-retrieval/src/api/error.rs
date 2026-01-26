//! API error handling for the retrieval service.
//!
//! This module provides error types that can be converted to HTTP responses
//! with appropriate status codes and JSON error bodies.

use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::{Deserialize, Serialize};

use crate::error::RetrievalError;
use crate::api::types::ValidationError;

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

    /// Create an unauthorized error (401).
    #[must_use]
    pub fn unauthorized(message: impl Into<String>) -> Self {
        Self::new(StatusCode::UNAUTHORIZED, "UNAUTHORIZED", message)
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

    /// Create a timeout error (408).
    #[must_use]
    pub fn timeout(message: impl Into<String>) -> Self {
        Self::new(StatusCode::REQUEST_TIMEOUT, "TIMEOUT", message)
    }

    /// Create an internal server error (500).
    #[must_use]
    pub fn internal(message: impl Into<String>) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", message)
    }

    /// Create a service unavailable error (503).
    #[must_use]
    pub fn service_unavailable(message: impl Into<String>) -> Self {
        Self::new(StatusCode::SERVICE_UNAVAILABLE, "SERVICE_UNAVAILABLE", message)
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

impl From<RetrievalError> for ApiError {
    fn from(err: RetrievalError) -> Self {
        match err {
            RetrievalError::InvalidRequest(msg) => Self::bad_request(msg),
            RetrievalError::Unauthorized(msg) => Self::unauthorized(msg),
            RetrievalError::Timeout(msg) => Self::timeout(msg),
            RetrievalError::Config(msg) => Self::internal(format!("Configuration error: {msg}")),
            RetrievalError::SemanticSearch(msg) => {
                Self::internal(format!("Semantic search error: {msg}"))
            }
            RetrievalError::KeywordSearch(msg) => {
                Self::internal(format!("Keyword search error: {msg}"))
            }
            RetrievalError::Embedding(msg) => Self::internal(format!("Embedding error: {msg}")),
            RetrievalError::Reranking(msg) => Self::internal(format!("Reranking error: {msg}")),
            RetrievalError::Cache(msg) => Self::internal(format!("Cache error: {msg}")),
            RetrievalError::Llm(msg) => Self::internal(format!("LLM error: {msg}")),
            RetrievalError::Internal(msg) => Self::internal(msg),
        }
    }
}

impl From<ValidationError> for ApiError {
    fn from(err: ValidationError) -> Self {
        Self::validation(format!("{}: {}", err.field, err.message)).with_details(
            serde_json::json!({
                "field": err.field,
                "message": err.message
            }),
        )
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
        assert!(err.message.contains("Invalid query parameter"));
    }

    #[test]
    fn test_api_error_with_details() {
        let err = ApiError::validation("Field validation failed")
            .with_details(serde_json::json!({"field": "query"}));

        assert!(err.details.is_some());
        let details = err.details.unwrap();
        assert_eq!(details["field"], "query");
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
        assert!(display.contains("Something went wrong"));
        assert!(display.contains("500"));
    }

    #[test]
    fn test_from_retrieval_error_invalid_request() {
        let retrieval_err = RetrievalError::invalid_request("Bad input");
        let api_err: ApiError = retrieval_err.into();

        assert_eq!(api_err.status, StatusCode::BAD_REQUEST);
        assert_eq!(api_err.code, "BAD_REQUEST");
    }

    #[test]
    fn test_from_retrieval_error_unauthorized() {
        let retrieval_err = RetrievalError::unauthorized("Access denied");
        let api_err: ApiError = retrieval_err.into();

        assert_eq!(api_err.status, StatusCode::UNAUTHORIZED);
    }

    #[test]
    fn test_from_retrieval_error_timeout() {
        let retrieval_err = RetrievalError::timeout("Request timed out");
        let api_err: ApiError = retrieval_err.into();

        assert_eq!(api_err.status, StatusCode::REQUEST_TIMEOUT);
    }

    #[test]
    fn test_from_retrieval_error_semantic_search() {
        let retrieval_err = RetrievalError::semantic_search("Qdrant error");
        let api_err: ApiError = retrieval_err.into();

        assert_eq!(api_err.status, StatusCode::INTERNAL_SERVER_ERROR);
        assert!(api_err.message.contains("Semantic search"));
    }

    #[test]
    fn test_from_validation_error() {
        let validation_err = ValidationError::new("query", "cannot be empty");
        let api_err: ApiError = validation_err.into();

        assert_eq!(api_err.status, StatusCode::BAD_REQUEST);
        assert_eq!(api_err.code, "VALIDATION_ERROR");
        assert!(api_err.details.is_some());
    }

    #[test]
    fn test_error_response_serialization() {
        let body = ErrorResponse {
            error: ErrorBody {
                code: "TEST_ERROR".into(),
                message: "Test message".into(),
                details: Some(serde_json::json!({"key": "value"})),
            },
        };

        let json = serde_json::to_string(&body).unwrap();
        assert!(json.contains("TEST_ERROR"));
        assert!(json.contains("Test message"));
        assert!(json.contains("\"key\":\"value\""));

        let deserialized: ErrorResponse = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.error.code, "TEST_ERROR");
    }
}

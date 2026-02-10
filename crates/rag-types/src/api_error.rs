//! Shared API error types for HTTP services.
//!
//! Provides a unified `ApiError` type with consistent JSON serialization
//! used by ingestion and retrieval services. The wire format is:
//!
//! ```json
//! { "error": { "code": "...", "message": "...", "details": ... } }
//! ```
//!
//! Requires the `axum` feature flag for `IntoResponse` implementation.

use serde::{Deserialize, Serialize};

/// JSON error response body.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorResponse {
    /// The error details.
    pub error: ErrorBody,
}

/// Error body within the response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorBody {
    /// Error code for programmatic handling (e.g., "`BAD_REQUEST`", "`INTERNAL_ERROR`").
    pub code: String,

    /// Human-readable error message.
    pub message: String,

    /// Optional additional details for debugging.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub details: Option<serde_json::Value>,
}

/// API error that can be converted to an HTTP response.
///
/// When the `axum` feature is enabled, this implements `IntoResponse` so it
/// can be returned directly from Axum route handlers.
#[derive(Debug, Clone)]
pub struct ApiError {
    /// HTTP status code.
    pub status: http::StatusCode,

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
    pub fn new(
        status: http::StatusCode,
        code: impl Into<String>,
        message: impl Into<String>,
    ) -> Self {
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
        Self::new(http::StatusCode::BAD_REQUEST, "BAD_REQUEST", message)
    }

    /// Create a validation error (400).
    #[must_use]
    pub fn validation(message: impl Into<String>) -> Self {
        Self::new(http::StatusCode::BAD_REQUEST, "VALIDATION_ERROR", message)
    }

    /// Create an unauthorized error (401).
    #[must_use]
    pub fn unauthorized(message: impl Into<String>) -> Self {
        Self::new(http::StatusCode::UNAUTHORIZED, "UNAUTHORIZED", message)
    }

    /// Create a forbidden error (403).
    #[must_use]
    pub fn forbidden(message: impl Into<String>) -> Self {
        Self::new(http::StatusCode::FORBIDDEN, "FORBIDDEN", message)
    }

    /// Create a not found error (404).
    #[must_use]
    pub fn not_found(message: impl Into<String>) -> Self {
        Self::new(http::StatusCode::NOT_FOUND, "NOT_FOUND", message)
    }

    /// Create a timeout error (408).
    #[must_use]
    pub fn timeout(message: impl Into<String>) -> Self {
        Self::new(http::StatusCode::REQUEST_TIMEOUT, "TIMEOUT", message)
    }

    /// Create an internal server error (500).
    #[must_use]
    pub fn internal(message: impl Into<String>) -> Self {
        Self::new(
            http::StatusCode::INTERNAL_SERVER_ERROR,
            "INTERNAL_ERROR",
            message,
        )
    }

    /// Create a service unavailable error (503).
    #[must_use]
    pub fn service_unavailable(message: impl Into<String>) -> Self {
        Self::new(
            http::StatusCode::SERVICE_UNAVAILABLE,
            "SERVICE_UNAVAILABLE",
            message,
        )
    }

    /// Convert to the JSON response body.
    #[must_use]
    pub fn to_error_response(&self) -> ErrorResponse {
        ErrorResponse {
            error: ErrorBody {
                code: self.code.clone(),
                message: self.message.clone(),
                details: self.details.clone(),
            },
        }
    }
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {} ({})", self.code, self.message, self.status)
    }
}

impl std::error::Error for ApiError {}

#[cfg(feature = "axum")]
impl axum::response::IntoResponse for ApiError {
    fn into_response(self) -> axum::response::Response {
        let body = self.to_error_response();
        (self.status, axum::Json(body)).into_response()
    }
}

/// Result type for API operations.
pub type ApiResult<T> = std::result::Result<T, ApiError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_api_error_creation() {
        let err = ApiError::bad_request("Invalid query parameter");
        assert_eq!(err.status, http::StatusCode::BAD_REQUEST);
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
    fn test_api_error_display() {
        let err = ApiError::internal("Something went wrong");
        let display = err.to_string();
        assert!(display.contains("INTERNAL_ERROR"));
        assert!(display.contains("Something went wrong"));
        assert!(display.contains("500"));
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

        let deserialized: ErrorResponse = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.error.code, "TEST_ERROR");
    }

    #[test]
    fn test_all_error_variants() {
        assert_eq!(ApiError::bad_request("x").status, http::StatusCode::BAD_REQUEST);
        assert_eq!(ApiError::validation("x").status, http::StatusCode::BAD_REQUEST);
        assert_eq!(ApiError::unauthorized("x").status, http::StatusCode::UNAUTHORIZED);
        assert_eq!(ApiError::forbidden("x").status, http::StatusCode::FORBIDDEN);
        assert_eq!(ApiError::not_found("x").status, http::StatusCode::NOT_FOUND);
        assert_eq!(ApiError::timeout("x").status, http::StatusCode::REQUEST_TIMEOUT);
        assert_eq!(
            ApiError::internal("x").status,
            http::StatusCode::INTERNAL_SERVER_ERROR
        );
        assert_eq!(
            ApiError::service_unavailable("x").status,
            http::StatusCode::SERVICE_UNAVAILABLE
        );
    }
}

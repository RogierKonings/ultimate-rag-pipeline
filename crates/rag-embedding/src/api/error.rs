//! API error handling for the embedding service.

use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Serialize;

use crate::error::EmbeddingError;

/// Result type for API operations.
pub type ApiResult<T> = std::result::Result<T, ApiError>;

/// API error with HTTP status and JSON body.
#[derive(Debug)]
pub struct ApiError {
    status: StatusCode,
    message: String,
}

impl ApiError {
    /// Create a bad request error (400).
    pub fn bad_request(msg: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            message: msg.into(),
        }
    }

    /// Create a service unavailable error (503).
    pub fn service_unavailable(msg: impl Into<String>) -> Self {
        Self {
            status: StatusCode::SERVICE_UNAVAILABLE,
            message: msg.into(),
        }
    }

    /// Create an internal server error (500).
    pub fn internal(msg: impl Into<String>) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            message: msg.into(),
        }
    }
}

impl From<EmbeddingError> for ApiError {
    fn from(err: EmbeddingError) -> Self {
        match &err {
            EmbeddingError::InvalidInput(_) => Self::bad_request(err.to_string()),
            EmbeddingError::NotReady(_) => Self::service_unavailable(err.to_string()),
            _ => Self::internal(err.to_string()),
        }
    }
}

/// Error response body.
#[derive(Debug, Serialize)]
struct ErrorBody {
    error: ErrorDetail,
}

#[derive(Debug, Serialize)]
struct ErrorDetail {
    message: String,
    r#type: &'static str,
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let error_type = match self.status {
            StatusCode::BAD_REQUEST => "invalid_request_error",
            StatusCode::SERVICE_UNAVAILABLE => "service_unavailable",
            _ => "internal_error",
        };

        let body = ErrorBody {
            error: ErrorDetail {
                message: self.message,
                r#type: error_type,
            },
        };

        (self.status, Json(body)).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_api_error_from_embedding_error() {
        let err = EmbeddingError::invalid_input("test");
        let api_err: ApiError = err.into();
        assert_eq!(api_err.status, StatusCode::BAD_REQUEST);

        let err = EmbeddingError::not_ready("loading");
        let api_err: ApiError = err.into();
        assert_eq!(api_err.status, StatusCode::SERVICE_UNAVAILABLE);

        let err = EmbeddingError::inference("failed");
        let api_err: ApiError = err.into();
        assert_eq!(api_err.status, StatusCode::INTERNAL_SERVER_ERROR);
    }
}

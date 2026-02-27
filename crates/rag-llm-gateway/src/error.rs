//! Error types for the LLM Gateway.

use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Serialize;

/// Gateway result type.
pub type Result<T> = std::result::Result<T, GatewayError>;

/// Gateway error types.
#[derive(Debug, thiserror::Error)]
pub enum GatewayError {
    #[error("Authentication failed: {0}")]
    Unauthorized(String),

    #[error("Forbidden: {0}")]
    Forbidden(String),

    #[error("Rate limit exceeded: retry after {retry_after_secs}s")]
    RateLimitExceeded { retry_after_secs: u64 },

    #[error("Bad request: {0}")]
    BadRequest(String),

    #[error("Service unavailable: {0}")]
    ServiceUnavailable(String),

    #[error("Upstream error: {0}")]
    UpstreamError(String),

    #[error("Internal error: {0}")]
    Internal(String),

    #[error("Embedding error: {0}")]
    Embedding(#[from] rag_embedding::EmbeddingError),

    #[error("Reranker error: {0}")]
    Reranker(String),

    #[error("Configuration error: {0}")]
    Config(String),
}

/// Error response body (OpenAI-compatible).
#[derive(Debug, Serialize)]
pub struct ErrorResponse {
    pub error: ErrorDetail,
}

#[derive(Debug, Serialize)]
pub struct ErrorDetail {
    pub message: String,
    pub r#type: &'static str,
    pub code: Option<&'static str>,
}

impl GatewayError {
    fn error_type(&self) -> &'static str {
        match self {
            Self::Unauthorized(_) => "authentication_error",
            Self::Forbidden(_) => "permission_error",
            Self::RateLimitExceeded { .. } => "rate_limit_error",
            Self::BadRequest(_) => "invalid_request_error",
            Self::ServiceUnavailable(_) => "service_error",
            Self::UpstreamError(_) => "upstream_error",
            Self::Internal(_) => "internal_error",
            Self::Embedding(_) => "embedding_error",
            Self::Reranker(_) => "reranker_error",
            Self::Config(_) => "configuration_error",
        }
    }

    fn status_code(&self) -> StatusCode {
        match self {
            Self::Unauthorized(_) => StatusCode::UNAUTHORIZED,
            Self::Forbidden(_) => StatusCode::FORBIDDEN,
            Self::RateLimitExceeded { .. } => StatusCode::TOO_MANY_REQUESTS,
            Self::BadRequest(_) => StatusCode::BAD_REQUEST,
            Self::ServiceUnavailable(_) => StatusCode::SERVICE_UNAVAILABLE,
            Self::UpstreamError(_) => StatusCode::BAD_GATEWAY,
            Self::Internal(_) | Self::Embedding(_) | Self::Reranker(_) | Self::Config(_) => {
                StatusCode::INTERNAL_SERVER_ERROR
            }
        }
    }
}

impl IntoResponse for GatewayError {
    fn into_response(self) -> Response {
        let status = self.status_code();
        let body = ErrorResponse {
            error: ErrorDetail {
                message: self.to_string(),
                r#type: self.error_type(),
                code: None,
            },
        };

        let mut response = (status, Json(body)).into_response();

        // Add Retry-After header for rate limit errors
        if let Self::RateLimitExceeded { retry_after_secs } = &self {
            response
                .headers_mut()
                .insert("Retry-After", retry_after_secs.to_string().parse().unwrap());
        }

        response
    }
}

//! API error handling for the retrieval service.
//!
//! Re-exports the shared `ApiError` type from `rag-types` and provides
//! service-specific conversions from `RetrievalError` and `ValidationError`.

pub use rag_types::{ApiError, ApiResult, ErrorBody, ErrorResponse};

use crate::api::types::ValidationError;
use crate::error::RetrievalError;

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

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::StatusCode;

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
        use axum::response::IntoResponse;
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

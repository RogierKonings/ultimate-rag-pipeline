//! API error handling for the ingestion service.
//!
//! Re-exports the shared `ApiError` type from `rag-types` and provides
//! service-specific conversions from `IngestionError`.

pub use rag_types::{ApiError, ApiResult, ErrorBody, ErrorResponse};

use crate::error::Error as IngestionError;

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

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::StatusCode;

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

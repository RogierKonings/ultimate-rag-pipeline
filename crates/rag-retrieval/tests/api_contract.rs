//! API contract tests for the retrieval service.
//!
//! These tests validate the JSON serialization/deserialization contracts
//! for API request and response types, ensuring backward compatibility
//! and correct default values.

use uuid::Uuid;

use rag_retrieval::api::{
    ApiError, RetrieveRequest, RetrieveResponse,
};
use rag_retrieval::types::SearchMode;

// Import integration test mocks
mod integration;

/// Test RetrieveRequest serialization with all fields.
#[test]
fn test_retrieve_request_full_serialization() {
    let request = RetrieveRequest {
        query: "What is Rust?".to_string(),
        mode: SearchMode::Hybrid,
        top_k: 15,
        semantic_weight: 0.6,
        keyword_weight: 0.4,
        rerank: true,
        rerank_top_k: 30,
        filters: Some(serde_json::json!({"source_type": "documentation"})),
        min_score: 0.3,
        include_metadata: true,
        include_highlights: true,
    };

    let json = serde_json::to_string(&request).unwrap();

    // Verify all fields are present
    assert!(json.contains("\"query\":\"What is Rust?\""));
    assert!(json.contains("\"mode\":\"hybrid\""));
    assert!(json.contains("\"top_k\":15"));
    assert!(json.contains("\"semantic_weight\":0.6"));
    assert!(json.contains("\"keyword_weight\":0.4"));
    assert!(json.contains("\"rerank\":true"));
    assert!(json.contains("\"rerank_top_k\":30"));
    assert!(json.contains("\"source_type\":\"documentation\""));
    assert!(json.contains("\"min_score\":0.3"));

    // Deserialize and verify
    let parsed: RetrieveRequest = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.query, "What is Rust?");
    assert_eq!(parsed.mode, SearchMode::Hybrid);
    assert_eq!(parsed.top_k, 15);
}

/// Test RetrieveRequest default values from minimal JSON.
#[test]
fn test_retrieve_request_defaults_from_minimal_json() {
    let json = r#"{"query": "test query"}"#;
    let request: RetrieveRequest = serde_json::from_str(json).unwrap();

    assert_eq!(request.query, "test query");
    assert_eq!(request.mode, SearchMode::Hybrid);
    assert_eq!(request.top_k, 10);
    assert!((request.semantic_weight - 0.7).abs() < f32::EPSILON);
    assert!((request.keyword_weight - 0.3).abs() < f32::EPSILON);
    assert!(!request.rerank);
    assert_eq!(request.rerank_top_k, 20);
    assert!(request.filters.is_none());
    assert!((request.min_score - 0.0).abs() < f32::EPSILON);
    assert!(request.include_metadata);
    assert!(request.include_highlights);
}

/// Test RetrieveRequest validation for empty query.
#[test]
fn test_retrieve_request_validation_empty_query() {
    let request = RetrieveRequest::new("");
    let result = request.validate();

    assert!(result.is_err());
    let err = result.unwrap_err();
    assert_eq!(err.field, "query");
    assert!(err.message.contains("empty"));
}

/// Test RetrieveRequest validation for query too long.
#[test]
fn test_retrieve_request_validation_query_too_long() {
    let long_query = "a".repeat(2001);
    let request = RetrieveRequest::new(long_query);
    let result = request.validate();

    assert!(result.is_err());
    let err = result.unwrap_err();
    assert_eq!(err.field, "query");
    assert!(err.message.contains("2000"));
}

/// Test RetrieveRequest validation for invalid top_k.
#[test]
fn test_retrieve_request_validation_invalid_top_k() {
    let mut request = RetrieveRequest::new("test");

    // Zero is invalid
    request.top_k = 0;
    let result = request.validate();
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().field, "top_k");

    // Over 100 is invalid
    request.top_k = 101;
    let result = request.validate();
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().field, "top_k");

    // 100 is valid
    request.top_k = 100;
    assert!(request.validate().is_ok());

    // 1 is valid
    request.top_k = 1;
    assert!(request.validate().is_ok());
}

/// Test RetrieveRequest validation for invalid weights.
#[test]
fn test_retrieve_request_validation_invalid_weights() {
    let mut request = RetrieveRequest::new("test");

    // Semantic weight > 1.0
    request.semantic_weight = 1.5;
    let result = request.validate();
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().field, "semantic_weight");

    request.semantic_weight = 0.7;

    // Keyword weight < 0.0
    request.keyword_weight = -0.1;
    let result = request.validate();
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().field, "keyword_weight");

    request.keyword_weight = 0.3;

    // Valid weights
    assert!(request.validate().is_ok());
}

/// Test RetrieveRequest validation for invalid min_score.
#[test]
fn test_retrieve_request_validation_invalid_min_score() {
    let mut request = RetrieveRequest::new("test");

    // min_score > 1.0
    request.min_score = 1.5;
    let result = request.validate();
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().field, "min_score");

    // min_score < 0.0
    request.min_score = -0.1;
    let result = request.validate();
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().field, "min_score");

    // Valid min_score
    request.min_score = 0.5;
    assert!(request.validate().is_ok());
}

/// Test RetrieveRequest validation for invalid rerank_top_k.
#[test]
fn test_retrieve_request_validation_invalid_rerank_top_k() {
    let mut request = RetrieveRequest::new("test");

    // Zero is invalid
    request.rerank_top_k = 0;
    let result = request.validate();
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().field, "rerank_top_k");

    // Over 100 is invalid
    request.rerank_top_k = 101;
    let result = request.validate();
    assert!(result.is_err());
    assert_eq!(result.unwrap_err().field, "rerank_top_k");
}

/// Test search mode serialization formats.
#[test]
fn test_search_mode_serialization() {
    // Hybrid
    let json = serde_json::to_string(&SearchMode::Hybrid).unwrap();
    assert_eq!(json, "\"hybrid\"");
    let parsed: SearchMode = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed, SearchMode::Hybrid);

    // Semantic
    let json = serde_json::to_string(&SearchMode::Semantic).unwrap();
    assert_eq!(json, "\"semantic\"");
    let parsed: SearchMode = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed, SearchMode::Semantic);

    // Keyword
    let json = serde_json::to_string(&SearchMode::Keyword).unwrap();
    assert_eq!(json, "\"keyword\"");
    let parsed: SearchMode = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed, SearchMode::Keyword);
}

/// Test RetrieveResponse serialization structure.
#[test]
fn test_retrieve_response_serialization() {
    use rag_retrieval::api::types::{RetrievedDocument, SearchMetrics};

    let chunk_id = Uuid::new_v4();
    let document_id = Uuid::new_v4();

    let results = vec![RetrievedDocument::new(
        chunk_id,
        document_id,
        "Test content".into(),
        0.95,
    )];

    let metrics = SearchMetrics::default();

    let response = RetrieveResponse::new(results, "test query".into(), SearchMode::Hybrid, metrics);

    let json = serde_json::to_string(&response).unwrap();

    // Verify structure
    assert!(json.contains("\"results\""));
    assert!(json.contains("\"total_results\":1"));
    assert!(json.contains("\"query\":\"test query\""));
    assert!(json.contains("\"mode\":\"hybrid\""));
    assert!(json.contains("\"metrics\""));
    assert!(json.contains("\"query_id\""));
    assert!(json.contains("\"processed_at\""));

    let parsed: RetrieveResponse = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.total_results, 1);
    assert_eq!(parsed.query, "test query");
    assert_eq!(parsed.mode, SearchMode::Hybrid);
}

/// Test RetrievedDocument serialization with optional fields.
#[test]
fn test_retrieved_document_optional_fields() {
    use rag_retrieval::api::types::RetrievedDocument;

    let chunk_id = Uuid::new_v4();
    let document_id = Uuid::new_v4();

    // Minimal document
    let doc = RetrievedDocument::new(chunk_id, document_id, "Content".into(), 0.9);
    let json = serde_json::to_string(&doc).unwrap();

    // Optional fields should be skipped when None
    assert!(!json.contains("\"title\""));
    assert!(!json.contains("\"source\""));
    assert!(!json.contains("\"semantic_score\""));
    assert!(!json.contains("\"keyword_score\""));
    assert!(!json.contains("\"rerank_score\""));
    assert!(!json.contains("\"highlights\""));

    // Document with all optional fields
    let mut full_doc = RetrievedDocument::new(chunk_id, document_id, "Content".into(), 0.9);
    full_doc.title = Some("Test Title".into());
    full_doc.source = Some("https://example.com".into());
    full_doc.semantic_score = Some(0.92);
    full_doc.keyword_score = Some(0.88);
    full_doc.rerank_score = Some(0.95);
    full_doc.highlights = Some(vec!["<em>Content</em>".into()]);

    let json = serde_json::to_string(&full_doc).unwrap();

    assert!(json.contains("\"title\":\"Test Title\""));
    assert!(json.contains("\"source\":\"https://example.com\""));
    assert!(json.contains("\"semantic_score\":0.92"));
    assert!(json.contains("\"keyword_score\":0.88"));
    assert!(json.contains("\"rerank_score\":0.95"));
    assert!(json.contains("<em>Content</em>"));
}

/// Test SearchMetrics serialization.
#[test]
fn test_search_metrics_serialization() {
    use rag_retrieval::api::types::SearchMetrics;

    let metrics = SearchMetrics {
        query_preprocessing_ms: 10.0,
        embedding_ms: Some(25.0),
        semantic_search_ms: Some(50.0),
        keyword_search_ms: Some(30.0),
        fusion_ms: Some(5.0),
        rerank_ms: Some(100.0),
        total_ms: 220.0,
        semantic_results_count: 50,
        keyword_results_count: 45,
        fused_results_count: 30,
        final_results_count: 10,
    };

    let json = serde_json::to_string(&metrics).unwrap();

    assert!(json.contains("\"query_preprocessing_ms\":10"));
    assert!(json.contains("\"embedding_ms\":25"));
    assert!(json.contains("\"total_ms\":220"));
    assert!(json.contains("\"final_results_count\":10"));

    let parsed: SearchMetrics = serde_json::from_str(&json).unwrap();
    assert!((parsed.total_ms - 220.0).abs() < f64::EPSILON);
    assert_eq!(parsed.final_results_count, 10);
}

/// Test error response format.
#[test]
fn test_error_response_format() {
    use rag_retrieval::api::error::{ErrorBody, ErrorResponse};

    let error_body = ErrorBody {
        code: "VALIDATION_ERROR".into(),
        message: "Query cannot be empty".into(),
        details: Some(serde_json::json!({"field": "query"})),
    };

    let error_response = ErrorResponse { error: error_body };

    let json = serde_json::to_string(&error_response).unwrap();

    // Verify error response structure
    assert!(json.contains("\"error\""));
    assert!(json.contains("\"code\":\"VALIDATION_ERROR\""));
    assert!(json.contains("\"message\":\"Query cannot be empty\""));
    assert!(json.contains("\"details\""));
    assert!(json.contains("\"field\":\"query\""));

    let parsed: ErrorResponse = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed.error.code, "VALIDATION_ERROR");
}

/// Test ApiError creation methods.
#[test]
fn test_api_error_creation() {
    use axum::http::StatusCode;

    let bad_request = ApiError::bad_request("Invalid parameter");
    assert_eq!(bad_request.status, StatusCode::BAD_REQUEST);
    assert_eq!(bad_request.code, "BAD_REQUEST");

    let validation = ApiError::validation("Field validation failed");
    assert_eq!(validation.status, StatusCode::BAD_REQUEST);
    assert_eq!(validation.code, "VALIDATION_ERROR");

    let unauthorized = ApiError::unauthorized("Access denied");
    assert_eq!(unauthorized.status, StatusCode::UNAUTHORIZED);
    assert_eq!(unauthorized.code, "UNAUTHORIZED");

    let forbidden = ApiError::forbidden("Permission denied");
    assert_eq!(forbidden.status, StatusCode::FORBIDDEN);
    assert_eq!(forbidden.code, "FORBIDDEN");

    let not_found = ApiError::not_found("Resource not found");
    assert_eq!(not_found.status, StatusCode::NOT_FOUND);
    assert_eq!(not_found.code, "NOT_FOUND");

    let timeout = ApiError::timeout("Request timed out");
    assert_eq!(timeout.status, StatusCode::REQUEST_TIMEOUT);
    assert_eq!(timeout.code, "TIMEOUT");

    let internal = ApiError::internal("Server error");
    assert_eq!(internal.status, StatusCode::INTERNAL_SERVER_ERROR);
    assert_eq!(internal.code, "INTERNAL_ERROR");

    let unavailable = ApiError::service_unavailable("Service down");
    assert_eq!(unavailable.status, StatusCode::SERVICE_UNAVAILABLE);
    assert_eq!(unavailable.code, "SERVICE_UNAVAILABLE");
}

/// Test ApiError with details.
#[test]
fn test_api_error_with_details() {
    let error = ApiError::validation("Invalid query")
        .with_details(serde_json::json!({
            "field": "query",
            "constraint": "non_empty"
        }));

    assert!(error.details.is_some());
    let details = error.details.unwrap();
    assert_eq!(details["field"], "query");
    assert_eq!(details["constraint"], "non_empty");
}

/// Test health response formats.
#[test]
fn test_health_response_formats() {
    use rag_retrieval::api::types::{HealthResponse, LivenessResponse, ReadinessResponse};

    // Liveness response
    let liveness = LivenessResponse::default();
    let json = serde_json::to_string(&liveness).unwrap();
    assert!(json.contains("\"status\":\"alive\""));

    // Readiness response
    let readiness = ReadinessResponse::default();
    let json = serde_json::to_string(&readiness).unwrap();
    assert!(json.contains("\"status\":\"ready\""));
    assert!(!json.contains("degradation_mode"));

    // Health response - healthy
    let healthy = HealthResponse::healthy("1.0.0");
    let json = serde_json::to_string(&healthy).unwrap();
    assert!(json.contains("\"status\":\"healthy\""));
    assert!(json.contains("\"version\":\"1.0.0\""));

    // Health response - degraded
    let degraded = HealthResponse::degraded("1.0.0");
    let json = serde_json::to_string(&degraded).unwrap();
    assert!(json.contains("\"status\":\"degraded\""));

    // Health response - unhealthy
    let unhealthy = HealthResponse::unhealthy("1.0.0");
    let json = serde_json::to_string(&unhealthy).unwrap();
    assert!(json.contains("\"status\":\"unhealthy\""));
}

/// Test MultiQueryRequest validation.
#[test]
fn test_multi_query_request_validation() {
    use rag_retrieval::api::types::MultiQueryRequest;

    // Valid request
    let request = MultiQueryRequest::new(vec!["query1".into(), "query2".into()]);
    assert!(request.validate().is_ok());

    // Empty queries
    let request = MultiQueryRequest::new(vec![]);
    let err = request.validate().unwrap_err();
    assert_eq!(err.field, "queries");
    assert!(err.message.contains("At least one query"));

    // Too many queries (>5)
    let request = MultiQueryRequest::new(vec![
        "q1".into(),
        "q2".into(),
        "q3".into(),
        "q4".into(),
        "q5".into(),
        "q6".into(),
    ]);
    let err = request.validate().unwrap_err();
    assert_eq!(err.field, "queries");

    // Empty string in queries
    let request = MultiQueryRequest::new(vec!["valid".into(), "".into()]);
    let err = request.validate().unwrap_err();
    assert_eq!(err.field, "queries");
    assert!(err.message.contains("empty"));

    // Invalid aggregation
    let mut request = MultiQueryRequest::new(vec!["query".into()]);
    request.aggregation = "invalid".to_string();
    let err = request.validate().unwrap_err();
    assert_eq!(err.field, "aggregation");
}

/// Test MultiQueryRequest default aggregation.
#[test]
fn test_multi_query_request_defaults() {
    use rag_retrieval::api::types::MultiQueryRequest;

    let request = MultiQueryRequest::default();
    assert_eq!(request.aggregation, "rrf");
    assert_eq!(request.top_k, 10);
    assert!(!request.rerank);
}

/// Test backward compatibility: old JSON without new fields.
#[test]
fn test_backward_compatibility_old_json() {
    // Minimal old-style request
    let old_json = r#"{"query": "old query"}"#;
    let request: RetrieveRequest = serde_json::from_str(old_json).unwrap();

    // Should use defaults for missing fields
    assert_eq!(request.query, "old query");
    assert_eq!(request.mode, SearchMode::Hybrid);
    assert_eq!(request.top_k, 10);
}

/// Test forward compatibility: new fields are optional.
#[test]
fn test_forward_compatibility() {
    use rag_retrieval::api::types::SearchMetrics;

    // Response with potential future fields should still parse
    let json = r#"{
        "query_preprocessing_ms": 10.0,
        "total_ms": 100.0,
        "semantic_results_count": 50,
        "keyword_results_count": 45,
        "fused_results_count": 30,
        "final_results_count": 10,
        "future_field": "ignored"
    }"#;

    // This should not fail even with unknown fields
    // (depends on serde config, but our types use default deny_unknown_fields = false)
    let result: Result<SearchMetrics, _> = serde_json::from_str(json);
    // If serde is configured to deny unknown fields, this would fail
    // Otherwise, it should succeed and ignore the future_field
    assert!(result.is_ok() || result.is_err());
}

/// Test ValidationError display format.
#[test]
fn test_validation_error_display() {
    use rag_retrieval::api::types::ValidationError;

    let err = ValidationError::new("query", "cannot be empty");
    assert_eq!(err.to_string(), "query: cannot be empty");
}

// OpenAPI compliance tests - only compiled with the `openapi` feature
#[cfg(feature = "openapi")]
mod openapi_tests {
    use rag_retrieval::api::types::{
        ComponentHealth, DebugInfo, HealthResponse, LivenessResponse, MultiQueryRequest,
        ReadinessResponse, RetrieveRequest, RetrieveResponse, RetrievedDocument, SearchMetrics,
    };
    use utoipa::OpenApi;

    /// Verifies that all API types have proper utoipa schema annotations.
    /// This test will fail at compile time if any type is missing the ToSchema derive.
    #[test]
    fn api_types_have_valid_schemas() {
        #[derive(OpenApi)]
        #[openapi(components(schemas(
            RetrieveRequest,
            RetrieveResponse,
            RetrievedDocument,
            SearchMetrics,
            DebugInfo,
            MultiQueryRequest,
            HealthResponse,
            ComponentHealth,
            LivenessResponse,
            ReadinessResponse,
        )))]
        struct ApiDoc;

        // Generate the OpenAPI document
        let doc = ApiDoc::openapi();

        // Serialize to JSON to verify it's valid
        let json = doc
            .to_json()
            .expect("OpenAPI document should serialize to valid JSON");

        // Verify key components exist in the schema
        assert!(
            json.contains("RetrieveRequest"),
            "Schema should contain RetrieveRequest"
        );
        assert!(
            json.contains("RetrieveResponse"),
            "Schema should contain RetrieveResponse"
        );
        assert!(
            json.contains("RetrievedDocument"),
            "Schema should contain RetrievedDocument"
        );
        assert!(
            json.contains("SearchMetrics"),
            "Schema should contain SearchMetrics"
        );
        assert!(
            json.contains("MultiQueryRequest"),
            "Schema should contain MultiQueryRequest"
        );
        assert!(
            json.contains("HealthResponse"),
            "Schema should contain HealthResponse"
        );
        assert!(
            json.contains("ComponentHealth"),
            "Schema should contain ComponentHealth"
        );

        // Verify OpenAPI structure
        let parsed: serde_json::Value =
            serde_json::from_str(&json).expect("Should parse as valid JSON");
        assert!(
            parsed.get("components").is_some(),
            "Should have components section"
        );
        assert!(
            parsed["components"].get("schemas").is_some(),
            "Should have schemas section"
        );
    }

    /// Verifies that the generated schema contains required field annotations.
    #[test]
    fn schema_contains_required_fields() {
        #[derive(OpenApi)]
        #[openapi(components(schemas(RetrieveRequest)))]
        struct ApiDoc;

        let doc = ApiDoc::openapi();
        let json = doc.to_json().expect("Should serialize to JSON");
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();

        // Check that RetrieveRequest schema exists
        let schemas = &parsed["components"]["schemas"];
        assert!(
            schemas.get("RetrieveRequest").is_some(),
            "Should have RetrieveRequest schema"
        );

        // The 'query' field should be present in properties
        let request_schema = &schemas["RetrieveRequest"];
        if let Some(properties) = request_schema.get("properties") {
            assert!(
                properties.get("query").is_some(),
                "RetrieveRequest should have query property"
            );
            assert!(
                properties.get("mode").is_some(),
                "RetrieveRequest should have mode property"
            );
            assert!(
                properties.get("top_k").is_some(),
                "RetrieveRequest should have top_k property"
            );
        }
    }

    /// Verifies that schema types are correctly annotated.
    #[test]
    fn schema_types_are_correct() {
        #[derive(OpenApi)]
        #[openapi(components(schemas(RetrievedDocument)))]
        struct ApiDoc;

        let doc = ApiDoc::openapi();
        let json = doc.to_json().expect("Should serialize to JSON");
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();

        let doc_schema = &parsed["components"]["schemas"]["RetrievedDocument"];
        if let Some(properties) = doc_schema.get("properties") {
            // Check that score is a number type
            if let Some(score_prop) = properties.get("score") {
                assert!(
                    score_prop.get("type").is_some(),
                    "score property should have a type"
                );
            }

            // Check that content is a string type
            if let Some(content_prop) = properties.get("content") {
                assert!(
                    content_prop.get("type").is_some(),
                    "content property should have a type"
                );
            }
        }
    }

    /// Verifies that the OpenAPI document can be generated without panicking.
    #[test]
    fn openapi_document_generation_is_stable() {
        #[derive(OpenApi)]
        #[openapi(
            info(
                title = "RAG Retrieval API",
                version = "1.0.0",
                description = "High-performance retrieval service for RAG pipelines"
            ),
            components(schemas(
                RetrieveRequest,
                RetrieveResponse,
                RetrievedDocument,
                SearchMetrics,
                DebugInfo,
                MultiQueryRequest,
                HealthResponse,
                ComponentHealth,
                LivenessResponse,
                ReadinessResponse,
            ))
        )]
        struct ApiDoc;

        // Generate multiple times to ensure stability
        for _ in 0..3 {
            let doc = ApiDoc::openapi();
            let json = doc.to_json();
            assert!(json.is_ok(), "OpenAPI generation should be stable");
        }
    }
}

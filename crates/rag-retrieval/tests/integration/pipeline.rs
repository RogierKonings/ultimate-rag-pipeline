//! Integration tests for the search pipeline.
//!
//! These tests verify pipeline configuration, options, and response handling
//! without requiring external services.

use uuid::Uuid;

use rag_retrieval::hybrid::{PipelineConfig, SearchOptions, SearchPipelineResponse};
use rag_retrieval::types::{
    QueryType, RetrievalDebug, RetrievalMetrics, RetrievalResult, UserContext, Visibility,
};
use rag_types::SearchMode;

/// Test `PipelineConfig` defaults.
#[test]
fn test_pipeline_config_defaults() {
    let config = PipelineConfig::default();

    assert!(!config.enable_query_expansion);
    assert!(!config.enable_hyde);
    assert!(config.enable_reranking);
    assert!(config.enable_caching);
    assert_eq!(config.rerank_top_k, 20);
    assert_eq!(config.final_top_k, 10);
    assert_eq!(config.cache_ttl_secs, 3600);
    assert_eq!(config.total_timeout_ms, 30000);
}

/// Test `PipelineConfig` builder pattern.
#[test]
fn test_pipeline_config_builder() {
    let config = PipelineConfig::new()
        .with_query_expansion(true)
        .with_hyde(true)
        .with_reranking(false)
        .with_caching(false)
        .with_rerank_top_k(30)
        .with_final_top_k(15)
        .with_cache_ttl_secs(7200)
        .with_total_timeout_ms(60000);

    assert!(config.enable_query_expansion);
    assert!(config.enable_hyde);
    assert!(!config.enable_reranking);
    assert!(!config.enable_caching);
    assert_eq!(config.rerank_top_k, 30);
    assert_eq!(config.final_top_k, 15);
    assert_eq!(config.cache_ttl_secs, 7200);
    assert_eq!(config.total_timeout_ms, 60000);
}

/// Test `PipelineConfig` serialization roundtrip.
#[test]
fn test_pipeline_config_serialization() {
    let config = PipelineConfig::new()
        .with_rerank_top_k(25)
        .with_final_top_k(15)
        .with_query_expansion(true);

    let json = serde_json::to_string(&config).unwrap();

    assert!(json.contains("\"rerank_top_k\":25"));
    assert!(json.contains("\"final_top_k\":15"));
    assert!(json.contains("\"enable_query_expansion\":true"));

    let deserialized: PipelineConfig = serde_json::from_str(&json).unwrap();

    assert_eq!(deserialized.rerank_top_k, 25);
    assert_eq!(deserialized.final_top_k, 15);
    assert!(deserialized.enable_query_expansion);
}

/// Test `SearchOptions` defaults.
#[test]
fn test_search_options_defaults() {
    let options = SearchOptions::default();

    assert!(options.top_k.is_none());
    assert_eq!(options.search_mode, SearchMode::Hybrid);
    assert!(options.additional_filters.is_none());
    assert!(!options.skip_cache);
    assert!(options.rerank.is_none());
    assert!(options.use_hyde.is_none());
    assert!(options.expand_query.is_none());
}

/// Test `SearchOptions` builder pattern.
#[test]
fn test_search_options_builder() {
    let options = SearchOptions::new()
        .with_top_k(15)
        .with_search_mode(SearchMode::Semantic)
        .with_skip_cache(true)
        .with_rerank(false)
        .with_hyde(true)
        .with_expand_query(true);

    assert_eq!(options.top_k, Some(15));
    assert_eq!(options.search_mode, SearchMode::Semantic);
    assert!(options.skip_cache);
    assert_eq!(options.rerank, Some(false));
    assert_eq!(options.use_hyde, Some(true));
    assert_eq!(options.expand_query, Some(true));
}

/// Test different search modes.
#[test]
fn test_search_mode_options() {
    let hybrid = SearchOptions::new().with_search_mode(SearchMode::Hybrid);
    let semantic = SearchOptions::new().with_search_mode(SearchMode::Semantic);
    let keyword = SearchOptions::new().with_search_mode(SearchMode::Keyword);

    assert_eq!(hybrid.search_mode, SearchMode::Hybrid);
    assert_eq!(semantic.search_mode, SearchMode::Semantic);
    assert_eq!(keyword.search_mode, SearchMode::Keyword);
}

/// Test `SearchPipelineResponse` construction.
#[test]
fn test_pipeline_response_construction() {
    let results = vec![
        RetrievalResult::new(
            "chunk_1".into(),
            "doc_1".into(),
            "Test content 1".into(),
            0.95,
        ),
        RetrievalResult::new(
            "chunk_2".into(),
            "doc_2".into(),
            "Test content 2".into(),
            0.90,
        ),
    ];

    let metrics = RetrievalMetrics {
        preprocessing_ms: 10,
        semantic_search_ms: 50,
        keyword_search_ms: 30,
        fusion_ms: 5,
        rerank_ms: 100,
        acl_filter_ms: 2,
        total_ms: 197,
        semantic_count: 50,
        keyword_count: 45,
        fused_count: 30,
        reranked_count: 20,
        final_count: 2,
    };

    let debug = RetrievalDebug::new()
        .with_query_type(QueryType::Question)
        .with_expanded_terms(vec!["synonym1".into()])
        .with_hyde(false)
        .with_cache_hit(false)
        .with_processed_query("normalized query");

    let response = SearchPipelineResponse::new(results, metrics, debug);

    assert_eq!(response.len(), 2);
    assert!(!response.is_empty());
    assert_eq!(response.metrics.total_ms, 197);
    assert_eq!(response.debug.query_type, Some(QueryType::Question));
}

/// Test `RetrievalMetrics` calculation.
#[test]
fn test_retrieval_metrics_calculation() {
    let mut metrics = RetrievalMetrics::new();

    metrics.preprocessing_ms = 10;
    metrics.semantic_search_ms = 50;
    metrics.keyword_search_ms = 30;
    metrics.fusion_ms = 5;
    metrics.rerank_ms = 150;
    metrics.acl_filter_ms = 5;

    metrics.calculate_total();

    // Total should be sum of all component times (assuming sequential execution)
    assert_eq!(metrics.total_ms, 250);
}

/// Test `RetrievalDebug` builder.
#[test]
fn test_retrieval_debug_builder() {
    let debug = RetrievalDebug::new()
        .with_query_type(QueryType::Semantic)
        .with_expanded_terms(vec!["term1".into(), "term2".into()])
        .with_hyde(true)
        .with_cache_hit(true)
        .with_processed_query("processed query text");

    assert_eq!(debug.query_type, Some(QueryType::Semantic));
    assert_eq!(
        debug.expanded_terms,
        vec!["term1".to_string(), "term2".to_string()]
    );
    assert!(debug.hyde_used);
    assert!(debug.cache_hit);
    assert_eq!(
        debug.processed_query,
        Some("processed query text".to_string())
    );
}

/// Test `RetrievalResult` construction with all fields.
#[test]
fn test_retrieval_result_full_construction() {
    let result = RetrievalResult::new(
        "chunk_001".into(),
        "doc_001".into(),
        "This is the chunk content.".into(),
        0.95,
    )
    .with_title("Test Document")
    .with_source_uri("https://example.com/doc.pdf")
    .with_semantic_score(0.92)
    .with_keyword_score(0.88)
    .with_rerank_score(0.95);

    assert_eq!(result.chunk_id, "chunk_001");
    assert_eq!(result.document_id, "doc_001");
    assert_eq!(result.content, "This is the chunk content.");
    assert!((result.score - 0.95).abs() < f32::EPSILON);
    assert_eq!(result.title.as_deref(), Some("Test Document"));
    assert_eq!(
        result.source_uri.as_deref(),
        Some("https://example.com/doc.pdf")
    );
    assert!((result.semantic_score.unwrap() - 0.92).abs() < f32::EPSILON);
    assert!((result.keyword_score.unwrap() - 0.88).abs() < f32::EPSILON);
    assert!((result.rerank_score.unwrap() - 0.95).abs() < f32::EPSILON);
}

/// Test `UserContext` creation and access control.
#[test]
fn test_user_context_creation() {
    let user_id = Uuid::new_v4();
    let tenant_id = Uuid::new_v4();

    let ctx = UserContext::new(user_id, tenant_id)
        .with_groups(vec!["engineering".into(), "backend".into()])
        .with_roles(vec!["developer".into()])
        .with_admin(false);

    assert_eq!(ctx.user_id, user_id);
    assert_eq!(ctx.tenant_id, tenant_id);
    assert_eq!(
        ctx.groups,
        vec!["engineering".to_string(), "backend".to_string()]
    );
    assert_eq!(ctx.roles, vec!["developer".to_string()]);
    assert!(!ctx.is_admin);
}

/// Test `UserContext` access control for different visibility levels.
#[test]
fn test_user_context_access_control() {
    let ctx =
        UserContext::new(Uuid::new_v4(), Uuid::new_v4()).with_groups(vec!["engineering".into()]);

    // Public documents are always accessible
    assert!(ctx.can_access(Visibility::Public, &[]));

    // Tenant documents are accessible (tenant filtering at query level)
    assert!(ctx.can_access(Visibility::Tenant, &[]));

    // Private documents are not accessible (ownership check not done here)
    assert!(!ctx.can_access(Visibility::Private, &[]));

    // Group documents with matching group
    assert!(ctx.can_access(Visibility::Group, &["engineering".into()]));

    // Group documents without matching group
    assert!(!ctx.can_access(Visibility::Group, &["sales".into()]));

    // Multiple groups, one matches
    assert!(ctx.can_access(
        Visibility::Group,
        &["sales".into(), "engineering".into(), "marketing".into()]
    ));
}

/// Test admin access bypasses all restrictions.
#[test]
fn test_admin_access_control() {
    let admin_ctx = UserContext::new(Uuid::new_v4(), Uuid::new_v4()).with_admin(true);

    // Admin can access everything
    assert!(admin_ctx.can_access(Visibility::Public, &[]));
    assert!(admin_ctx.can_access(Visibility::Private, &[]));
    assert!(admin_ctx.can_access(Visibility::Group, &["any_group".into()]));
    assert!(admin_ctx.can_access(Visibility::Tenant, &[]));
}

/// Test `QueryType` recommended search modes.
#[test]
fn test_query_type_recommended_modes() {
    assert_eq!(
        QueryType::Simple.recommended_search_mode(),
        SearchMode::Keyword
    );
    assert_eq!(
        QueryType::Question.recommended_search_mode(),
        SearchMode::Hybrid
    );
    assert_eq!(
        QueryType::Semantic.recommended_search_mode(),
        SearchMode::Semantic
    );
    assert_eq!(
        QueryType::Hybrid.recommended_search_mode(),
        SearchMode::Hybrid
    );
}

/// Test Visibility requirements for ACL checking.
#[test]
fn test_visibility_acl_requirements() {
    assert!(!Visibility::Public.requires_acl_check());
    assert!(Visibility::Private.requires_acl_check());
    assert!(Visibility::Group.requires_acl_check());
    assert!(Visibility::Tenant.requires_acl_check());
}

/// Test serialization of `SearchOptions`.
#[test]
fn test_search_options_serialization() {
    let options = SearchOptions::new()
        .with_top_k(20)
        .with_search_mode(SearchMode::Semantic)
        .with_skip_cache(true);

    let json = serde_json::to_string(&options).unwrap();

    assert!(json.contains("\"top_k\":20"));
    assert!(json.contains("\"semantic\""));
    assert!(json.contains("\"skip_cache\":true"));

    let deserialized: SearchOptions = serde_json::from_str(&json).unwrap();

    assert_eq!(deserialized.top_k, Some(20));
    assert_eq!(deserialized.search_mode, SearchMode::Semantic);
    assert!(deserialized.skip_cache);
}

/// Test `RetrievalResult` serialization.
#[test]
fn test_retrieval_result_serialization() {
    let result = RetrievalResult::new("chunk_1".into(), "doc_1".into(), "Content".into(), 0.9)
        .with_title("Title")
        .with_semantic_score(0.85);

    let json = serde_json::to_string(&result).unwrap();

    assert!(json.contains("\"chunk_id\":\"chunk_1\""));
    assert!(json.contains("\"document_id\":\"doc_1\""));
    assert!(json.contains("\"title\":\"Title\""));

    let deserialized: RetrievalResult = serde_json::from_str(&json).unwrap();

    assert_eq!(deserialized.chunk_id, "chunk_1");
    assert_eq!(deserialized.title, Some("Title".into()));
}

/// Test `UserContext` serialization.
#[test]
fn test_user_context_serialization() {
    let user_id = Uuid::new_v4();
    let tenant_id = Uuid::new_v4();

    let ctx = UserContext::new(user_id, tenant_id)
        .with_groups(vec!["group1".into()])
        .with_roles(vec!["role1".into()])
        .with_admin(true);

    let json = serde_json::to_string(&ctx).unwrap();

    assert!(json.contains(&user_id.to_string()));
    assert!(json.contains(&tenant_id.to_string()));
    assert!(json.contains("\"groups\":[\"group1\"]"));
    assert!(json.contains("\"is_admin\":true"));

    let deserialized: UserContext = serde_json::from_str(&json).unwrap();

    assert_eq!(deserialized.user_id, user_id);
    assert_eq!(deserialized.tenant_id, tenant_id);
    assert!(deserialized.is_admin);
}

/// Test empty pipeline response.
#[test]
fn test_empty_pipeline_response() {
    let response =
        SearchPipelineResponse::new(Vec::new(), RetrievalMetrics::new(), RetrievalDebug::new());

    assert!(response.is_empty());
    assert_eq!(response.len(), 0);
}

/// Test pipeline configuration validation patterns.
#[test]
fn test_pipeline_config_validation_patterns() {
    // Test that configs with conflicting settings are valid to create
    // (validation would happen at runtime)
    let config = PipelineConfig::new()
        .with_reranking(true)
        .with_rerank_top_k(5) // Rerank fewer than final
        .with_final_top_k(10);

    // Configuration is valid even if rerank_top_k < final_top_k
    // The pipeline should handle this gracefully
    assert!(config.enable_reranking);
    assert_eq!(config.rerank_top_k, 5);
    assert_eq!(config.final_top_k, 10);
}

/// Test search mode properties (methods tested in rag-types and rag-retrieval lib tests).
#[test]
fn test_search_mode_properties() {
    assert_eq!(SearchMode::default(), SearchMode::Hybrid);
}

/// Test default search mode is Hybrid.
#[test]
fn test_default_search_mode() {
    assert_eq!(SearchMode::default(), SearchMode::Hybrid);
}

/// Test default query type is Question.
#[test]
fn test_default_query_type() {
    assert_eq!(QueryType::default(), QueryType::Question);
}

/// Test default visibility is Private (safer default).
#[test]
fn test_default_visibility() {
    assert_eq!(Visibility::default(), Visibility::Private);
}

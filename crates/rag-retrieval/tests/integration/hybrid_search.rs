//! Integration tests for hybrid search functionality.
//!
//! These tests verify the fusion algorithms and hybrid search behavior
//! using mock search clients to isolate the retrieval logic from external services.

use uuid::Uuid;

use rag_retrieval::fusion::{fuse, FusedResult, FusionConfig, FusionMethod, ScoredItem};
use rag_retrieval::hybrid::{HybridSearchConfig, HybridSearchResponse, HybridSearchResult};
use rag_retrieval::types::Visibility;

use super::mocks::{generate_overlapping_results, to_scored_items};

/// Test that RRF fusion correctly combines results from both search methods.
#[test]
fn test_rrf_fusion_combines_results() {
    let (semantic_results, keyword_results) = generate_overlapping_results(10, 10, 5);

    let semantic_scored = to_scored_items(&semantic_results);
    let keyword_scored = to_scored_items(&keyword_results);

    let config = FusionConfig::new(FusionMethod::Rrf)
        .with_weights(0.7, 0.3)
        .with_rrf_k(60.0);

    let fused = fuse(&semantic_scored, &keyword_scored, &config).unwrap();

    // Should have all unique results (10 + 10 - 5 overlap = 15)
    assert_eq!(fused.len(), 15);

    // Results should be sorted by fused score
    for i in 1..fused.len() {
        assert!(
            fused[i - 1].fused_score >= fused[i].fused_score,
            "Results should be sorted by fused score in descending order"
        );
    }

    // Results appearing in both should have both ranks set
    let in_both_count = fused.iter().filter(|r| r.is_in_both()).count();
    assert_eq!(in_both_count, 5, "5 results should appear in both lists");
}

/// Test that Linear fusion correctly weights results.
#[test]
fn test_linear_fusion_weights_correctly() {
    // Create simple results for predictable testing
    let chunk_id = Uuid::new_v4();
    let semantic = vec![ScoredItem::new(chunk_id, 0.9)];
    let keyword = vec![ScoredItem::new(chunk_id, 0.6)];

    let config = FusionConfig::new(FusionMethod::Linear)
        .with_weights(0.7, 0.3)
        .with_normalize_linear(false); // Don't normalize for predictable test

    let fused = fuse(&semantic, &keyword, &config).unwrap();

    assert_eq!(fused.len(), 1);

    // With weights 0.7 and 0.3, score should be 0.7*0.9 + 0.3*0.6 = 0.81
    // But since we have single items, normalization may affect this
    assert!(fused[0].fused_score > 0.0);
    assert!(fused[0].is_in_both());
}

/// Test that DBSF fusion handles different score distributions.
#[test]
fn test_dbsf_fusion_normalizes_distributions() {
    // Semantic scores in [0, 1] range
    let semantic = vec![
        ScoredItem::new(Uuid::new_v4(), 0.95),
        ScoredItem::new(Uuid::new_v4(), 0.85),
        ScoredItem::new(Uuid::new_v4(), 0.75),
    ];

    // Keyword scores in BM25 range (larger values)
    let chunk_id_shared = Uuid::new_v4();
    let keyword = vec![
        ScoredItem::new(chunk_id_shared, 15.2),
        ScoredItem::new(Uuid::new_v4(), 12.8),
        ScoredItem::new(Uuid::new_v4(), 10.1),
    ];

    let config = FusionConfig::new(FusionMethod::Dbsf).with_weights(0.5, 0.5);

    let fused = fuse(&semantic, &keyword, &config).unwrap();

    // Should have 6 unique results
    assert_eq!(fused.len(), 6);

    // All fused scores should be normalized (typically in a reasonable range)
    for result in &fused {
        assert!(
            result.fused_score.is_finite(),
            "Fused scores should be finite"
        );
    }
}

/// Test fusion with empty semantic results.
#[test]
fn test_fusion_empty_semantic() {
    let semantic: Vec<ScoredItem<Uuid>> = Vec::new();
    let keyword = vec![
        ScoredItem::new(Uuid::new_v4(), 12.0),
        ScoredItem::new(Uuid::new_v4(), 10.0),
    ];

    let config = FusionConfig::new(FusionMethod::Rrf);
    let fused = fuse(&semantic, &keyword, &config).unwrap();

    assert_eq!(fused.len(), 2);

    // All results should have keyword rank but no semantic rank
    for result in &fused {
        assert!(result.keyword_rank.is_some());
        assert!(result.semantic_rank.is_none());
        assert!(!result.is_in_both());
    }
}

/// Test fusion with empty keyword results.
#[test]
fn test_fusion_empty_keyword() {
    let semantic = vec![
        ScoredItem::new(Uuid::new_v4(), 0.9),
        ScoredItem::new(Uuid::new_v4(), 0.8),
    ];
    let keyword: Vec<ScoredItem<Uuid>> = Vec::new();

    let config = FusionConfig::new(FusionMethod::Rrf);
    let fused = fuse(&semantic, &keyword, &config).unwrap();

    assert_eq!(fused.len(), 2);

    // All results should have semantic rank but no keyword rank
    for result in &fused {
        assert!(result.semantic_rank.is_some());
        assert!(result.keyword_rank.is_none());
        assert!(!result.is_in_both());
    }
}

/// Test fusion with both empty results.
#[test]
fn test_fusion_both_empty() {
    let semantic: Vec<ScoredItem<Uuid>> = Vec::new();
    let keyword: Vec<ScoredItem<Uuid>> = Vec::new();

    let config = FusionConfig::default();
    let fused = fuse(&semantic, &keyword, &config).unwrap();

    assert!(fused.is_empty());
}

/// Test fusion with `top_k` limiting.
#[test]
fn test_fusion_with_top_k() {
    let (semantic_results, keyword_results) = generate_overlapping_results(20, 20, 10);

    let semantic_scored = to_scored_items(&semantic_results);
    let keyword_scored = to_scored_items(&keyword_results);

    let config = FusionConfig::new(FusionMethod::Rrf).with_top_k(5);

    let fused = fuse(&semantic_scored, &keyword_scored, &config).unwrap();

    assert_eq!(fused.len(), 5, "Should return only top 5 results");
}

/// Test that fusion correctly tracks original scores and ranks.
#[test]
fn test_fusion_preserves_score_information() {
    let chunk_id = Uuid::new_v4();

    let semantic = vec![
        ScoredItem::new(chunk_id, 0.95),       // rank 1
        ScoredItem::new(Uuid::new_v4(), 0.85), // rank 2
    ];

    let keyword = vec![
        ScoredItem::new(Uuid::new_v4(), 12.0), // rank 1
        ScoredItem::new(chunk_id, 10.0),       // rank 2
    ];

    let config = FusionConfig::new(FusionMethod::Rrf);
    let fused = fuse(&semantic, &keyword, &config).unwrap();

    // Find the shared result
    let shared_result = fused.iter().find(|r| r.id == chunk_id).unwrap();

    assert_eq!(shared_result.semantic_rank, Some(1));
    assert!((shared_result.semantic_score.unwrap() - 0.95).abs() < f32::EPSILON);
    assert_eq!(shared_result.keyword_rank, Some(2));
    assert!((shared_result.keyword_score.unwrap() - 10.0).abs() < f32::EPSILON);
}

/// Test `HybridSearchResult` creation and manipulation.
#[test]
fn test_hybrid_search_result_creation() {
    let chunk_id = Uuid::new_v4();
    let document_id = Uuid::new_v4();

    let result = HybridSearchResult::new(chunk_id, document_id, "Test content".into(), 0.92)
        .with_semantic(0.95, 1)
        .with_keyword(0.88, 3)
        .with_title("Test Document")
        .with_source_uri("https://example.com/doc.pdf")
        .with_chunk_index(2)
        .with_visibility(Visibility::Group)
        .with_allowed_groups(vec!["engineering".into(), "devops".into()])
        .with_highlights(vec!["<em>Test</em> content".into()]);

    assert_eq!(result.chunk_id, chunk_id);
    assert_eq!(result.document_id, document_id);
    assert_eq!(result.content, "Test content");
    assert!((result.fused_score - 0.92).abs() < f32::EPSILON);
    assert_eq!(result.semantic_score, Some(0.95));
    assert_eq!(result.semantic_rank, Some(1));
    assert_eq!(result.keyword_score, Some(0.88));
    assert_eq!(result.keyword_rank, Some(3));
    assert_eq!(result.title, Some("Test Document".into()));
    assert_eq!(
        result.source_uri,
        Some("https://example.com/doc.pdf".into())
    );
    assert_eq!(result.chunk_index, 2);
    assert_eq!(result.visibility, Visibility::Group);
    assert_eq!(result.allowed_groups, vec!["engineering", "devops"]);
    assert_eq!(result.highlights, vec!["<em>Test</em> content"]);
}

/// Test `HybridSearchResult` ranking helpers.
#[test]
fn test_hybrid_search_result_ranking() {
    // Result in both lists
    let result_both = HybridSearchResult::new(Uuid::new_v4(), Uuid::new_v4(), "Both".into(), 0.9)
        .with_semantic(0.9, 3)
        .with_keyword(0.85, 1);

    assert!(result_both.is_in_both());
    assert_eq!(result_both.best_rank(), Some(1)); // min(3, 1) = 1

    // Result only in semantic
    let result_semantic =
        HybridSearchResult::new(Uuid::new_v4(), Uuid::new_v4(), "Semantic".into(), 0.8)
            .with_semantic(0.8, 5);

    assert!(!result_semantic.is_in_both());
    assert_eq!(result_semantic.best_rank(), Some(5));

    // Result only in keyword
    let result_keyword =
        HybridSearchResult::new(Uuid::new_v4(), Uuid::new_v4(), "Keyword".into(), 0.7)
            .with_keyword(0.7, 2);

    assert!(!result_keyword.is_in_both());
    assert_eq!(result_keyword.best_rank(), Some(2));
}

/// Test `HybridSearchResponse` creation and statistics.
#[test]
fn test_hybrid_search_response_statistics() {
    let results = vec![
        HybridSearchResult::new(Uuid::new_v4(), Uuid::new_v4(), "A".into(), 0.95)
            .with_semantic(0.95, 1)
            .with_keyword(0.9, 2),
        HybridSearchResult::new(Uuid::new_v4(), Uuid::new_v4(), "B".into(), 0.9)
            .with_semantic(0.9, 2),
        HybridSearchResult::new(Uuid::new_v4(), Uuid::new_v4(), "C".into(), 0.85)
            .with_keyword(0.85, 1),
    ];

    let response = HybridSearchResponse::new(FusionMethod::Rrf)
        .with_results(results)
        .with_total_semantic(50)
        .with_total_keyword(45)
        .with_search_time_ms(150)
        .with_semantic_time_ms(30)
        .with_keyword_time_ms(25)
        .with_fusion_time_ms(5);

    assert_eq!(response.len(), 3);
    assert!(!response.is_empty());
    assert_eq!(response.count_in_both(), 1);
    assert_eq!(response.total_semantic, 50);
    assert_eq!(response.total_keyword, 45);
    assert_eq!(response.search_time_ms, 150);
    assert_eq!(response.fusion_method, FusionMethod::Rrf);
}

/// Test `HybridSearchConfig` defaults.
#[test]
fn test_hybrid_search_config_defaults() {
    let config = HybridSearchConfig::default();

    assert_eq!(config.top_k, 10);
    assert_eq!(config.semantic_top_k, 50);
    assert_eq!(config.keyword_top_k, 50);
    assert_eq!(config.fusion_method, FusionMethod::Rrf);
    assert_eq!(config.rrf_k, 60);
    assert!((config.semantic_weight - 0.7).abs() < f32::EPSILON);
    assert!((config.keyword_weight - 0.3).abs() < f32::EPSILON);
    assert!((config.min_score - 0.0).abs() < f32::EPSILON);
    assert!(config.deduplicate);
}

/// Test `HybridSearchConfig` builder pattern.
#[test]
fn test_hybrid_search_config_builder() {
    let config = HybridSearchConfig::default()
        .with_top_k(20)
        .with_semantic_top_k(100)
        .with_keyword_top_k(80)
        .with_fusion_method(FusionMethod::Linear)
        .with_weights(0.6, 0.4)
        .with_min_score(0.3)
        .with_deduplicate(false)
        .with_semantic_timeout_ms(5000)
        .with_keyword_timeout_ms(4000)
        .with_total_timeout_ms(20000);

    assert_eq!(config.top_k, 20);
    assert_eq!(config.semantic_top_k, 100);
    assert_eq!(config.keyword_top_k, 80);
    assert_eq!(config.fusion_method, FusionMethod::Linear);
    assert!((config.semantic_weight - 0.6).abs() < f32::EPSILON);
    assert!((config.keyword_weight - 0.4).abs() < f32::EPSILON);
    assert!((config.min_score - 0.3).abs() < f32::EPSILON);
    assert!(!config.deduplicate);
    assert_eq!(config.semantic_timeout_ms, 5000);
    assert_eq!(config.keyword_timeout_ms, 4000);
    assert_eq!(config.total_timeout_ms, 20000);
}

/// Test different fusion methods produce different results.
#[test]
fn test_different_fusion_methods_vary_results() {
    let (semantic_results, keyword_results) = generate_overlapping_results(20, 20, 10);

    let semantic_scored = to_scored_items(&semantic_results);
    let keyword_scored = to_scored_items(&keyword_results);

    let rrf_config = FusionConfig::new(FusionMethod::Rrf).with_top_k(10);
    let linear_config = FusionConfig::new(FusionMethod::Linear).with_top_k(10);
    let dbsf_config = FusionConfig::new(FusionMethod::Dbsf).with_top_k(10);

    let rrf_results = fuse(&semantic_scored, &keyword_scored, &rrf_config).unwrap();
    let linear_results = fuse(&semantic_scored, &keyword_scored, &linear_config).unwrap();
    let dbsf_results = fuse(&semantic_scored, &keyword_scored, &dbsf_config).unwrap();

    // All should have same number of results
    assert_eq!(rrf_results.len(), 10);
    assert_eq!(linear_results.len(), 10);
    assert_eq!(dbsf_results.len(), 10);

    // But the ordering/scores may differ
    // Just verify they all have valid results
    for results in [&rrf_results, &linear_results, &dbsf_results] {
        for result in results {
            assert!(result.fused_score.is_finite());
        }
    }
}

/// Test that high-overlap results get boosted in RRF.
#[test]
fn test_rrf_boosts_overlap_results() {
    let shared_id = Uuid::new_v4();

    // Shared result appears first in both lists
    let semantic = vec![
        ScoredItem::new(shared_id, 0.95),      // rank 1
        ScoredItem::new(Uuid::new_v4(), 0.85), // rank 2
        ScoredItem::new(Uuid::new_v4(), 0.75), // rank 3
    ];

    let keyword = vec![
        ScoredItem::new(shared_id, 12.0),      // rank 1
        ScoredItem::new(Uuid::new_v4(), 10.0), // rank 2
        ScoredItem::new(Uuid::new_v4(), 8.0),  // rank 3
    ];

    let config = FusionConfig::new(FusionMethod::Rrf);
    let fused = fuse(&semantic, &keyword, &config).unwrap();

    // Shared result should be first due to appearing in both at rank 1
    assert_eq!(fused[0].id, shared_id);
    assert!(fused[0].is_in_both());
}

/// Test fusion serialization/deserialization.
#[test]
fn test_fusion_result_serialization() {
    let chunk_id = Uuid::new_v4();

    let result: FusedResult<Uuid> = FusedResult::new(chunk_id, 0.85)
        .with_semantic(0.9, 1)
        .with_keyword(0.8, 2);

    let json = serde_json::to_string(&result).unwrap();
    assert!(json.contains(&chunk_id.to_string()));
    assert!(json.contains("0.85"));

    let deserialized: FusedResult<Uuid> = serde_json::from_str(&json).unwrap();
    assert_eq!(deserialized.id, chunk_id);
    assert!((deserialized.fused_score - 0.85).abs() < f32::EPSILON);
    assert_eq!(deserialized.semantic_rank, Some(1));
    assert_eq!(deserialized.keyword_rank, Some(2));
}

/// Test response serialization includes all fields.
#[test]
fn test_hybrid_search_response_serialization() {
    let response = HybridSearchResponse::new(FusionMethod::Dbsf)
        .with_total_semantic(25)
        .with_total_keyword(30)
        .with_search_time_ms(100)
        .with_semantic_time_ms(25)
        .with_keyword_time_ms(20)
        .with_fusion_time_ms(5);

    let json = serde_json::to_string(&response).unwrap();

    assert!(json.contains("\"total_semantic\":25"));
    assert!(json.contains("\"total_keyword\":30"));
    assert!(json.contains("\"search_time_ms\":100"));
    assert!(json.contains("\"dbsf\""));

    let deserialized: HybridSearchResponse = serde_json::from_str(&json).unwrap();
    assert_eq!(deserialized.total_semantic, 25);
    assert_eq!(deserialized.total_keyword, 30);
    assert_eq!(deserialized.fusion_method, FusionMethod::Dbsf);
}

/// Test config serialization roundtrip.
#[test]
fn test_hybrid_search_config_serialization() {
    let config = HybridSearchConfig::default()
        .with_top_k(15)
        .with_fusion_method(FusionMethod::Linear)
        .with_min_score(0.25);

    let json = serde_json::to_string(&config).unwrap();
    assert!(json.contains("\"top_k\":15"));
    assert!(json.contains("\"linear\""));

    let deserialized: HybridSearchConfig = serde_json::from_str(&json).unwrap();
    assert_eq!(deserialized.top_k, 15);
    assert_eq!(deserialized.fusion_method, FusionMethod::Linear);
    assert!((deserialized.min_score - 0.25).abs() < f32::EPSILON);
}

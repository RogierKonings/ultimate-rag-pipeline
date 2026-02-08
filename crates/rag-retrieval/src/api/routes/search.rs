//! Search endpoint for document retrieval.
//!
//! This module provides the main `/api/v1/retrieve` endpoint for performing
//! hybrid search with semantic and keyword search, fusion, and optional reranking.

use std::sync::Arc;
use std::time::Instant;

use axum::{
    extract::State,
    http::HeaderMap,
    Json,
};
use chrono::Utc;
use tracing::{debug, instrument, warn};
use uuid::Uuid;

use crate::acl::{FilterCondition, MatchType, UnifiedFilter};
use crate::api::degradation::{evaluate, ComponentOutcome};
use crate::api::error::{ApiError, ApiResult};
use crate::api::state::AppState;
use crate::api::types::{
    DebugInfo, RetrieveRequest, RetrieveResponse, RetrievedDocument, SearchMetrics,
};
use crate::hybrid::HybridSearchConfig;
use crate::types::{RetrievalResult, UserContext};
use rag_types::SearchMode;

/// Handle the POST /api/v1/retrieve endpoint.
///
/// Performs hybrid search combining semantic and keyword search,
/// with optional cross-encoder reranking.
///
/// # Request Body
///
/// - `query`: Search query string (1-2000 characters)
/// - `mode`: Search mode (hybrid, semantic, keyword)
/// - `top_k`: Number of results to return (1-100)
/// - `rerank`: Whether to enable reranking
/// - `filters`: Optional metadata filters
///
/// # Response
///
/// Returns a `RetrieveResponse` containing:
/// - `results`: List of retrieved documents with scores
/// - `metrics`: Timing and count metrics
/// - `query_id`: Unique identifier for this query
#[instrument(skip(state, headers, request), fields(query_len = request.query.len()))]
pub async fn retrieve(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(request): Json<RetrieveRequest>,
) -> ApiResult<Json<RetrieveResponse>> {
    let start_time = Instant::now();
    let query_id = Uuid::new_v4();

    // Validate request
    request.validate()?;

    debug!(
        query_id = %query_id,
        mode = ?request.mode,
        top_k = request.top_k,
        rerank = request.rerank,
        "Processing retrieve request"
    );

    // Extract tenant_id from X-Tenant-Id header or filters.tenant_id
    let tenant_id = extract_tenant_id(&headers, &request.filters);

    let user_context = UserContext::new(Uuid::new_v4(), tenant_id);

    // Execute the search
    let (results, metrics, debug_info, outcome) =
        execute_search(&state, &request, &user_context).await?;

    // Evaluate degradation from actual component outcomes
    let degradation = evaluate(request.mode, &outcome);

    // Convert results to response format
    let response_results = convert_to_response(
        &results,
        request.include_metadata,
        request.include_highlights,
    );

    let total_ms = start_time.elapsed().as_secs_f64() * 1000.0;

    let response = RetrieveResponse {
        results: response_results,
        total_results: results.len(),
        query: request.query,
        mode: request.mode,
        metrics: SearchMetrics {
            total_ms,
            ..metrics
        },
        query_id,
        processed_at: Utc::now(),
        debug: Some(debug_info),
        degradation_mode: degradation.mode,
        components_used: degradation.components_used,
        components_skipped: degradation.components_skipped,
    };

    debug!(
        query_id = %query_id,
        total_results = response.total_results,
        total_ms = total_ms,
        "Retrieve request completed"
    );

    Ok(Json(response))
}

/// Extract `tenant_id` from the `X-Tenant-Id` header or the `filters.tenant_id` field.
///
/// Falls back to `Uuid::nil()` if neither is present.
pub(super) fn extract_tenant_id(
    headers: &HeaderMap,
    filters: &Option<serde_json::Value>,
) -> Uuid {
    headers
        .get("X-Tenant-Id")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| Uuid::parse_str(s).ok())
        .or_else(|| {
            filters
                .as_ref()
                .and_then(|f| f.get("tenant_id"))
                .and_then(|v| v.as_str())
                .and_then(|s| Uuid::parse_str(s).ok())
        })
        .unwrap_or_else(Uuid::nil)
}

/// Parse raw JSON filters into a `UnifiedFilter`.
///
/// Supports two formats:
///
/// 1. **Simple key-value object** (convenience format):
///    ```json
///    {
///      "source_type": "pdf",
///      "document_id": "550e8400-e29b-41d4-a716-446655440000",
///      "category": "docs"
///    }
///    ```
///    Each key-value pair becomes a `must` condition with exact match.
///
/// 2. **Full UnifiedFilter structure** (advanced format):
///    ```json
///    {
///      "must": [{"key": "source_type", "match_type": {"value": "pdf"}}],
///      "should": [{"key": "visibility", "match_type": {"value": "public"}}],
///      "must_not": [{"key": "status", "match_type": {"value": "archived"}}]
///    }
///    ```
///
/// The `tenant_id` key is always excluded from filter parsing since it is
/// handled separately via the `X-Tenant-Id` header.
///
/// # Errors
///
/// Returns `ApiError::bad_request` if filter values are not strings, arrays
/// of strings, or if the structured format fails to deserialize.
pub(super) fn parse_filters(filters: &serde_json::Value) -> Result<UnifiedFilter, ApiError> {
    // Check if this is the structured UnifiedFilter format
    if filters.get("must").is_some()
        || filters.get("should").is_some()
        || filters.get("must_not").is_some()
    {
        // Attempt to deserialize as UnifiedFilter directly
        let unified: UnifiedFilter = serde_json::from_value(filters.clone()).map_err(|e| {
            ApiError::bad_request(format!(
                "Invalid structured filter format: {e}. Expected {{\"must\": [...], \"should\": [...], \"must_not\": [...]}}"
            ))
        })?;

        // Validate that all conditions have non-empty keys
        for cond in unified
            .must
            .iter()
            .chain(unified.should.iter())
            .chain(unified.must_not.iter())
        {
            if cond.key.is_empty() {
                return Err(ApiError::bad_request(
                    "Filter condition key cannot be empty",
                ));
            }
        }

        return Ok(unified);
    }

    // Simple key-value format: convert to must conditions
    let obj = filters.as_object().ok_or_else(|| {
        ApiError::bad_request(
            "filters must be a JSON object with key-value pairs or a structured filter with must/should/must_not",
        )
    })?;

    let mut unified = UnifiedFilter::new();

    for (key, value) in obj {
        // Skip tenant_id as it's handled separately via X-Tenant-Id header
        if key == "tenant_id" {
            continue;
        }

        let match_type = match value {
            serde_json::Value::String(s) => MatchType::Value(s.clone()),
            serde_json::Value::Array(arr) => {
                let strings: Result<Vec<String>, _> = arr
                    .iter()
                    .map(|v| {
                        v.as_str()
                            .map(String::from)
                            .ok_or_else(|| {
                                ApiError::bad_request(format!(
                                    "Filter array values for key '{}' must be strings, got: {}",
                                    key, v
                                ))
                            })
                    })
                    .collect();
                MatchType::Any(strings?)
            }
            _ => {
                return Err(ApiError::bad_request(format!(
                    "Filter value for key '{}' must be a string or array of strings, got: {}",
                    key,
                    match value {
                        serde_json::Value::Null => "null",
                        serde_json::Value::Bool(_) => "boolean",
                        serde_json::Value::Number(_) => "number",
                        serde_json::Value::Object(_) => "object",
                        _ => "unknown",
                    }
                )));
            }
        };

        unified = unified.must(FilterCondition::new(key.clone(), match_type));
    }

    Ok(unified)
}

/// Execute the hybrid search based on the request parameters.
///
/// Returns the results, metrics, debug info, and component outcome for
/// degradation evaluation.
async fn execute_search(
    state: &AppState,
    request: &RetrieveRequest,
    user_context: &UserContext,
) -> ApiResult<(Vec<RetrievalResult>, SearchMetrics, DebugInfo, ComponentOutcome)> {
    let start_time = Instant::now();
    let mut metrics = SearchMetrics::default();
    let mut debug_info = DebugInfo::default();
    let mut outcome = ComponentOutcome::new();

    // Step 1: Generate query embedding
    let embed_start = Instant::now();
    let embedding = state
        .embedding
        .embed_query(&request.query)
        .await
        .map_err(|e| ApiError::internal(format!("Embedding error: {e}")))?;

    // Embedding succeeded
    outcome = outcome.with_embedding_ok();

    metrics.embedding_ms = Some(embed_start.elapsed().as_secs_f64() * 1000.0);
    debug_info.embedding_latency_ms = metrics.embedding_ms.unwrap_or(0.0);

    // Step 2: Parse filters from request
    let unified_filter = match &request.filters {
        Some(filters) => {
            let parsed = parse_filters(filters)?;
            if parsed.is_empty() {
                None
            } else {
                debug!(
                    must_count = parsed.must.len(),
                    should_count = parsed.should.len(),
                    must_not_count = parsed.must_not.len(),
                    "Parsed request filters"
                );
                Some(parsed)
            }
        }
        None => None,
    };

    // Step 3: Configure search
    let search_top_k = if request.rerank {
        request.rerank_top_k
    } else {
        request.top_k
    };

    // Step 4: Execute search based on mode
    let search_result = match request.mode {
        SearchMode::Hybrid => {
            let _config = HybridSearchConfig::default()
                .with_semantic_weight(request.semantic_weight)
                .with_keyword_weight(request.keyword_weight);

            let search_start = Instant::now();
            let result = state
                .hybrid
                .search(&request.query, &embedding, Some(search_top_k), unified_filter.as_ref(), Some(user_context))
                .await
                .map_err(|e| ApiError::internal(format!("Search error: {e}")))?;

            let elapsed = search_start.elapsed().as_secs_f64() * 1000.0;
            metrics.semantic_search_ms = Some(result.semantic_time_ms as f64);
            metrics.keyword_search_ms = Some(result.keyword_time_ms as f64);
            metrics.fusion_ms = Some(result.fusion_time_ms as f64);
            debug_info.semantic_search_latency_ms = result.semantic_time_ms as f64;
            debug_info.keyword_search_latency_ms = result.keyword_time_ms as f64;
            debug_info.fusion_latency_ms = result.fusion_time_ms as f64;
            debug_info.semantic_weight = request.semantic_weight;
            debug_info.keyword_weight = request.keyword_weight;

            debug!(
                semantic_count = result.total_semantic,
                keyword_count = result.total_keyword,
                fused_count = result.results.len(),
                elapsed_ms = elapsed,
                "Hybrid search completed"
            );

            metrics.semantic_results_count = result.total_semantic;
            metrics.keyword_results_count = result.total_keyword;
            metrics.fused_results_count = result.results.len();
            debug_info.semantic_candidates = result.total_semantic;
            debug_info.keyword_candidates = result.total_keyword;
            debug_info.after_fusion = result.results.len();

            // Both components succeeded (search() propagates errors)
            outcome = outcome.with_semantic(true).with_keyword(true);

            result
        }
        SearchMode::Semantic => {
            let search_start = Instant::now();
            let result = state
                .hybrid
                .search_semantic_only(&embedding, search_top_k, unified_filter.as_ref(), Some(user_context))
                .await
                .map_err(|e| ApiError::internal(format!("Semantic search error: {e}")))?;

            metrics.semantic_search_ms = Some(search_start.elapsed().as_secs_f64() * 1000.0);
            metrics.semantic_results_count = result.total_semantic;
            debug_info.semantic_candidates = result.total_semantic;
            debug_info.semantic_search_latency_ms = metrics.semantic_search_ms.unwrap_or(0.0);

            // Semantic succeeded
            outcome = outcome.with_semantic(true);

            result
        }
        SearchMode::Keyword => {
            let search_start = Instant::now();
            let result = state
                .hybrid
                .search_keyword_only(&request.query, search_top_k, unified_filter.as_ref(), Some(user_context))
                .await
                .map_err(|e| ApiError::internal(format!("Keyword search error: {e}")))?;

            metrics.keyword_search_ms = Some(search_start.elapsed().as_secs_f64() * 1000.0);
            metrics.keyword_results_count = result.total_keyword;
            debug_info.keyword_candidates = result.total_keyword;
            debug_info.keyword_search_latency_ms = metrics.keyword_search_ms.unwrap_or(0.0);

            // Keyword succeeded
            outcome = outcome.with_keyword(true);

            result
        }
    };

    // Convert hybrid results to retrieval results
    let mut results: Vec<RetrievalResult> = search_result
        .results
        .into_iter()
        .map(|r| {
            let mut result = RetrievalResult::new(
                r.chunk_id.to_string(),
                r.document_id.to_string(),
                r.content,
                r.fused_score,
            );
            result.semantic_score = r.semantic_score;
            result.keyword_score = r.keyword_score;
            result.title = r.title;
            result.source_uri = r.source_uri;
            result.chunk_index = r.chunk_index;
            result.highlights = r.highlights;
            result.metadata = r.metadata;
            result.visibility = r.visibility;
            result.allowed_groups = r.allowed_groups;
            result
        })
        .collect();

    // Step 5: Rerank if enabled and reranker is available
    let rerank_requested = request.rerank && state.has_reranker();
    let mut rerank_ok = false;

    if rerank_requested {
        let rerank_start = Instant::now();

        if let Some(ref reranker) = state.reranker {
            match reranker
                .rerank_results(&request.query, results.clone(), Some(request.top_k))
                .await
            {
                Ok(reranked) => {
                    // Re-order results based on rerank scores
                    let mut result_map: std::collections::HashMap<String, RetrievalResult> =
                        results.into_iter().map(|r| (r.chunk_id.clone(), r)).collect();

                    results = reranked
                        .into_iter()
                        .filter_map(|rr| {
                            result_map.remove(&rr.chunk_id).map(|mut r| {
                                r.score = rr.score;
                                r.rerank_score = Some(rr.score);
                                r
                            })
                        })
                        .collect();

                    debug_info.after_rerank = results.len();
                    rerank_ok = true;
                }
                Err(e) => {
                    warn!("Reranking failed, using fusion scores: {e}");
                }
            }
        }

        metrics.rerank_ms = Some(rerank_start.elapsed().as_secs_f64() * 1000.0);
        debug_info.rerank_latency_ms = metrics.rerank_ms.unwrap_or(0.0);
    }

    outcome = outcome.with_rerank(rerank_requested, rerank_ok);

    // Step 6: Apply ACL filter
    let acl_start = Instant::now();
    let before_acl = results.len();

    results = results
        .into_iter()
        .filter(|r| user_context.can_access(r.visibility, &r.allowed_groups))
        .collect();

    debug_info.acl_filter_latency_ms = acl_start.elapsed().as_secs_f64() * 1000.0;
    debug_info.after_acl = results.len();

    if results.len() != before_acl {
        debug!(
            before = before_acl,
            after = results.len(),
            "ACL filter applied"
        );
    }

    // Step 7: Apply score threshold
    if request.min_score > 0.0 {
        results.retain(|r| r.score >= request.min_score);
    }

    // Step 8: Apply top_k limit
    results.truncate(request.top_k);
    metrics.final_results_count = results.len();

    debug_info.total_latency_ms = start_time.elapsed().as_secs_f64() * 1000.0;

    Ok((results, metrics, debug_info, outcome))
}

/// Convert retrieval results to response format.
fn convert_to_response(
    results: &[RetrievalResult],
    include_metadata: bool,
    include_highlights: bool,
) -> Vec<RetrievedDocument> {
    results
        .iter()
        .map(|r| {
            let chunk_id = Uuid::parse_str(&r.chunk_id).unwrap_or_else(|_| Uuid::nil());
            let document_id = Uuid::parse_str(&r.document_id).unwrap_or_else(|_| Uuid::nil());

            let metadata_dict = r.metadata.clone();
            let source_type = metadata_dict
                .get("source_type")
                .and_then(|v| v.as_str())
                .map(String::from);
            let total_chunks = metadata_dict
                .get("total_chunks")
                .and_then(|v| v.as_u64())
                .map(|v| v as u32)
                .unwrap_or(1);

            RetrievedDocument {
                chunk_id,
                document_id,
                content: r.content.clone(),
                score: r.score,
                title: r.title.clone(),
                source: r.source_uri.clone(),
                source_type,
                chunk_index: r.chunk_index,
                total_chunks,
                created_at: None,
                updated_at: None,
                semantic_score: r.semantic_score,
                keyword_score: r.keyword_score,
                rerank_score: r.rerank_score,
                metadata: if include_metadata {
                    serde_json::to_value(&metadata_dict).unwrap_or_default()
                } else {
                    serde_json::Value::Object(serde_json::Map::new())
                },
                highlights: if include_highlights && !r.highlights.is_empty() {
                    Some(r.highlights.clone())
                } else {
                    None
                },
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_convert_to_response_with_metadata() {
        let results = vec![RetrievalResult::new(
            Uuid::new_v4().to_string(),
            Uuid::new_v4().to_string(),
            "test content".into(),
            0.95,
        )
        .with_title("Test Document")
        .with_semantic_score(0.92)
        .with_keyword_score(0.88)];

        let response = convert_to_response(&results, true, true);

        assert_eq!(response.len(), 1);
        assert_eq!(response[0].content, "test content");
        assert!((response[0].score - 0.95).abs() < f32::EPSILON);
        assert_eq!(response[0].title, Some("Test Document".into()));
        assert_eq!(response[0].semantic_score, Some(0.92));
        assert_eq!(response[0].keyword_score, Some(0.88));
    }

    #[test]
    fn test_convert_to_response_without_metadata() {
        let mut result = RetrievalResult::new(
            Uuid::new_v4().to_string(),
            Uuid::new_v4().to_string(),
            "test".into(),
            0.9,
        );
        result.metadata.insert(
            "custom_field".into(),
            serde_json::Value::String("value".into()),
        );

        let response = convert_to_response(&[result], false, false);

        assert!(response[0].metadata.as_object().unwrap().is_empty());
        assert!(response[0].highlights.is_none());
    }

    #[test]
    fn test_convert_to_response_with_highlights() {
        let mut result = RetrievalResult::new(
            Uuid::new_v4().to_string(),
            Uuid::new_v4().to_string(),
            "test".into(),
            0.9,
        );
        result.highlights = vec!["<em>test</em> highlight".into()];

        let response = convert_to_response(&[result], false, true);

        assert!(response[0].highlights.is_some());
        assert_eq!(response[0].highlights.as_ref().unwrap().len(), 1);
    }

    // --- Filter parsing tests ---

    #[test]
    fn test_parse_filters_simple_key_value() {
        let filters = serde_json::json!({
            "source_type": "pdf",
            "category": "docs"
        });

        let result = parse_filters(&filters).unwrap();
        assert_eq!(result.must.len(), 2);
        assert!(result.should.is_empty());
        assert!(result.must_not.is_empty());

        // Check that both conditions are present (order may vary)
        let keys: Vec<&str> = result.must.iter().map(|c| c.key.as_str()).collect();
        assert!(keys.contains(&"source_type"));
        assert!(keys.contains(&"category"));
    }

    #[test]
    fn test_parse_filters_simple_array_value() {
        let filters = serde_json::json!({
            "allowed_groups": ["engineering", "product"]
        });

        let result = parse_filters(&filters).unwrap();
        assert_eq!(result.must.len(), 1);

        let cond = &result.must[0];
        assert_eq!(cond.key, "allowed_groups");
        match &cond.match_type {
            MatchType::Any(values) => {
                assert_eq!(values, &vec!["engineering".to_string(), "product".to_string()]);
            }
            _ => panic!("Expected MatchType::Any"),
        }
    }

    #[test]
    fn test_parse_filters_skips_tenant_id() {
        let filters = serde_json::json!({
            "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
            "source_type": "pdf"
        });

        let result = parse_filters(&filters).unwrap();
        assert_eq!(result.must.len(), 1);
        assert_eq!(result.must[0].key, "source_type");
    }

    #[test]
    fn test_parse_filters_structured_format() {
        let filters = serde_json::json!({
            "must": [
                {"key": "source_type", "match_type": {"value": "pdf"}}
            ],
            "should": [
                {"key": "visibility", "match_type": {"value": "public"}}
            ],
            "must_not": []
        });

        let result = parse_filters(&filters).unwrap();
        assert_eq!(result.must.len(), 1);
        assert_eq!(result.should.len(), 1);
        assert!(result.must_not.is_empty());
    }

    #[test]
    fn test_parse_filters_rejects_non_object() {
        let filters = serde_json::json!("not an object");
        let result = parse_filters(&filters);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_filters_rejects_number_value() {
        let filters = serde_json::json!({
            "count": 42
        });
        let result = parse_filters(&filters);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_filters_rejects_non_string_array_items() {
        let filters = serde_json::json!({
            "groups": ["valid", 123]
        });
        let result = parse_filters(&filters);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_filters_empty_object_returns_empty_filter() {
        let filters = serde_json::json!({});
        let result = parse_filters(&filters).unwrap();
        assert!(result.is_empty());
    }

    #[test]
    fn test_parse_filters_document_id_filter() {
        let doc_id = Uuid::new_v4();
        let filters = serde_json::json!({
            "document_id": doc_id.to_string()
        });

        let result = parse_filters(&filters).unwrap();
        assert_eq!(result.must.len(), 1);
        assert_eq!(result.must[0].key, "document_id");
        match &result.must[0].match_type {
            MatchType::Value(v) => assert_eq!(v, &doc_id.to_string()),
            _ => panic!("Expected MatchType::Value"),
        }
    }

    #[test]
    fn test_parse_filters_structured_rejects_empty_key() {
        let filters = serde_json::json!({
            "must": [
                {"key": "", "match_type": {"value": "pdf"}}
            ]
        });

        let result = parse_filters(&filters);
        assert!(result.is_err());
    }
}

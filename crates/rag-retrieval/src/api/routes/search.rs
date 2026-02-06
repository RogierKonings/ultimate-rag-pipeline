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

use crate::api::error::{ApiError, ApiResult};
use crate::api::state::AppState;
use crate::api::types::{
    DebugInfo, RetrieveRequest, RetrieveResponse, RetrievedDocument, SearchMetrics,
};
use crate::hybrid::HybridSearchConfig;
use crate::types::{RetrievalResult, SearchMode, UserContext};

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
    let tenant_id = headers
        .get("X-Tenant-Id")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| Uuid::parse_str(s).ok())
        .or_else(|| {
            request.filters.as_ref()
                .and_then(|f| f.get("tenant_id"))
                .and_then(|v| v.as_str())
                .and_then(|s| Uuid::parse_str(s).ok())
        })
        .unwrap_or_else(Uuid::nil);

    let user_context = UserContext::new(Uuid::new_v4(), tenant_id);

    // Execute the search
    let (results, metrics, debug_info) = execute_search(&state, &request, &user_context).await?;

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
        degradation_mode: None,
        components_used: vec!["semantic".into(), "keyword".into()],
        components_skipped: vec![],
    };

    debug!(
        query_id = %query_id,
        total_results = response.total_results,
        total_ms = total_ms,
        "Retrieve request completed"
    );

    Ok(Json(response))
}

/// Execute the hybrid search based on the request parameters.
async fn execute_search(
    state: &AppState,
    request: &RetrieveRequest,
    user_context: &UserContext,
) -> ApiResult<(Vec<RetrievalResult>, SearchMetrics, DebugInfo)> {
    let start_time = Instant::now();
    let mut metrics = SearchMetrics::default();
    let mut debug_info = DebugInfo::default();

    // Step 1: Generate query embedding
    let embed_start = Instant::now();
    let embedding = state
        .embedding
        .embed_query(&request.query)
        .await
        .map_err(|e| ApiError::internal(format!("Embedding error: {e}")))?;

    metrics.embedding_ms = Some(embed_start.elapsed().as_secs_f64() * 1000.0);
    debug_info.embedding_latency_ms = metrics.embedding_ms.unwrap_or(0.0);

    // Step 2: Configure search
    let search_top_k = if request.rerank {
        request.rerank_top_k
    } else {
        request.top_k
    };

    // Step 3: Execute search based on mode
    let search_result = match request.mode {
        SearchMode::Hybrid => {
            let _config = HybridSearchConfig::default()
                .with_semantic_weight(request.semantic_weight)
                .with_keyword_weight(request.keyword_weight);

            let search_start = Instant::now();
            let result = state
                .hybrid
                .search(&request.query, &embedding, Some(search_top_k), None, Some(user_context))
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

            result
        }
        SearchMode::Semantic => {
            let search_start = Instant::now();
            let result = state
                .hybrid
                .search_semantic_only(&embedding, search_top_k, None, Some(user_context))
                .await
                .map_err(|e| ApiError::internal(format!("Semantic search error: {e}")))?;

            metrics.semantic_search_ms = Some(search_start.elapsed().as_secs_f64() * 1000.0);
            metrics.semantic_results_count = result.total_semantic;
            debug_info.semantic_candidates = result.total_semantic;
            debug_info.semantic_search_latency_ms = metrics.semantic_search_ms.unwrap_or(0.0);

            result
        }
        SearchMode::Keyword => {
            let search_start = Instant::now();
            let result = state
                .hybrid
                .search_keyword_only(&request.query, search_top_k, None, Some(user_context))
                .await
                .map_err(|e| ApiError::internal(format!("Keyword search error: {e}")))?;

            metrics.keyword_search_ms = Some(search_start.elapsed().as_secs_f64() * 1000.0);
            metrics.keyword_results_count = result.total_keyword;
            debug_info.keyword_candidates = result.total_keyword;
            debug_info.keyword_search_latency_ms = metrics.keyword_search_ms.unwrap_or(0.0);

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

    // Step 4: Rerank if enabled and reranker is available
    if request.rerank && state.has_reranker() {
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
                }
                Err(e) => {
                    warn!("Reranking failed, using fusion scores: {e}");
                }
            }
        }

        metrics.rerank_ms = Some(rerank_start.elapsed().as_secs_f64() * 1000.0);
        debug_info.rerank_latency_ms = metrics.rerank_ms.unwrap_or(0.0);
    }

    // Step 5: Apply ACL filter
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

    // Step 6: Apply score threshold
    if request.min_score > 0.0 {
        results.retain(|r| r.score >= request.min_score);
    }

    // Step 7: Apply top_k limit
    results.truncate(request.top_k);
    metrics.final_results_count = results.len();

    debug_info.total_latency_ms = start_time.elapsed().as_secs_f64() * 1000.0;

    Ok((results, metrics, debug_info))
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
}

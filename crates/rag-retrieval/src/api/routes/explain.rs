//! Explain endpoint for retrieval pipeline diagnostics.
//!
//! This module provides the `POST /api/v1/retrieve/explain` endpoint that returns
//! stage-level diagnostics for triage and tuning. The endpoint is admin-only.

use std::collections::HashSet;
use std::sync::Arc;
use std::time::Instant;

use axum::{extract::State, http::HeaderMap, Json};
use chrono::Utc;
use tracing::{debug, instrument, warn};
use uuid::Uuid;

use crate::api::degradation::{evaluate, ComponentOutcome};
use crate::api::error::{ApiError, ApiResult};
use crate::api::state::AppState;
use crate::api::types::{
    ExplainEffectiveConfig, ExplainResponse, ExplainResultSummary, ExplainStage, RetrieveRequest,
};
use crate::types::{RetrievalResult, UserContext};
use rag_types::SearchMode;

use super::search::{extract_tenant_id, parse_filters};

/// Extract user context from headers, including admin status.
///
/// Checks the `X-User-Role` header for "admin" to determine admin status.
/// Falls back to `X-User-Admin` header ("true"/"false") as alternative.
fn extract_user_context(headers: &HeaderMap, tenant_id: Uuid) -> UserContext {
    let user_id = headers
        .get("X-User-Id")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| Uuid::parse_str(s).ok())
        .unwrap_or_else(Uuid::new_v4);

    let is_admin = headers
        .get("X-User-Role")
        .and_then(|v| v.to_str().ok())
        .map(|role| role.eq_ignore_ascii_case("admin"))
        .unwrap_or(false)
        || headers
            .get("X-User-Admin")
            .and_then(|v| v.to_str().ok())
            .map(|v| v.eq_ignore_ascii_case("true"))
            .unwrap_or(false);

    let groups: Vec<String> = headers
        .get("X-User-Groups")
        .and_then(|v| v.to_str().ok())
        .map(|s| s.split(',').map(|g| g.trim().to_string()).collect())
        .unwrap_or_default();

    let roles: Vec<String> = headers
        .get("X-User-Role")
        .and_then(|v| v.to_str().ok())
        .map(|s| vec![s.to_string()])
        .unwrap_or_default();

    UserContext::new(user_id, tenant_id)
        .with_groups(groups)
        .with_roles(roles)
        .with_admin(is_admin)
}

/// Handle the POST /api/v1/retrieve/explain endpoint.
///
/// Performs the same retrieval pipeline as the standard retrieve endpoint but
/// returns detailed stage-level diagnostics instead of full document results.
///
/// # Authorization
///
/// This endpoint requires admin privileges. Non-admin users receive a 403 Forbidden.
///
/// # Request Body
///
/// Same as the standard retrieve endpoint (`RetrieveRequest`).
///
/// # Response
///
/// Returns an `ExplainResponse` containing:
/// - `effective_config`: The resolved configuration used for this request
/// - `stages`: Ordered list of pipeline stages with timing and candidate counts
/// - `components_used` / `components_skipped`: Component health summary
/// - `result_summary`: Final result count and score range (no raw content)
#[instrument(skip(state, headers, request), fields(query_len = request.query.len()))]
pub async fn explain(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(request): Json<RetrieveRequest>,
) -> ApiResult<Json<ExplainResponse>> {
    let start_time = Instant::now();
    let query_id = Uuid::new_v4();

    // Extract tenant and user context
    let tenant_id = extract_tenant_id(&headers, &request.filters);
    let user_context = extract_user_context(&headers, tenant_id);

    // Admin-only guard
    if !user_context.is_admin {
        return Err(ApiError::forbidden(
            "The explain endpoint requires admin privileges",
        ));
    }

    // Validate request
    request.validate()?;

    debug!(
        query_id = %query_id,
        mode = ?request.mode,
        top_k = request.top_k,
        rerank = request.rerank,
        "Processing explain request"
    );

    // Build effective config
    let effective_config = ExplainEffectiveConfig {
        mode: request.mode,
        top_k: request.top_k,
        semantic_weight: request.semantic_weight,
        keyword_weight: request.keyword_weight,
        fusion_method: "rrf".to_string(),
        rrf_k: 60,
        rerank_enabled: request.rerank,
        rerank_top_k: if request.rerank {
            Some(request.rerank_top_k)
        } else {
            None
        },
        min_score: request.min_score,
        reranker_available: state.has_reranker(),
    };

    // Execute the pipeline and collect stage data
    let (results, stages, outcome) =
        execute_explain_pipeline(&state, &request, &user_context).await?;

    // Build degradation info
    let degradation = evaluate(request.mode, &outcome);

    // Build result summary (no raw content or internal IDs)
    let result_summary = build_result_summary(&results);

    let total_latency_ms = start_time.elapsed().as_secs_f64() * 1000.0;

    let response = ExplainResponse {
        query_id,
        query: request.query,
        processed_at: Utc::now(),
        effective_config,
        stages,
        components_used: degradation.components_used,
        components_skipped: degradation.components_skipped,
        degradation_mode: degradation.mode,
        result_summary,
        total_latency_ms,
    };

    debug!(
        query_id = %query_id,
        total_latency_ms = total_latency_ms,
        "Explain request completed"
    );

    Ok(Json(response))
}

/// Execute the retrieval pipeline, collecting stage-level diagnostic data.
///
/// Returns the final results, ordered stage diagnostics, and component outcomes.
async fn execute_explain_pipeline(
    state: &AppState,
    request: &RetrieveRequest,
    user_context: &UserContext,
) -> ApiResult<(Vec<RetrievalResult>, Vec<ExplainStage>, ComponentOutcome)> {
    let mut stages: Vec<ExplainStage> = Vec::new();
    let mut outcome = ComponentOutcome::new();

    // Stage 1: Embedding
    let embed_start = Instant::now();
    let embedding = state
        .embedding
        .embed_query(&request.query)
        .await
        .map_err(|e| ApiError::internal(format!("Embedding error: {e}")))?;

    outcome = outcome.with_embedding_ok();
    let embed_ms = embed_start.elapsed().as_secs_f64() * 1000.0;

    stages.push(ExplainStage::executed("embedding", embed_ms).with_counts(1, 1));

    // Stage 2: Parse filters
    let unified_filter = match &request.filters {
        Some(filters) => {
            let parsed = parse_filters(filters)?;
            if parsed.is_empty() {
                None
            } else {
                Some(parsed)
            }
        }
        None => None,
    };

    // Stage 3: Search
    let search_top_k = if request.rerank {
        request.rerank_top_k
    } else {
        request.top_k
    };

    let search_result = match request.mode {
        SearchMode::Hybrid => {
            // Semantic search stage
            let search_start = Instant::now();
            let result = state
                .hybrid
                .search(
                    &request.query,
                    &embedding,
                    Some(search_top_k),
                    unified_filter.as_ref(),
                    Some(user_context),
                )
                .await
                .map_err(|e| ApiError::internal(format!("Search error: {e}")))?;

            let _search_ms = search_start.elapsed().as_secs_f64() * 1000.0;

            // Semantic search stage
            stages.push(
                ExplainStage::executed("semantic_search", result.semantic_time_ms as f64)
                    .with_counts(0, result.total_semantic),
            );

            // Keyword search stage
            stages.push(
                ExplainStage::executed("keyword_search", result.keyword_time_ms as f64)
                    .with_counts(0, result.total_keyword),
            );

            // Fusion stage
            let fusion_input = result.total_semantic + result.total_keyword;
            stages.push(
                ExplainStage::executed("fusion", result.fusion_time_ms as f64)
                    .with_counts(fusion_input, result.results.len()),
            );

            outcome = outcome.with_semantic(true).with_keyword(true);

            result
        }
        SearchMode::Semantic => {
            let search_start = Instant::now();
            let result = state
                .hybrid
                .search_semantic_only(
                    &embedding,
                    search_top_k,
                    unified_filter.as_ref(),
                    Some(user_context),
                )
                .await
                .map_err(|e| ApiError::internal(format!("Semantic search error: {e}")))?;

            let search_ms = search_start.elapsed().as_secs_f64() * 1000.0;

            stages.push(
                ExplainStage::executed("semantic_search", search_ms)
                    .with_counts(0, result.total_semantic),
            );

            stages.push(ExplainStage::skipped(
                "keyword_search",
                "Not used in semantic-only mode",
            ));

            stages.push(ExplainStage::skipped(
                "fusion",
                "Not needed for single-source search",
            ));

            outcome = outcome.with_semantic(true);

            result
        }
        SearchMode::Keyword => {
            let search_start = Instant::now();
            let result = state
                .hybrid
                .search_keyword_only(
                    &request.query,
                    search_top_k,
                    unified_filter.as_ref(),
                    Some(user_context),
                )
                .await
                .map_err(|e| ApiError::internal(format!("Keyword search error: {e}")))?;

            let search_ms = search_start.elapsed().as_secs_f64() * 1000.0;

            stages.push(ExplainStage::skipped(
                "semantic_search",
                "Not used in keyword-only mode",
            ));

            stages.push(
                ExplainStage::executed("keyword_search", search_ms)
                    .with_counts(0, result.total_keyword),
            );

            stages.push(ExplainStage::skipped(
                "fusion",
                "Not needed for single-source search",
            ));

            outcome = outcome.with_keyword(true);

            result
        }
    };

    // Convert to RetrievalResult for reranking and ACL stages
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

    // Stage 4: Reranking
    let rerank_requested = request.rerank && state.has_reranker();
    let mut rerank_ok = false;
    let before_rerank = results.len();

    if rerank_requested {
        let rerank_start = Instant::now();

        if let Some(ref reranker) = state.reranker {
            match reranker
                .rerank_results(&request.query, results.clone(), Some(request.top_k))
                .await
            {
                Ok(reranked) => {
                    let mut result_map: std::collections::HashMap<String, RetrievalResult> =
                        results
                            .into_iter()
                            .map(|r| (r.chunk_id.clone(), r))
                            .collect();

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

                    rerank_ok = true;

                    let rerank_ms = rerank_start.elapsed().as_secs_f64() * 1000.0;
                    stages.push(
                        ExplainStage::executed("reranking", rerank_ms)
                            .with_counts(before_rerank, results.len()),
                    );
                }
                Err(e) => {
                    let _rerank_ms = rerank_start.elapsed().as_secs_f64() * 1000.0;
                    warn!("Reranking failed in explain: {e}");
                    stages.push(ExplainStage::skipped(
                        "reranking",
                        format!("Reranking failed: {e}"),
                    ));
                }
            }
        }
    } else if request.rerank && !state.has_reranker() {
        stages.push(ExplainStage::skipped(
            "reranking",
            "Reranker requested but not available in this deployment",
        ));
    } else {
        stages.push(ExplainStage::skipped("reranking", "Not requested"));
    }

    outcome = outcome.with_rerank(rerank_requested, rerank_ok);

    // Stage 5: ACL filtering
    let acl_start = Instant::now();
    let before_acl = results.len();

    results = results
        .into_iter()
        .filter(|r| user_context.can_access(r.visibility, &r.allowed_groups))
        .collect();

    let acl_ms = acl_start.elapsed().as_secs_f64() * 1000.0;
    stages
        .push(ExplainStage::executed("acl_filter", acl_ms).with_counts(before_acl, results.len()));

    // Stage 6: Score threshold
    if request.min_score > 0.0 {
        let before_threshold = results.len();
        results.retain(|r| r.score >= request.min_score);
        // No separate stage timing needed for this fast operation
        stages.push(
            ExplainStage::executed("score_threshold", 0.0)
                .with_counts(before_threshold, results.len()),
        );
    }

    // Stage 7: Top-K truncation
    let before_topk = results.len();
    results.truncate(request.top_k);
    stages.push(
        ExplainStage::executed("top_k_truncation", 0.0).with_counts(before_topk, results.len()),
    );

    Ok((results, stages, outcome))
}

/// Build a result summary without exposing raw content or internal IDs.
fn build_result_summary(results: &[RetrievalResult]) -> ExplainResultSummary {
    let count = results.len();

    let score_range = if results.is_empty() {
        None
    } else {
        let min_score = results
            .iter()
            .map(|r| r.score)
            .fold(f32::INFINITY, f32::min);
        let max_score = results
            .iter()
            .map(|r| r.score)
            .fold(f32::NEG_INFINITY, f32::max);
        Some((min_score, max_score))
    };

    let unique_documents: HashSet<&str> = results.iter().map(|r| r.document_id.as_str()).collect();

    ExplainResultSummary {
        count,
        score_range,
        unique_documents: unique_documents.len(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // --- Unit tests for helper functions ---

    #[test]
    fn test_extract_user_context_admin_from_role_header() {
        let mut headers = HeaderMap::new();
        headers.insert("X-User-Role", "admin".parse().unwrap());
        headers.insert("X-Tenant-Id", Uuid::nil().to_string().parse().unwrap());

        let ctx = extract_user_context(&headers, Uuid::nil());
        assert!(ctx.is_admin);
        assert_eq!(ctx.roles, vec!["admin".to_string()]);
    }

    #[test]
    fn test_extract_user_context_admin_from_admin_header() {
        let mut headers = HeaderMap::new();
        headers.insert("X-User-Admin", "true".parse().unwrap());

        let ctx = extract_user_context(&headers, Uuid::nil());
        assert!(ctx.is_admin);
    }

    #[test]
    fn test_extract_user_context_non_admin() {
        let mut headers = HeaderMap::new();
        headers.insert("X-User-Role", "viewer".parse().unwrap());

        let ctx = extract_user_context(&headers, Uuid::nil());
        assert!(!ctx.is_admin);
    }

    #[test]
    fn test_extract_user_context_no_headers() {
        let headers = HeaderMap::new();
        let ctx = extract_user_context(&headers, Uuid::nil());
        assert!(!ctx.is_admin);
        assert!(ctx.groups.is_empty());
        assert!(ctx.roles.is_empty());
    }

    #[test]
    fn test_extract_user_context_with_groups() {
        let mut headers = HeaderMap::new();
        headers.insert(
            "X-User-Groups",
            "engineering, product, backend".parse().unwrap(),
        );

        let ctx = extract_user_context(&headers, Uuid::nil());
        assert_eq!(
            ctx.groups,
            vec![
                "engineering".to_string(),
                "product".to_string(),
                "backend".to_string(),
            ]
        );
    }

    #[test]
    fn test_extract_user_context_with_user_id() {
        let user_id = Uuid::new_v4();
        let mut headers = HeaderMap::new();
        headers.insert("X-User-Id", user_id.to_string().parse().unwrap());

        let ctx = extract_user_context(&headers, Uuid::nil());
        assert_eq!(ctx.user_id, user_id);
    }

    #[test]
    fn test_build_result_summary_empty() {
        let results: Vec<RetrievalResult> = Vec::new();
        let summary = build_result_summary(&results);

        assert_eq!(summary.count, 0);
        assert!(summary.score_range.is_none());
        assert_eq!(summary.unique_documents, 0);
    }

    #[test]
    fn test_build_result_summary_with_results() {
        let results = vec![
            RetrievalResult::new("c1".into(), "d1".into(), "content".into(), 0.95),
            RetrievalResult::new("c2".into(), "d1".into(), "content".into(), 0.85),
            RetrievalResult::new("c3".into(), "d2".into(), "content".into(), 0.75),
        ];

        let summary = build_result_summary(&results);

        assert_eq!(summary.count, 3);
        assert_eq!(summary.unique_documents, 2);

        let (min, max) = summary.score_range.unwrap();
        assert!((min - 0.75).abs() < f32::EPSILON);
        assert!((max - 0.95).abs() < f32::EPSILON);
    }

    #[test]
    fn test_build_result_summary_single_result() {
        let results = vec![RetrievalResult::new(
            "c1".into(),
            "d1".into(),
            "content".into(),
            0.9,
        )];

        let summary = build_result_summary(&results);

        assert_eq!(summary.count, 1);
        assert_eq!(summary.unique_documents, 1);

        let (min, max) = summary.score_range.unwrap();
        assert!((min - 0.9).abs() < f32::EPSILON);
        assert!((max - 0.9).abs() < f32::EPSILON);
    }

    // --- ExplainStage tests ---

    #[test]
    fn test_explain_stage_executed() {
        let stage = ExplainStage::executed("embedding", 15.5);
        assert_eq!(stage.name, "embedding");
        assert!(stage.executed);
        assert!((stage.latency_ms.unwrap() - 15.5).abs() < f64::EPSILON);
        assert!(stage.input_count.is_none());
        assert!(stage.output_count.is_none());
        assert!(stage.skipped_reason.is_none());
    }

    #[test]
    fn test_explain_stage_skipped() {
        let stage = ExplainStage::skipped("reranking", "Not requested");
        assert_eq!(stage.name, "reranking");
        assert!(!stage.executed);
        assert!(stage.latency_ms.is_none());
        assert_eq!(stage.skipped_reason.as_deref(), Some("Not requested"));
    }

    #[test]
    fn test_explain_stage_with_counts() {
        let stage = ExplainStage::executed("fusion", 2.0).with_counts(100, 50);
        assert_eq!(stage.input_count, Some(100));
        assert_eq!(stage.output_count, Some(50));
    }

    // --- ExplainResponse serialization ---

    #[test]
    fn test_explain_response_serialization() {
        let response = ExplainResponse {
            query_id: Uuid::nil(),
            query: "test query".into(),
            processed_at: Utc::now(),
            effective_config: ExplainEffectiveConfig {
                mode: SearchMode::Hybrid,
                top_k: 10,
                semantic_weight: 0.7,
                keyword_weight: 0.3,
                fusion_method: "rrf".into(),
                rrf_k: 60,
                rerank_enabled: false,
                rerank_top_k: None,
                min_score: 0.0,
                reranker_available: false,
            },
            stages: vec![
                ExplainStage::executed("embedding", 12.5).with_counts(1, 1),
                ExplainStage::executed("semantic_search", 45.0).with_counts(0, 50),
            ],
            components_used: vec!["embedding".into(), "semantic".into()],
            components_skipped: Vec::new(),
            degradation_mode: None,
            result_summary: ExplainResultSummary {
                count: 10,
                score_range: Some((0.5, 0.95)),
                unique_documents: 8,
            },
            total_latency_ms: 150.0,
        };

        let json = serde_json::to_string(&response).unwrap();
        assert!(json.contains("\"query\":\"test query\""));
        assert!(json.contains("\"effective_config\""));
        assert!(json.contains("\"stages\""));
        assert!(json.contains("\"result_summary\""));
        assert!(json.contains("\"embedding\""));

        // Verify it deserializes correctly
        let deserialized: ExplainResponse = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.query, "test query");
        assert_eq!(deserialized.stages.len(), 2);
        assert_eq!(deserialized.result_summary.count, 10);
    }

    // --- Admin auth guard test (handler-level; cannot fully test without mock state) ---

    #[test]
    fn test_admin_guard_rejects_non_admin_context() {
        // Verify that non-admin user contexts are correctly identified
        let headers = HeaderMap::new();
        let ctx = extract_user_context(&headers, Uuid::nil());
        assert!(!ctx.is_admin, "Empty headers should not grant admin access");

        let mut headers = HeaderMap::new();
        headers.insert("X-User-Role", "viewer".parse().unwrap());
        let ctx = extract_user_context(&headers, Uuid::nil());
        assert!(!ctx.is_admin, "Viewer role should not grant admin access");

        let mut headers = HeaderMap::new();
        headers.insert("X-User-Admin", "false".parse().unwrap());
        let ctx = extract_user_context(&headers, Uuid::nil());
        assert!(
            !ctx.is_admin,
            "Explicit false should not grant admin access"
        );
    }

    #[test]
    fn test_admin_guard_accepts_admin_context() {
        let mut headers = HeaderMap::new();
        headers.insert("X-User-Role", "admin".parse().unwrap());
        let ctx = extract_user_context(&headers, Uuid::nil());
        assert!(ctx.is_admin, "Admin role should grant admin access");

        let mut headers = HeaderMap::new();
        headers.insert("X-User-Admin", "true".parse().unwrap());
        let ctx = extract_user_context(&headers, Uuid::nil());
        assert!(ctx.is_admin, "Explicit true should grant admin access");

        // Case insensitive
        let mut headers = HeaderMap::new();
        headers.insert("X-User-Role", "Admin".parse().unwrap());
        let ctx = extract_user_context(&headers, Uuid::nil());
        assert!(ctx.is_admin, "Admin role check should be case insensitive");

        let mut headers = HeaderMap::new();
        headers.insert("X-User-Admin", "TRUE".parse().unwrap());
        let ctx = extract_user_context(&headers, Uuid::nil());
        assert!(
            ctx.is_admin,
            "Admin header check should be case insensitive"
        );
    }
}

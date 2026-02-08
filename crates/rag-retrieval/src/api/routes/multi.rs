//! Multi-query retrieval endpoint.
//!
//! This module provides the `/api/v1/retrieve/multi` endpoint for executing
//! multiple queries in parallel and aggregating results.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use axum::{extract::State, http::HeaderMap, Json};
use chrono::Utc;
use futures::future::join_all;
use tracing::{debug, instrument, warn};
use uuid::Uuid;

use crate::acl::UnifiedFilter;
use crate::api::degradation::{evaluate, ComponentOutcome};
use crate::api::error::{ApiError, ApiResult};
use crate::api::state::AppState;
use crate::api::types::{MultiQueryRequest, RetrieveResponse, RetrievedDocument, SearchMetrics};
use crate::hybrid::HybridSearchResult;
use crate::types::{RetrievalResult, UserContext};
use rag_types::SearchMode;

use super::search::{extract_tenant_id, extract_user_context, parse_filters};

struct QueryExecution {
    results: Vec<HybridSearchResult>,
    outcome: ComponentOutcome,
}

fn merge_component_outcomes(outcomes: &[ComponentOutcome]) -> ComponentOutcome {
    let mut merged = ComponentOutcome::new();
    for subquery in outcomes {
        merged.embedding_ok |= subquery.embedding_ok;
        merged.semantic_attempted |= subquery.semantic_attempted;
        merged.semantic_ok |= subquery.semantic_ok;
        merged.keyword_attempted |= subquery.keyword_attempted;
        merged.keyword_ok |= subquery.keyword_ok;
    }
    merged
}

fn has_partial_component_degradation(outcomes: &[ComponentOutcome]) -> bool {
    outcomes.iter().any(|subquery| {
        (subquery.semantic_attempted && !subquery.semantic_ok)
            || (subquery.keyword_attempted && !subquery.keyword_ok)
    })
}

/// Handle the POST /api/v1/retrieve/multi endpoint.
///
/// Executes multiple queries in parallel and aggregates results using
/// the specified aggregation method (max, avg, or rrf).
///
/// # Request Body
///
/// - `queries`: List of 1-5 query strings
/// - `aggregation`: Aggregation method ("max", "avg", "rrf")
/// - `top_k`: Number of results to return
/// - `filters`: Optional metadata filters
/// - `rerank`: Whether to enable reranking
///
/// # Response
///
/// Returns a `RetrieveResponse` containing aggregated results from all queries.
#[instrument(skip(state, headers, request), fields(num_queries = request.queries.len()))]
pub async fn retrieve_multi(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(request): Json<MultiQueryRequest>,
) -> ApiResult<Json<RetrieveResponse>> {
    let start_time = Instant::now();
    let query_id = Uuid::new_v4();

    // Validate request
    request.validate()?;

    debug!(
        query_id = %query_id,
        num_queries = request.queries.len(),
        aggregation = %request.aggregation,
        top_k = request.top_k,
        "Processing multi-query retrieve request"
    );

    // Extract tenant_id from X-Tenant-Id header or filters.tenant_id,
    // mirroring the single-query route behavior.
    let tenant_id = extract_tenant_id(&headers, &request.filters);

    let user_context = extract_user_context(&headers, tenant_id);

    // Parse filters from request, mirroring the single-query route behavior.
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
                    "Parsed request filters for multi-query"
                );
                Some(parsed)
            }
        }
        None => None,
    };

    // Execute all queries in parallel, threading filters and user context
    // into each sub-query.
    let query_futures: Vec<_> = request
        .queries
        .iter()
        .map(|query| {
            execute_single_query(
                &state,
                query,
                request.top_k * 2,
                unified_filter.as_ref(),
                &user_context,
            )
        })
        .collect();

    let query_results = join_all(query_futures).await;

    // Collect all results, logging any errors.
    // Track component outcomes: embedding is attempted per-query via
    // embed_query, and each sub-query runs hybrid search (semantic + keyword).
    let total_queries = request.queries.len();
    let mut succeeded_queries = 0usize;
    let mut query_outcomes: Vec<ComponentOutcome> = Vec::new();

    let mut all_results: Vec<(String, Vec<HybridSearchResult>)> = Vec::new();
    for (query, result) in request.queries.iter().zip(query_results.into_iter()) {
        match result {
            Ok(execution) => {
                all_results.push((query.clone(), execution.results));
                query_outcomes.push(execution.outcome);
                succeeded_queries += 1;
            }
            Err(e) => {
                debug!(query = %query, error = %e, "Query failed, skipping");
            }
        }
    }

    if all_results.is_empty() {
        return Err(ApiError::internal("All queries failed"));
    }

    // Build component outcome based on which sub-queries succeeded.
    // Each sub-query uses hybrid search (semantic + keyword).
    // If all succeeded, both components are fully healthy.
    // If some failed, we still had at least partial success.
    let mut outcome = merge_component_outcomes(&query_outcomes);

    // If not all queries succeeded, record a partial degradation via a
    // non-None mode to signal the caller.
    let partial_failure = succeeded_queries < total_queries;
    let partial_component_degradation = has_partial_component_degradation(&query_outcomes);

    // Aggregate results based on method
    let aggregated = match request.aggregation.as_str() {
        "max" => aggregate_max(&all_results),
        "avg" => aggregate_avg(&all_results),
        "rrf" | _ => aggregate_rrf(&all_results),
    };

    // Rerank aggregated results if enabled and reranker is available,
    // mirroring the single-query route behavior.
    let rerank_requested = request.rerank && state.has_reranker();
    let mut rerank_ok = false;
    let mut rerank_ms: Option<f64> = None;

    let mut results_for_acl: Vec<HybridSearchResult> = aggregated;

    if rerank_requested {
        let rerank_start = Instant::now();

        if let Some(ref reranker) = state.reranker {
            // Convert HybridSearchResult to RetrievalResult for the reranker
            let retrieval_results: Vec<RetrievalResult> = results_for_acl
                .iter()
                .map(|r| {
                    let mut result = RetrievalResult::new(
                        r.chunk_id.to_string(),
                        r.document_id.to_string(),
                        r.content.clone(),
                        r.fused_score,
                    );
                    result.semantic_score = r.semantic_score;
                    result.keyword_score = r.keyword_score;
                    result.title = r.title.clone();
                    result.source_uri = r.source_uri.clone();
                    result.chunk_index = r.chunk_index;
                    result.highlights = r.highlights.clone();
                    result.metadata = r.metadata.clone();
                    result.visibility = r.visibility;
                    result.allowed_groups = r.allowed_groups.clone();
                    result
                })
                .collect();

            // Use the first query as representative for reranking
            let rerank_query = &request.queries[0];

            match reranker
                .rerank_results(rerank_query, retrieval_results, Some(request.top_k))
                .await
            {
                Ok(reranked) => {
                    // Build a lookup from chunk_id -> original HybridSearchResult
                    let mut result_map: HashMap<String, HybridSearchResult> = results_for_acl
                        .into_iter()
                        .map(|r| (r.chunk_id.to_string(), r))
                        .collect();

                    // Reorder based on reranker output, updating scores
                    results_for_acl = reranked
                        .into_iter()
                        .filter_map(|rr| {
                            result_map.remove(&rr.chunk_id).map(|mut r| {
                                r.fused_score = rr.score;
                                r
                            })
                        })
                        .collect();

                    rerank_ok = true;
                }
                Err(e) => {
                    warn!("Reranking failed in multi-query, using aggregation scores: {e}");
                }
            }
        }

        rerank_ms = Some(rerank_start.elapsed().as_secs_f64() * 1000.0);
    }

    outcome = outcome.with_rerank(rerank_requested, rerank_ok);

    // Apply ACL filter
    let filtered: Vec<_> = results_for_acl
        .into_iter()
        .filter(|r| user_context.can_access(r.visibility, &r.allowed_groups))
        .collect();

    // Apply top_k limit
    let final_results: Vec<_> = filtered.into_iter().take(request.top_k).collect();

    // Convert to response format
    let response_results: Vec<RetrievedDocument> = final_results
        .iter()
        .map(|r| {
            RetrievedDocument::new(r.chunk_id, r.document_id, r.content.clone(), r.fused_score)
        })
        .collect();

    let total_ms = start_time.elapsed().as_secs_f64() * 1000.0;

    // Evaluate degradation from component outcomes
    let mut degradation = evaluate(SearchMode::Hybrid, &outcome);

    // Override mode when some sub-queries failed/degraded even though the
    // aggregate component matrix resolves to a healthy mode.
    if partial_failure && degradation.mode.is_none() {
        degradation.mode = Some("partial_queries_failed".into());
    } else if partial_component_degradation && degradation.mode.is_none() {
        degradation.mode = Some("partial_queries_degraded".into());
    }

    let response = RetrieveResponse {
        results: response_results,
        total_results: final_results.len(),
        query: request.queries.join("; "),
        mode: SearchMode::Hybrid,
        metrics: SearchMetrics {
            total_ms,
            final_results_count: final_results.len(),
            rerank_ms,
            ..Default::default()
        },
        query_id,
        processed_at: Utc::now(),
        debug: None,
        degradation_mode: degradation.mode,
        components_used: degradation.components_used,
        components_skipped: degradation.components_skipped,
    };

    debug!(
        query_id = %query_id,
        total_results = response.total_results,
        total_ms = total_ms,
        "Multi-query retrieve request completed"
    );

    Ok(Json(response))
}

/// Execute a single query against the hybrid searcher with filters and user context.
async fn execute_single_query(
    state: &AppState,
    query: &str,
    top_k: usize,
    filters: Option<&UnifiedFilter>,
    user_context: &UserContext,
) -> Result<QueryExecution, ApiError> {
    let mut outcome = ComponentOutcome::new();

    // Generate embedding. If this fails, degrade to keyword-only for the
    // current sub-query instead of failing the whole multi-query request.
    let embedding = match state.embedding.embed_query(query).await {
        Ok(embedding) => {
            outcome = outcome.with_embedding_ok();
            embedding
        }
        Err(embed_err) => {
            warn!(
                query = %query,
                error = %embed_err,
                "Embedding failed in multi-query sub-request, attempting keyword-only fallback"
            );

            let keyword_only = state
                .hybrid
                .search_keyword_only(query, top_k, filters, Some(user_context))
                .await
                .map_err(|keyword_err| {
                    ApiError::internal(format!(
                        "Embedding error: {embed_err}; keyword fallback error: {keyword_err}"
                    ))
                })?;

            outcome = outcome.with_semantic(false).with_keyword(true);

            return Ok(QueryExecution {
                results: keyword_only.results,
                outcome,
            });
        }
    };

    // Execute hybrid search with filters and user context.
    match state
        .hybrid
        .search(query, &embedding, Some(top_k), filters, Some(user_context))
        .await
    {
        Ok(result) => {
            outcome = outcome.with_semantic(true).with_keyword(true);
            Ok(QueryExecution {
                results: result.results,
                outcome,
            })
        }
        Err(primary_err) => {
            warn!(
                query = %query,
                error = %primary_err,
                "Hybrid search failed in multi-query sub-request, attempting component fallback"
            );

            let (semantic_result, keyword_result) = tokio::join!(
                state
                    .hybrid
                    .search_semantic_only(&embedding, top_k, filters, Some(user_context)),
                state
                    .hybrid
                    .search_keyword_only(query, top_k, filters, Some(user_context)),
            );

            match (semantic_result, keyword_result) {
                (Ok(semantic_only), Err(keyword_err)) => {
                    warn!(
                        query = %query,
                        error = %keyword_err,
                        "Keyword fallback failed in multi-query sub-request, serving semantic-only results"
                    );
                    outcome = outcome.with_semantic(true).with_keyword(false);
                    Ok(QueryExecution {
                        results: semantic_only.results,
                        outcome,
                    })
                }
                (Err(semantic_err), Ok(keyword_only)) => {
                    warn!(
                        query = %query,
                        error = %semantic_err,
                        "Semantic fallback failed in multi-query sub-request, serving keyword-only results"
                    );
                    outcome = outcome.with_semantic(false).with_keyword(true);
                    Ok(QueryExecution {
                        results: keyword_only.results,
                        outcome,
                    })
                }
                (Ok(semantic_only), Ok(keyword_only)) => {
                    // If both component fallbacks succeeded but hybrid fusion failed,
                    // serve whichever side produced more candidates.
                    if semantic_only.results.len() >= keyword_only.results.len() {
                        outcome = outcome.with_semantic(true).with_keyword(false);
                        Ok(QueryExecution {
                            results: semantic_only.results,
                            outcome,
                        })
                    } else {
                        outcome = outcome.with_semantic(false).with_keyword(true);
                        Ok(QueryExecution {
                            results: keyword_only.results,
                            outcome,
                        })
                    }
                }
                (Err(semantic_err), Err(keyword_err)) => Err(ApiError::internal(format!(
                    "Search error: {primary_err}; semantic fallback failed: {semantic_err}; keyword fallback failed: {keyword_err}",
                ))),
            }
        }
    }
}

/// Aggregate results using maximum score across all queries.
fn aggregate_max(results: &[(String, Vec<HybridSearchResult>)]) -> Vec<HybridSearchResult> {
    let mut aggregated: HashMap<Uuid, HybridSearchResult> = HashMap::new();

    for (_query, query_results) in results {
        for result in query_results {
            aggregated
                .entry(result.chunk_id)
                .and_modify(|existing| {
                    if result.fused_score > existing.fused_score {
                        *existing = result.clone();
                    }
                })
                .or_insert_with(|| result.clone());
        }
    }

    let mut sorted: Vec<_> = aggregated.into_values().collect();
    sorted.sort_by(|a, b| {
        b.fused_score
            .partial_cmp(&a.fused_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    sorted
}

/// Aggregate results using average score across all queries.
fn aggregate_avg(results: &[(String, Vec<HybridSearchResult>)]) -> Vec<HybridSearchResult> {
    let mut score_sums: HashMap<Uuid, (HybridSearchResult, f32, usize)> = HashMap::new();

    for (_query, query_results) in results {
        for result in query_results {
            score_sums
                .entry(result.chunk_id)
                .and_modify(|(_, sum, count)| {
                    *sum += result.fused_score;
                    *count += 1;
                })
                .or_insert_with(|| (result.clone(), result.fused_score, 1));
        }
    }

    let mut sorted: Vec<_> = score_sums
        .into_iter()
        .map(|(_, (mut result, sum, count))| {
            result.fused_score = sum / count as f32;
            result
        })
        .collect();

    sorted.sort_by(|a, b| {
        b.fused_score
            .partial_cmp(&a.fused_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    sorted
}

/// Aggregate results using Reciprocal Rank Fusion (RRF).
fn aggregate_rrf(results: &[(String, Vec<HybridSearchResult>)]) -> Vec<HybridSearchResult> {
    const RRF_K: f32 = 60.0;

    let mut rrf_scores: HashMap<Uuid, (HybridSearchResult, f32)> = HashMap::new();

    for (_query, query_results) in results {
        for (rank, result) in query_results.iter().enumerate() {
            let rrf_contribution = 1.0 / (RRF_K + (rank + 1) as f32);

            rrf_scores
                .entry(result.chunk_id)
                .and_modify(|(_, score)| {
                    *score += rrf_contribution;
                })
                .or_insert_with(|| (result.clone(), rrf_contribution));
        }
    }

    let mut sorted: Vec<_> = rrf_scores
        .into_iter()
        .map(|(_, (mut result, score))| {
            result.fused_score = score;
            result
        })
        .collect();

    sorted.sort_by(|a, b| {
        b.fused_score
            .partial_cmp(&a.fused_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });
    sorted
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::Visibility;

    fn create_test_result(chunk_id: Uuid, score: f32) -> HybridSearchResult {
        HybridSearchResult::new(chunk_id, Uuid::new_v4(), "content".into(), score)
    }

    #[test]
    fn test_aggregate_max() {
        let chunk1 = Uuid::new_v4();
        let chunk2 = Uuid::new_v4();

        let results = vec![
            (
                "query1".into(),
                vec![
                    create_test_result(chunk1, 0.9),
                    create_test_result(chunk2, 0.8),
                ],
            ),
            (
                "query2".into(),
                vec![
                    create_test_result(chunk1, 0.7),
                    create_test_result(chunk2, 0.95),
                ],
            ),
        ];

        let aggregated = aggregate_max(&results);

        assert_eq!(aggregated.len(), 2);
        // chunk2 should be first with score 0.95
        assert_eq!(aggregated[0].chunk_id, chunk2);
        assert!((aggregated[0].fused_score - 0.95).abs() < f32::EPSILON);
        // chunk1 should be second with score 0.9
        assert_eq!(aggregated[1].chunk_id, chunk1);
        assert!((aggregated[1].fused_score - 0.9).abs() < f32::EPSILON);
    }

    #[test]
    fn test_aggregate_avg() {
        let chunk1 = Uuid::new_v4();

        let results = vec![
            ("query1".into(), vec![create_test_result(chunk1, 0.8)]),
            ("query2".into(), vec![create_test_result(chunk1, 0.6)]),
        ];

        let aggregated = aggregate_avg(&results);

        assert_eq!(aggregated.len(), 1);
        assert_eq!(aggregated[0].chunk_id, chunk1);
        // Average of 0.8 and 0.6 = 0.7
        assert!((aggregated[0].fused_score - 0.7).abs() < f32::EPSILON);
    }

    #[test]
    fn test_aggregate_rrf() {
        let chunk1 = Uuid::new_v4();
        let chunk2 = Uuid::new_v4();

        let results = vec![
            (
                "query1".into(),
                vec![
                    create_test_result(chunk1, 0.9), // rank 1
                    create_test_result(chunk2, 0.8), // rank 2
                ],
            ),
            (
                "query2".into(),
                vec![
                    create_test_result(chunk2, 0.95), // rank 1
                    create_test_result(chunk1, 0.7),  // rank 2
                ],
            ),
        ];

        let aggregated = aggregate_rrf(&results);

        assert_eq!(aggregated.len(), 2);
        // Both chunks appear in both queries
        // chunk1: 1/(60+1) + 1/(60+2) = 0.01639 + 0.01613 = 0.03252
        // chunk2: 1/(60+2) + 1/(60+1) = 0.01613 + 0.01639 = 0.03252
        // They should be approximately equal
        let diff = (aggregated[0].fused_score - aggregated[1].fused_score).abs();
        assert!(diff < 0.001);
    }

    #[test]
    fn test_aggregate_rrf_ordering() {
        let chunk1 = Uuid::new_v4();
        let chunk2 = Uuid::new_v4();
        let chunk3 = Uuid::new_v4();

        let results = vec![
            (
                "query1".into(),
                vec![
                    create_test_result(chunk1, 0.9), // rank 1 in query1
                ],
            ),
            (
                "query2".into(),
                vec![
                    create_test_result(chunk1, 0.95), // rank 1 in query2
                    create_test_result(chunk2, 0.8),  // rank 2 in query2
                ],
            ),
            (
                "query3".into(),
                vec![
                    create_test_result(chunk1, 0.7), // rank 1 in query3
                    create_test_result(chunk3, 0.6), // rank 2 in query3
                ],
            ),
        ];

        let aggregated = aggregate_rrf(&results);

        // chunk1 appears first in all 3 queries, so it should have highest RRF score
        assert_eq!(aggregated[0].chunk_id, chunk1);
    }

    // --- Parity tests: multi-query should respect tenant and ACL like single-query ---

    #[test]
    fn test_acl_filter_respects_tenant_context() {
        // Verify that the ACL filter on aggregated results works correctly
        // with a tenant-scoped user context
        let tenant_id = Uuid::new_v4();
        let user_context = UserContext::new(Uuid::new_v4(), tenant_id);

        let chunk1 = Uuid::new_v4();
        let chunk2 = Uuid::new_v4();
        let chunk3 = Uuid::new_v4();

        // chunk1: public (accessible)
        let mut r1 = HybridSearchResult::new(chunk1, Uuid::new_v4(), "public doc".into(), 0.9);
        r1.visibility = Visibility::Public;

        // chunk2: group-restricted, user NOT in the group (not accessible)
        let mut r2 = HybridSearchResult::new(chunk2, Uuid::new_v4(), "group doc".into(), 0.85);
        r2.visibility = Visibility::Group;
        r2.allowed_groups = vec!["secret-group".into()];

        // chunk3: tenant-scoped (accessible since tenant filtering is at query level)
        let mut r3 = HybridSearchResult::new(chunk3, Uuid::new_v4(), "tenant doc".into(), 0.8);
        r3.visibility = Visibility::Tenant;

        let aggregated = vec![r1, r2, r3];

        let filtered: Vec<_> = aggregated
            .into_iter()
            .filter(|r| user_context.can_access(r.visibility, &r.allowed_groups))
            .collect();

        // chunk2 should be filtered out (group restriction, user not in group)
        assert_eq!(filtered.len(), 2);
        assert_eq!(filtered[0].chunk_id, chunk1);
        assert_eq!(filtered[1].chunk_id, chunk3);
    }

    #[test]
    fn test_acl_filter_admin_bypasses() {
        // Admin users should see all documents regardless of visibility
        let user_context = UserContext::new(Uuid::new_v4(), Uuid::new_v4()).with_admin(true);

        let chunk1 = Uuid::new_v4();
        let chunk2 = Uuid::new_v4();

        let mut r1 = HybridSearchResult::new(chunk1, Uuid::new_v4(), "private doc".into(), 0.9);
        r1.visibility = Visibility::Private;

        let mut r2 = HybridSearchResult::new(chunk2, Uuid::new_v4(), "group doc".into(), 0.8);
        r2.visibility = Visibility::Group;
        r2.allowed_groups = vec!["secret-group".into()];

        let aggregated = vec![r1, r2];

        let filtered: Vec<_> = aggregated
            .into_iter()
            .filter(|r| user_context.can_access(r.visibility, &r.allowed_groups))
            .collect();

        // Admin should see both
        assert_eq!(filtered.len(), 2);
    }

    #[test]
    fn test_acl_filter_group_membership() {
        // User in the correct group should see group-restricted documents
        let user_context = UserContext::new(Uuid::new_v4(), Uuid::new_v4())
            .with_groups(vec!["engineering".into()]);

        let chunk1 = Uuid::new_v4();
        let chunk2 = Uuid::new_v4();

        let mut r1 = HybridSearchResult::new(chunk1, Uuid::new_v4(), "eng doc".into(), 0.9);
        r1.visibility = Visibility::Group;
        r1.allowed_groups = vec!["engineering".into()];

        let mut r2 = HybridSearchResult::new(chunk2, Uuid::new_v4(), "sales doc".into(), 0.8);
        r2.visibility = Visibility::Group;
        r2.allowed_groups = vec!["sales".into()];

        let aggregated = vec![r1, r2];

        let filtered: Vec<_> = aggregated
            .into_iter()
            .filter(|r| user_context.can_access(r.visibility, &r.allowed_groups))
            .collect();

        // Only engineering doc should pass
        assert_eq!(filtered.len(), 1);
        assert_eq!(filtered[0].chunk_id, chunk1);
    }

    #[test]
    fn test_merge_component_outcomes_or_semantics() {
        let outcomes = vec![
            ComponentOutcome::new()
                .with_embedding_ok()
                .with_semantic(true),
            ComponentOutcome::new().with_keyword(true),
            ComponentOutcome::new().with_semantic(false),
        ];

        let merged = merge_component_outcomes(&outcomes);

        assert!(merged.embedding_ok);
        assert!(merged.semantic_attempted);
        assert!(merged.semantic_ok);
        assert!(merged.keyword_attempted);
        assert!(merged.keyword_ok);
    }

    #[test]
    fn test_has_partial_component_degradation() {
        let healthy = vec![ComponentOutcome::new()
            .with_semantic(true)
            .with_keyword(true)];
        assert!(!has_partial_component_degradation(&healthy));

        let degraded = vec![
            ComponentOutcome::new()
                .with_semantic(true)
                .with_keyword(true),
            ComponentOutcome::new()
                .with_semantic(false)
                .with_keyword(true),
        ];
        assert!(has_partial_component_degradation(&degraded));
    }

    #[test]
    fn test_multi_query_request_defaults() {
        let request = MultiQueryRequest::new(vec!["query1".into(), "query2".into()]);
        assert_eq!(request.top_k, 10);
        assert_eq!(request.aggregation, "rrf");
        assert!(!request.rerank);
        assert!(request.filters.is_none());
    }
}

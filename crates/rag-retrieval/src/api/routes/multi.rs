//! Multi-query retrieval endpoint.
//!
//! This module provides the `/api/v1/retrieve/multi` endpoint for executing
//! multiple queries in parallel and aggregating results.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use axum::{extract::State, Json};
use chrono::Utc;
use futures::future::join_all;
use tracing::{debug, instrument};
use uuid::Uuid;

use crate::api::degradation::{evaluate, ComponentOutcome};
use crate::api::error::{ApiError, ApiResult};
use crate::api::state::AppState;
use crate::api::types::{
    MultiQueryRequest, RetrieveResponse, RetrievedDocument, SearchMetrics,
};
use crate::hybrid::HybridSearchResult;
use crate::types::UserContext;
use rag_types::SearchMode;

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
#[instrument(skip(state, request), fields(num_queries = request.queries.len()))]
pub async fn retrieve_multi(
    State(state): State<Arc<AppState>>,
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

    // Create a default user context
    let user_context = UserContext::new(Uuid::new_v4(), Uuid::new_v4());

    // Execute all queries in parallel
    let query_futures: Vec<_> = request
        .queries
        .iter()
        .map(|query| execute_single_query(&state, query, request.top_k * 2))
        .collect();

    let query_results = join_all(query_futures).await;

    // Collect all results, logging any errors.
    // Track component outcomes: embedding is attempted per-query via
    // embed_query, and each sub-query runs hybrid search (semantic + keyword).
    let total_queries = request.queries.len();
    let mut succeeded_queries = 0usize;
    let mut embedding_ok = false;

    let mut all_results: Vec<(String, Vec<HybridSearchResult>)> = Vec::new();
    for (query, result) in request.queries.iter().zip(query_results.into_iter()) {
        match result {
            Ok(results) => {
                all_results.push((query.clone(), results));
                succeeded_queries += 1;
                // If we got results, embedding + both search components worked
                embedding_ok = true;
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
    let mut outcome = ComponentOutcome::new();
    if embedding_ok {
        outcome = outcome.with_embedding_ok();
    }
    // The sub-queries use hybrid (semantic + keyword). If at least one
    // succeeded, both search backends were reachable. If some failed we
    // still mark the search components as ok because the aggregated response
    // contains valid results from at least one successful sub-query.
    outcome = outcome.with_semantic(true).with_keyword(true);

    // If not all queries succeeded, record a partial degradation via a
    // non-None mode to signal the caller.
    let partial_failure = succeeded_queries < total_queries;

    // Aggregate results based on method
    let aggregated = match request.aggregation.as_str() {
        "max" => aggregate_max(&all_results),
        "avg" => aggregate_avg(&all_results),
        "rrf" | _ => aggregate_rrf(&all_results),
    };

    // Apply ACL filter
    let filtered: Vec<_> = aggregated
        .into_iter()
        .filter(|r| user_context.can_access(r.visibility, &r.allowed_groups))
        .collect();

    // Apply top_k limit
    let final_results: Vec<_> = filtered.into_iter().take(request.top_k).collect();

    // Convert to response format
    let response_results: Vec<RetrievedDocument> = final_results
        .iter()
        .map(|r| {
            RetrievedDocument::new(
                r.chunk_id,
                r.document_id,
                r.content.clone(),
                r.fused_score,
            )
        })
        .collect();

    let total_ms = start_time.elapsed().as_secs_f64() * 1000.0;

    // Evaluate degradation from component outcomes
    let mut degradation = evaluate(SearchMode::Hybrid, &outcome);

    // Override mode when some sub-queries failed even though components are ok
    if partial_failure && degradation.mode.is_none() {
        degradation.mode = Some("partial_queries_failed".into());
    }

    let response = RetrieveResponse {
        results: response_results,
        total_results: final_results.len(),
        query: request.queries.join("; "),
        mode: SearchMode::Hybrid,
        metrics: SearchMetrics {
            total_ms,
            final_results_count: final_results.len(),
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

/// Execute a single query against the hybrid searcher.
async fn execute_single_query(
    state: &AppState,
    query: &str,
    top_k: usize,
) -> Result<Vec<HybridSearchResult>, ApiError> {
    // Generate embedding
    let embedding = state
        .embedding
        .embed_query(query)
        .await
        .map_err(|e| ApiError::internal(format!("Embedding error: {e}")))?;

    // Execute hybrid search
    let result = state
        .hybrid
        .search(query, &embedding, Some(top_k), None, None)
        .await
        .map_err(|e| ApiError::internal(format!("Search error: {e}")))?;

    Ok(result.results)
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
    sorted.sort_by(|a, b| b.fused_score.partial_cmp(&a.fused_score).unwrap_or(std::cmp::Ordering::Equal));
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

    sorted.sort_by(|a, b| b.fused_score.partial_cmp(&a.fused_score).unwrap_or(std::cmp::Ordering::Equal));
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

    sorted.sort_by(|a, b| b.fused_score.partial_cmp(&a.fused_score).unwrap_or(std::cmp::Ordering::Equal));
    sorted
}

#[cfg(test)]
mod tests {
    use super::*;

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
}

//! Hybrid searcher combining semantic and keyword search.
//!
//! This module provides the `HybridSearcher` that orchestrates parallel
//! semantic and keyword search execution with result fusion.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use tracing::{debug, instrument, warn};
use uuid::Uuid;

use crate::acl::{MatchType, UnifiedFilter};
use crate::error::{Result, RetrievalError};
use crate::fusion::{fuse, FusionConfig, ScoredItem};
use crate::search::{
    KeywordResult, KeywordSearchFilters, KeywordSearcher, SearchFilters, SemanticResult,
    SemanticSearcher,
};

use super::config::HybridSearchConfig;
use super::response::{HybridSearchResponse, HybridSearchResult};

/// Hybrid searcher that combines semantic and keyword search.
///
/// This struct orchestrates parallel execution of both search methods and
/// fuses the results using configurable fusion algorithms.
///
/// # Example
///
/// ```no_run
/// use std::sync::Arc;
/// use rag_retrieval::hybrid::{HybridSearcher, HybridSearchConfig};
/// use rag_retrieval::search::{SemanticSearcher, KeywordSearcher, SemanticSearchConfig, KeywordSearchConfig};
///
/// #[tokio::main]
/// async fn main() -> Result<(), Box<dyn std::error::Error>> {
///     // Set up searchers
///     let semantic_config = SemanticSearchConfig::default();
///     let semantic = Arc::new(SemanticSearcher::new(&semantic_config).await?);
///
///     let keyword_config = KeywordSearchConfig::default();
///     let keyword = Arc::new(KeywordSearcher::new(&keyword_config)?);
///
///     // Create hybrid searcher
///     let config = HybridSearchConfig::default();
///     let hybrid = HybridSearcher::new(semantic, keyword, config);
///
///     // Execute search
///     let embedding = vec![0.1; 384];
///     let response = hybrid.search("my query", &embedding, Some(10), None, None).await?;
///
///     Ok(())
/// }
/// ```
pub struct HybridSearcher {
    semantic: Arc<SemanticSearcher>,
    keyword: Arc<KeywordSearcher>,
    config: HybridSearchConfig,
}

impl HybridSearcher {
    /// Create a new hybrid searcher.
    ///
    /// # Arguments
    ///
    /// * `semantic` - Semantic searcher instance
    /// * `keyword` - Keyword searcher instance
    /// * `config` - Hybrid search configuration
    #[must_use]
    pub fn new(
        semantic: Arc<SemanticSearcher>,
        keyword: Arc<KeywordSearcher>,
        config: HybridSearchConfig,
    ) -> Self {
        Self {
            semantic,
            keyword,
            config,
        }
    }

    /// Execute hybrid search with parallel semantic and keyword search.
    ///
    /// This method runs both searches concurrently using `tokio::join!` and
    /// fuses the results according to the configured fusion method.
    ///
    /// # Arguments
    ///
    /// * `query` - Text query for keyword search
    /// * `query_embedding` - Query embedding for semantic search
    /// * `top_k` - Override for final number of results (uses config default if None)
    /// * `filters` - Optional unified filter for both search methods
    ///
    /// # Errors
    ///
    /// Returns an error if either search fails or if fusion fails.
    #[allow(clippy::too_many_lines)]
    #[instrument(skip(self, query_embedding, filters), fields(query_len = query.len()))]
    pub async fn search(
        &self,
        query: &str,
        query_embedding: &[f32],
        top_k: Option<usize>,
        filters: Option<&UnifiedFilter>,
        user_context: Option<&crate::types::UserContext>,
    ) -> Result<HybridSearchResponse> {
        let start_time = Instant::now();
        let final_top_k = top_k.unwrap_or(self.config.top_k);

        // Convert unified filter to search-specific filters
        let semantic_filters = filters.map(convert_to_semantic_filters);
        let keyword_filters = filters.map(convert_to_keyword_filters);

        // Use provided user context, or fall back to admin context
        let default_ctx = crate::types::UserContext::new(Uuid::nil(), Uuid::nil()).with_admin(true);
        let ctx = user_context.unwrap_or(&default_ctx);

        // Run both searches in parallel
        let semantic_start = Instant::now();
        let keyword_start = Instant::now();

        let (semantic_result, keyword_result) = tokio::join!(
            self.semantic.search(
                query_embedding,
                ctx,
                semantic_filters,
                Some(self.config.semantic_top_k),
            ),
            self.keyword
                .search(query, ctx, keyword_filters, Some(self.config.keyword_top_k),),
        );

        #[allow(clippy::cast_possible_truncation)]
        let semantic_time_ms = semantic_start.elapsed().as_millis() as u64;
        #[allow(clippy::cast_possible_truncation)]
        let keyword_time_ms = keyword_start.elapsed().as_millis() as u64;

        // Handle results
        let semantic_results = semantic_result.map_err(|e| {
            warn!("Semantic search failed: {}", e);
            e
        })?;

        let keyword_results = keyword_result.map_err(|e| {
            warn!("Keyword search failed: {}", e);
            e
        })?;

        let total_semantic = semantic_results.len();
        let total_keyword = keyword_results.len();

        debug!(
            total_semantic,
            total_keyword, semantic_time_ms, keyword_time_ms, "Parallel search completed"
        );

        // Build content lookup maps for enriching fused results
        let semantic_content_map = build_semantic_content_map(&semantic_results);
        let keyword_content_map = build_keyword_content_map(&keyword_results);

        // Convert to ScoredItems for fusion
        let semantic_scored: Vec<ScoredItem<Uuid>> = semantic_results
            .iter()
            .map(|r| ScoredItem::new(r.chunk_id, r.score))
            .collect();

        let keyword_scored: Vec<ScoredItem<Uuid>> = keyword_results
            .iter()
            .map(|r| ScoredItem::new(r.chunk_id, r.score))
            .collect();

        // Perform fusion
        let fusion_start = Instant::now();

        let fusion_config = FusionConfig::new(self.config.fusion_method)
            .with_weights(self.config.semantic_weight, self.config.keyword_weight)
            .with_rrf_k(self.config.rrf_k as f32)
            .with_top_k(final_top_k)
            .with_deduplicate(false); // We handle deduplication separately

        let fused_results = fuse(&semantic_scored, &keyword_scored, &fusion_config)
            .map_err(|e| RetrievalError::internal(format!("Fusion failed: {e}")))?;

        #[allow(clippy::cast_possible_truncation)]
        let fusion_time_ms = fusion_start.elapsed().as_millis() as u64;

        debug!(
            fused_count = fused_results.len(),
            fusion_time_ms, "Fusion completed"
        );

        // Enrich fused results with content data
        let mut enriched_results: Vec<HybridSearchResult> = fused_results
            .into_iter()
            .filter_map(|fused| {
                // Get content from either source
                let (
                    content,
                    document_id,
                    title,
                    source_uri,
                    chunk_index,
                    visibility,
                    allowed_groups,
                    owner_id,
                    allowed_users,
                    denied_groups,
                    denied_users,
                    highlights,
                    metadata,
                ) = if let Some(semantic) = semantic_content_map.get(&fused.id) {
                    (
                        semantic.content.clone(),
                        semantic.document_id,
                        semantic.title.clone(),
                        semantic.source_uri.clone(),
                        semantic.chunk_index,
                        semantic.visibility,
                        semantic.allowed_groups.clone(),
                        semantic.owner_id.clone(),
                        semantic.allowed_users.clone(),
                        semantic.denied_groups.clone(),
                        semantic.denied_users.clone(),
                        Vec::new(),
                        semantic.metadata.clone(),
                    )
                } else if let Some(keyword) = keyword_content_map.get(&fused.id) {
                    (
                        keyword.content.clone(),
                        keyword.document_id,
                        keyword.title.clone(),
                        keyword.source_uri.clone(),
                        keyword.chunk_index,
                        keyword.visibility,
                        keyword.allowed_groups.clone(),
                        keyword.owner_id.clone(),
                        keyword.allowed_users.clone(),
                        keyword.denied_groups.clone(),
                        keyword.denied_users.clone(),
                        keyword.highlights.clone(),
                        keyword.metadata.clone(),
                    )
                } else {
                    // This shouldn't happen, but skip if it does
                    warn!("Fused result {} has no content source", fused.id);
                    return None;
                };

                let mut result =
                    HybridSearchResult::new(fused.id, document_id, content, fused.fused_score)
                        .with_chunk_index(chunk_index)
                        .with_visibility(visibility)
                        .with_allowed_groups(allowed_groups)
                        .with_owner_id(owner_id)
                        .with_allowed_users(allowed_users)
                        .with_denied_groups(denied_groups)
                        .with_denied_users(denied_users)
                        .with_highlights(highlights)
                        .with_metadata(metadata);

                if let Some(title) = title {
                    result = result.with_title(title);
                }

                if let Some(uri) = source_uri {
                    result = result.with_source_uri(uri);
                }

                if let (Some(score), Some(rank)) = (fused.semantic_score, fused.semantic_rank) {
                    result = result.with_semantic(score, rank);
                }

                if let (Some(score), Some(rank)) = (fused.keyword_score, fused.keyword_rank) {
                    result = result.with_keyword(score, rank);
                }

                Some(result)
            })
            .collect();

        // Apply score threshold
        if self.config.min_score > 0.0 {
            let before_count = enriched_results.len();
            enriched_results.retain(|r| r.fused_score >= self.config.min_score);
            debug!(
                before = before_count,
                after = enriched_results.len(),
                min_score = self.config.min_score,
                "Applied score threshold"
            );
        }

        // Apply deduplication
        if self.config.deduplicate {
            enriched_results = self.deduplicate(enriched_results);
        }

        // Apply final top_k limit
        enriched_results.truncate(final_top_k);

        #[allow(clippy::cast_possible_truncation)]
        let search_time_ms = start_time.elapsed().as_millis() as u64;

        Ok(HybridSearchResponse::new(self.config.fusion_method)
            .with_results(enriched_results)
            .with_total_semantic(total_semantic)
            .with_total_keyword(total_keyword)
            .with_search_time_ms(search_time_ms)
            .with_semantic_time_ms(semantic_time_ms)
            .with_keyword_time_ms(keyword_time_ms)
            .with_fusion_time_ms(fusion_time_ms))
    }

    /// Semantic search only (bypass keyword search and fusion).
    ///
    /// # Arguments
    ///
    /// * `query_embedding` - Query embedding for semantic search
    /// * `top_k` - Number of results to return
    /// * `filters` - Optional unified filter
    ///
    /// # Errors
    ///
    /// Returns an error if the semantic search fails.
    #[instrument(skip(self, query_embedding, filters))]
    pub async fn search_semantic_only(
        &self,
        query_embedding: &[f32],
        top_k: usize,
        filters: Option<&UnifiedFilter>,
        user_context: Option<&crate::types::UserContext>,
    ) -> Result<HybridSearchResponse> {
        let start_time = Instant::now();

        let semantic_filters = filters.map(convert_to_semantic_filters);
        let default_ctx = crate::types::UserContext::new(Uuid::nil(), Uuid::nil()).with_admin(true);
        let ctx = user_context.unwrap_or(&default_ctx);

        let results = self
            .semantic
            .search(query_embedding, ctx, semantic_filters, Some(top_k))
            .await?;

        #[allow(clippy::cast_possible_truncation)]
        let search_time_ms = start_time.elapsed().as_millis() as u64;
        let total_semantic = results.len();

        // Convert to HybridSearchResult format
        let hybrid_results: Vec<HybridSearchResult> = results
            .into_iter()
            .enumerate()
            .map(|(i, r)| {
                let mut result =
                    HybridSearchResult::new(r.chunk_id, r.document_id, r.content, r.score)
                        .with_semantic(r.score, i + 1)
                        .with_chunk_index(r.chunk_index)
                        .with_visibility(r.visibility)
                        .with_allowed_groups(r.allowed_groups)
                        .with_owner_id(r.owner_id)
                        .with_allowed_users(r.allowed_users)
                        .with_denied_groups(r.denied_groups)
                        .with_denied_users(r.denied_users)
                        .with_metadata(r.metadata);

                if let Some(title) = r.title {
                    result = result.with_title(title);
                }

                if let Some(uri) = r.source_uri {
                    result = result.with_source_uri(uri);
                }

                result
            })
            .collect();

        Ok(HybridSearchResponse::new(self.config.fusion_method)
            .with_results(hybrid_results)
            .with_total_semantic(total_semantic)
            .with_total_keyword(0)
            .with_search_time_ms(search_time_ms)
            .with_semantic_time_ms(search_time_ms))
    }

    /// Keyword search only (bypass semantic search and fusion).
    ///
    /// # Arguments
    ///
    /// * `query` - Text query for keyword search
    /// * `top_k` - Number of results to return
    /// * `filters` - Optional unified filter
    ///
    /// # Errors
    ///
    /// Returns an error if the keyword search fails.
    #[instrument(skip(self, filters), fields(query_len = query.len()))]
    pub async fn search_keyword_only(
        &self,
        query: &str,
        top_k: usize,
        filters: Option<&UnifiedFilter>,
        user_context: Option<&crate::types::UserContext>,
    ) -> Result<HybridSearchResponse> {
        let start_time = Instant::now();

        let keyword_filters = filters.map(convert_to_keyword_filters);
        let default_ctx = crate::types::UserContext::new(Uuid::nil(), Uuid::nil()).with_admin(true);
        let ctx = user_context.unwrap_or(&default_ctx);

        let results = self
            .keyword
            .search(query, ctx, keyword_filters, Some(top_k))
            .await?;

        #[allow(clippy::cast_possible_truncation)]
        let search_time_ms = start_time.elapsed().as_millis() as u64;
        let total_keyword = results.len();

        // Convert to HybridSearchResult format
        let hybrid_results: Vec<HybridSearchResult> = results
            .into_iter()
            .enumerate()
            .map(|(i, r)| {
                let mut result =
                    HybridSearchResult::new(r.chunk_id, r.document_id, r.content, r.score)
                        .with_keyword(r.score, i + 1)
                        .with_chunk_index(r.chunk_index)
                        .with_visibility(r.visibility)
                        .with_allowed_groups(r.allowed_groups)
                        .with_owner_id(r.owner_id)
                        .with_allowed_users(r.allowed_users)
                        .with_denied_groups(r.denied_groups)
                        .with_denied_users(r.denied_users)
                        .with_highlights(r.highlights)
                        .with_metadata(r.metadata);

                if let Some(title) = r.title {
                    result = result.with_title(title);
                }

                if let Some(uri) = r.source_uri {
                    result = result.with_source_uri(uri);
                }

                result
            })
            .collect();

        Ok(HybridSearchResponse::new(self.config.fusion_method)
            .with_results(hybrid_results)
            .with_total_semantic(0)
            .with_total_keyword(total_keyword)
            .with_search_time_ms(search_time_ms)
            .with_keyword_time_ms(search_time_ms))
    }

    /// Check health of both search backends.
    ///
    /// # Returns
    ///
    /// Returns `Ok(true)` if both backends are healthy, `Ok(false)` if one or both
    /// are unhealthy, or an error if health checks fail.
    pub async fn health_check(&self) -> Result<bool> {
        let (semantic_health, keyword_health) =
            tokio::join!(self.semantic.health_check(), self.keyword.health_check(),);

        match (semantic_health, keyword_health) {
            (Ok(()), Ok(())) => Ok(true),
            (Err(e), _) => {
                warn!("Semantic search health check failed: {}", e);
                Ok(false)
            }
            (_, Err(e)) => {
                warn!("Keyword search health check failed: {}", e);
                Ok(false)
            }
        }
    }

    /// Check health of the semantic search backend (Qdrant).
    ///
    /// # Errors
    ///
    /// Returns an error if the semantic search backend is unhealthy.
    pub async fn health_check_semantic(&self) -> Result<()> {
        self.semantic
            .health_check()
            .await
            .map_err(|e| RetrievalError::semantic_search(format!("Health check failed: {e}")))
    }

    /// Check health of the keyword search backend (`OpenSearch`).
    ///
    /// # Errors
    ///
    /// Returns an error if the keyword search backend is unhealthy.
    pub async fn health_check_keyword(&self) -> Result<()> {
        self.keyword
            .health_check()
            .await
            .map_err(|e| RetrievalError::keyword_search(format!("Health check failed: {e}")))
    }

    /// Get the current configuration.
    #[must_use]
    pub const fn config(&self) -> &HybridSearchConfig {
        &self.config
    }

    /// Update the configuration.
    pub fn set_config(&mut self, config: HybridSearchConfig) {
        self.config = config;
    }

    /// Deduplicate results by document ID, keeping the highest-scored chunk per document.
    #[allow(clippy::unused_self)]
    fn deduplicate(&self, results: Vec<HybridSearchResult>) -> Vec<HybridSearchResult> {
        let mut seen_docs: HashMap<Uuid, HybridSearchResult> = HashMap::new();

        for result in results {
            seen_docs
                .entry(result.document_id)
                .and_modify(|existing| {
                    if result.fused_score > existing.fused_score {
                        *existing = result.clone();
                    }
                })
                .or_insert(result);
        }

        // Convert to sorted vector maintaining score order
        let mut deduped: Vec<HybridSearchResult> = seen_docs.into_values().collect();
        deduped.sort_by(|a, b| {
            b.fused_score
                .partial_cmp(&a.fused_score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        deduped
    }
}

impl std::fmt::Debug for HybridSearcher {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("HybridSearcher")
            .field("config", &self.config)
            .finish_non_exhaustive()
    }
}

/// Build a content lookup map from semantic results.
fn build_semantic_content_map(results: &[SemanticResult]) -> HashMap<Uuid, &SemanticResult> {
    results.iter().map(|r| (r.chunk_id, r)).collect()
}

/// Build a content lookup map from keyword results.
fn build_keyword_content_map(results: &[KeywordResult]) -> HashMap<Uuid, &KeywordResult> {
    results.iter().map(|r| (r.chunk_id, r)).collect()
}

/// Convert unified filter to semantic search filters.
///
/// Maps `UnifiedFilter` conditions to `SearchFilters` fields:
/// - `source_type` key -> `SearchFilters.source_type`
/// - `document_id` key -> `SearchFilters.document_id` (parsed as UUID)
/// - `allowed_groups` key -> `SearchFilters.groups`
/// - Any other key -> `SearchFilters.custom` (for exact Value matches)
///
/// Only `must` conditions are processed since `SearchFilters` uses AND logic.
/// `should` and `must_not` conditions are logged as warnings and skipped,
/// as they require more complex filter logic not yet supported by the
/// `SearchFilters` struct.
fn convert_to_semantic_filters(filter: &UnifiedFilter) -> SearchFilters {
    let mut search_filters = SearchFilters::new();

    for condition in &filter.must {
        match condition.key.as_str() {
            "source_type" => {
                if let MatchType::Value(ref v) = condition.match_type {
                    search_filters = search_filters.with_source_type(v.clone());
                }
            }
            "document_id" => {
                if let MatchType::Value(ref v) = condition.match_type {
                    if let Ok(uuid) = Uuid::parse_str(v) {
                        search_filters = search_filters.with_document_id(uuid);
                    } else {
                        warn!(
                            value = %v,
                            "Ignoring invalid UUID in document_id filter"
                        );
                    }
                }
            }
            "allowed_groups" => match &condition.match_type {
                MatchType::Any(ref values) => {
                    search_filters = search_filters.with_groups(values.clone());
                }
                MatchType::Value(ref v) => {
                    search_filters = search_filters.with_groups(vec![v.clone()]);
                }
            },
            key => {
                // Map other conditions to custom filters
                if let MatchType::Value(ref v) = condition.match_type {
                    search_filters = search_filters.with_custom(key.to_string(), v.clone());
                } else if let MatchType::Any(ref values) = condition.match_type {
                    // Custom filters only support single values, use first match
                    // for best-effort compatibility
                    if let Some(first) = values.first() {
                        debug!(
                            key = key,
                            "Converting Any filter to single-value custom filter for semantic search"
                        );
                        search_filters = search_filters.with_custom(key.to_string(), first.clone());
                    }
                }
            }
        }
    }

    if !filter.should.is_empty() {
        debug!(
            count = filter.should.len(),
            "Semantic search: should conditions mapped to custom filters where possible"
        );
    }

    if !filter.must_not.is_empty() {
        debug!(
            count = filter.must_not.len(),
            "Semantic search: must_not conditions are not directly supported by SearchFilters"
        );
    }

    search_filters
}

/// Convert unified filter to keyword search filters.
///
/// Maps `UnifiedFilter` conditions to `KeywordSearchFilters` fields:
/// - `source_type` key -> `KeywordSearchFilters.source_type`
/// - `document_id` key -> `KeywordSearchFilters.document_id` (parsed as UUID)
/// - `allowed_groups` key -> `KeywordSearchFilters.groups`
/// - Any other key -> `KeywordSearchFilters.custom` (for exact Value matches)
///
/// Only `must` conditions are processed since `KeywordSearchFilters` uses AND logic.
/// `should` and `must_not` conditions are logged as warnings and skipped.
fn convert_to_keyword_filters(filter: &UnifiedFilter) -> KeywordSearchFilters {
    let mut keyword_filters = KeywordSearchFilters::new();

    for condition in &filter.must {
        match condition.key.as_str() {
            "source_type" => {
                if let MatchType::Value(ref v) = condition.match_type {
                    keyword_filters = keyword_filters.with_source_type(v.clone());
                }
            }
            "document_id" => {
                if let MatchType::Value(ref v) = condition.match_type {
                    if let Ok(uuid) = Uuid::parse_str(v) {
                        keyword_filters = keyword_filters.with_document_id(uuid);
                    } else {
                        warn!(
                            value = %v,
                            "Ignoring invalid UUID in document_id filter"
                        );
                    }
                }
            }
            "allowed_groups" => match &condition.match_type {
                MatchType::Any(ref values) => {
                    keyword_filters = keyword_filters.with_groups(values.clone());
                }
                MatchType::Value(ref v) => {
                    keyword_filters = keyword_filters.with_groups(vec![v.clone()]);
                }
            },
            key => {
                if let MatchType::Value(ref v) = condition.match_type {
                    keyword_filters = keyword_filters.with_custom(key.to_string(), v.clone());
                } else if let MatchType::Any(ref values) = condition.match_type {
                    if let Some(first) = values.first() {
                        debug!(
                            key = key,
                            "Converting Any filter to single-value custom filter for keyword search"
                        );
                        keyword_filters =
                            keyword_filters.with_custom(key.to_string(), first.clone());
                    }
                }
            }
        }
    }

    if !filter.should.is_empty() {
        debug!(
            count = filter.should.len(),
            "Keyword search: should conditions mapped to custom filters where possible"
        );
    }

    if !filter.must_not.is_empty() {
        debug!(
            count = filter.must_not.len(),
            "Keyword search: must_not conditions are not directly supported by KeywordSearchFilters"
        );
    }

    keyword_filters
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_deduplicate() {
        // We can't create a HybridSearcher without real backends,
        // so we test the deduplication logic directly
        let doc_id_1 = Uuid::new_v4();
        let doc_id_2 = Uuid::new_v4();

        let results = vec![
            HybridSearchResult::new(Uuid::new_v4(), doc_id_1, "Chunk 1 from Doc 1".into(), 0.95),
            HybridSearchResult::new(Uuid::new_v4(), doc_id_1, "Chunk 2 from Doc 1".into(), 0.90),
            HybridSearchResult::new(Uuid::new_v4(), doc_id_2, "Chunk 1 from Doc 2".into(), 0.85),
        ];

        // Simulate deduplication logic
        let mut seen_docs: HashMap<Uuid, HybridSearchResult> = HashMap::new();
        for result in results {
            seen_docs
                .entry(result.document_id)
                .and_modify(|existing| {
                    if result.fused_score > existing.fused_score {
                        *existing = result.clone();
                    }
                })
                .or_insert(result);
        }

        let mut deduped: Vec<HybridSearchResult> = seen_docs.into_values().collect();
        deduped.sort_by(|a, b| {
            b.fused_score
                .partial_cmp(&a.fused_score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        assert_eq!(deduped.len(), 2);
        assert_eq!(deduped[0].document_id, doc_id_1);
        assert!((deduped[0].fused_score - 0.95).abs() < f32::EPSILON);
        assert_eq!(deduped[1].document_id, doc_id_2);
    }

    #[test]
    fn test_hybrid_search_config_builder() {
        let config = HybridSearchConfig::default()
            .with_top_k(15)
            .with_semantic_top_k(100)
            .with_keyword_top_k(100)
            .with_min_score(0.3)
            .with_deduplicate(false);

        assert_eq!(config.top_k, 15);
        assert_eq!(config.semantic_top_k, 100);
        assert_eq!(config.keyword_top_k, 100);
        assert!((config.min_score - 0.3).abs() < f32::EPSILON);
        assert!(!config.deduplicate);
    }

    #[test]
    fn test_build_content_maps() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let semantic_results = vec![SemanticResult::new(
            chunk_id,
            document_id,
            0.9,
            "Test content".into(),
        )];

        let keyword_results = vec![KeywordResult::new(
            chunk_id,
            document_id,
            0.85,
            12.0,
            "Test content".into(),
        )];

        let semantic_map = build_semantic_content_map(&semantic_results);
        let keyword_map = build_keyword_content_map(&keyword_results);

        assert!(semantic_map.contains_key(&chunk_id));
        assert!(keyword_map.contains_key(&chunk_id));
        assert_eq!(semantic_map.get(&chunk_id).unwrap().content, "Test content");
        assert_eq!(keyword_map.get(&chunk_id).unwrap().content, "Test content");
    }

    // --- Filter conversion tests ---

    use crate::acl::FilterCondition;

    #[test]
    fn test_convert_to_semantic_filters_source_type() {
        let filter = UnifiedFilter::new().must(FilterCondition::value("source_type", "pdf"));

        let result = convert_to_semantic_filters(&filter);
        assert_eq!(result.source_type, Some("pdf".to_string()));
    }

    #[test]
    fn test_convert_to_semantic_filters_document_id() {
        let doc_id = Uuid::new_v4();
        let filter =
            UnifiedFilter::new().must(FilterCondition::value("document_id", doc_id.to_string()));

        let result = convert_to_semantic_filters(&filter);
        assert_eq!(result.document_id, Some(doc_id));
    }

    #[test]
    fn test_convert_to_semantic_filters_groups_any() {
        let filter = UnifiedFilter::new().must(FilterCondition::any_of(
            "allowed_groups",
            vec!["engineering".to_string(), "product".to_string()],
        ));

        let result = convert_to_semantic_filters(&filter);
        assert_eq!(
            result.groups,
            Some(vec!["engineering".to_string(), "product".to_string()])
        );
    }

    #[test]
    fn test_convert_to_semantic_filters_groups_single_value() {
        let filter =
            UnifiedFilter::new().must(FilterCondition::value("allowed_groups", "engineering"));

        let result = convert_to_semantic_filters(&filter);
        assert_eq!(result.groups, Some(vec!["engineering".to_string()]));
    }

    #[test]
    fn test_convert_to_semantic_filters_custom_field() {
        let filter = UnifiedFilter::new().must(FilterCondition::value("category", "docs"));

        let result = convert_to_semantic_filters(&filter);
        assert_eq!(result.custom.get("category"), Some(&"docs".to_string()));
    }

    #[test]
    fn test_convert_to_semantic_filters_multiple_conditions() {
        let doc_id = Uuid::new_v4();
        let filter = UnifiedFilter::new()
            .must(FilterCondition::value("source_type", "pdf"))
            .must(FilterCondition::value("document_id", doc_id.to_string()))
            .must(FilterCondition::value("category", "docs"));

        let result = convert_to_semantic_filters(&filter);
        assert_eq!(result.source_type, Some("pdf".to_string()));
        assert_eq!(result.document_id, Some(doc_id));
        assert_eq!(result.custom.get("category"), Some(&"docs".to_string()));
    }

    #[test]
    fn test_convert_to_semantic_filters_invalid_uuid_ignored() {
        let filter = UnifiedFilter::new().must(FilterCondition::value("document_id", "not-a-uuid"));

        let result = convert_to_semantic_filters(&filter);
        assert!(result.document_id.is_none());
    }

    #[test]
    fn test_convert_to_semantic_filters_empty_filter() {
        let filter = UnifiedFilter::new();
        let result = convert_to_semantic_filters(&filter);
        assert!(result.source_type.is_none());
        assert!(result.document_id.is_none());
        assert!(result.groups.is_none());
        assert!(result.custom.is_empty());
    }

    #[test]
    fn test_convert_to_keyword_filters_source_type() {
        let filter = UnifiedFilter::new().must(FilterCondition::value("source_type", "pdf"));

        let result = convert_to_keyword_filters(&filter);
        assert_eq!(result.source_type, Some("pdf".to_string()));
    }

    #[test]
    fn test_convert_to_keyword_filters_document_id() {
        let doc_id = Uuid::new_v4();
        let filter =
            UnifiedFilter::new().must(FilterCondition::value("document_id", doc_id.to_string()));

        let result = convert_to_keyword_filters(&filter);
        assert_eq!(result.document_id, Some(doc_id));
    }

    #[test]
    fn test_convert_to_keyword_filters_groups() {
        let filter = UnifiedFilter::new().must(FilterCondition::any_of(
            "allowed_groups",
            vec!["engineering".to_string()],
        ));

        let result = convert_to_keyword_filters(&filter);
        assert_eq!(result.groups, Some(vec!["engineering".to_string()]));
    }

    #[test]
    fn test_convert_to_keyword_filters_custom_field() {
        let filter = UnifiedFilter::new().must(FilterCondition::value("category", "docs"));

        let result = convert_to_keyword_filters(&filter);
        assert_eq!(result.custom.get("category"), Some(&"docs".to_string()));
    }

    #[test]
    fn test_convert_to_keyword_filters_multiple_conditions() {
        let doc_id = Uuid::new_v4();
        let filter = UnifiedFilter::new()
            .must(FilterCondition::value("source_type", "html"))
            .must(FilterCondition::value("document_id", doc_id.to_string()))
            .must(FilterCondition::any_of(
                "allowed_groups",
                vec!["engineering".to_string(), "product".to_string()],
            ))
            .must(FilterCondition::value("region", "eu-west"));

        let result = convert_to_keyword_filters(&filter);
        assert_eq!(result.source_type, Some("html".to_string()));
        assert_eq!(result.document_id, Some(doc_id));
        assert_eq!(
            result.groups,
            Some(vec!["engineering".to_string(), "product".to_string()])
        );
        assert_eq!(result.custom.get("region"), Some(&"eu-west".to_string()));
    }

    #[test]
    fn test_convert_to_keyword_filters_invalid_uuid_ignored() {
        let filter =
            UnifiedFilter::new().must(FilterCondition::value("document_id", "invalid-uuid"));

        let result = convert_to_keyword_filters(&filter);
        assert!(result.document_id.is_none());
    }
}

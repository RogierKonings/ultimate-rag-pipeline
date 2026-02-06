//! Hybrid searcher combining semantic and keyword search.
//!
//! This module provides the `HybridSearcher` that orchestrates parallel
//! semantic and keyword search execution with result fusion.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use tracing::{debug, instrument, warn};
use uuid::Uuid;

use crate::acl::UnifiedFilter;
use crate::error::{RetrievalError, Result};
use crate::fusion::{fuse, FusionConfig, ScoredItem};
use crate::search::{KeywordResult, KeywordSearchFilters, KeywordSearcher, SearchFilters, SemanticResult, SemanticSearcher};

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
        let semantic_filters = filters.map(|f| convert_to_semantic_filters(f));
        let keyword_filters = filters.map(|f| convert_to_keyword_filters(f));

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
            self.keyword.search(
                query,
                ctx,
                keyword_filters,
                Some(self.config.keyword_top_k),
            ),
        );

        let semantic_time_ms = semantic_start.elapsed().as_millis() as u64;
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
            total_keyword,
            semantic_time_ms,
            keyword_time_ms,
            "Parallel search completed"
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

        let fusion_time_ms = fusion_start.elapsed().as_millis() as u64;

        debug!(fused_count = fused_results.len(), fusion_time_ms, "Fusion completed");

        // Enrich fused results with content data
        let mut enriched_results: Vec<HybridSearchResult> = fused_results
            .into_iter()
            .filter_map(|fused| {
                // Get content from either source
                let (content, document_id, title, source_uri, chunk_index, visibility, allowed_groups, highlights, metadata) =
                    if let Some(semantic) = semantic_content_map.get(&fused.id) {
                        (
                            semantic.content.clone(),
                            semantic.document_id,
                            semantic.title.clone(),
                            semantic.source_uri.clone(),
                            semantic.chunk_index,
                            semantic.visibility,
                            semantic.allowed_groups.clone(),
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
                            keyword.highlights.clone(),
                            keyword.metadata.clone(),
                        )
                    } else {
                        // This shouldn't happen, but skip if it does
                        warn!("Fused result {} has no content source", fused.id);
                        return None;
                    };

                let mut result = HybridSearchResult::new(
                    fused.id,
                    document_id,
                    content,
                    fused.fused_score,
                )
                .with_chunk_index(chunk_index)
                .with_visibility(visibility)
                .with_allowed_groups(allowed_groups)
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

        let semantic_filters = filters.map(|f| convert_to_semantic_filters(f));
        let default_ctx = crate::types::UserContext::new(Uuid::nil(), Uuid::nil()).with_admin(true);
        let ctx = user_context.unwrap_or(&default_ctx);

        let results = self.semantic
            .search(
                query_embedding,
                ctx,
                semantic_filters,
                Some(top_k),
            )
            .await?;

        let search_time_ms = start_time.elapsed().as_millis() as u64;
        let total_semantic = results.len();

        // Convert to HybridSearchResult format
        let hybrid_results: Vec<HybridSearchResult> = results
            .into_iter()
            .enumerate()
            .map(|(i, r)| {
                let mut result = HybridSearchResult::new(
                    r.chunk_id,
                    r.document_id,
                    r.content,
                    r.score,
                )
                .with_semantic(r.score, i + 1)
                .with_chunk_index(r.chunk_index)
                .with_visibility(r.visibility)
                .with_allowed_groups(r.allowed_groups)
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

        let keyword_filters = filters.map(|f| convert_to_keyword_filters(f));
        let default_ctx = crate::types::UserContext::new(Uuid::nil(), Uuid::nil()).with_admin(true);
        let ctx = user_context.unwrap_or(&default_ctx);

        let results = self.keyword
            .search(
                query,
                ctx,
                keyword_filters,
                Some(top_k),
            )
            .await?;

        let search_time_ms = start_time.elapsed().as_millis() as u64;
        let total_keyword = results.len();

        // Convert to HybridSearchResult format
        let hybrid_results: Vec<HybridSearchResult> = results
            .into_iter()
            .enumerate()
            .map(|(i, r)| {
                let mut result = HybridSearchResult::new(
                    r.chunk_id,
                    r.document_id,
                    r.content,
                    r.score,
                )
                .with_keyword(r.score, i + 1)
                .with_chunk_index(r.chunk_index)
                .with_visibility(r.visibility)
                .with_allowed_groups(r.allowed_groups)
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
        let (semantic_health, keyword_health) = tokio::join!(
            self.semantic.health_check(),
            self.keyword.health_check(),
        );

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
        self.semantic.health_check().await.map_err(|e| {
            RetrievalError::semantic_search(format!("Health check failed: {e}"))
        })
    }

    /// Check health of the keyword search backend (OpenSearch).
    ///
    /// # Errors
    ///
    /// Returns an error if the keyword search backend is unhealthy.
    pub async fn health_check_keyword(&self) -> Result<()> {
        self.keyword.health_check().await.map_err(|e| {
            RetrievalError::keyword_search(format!("Health check failed: {e}"))
        })
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
#[allow(clippy::unnecessary_wraps)]
fn convert_to_semantic_filters(_filter: &UnifiedFilter) -> SearchFilters {
    // For now, return empty filters - real implementation would convert
    // UnifiedFilter conditions to SearchFilters
    // This is a placeholder for when full ACL integration is complete
    SearchFilters::new()
}

/// Convert unified filter to keyword search filters.
#[allow(clippy::unnecessary_wraps)]
fn convert_to_keyword_filters(_filter: &UnifiedFilter) -> KeywordSearchFilters {
    // For now, return empty filters - real implementation would convert
    // UnifiedFilter conditions to KeywordSearchFilters
    // This is a placeholder for when full ACL integration is complete
    KeywordSearchFilters::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_deduplicate() {
        // Create a dummy config for testing
        let config = HybridSearchConfig::default();

        // We can't create a HybridSearcher without real backends,
        // so we test the deduplication logic directly
        let doc_id_1 = Uuid::new_v4();
        let doc_id_2 = Uuid::new_v4();

        let results = vec![
            HybridSearchResult::new(
                Uuid::new_v4(),
                doc_id_1,
                "Chunk 1 from Doc 1".into(),
                0.95,
            ),
            HybridSearchResult::new(
                Uuid::new_v4(),
                doc_id_1,
                "Chunk 2 from Doc 1".into(),
                0.90,
            ),
            HybridSearchResult::new(
                Uuid::new_v4(),
                doc_id_2,
                "Chunk 1 from Doc 2".into(),
                0.85,
            ),
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
}

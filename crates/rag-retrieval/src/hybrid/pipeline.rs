//! Full search pipeline with all retrieval stages.
//!
//! This module provides the `SearchPipeline` that orchestrates the complete
//! retrieval workflow including:
//! - Query preprocessing and expansion
//! - HyDE (Hypothetical Document Embeddings) generation
//! - Query embedding
//! - Hybrid search execution
//! - ACL filtering
//! - Cross-encoder reranking
//! - Result caching

use std::sync::Arc;
use std::time::Instant;

use serde::{Deserialize, Serialize};
use tracing::{debug, instrument, warn};

use crate::acl::{ACLFilter, UnifiedFilter};
use crate::cache::RetrievalCache;
use crate::embedding::EmbeddingClient;
use crate::error::{RetrievalError, Result};
use crate::query::{HydeGenerator, QueryCache, QueryExpander, QueryPreprocessor};
use crate::reranking::RerankerService;
use crate::types::{RetrievalDebug, RetrievalMetrics, RetrievalResult, SearchMode, UserContext};

use super::response::HybridSearchResult;
use super::searcher::HybridSearcher;

/// Configuration for the search pipeline.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PipelineConfig {
    /// Whether to enable query expansion.
    #[serde(default)]
    pub enable_query_expansion: bool,

    /// Whether to enable HyDE (Hypothetical Document Embeddings).
    #[serde(default)]
    pub enable_hyde: bool,

    /// Whether to enable cross-encoder reranking.
    #[serde(default = "default_enable_reranking")]
    pub enable_reranking: bool,

    /// Whether to enable result caching.
    #[serde(default = "default_enable_caching")]
    pub enable_caching: bool,

    /// Number of results to pass to the reranker.
    #[serde(default = "default_rerank_top_k")]
    pub rerank_top_k: usize,

    /// Final number of results to return.
    #[serde(default = "default_final_top_k")]
    pub final_top_k: usize,

    /// Cache TTL in seconds.
    #[serde(default = "default_cache_ttl_secs")]
    pub cache_ttl_secs: u64,

    /// Total pipeline timeout in milliseconds.
    #[serde(default = "default_total_timeout_ms")]
    pub total_timeout_ms: u64,
}

fn default_enable_reranking() -> bool {
    true
}

fn default_enable_caching() -> bool {
    true
}

fn default_rerank_top_k() -> usize {
    20
}

fn default_final_top_k() -> usize {
    10
}

fn default_cache_ttl_secs() -> u64 {
    3600
}

fn default_total_timeout_ms() -> u64 {
    30000
}

impl Default for PipelineConfig {
    fn default() -> Self {
        Self {
            enable_query_expansion: false,
            enable_hyde: false,
            enable_reranking: default_enable_reranking(),
            enable_caching: default_enable_caching(),
            rerank_top_k: default_rerank_top_k(),
            final_top_k: default_final_top_k(),
            cache_ttl_secs: default_cache_ttl_secs(),
            total_timeout_ms: default_total_timeout_ms(),
        }
    }
}

impl PipelineConfig {
    /// Create a new pipeline config with default values.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Enable query expansion.
    #[must_use]
    pub const fn with_query_expansion(mut self, enable: bool) -> Self {
        self.enable_query_expansion = enable;
        self
    }

    /// Enable HyDE.
    #[must_use]
    pub const fn with_hyde(mut self, enable: bool) -> Self {
        self.enable_hyde = enable;
        self
    }

    /// Enable reranking.
    #[must_use]
    pub const fn with_reranking(mut self, enable: bool) -> Self {
        self.enable_reranking = enable;
        self
    }

    /// Enable caching.
    #[must_use]
    pub const fn with_caching(mut self, enable: bool) -> Self {
        self.enable_caching = enable;
        self
    }

    /// Set the rerank top-k.
    #[must_use]
    pub const fn with_rerank_top_k(mut self, top_k: usize) -> Self {
        self.rerank_top_k = top_k;
        self
    }

    /// Set the final top-k.
    #[must_use]
    pub const fn with_final_top_k(mut self, top_k: usize) -> Self {
        self.final_top_k = top_k;
        self
    }

    /// Set the cache TTL.
    #[must_use]
    pub const fn with_cache_ttl_secs(mut self, ttl: u64) -> Self {
        self.cache_ttl_secs = ttl;
        self
    }

    /// Set the total timeout.
    #[must_use]
    pub const fn with_total_timeout_ms(mut self, timeout_ms: u64) -> Self {
        self.total_timeout_ms = timeout_ms;
        self
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `PIPELINE_ENABLE_EXPANSION`: Enable query expansion (default: false)
    /// - `PIPELINE_ENABLE_HYDE`: Enable HyDE (default: false)
    /// - `PIPELINE_ENABLE_RERANKING`: Enable reranking (default: true)
    /// - `PIPELINE_ENABLE_CACHING`: Enable caching (default: true)
    /// - `PIPELINE_RERANK_TOP_K`: Rerank top-k (default: 20)
    /// - `PIPELINE_FINAL_TOP_K`: Final top-k (default: 10)
    /// - `PIPELINE_CACHE_TTL_SECS`: Cache TTL (default: 3600)
    /// - `PIPELINE_TOTAL_TIMEOUT_MS`: Total timeout (default: 30000)
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(val) = std::env::var("PIPELINE_ENABLE_EXPANSION") {
            config.enable_query_expansion = val.to_lowercase() == "true";
        }

        if let Ok(val) = std::env::var("PIPELINE_ENABLE_HYDE") {
            config.enable_hyde = val.to_lowercase() == "true";
        }

        if let Ok(val) = std::env::var("PIPELINE_ENABLE_RERANKING") {
            config.enable_reranking = val.to_lowercase() == "true";
        }

        if let Ok(val) = std::env::var("PIPELINE_ENABLE_CACHING") {
            config.enable_caching = val.to_lowercase() == "true";
        }

        if let Ok(val) = std::env::var("PIPELINE_RERANK_TOP_K") {
            if let Ok(v) = val.parse() {
                config.rerank_top_k = v;
            }
        }

        if let Ok(val) = std::env::var("PIPELINE_FINAL_TOP_K") {
            if let Ok(v) = val.parse() {
                config.final_top_k = v;
            }
        }

        if let Ok(val) = std::env::var("PIPELINE_CACHE_TTL_SECS") {
            if let Ok(v) = val.parse() {
                config.cache_ttl_secs = v;
            }
        }

        if let Ok(val) = std::env::var("PIPELINE_TOTAL_TIMEOUT_MS") {
            if let Ok(v) = val.parse() {
                config.total_timeout_ms = v;
            }
        }

        config
    }
}

/// Options for a single search request.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SearchOptions {
    /// Override for number of results.
    #[serde(default)]
    pub top_k: Option<usize>,

    /// Search mode (hybrid, semantic, or keyword).
    #[serde(default)]
    pub search_mode: SearchMode,

    /// Additional filters to apply.
    #[serde(default)]
    pub additional_filters: Option<UnifiedFilter>,

    /// Whether to skip the cache for this request.
    #[serde(default)]
    pub skip_cache: bool,

    /// Override for reranking.
    #[serde(default)]
    pub rerank: Option<bool>,

    /// Override for HyDE.
    #[serde(default)]
    pub use_hyde: Option<bool>,

    /// Override for query expansion.
    #[serde(default)]
    pub expand_query: Option<bool>,
}

impl SearchOptions {
    /// Create new search options.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the top-k.
    #[must_use]
    pub const fn with_top_k(mut self, top_k: usize) -> Self {
        self.top_k = Some(top_k);
        self
    }

    /// Set the search mode.
    #[must_use]
    pub const fn with_search_mode(mut self, mode: SearchMode) -> Self {
        self.search_mode = mode;
        self
    }

    /// Set additional filters.
    #[must_use]
    pub fn with_filters(mut self, filters: UnifiedFilter) -> Self {
        self.additional_filters = Some(filters);
        self
    }

    /// Skip the cache.
    #[must_use]
    pub const fn with_skip_cache(mut self, skip: bool) -> Self {
        self.skip_cache = skip;
        self
    }

    /// Override reranking.
    #[must_use]
    pub const fn with_rerank(mut self, rerank: bool) -> Self {
        self.rerank = Some(rerank);
        self
    }

    /// Override HyDE.
    #[must_use]
    pub const fn with_hyde(mut self, use_hyde: bool) -> Self {
        self.use_hyde = Some(use_hyde);
        self
    }

    /// Override query expansion.
    #[must_use]
    pub const fn with_expand_query(mut self, expand: bool) -> Self {
        self.expand_query = Some(expand);
        self
    }
}

/// Response from the search pipeline.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchPipelineResponse {
    /// The search results.
    pub results: Vec<RetrievalResult>,

    /// Timing and count metrics.
    pub metrics: RetrievalMetrics,

    /// Debug information about the search.
    pub debug: RetrievalDebug,
}

impl SearchPipelineResponse {
    /// Create a new response.
    #[must_use]
    pub fn new(results: Vec<RetrievalResult>, metrics: RetrievalMetrics, debug: RetrievalDebug) -> Self {
        Self {
            results,
            metrics,
            debug,
        }
    }

    /// Get the number of results.
    #[must_use]
    pub fn len(&self) -> usize {
        self.results.len()
    }

    /// Check if there are no results.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.results.is_empty()
    }
}

/// Builder for constructing a `SearchPipeline`.
pub struct SearchPipelineBuilder {
    hybrid_searcher: Option<Arc<HybridSearcher>>,
    embedding_client: Option<Arc<EmbeddingClient>>,
    preprocessor: Option<QueryPreprocessor>,
    expander: Option<QueryExpander>,
    hyde: Option<HydeGenerator>,
    reranker: Option<RerankerService>,
    acl_filter: Option<ACLFilter>,
    query_cache: Option<QueryCache>,
    retrieval_cache: Option<RetrievalCache>,
    config: PipelineConfig,
}

impl SearchPipelineBuilder {
    /// Create a new builder.
    #[must_use]
    pub fn new() -> Self {
        Self {
            hybrid_searcher: None,
            embedding_client: None,
            preprocessor: None,
            expander: None,
            hyde: None,
            reranker: None,
            acl_filter: None,
            query_cache: None,
            retrieval_cache: None,
            config: PipelineConfig::default(),
        }
    }

    /// Set the hybrid searcher (required).
    #[must_use]
    pub fn with_hybrid_searcher(mut self, searcher: Arc<HybridSearcher>) -> Self {
        self.hybrid_searcher = Some(searcher);
        self
    }

    /// Set the embedding client (required).
    #[must_use]
    pub fn with_embedding_client(mut self, client: Arc<EmbeddingClient>) -> Self {
        self.embedding_client = Some(client);
        self
    }

    /// Set the query preprocessor.
    #[must_use]
    pub fn with_preprocessor(mut self, preprocessor: QueryPreprocessor) -> Self {
        self.preprocessor = Some(preprocessor);
        self
    }

    /// Set the query expander.
    #[must_use]
    pub fn with_expander(mut self, expander: QueryExpander) -> Self {
        self.expander = Some(expander);
        self
    }

    /// Set the HyDE generator.
    #[must_use]
    pub fn with_hyde(mut self, hyde: HydeGenerator) -> Self {
        self.hyde = Some(hyde);
        self
    }

    /// Set the reranker service.
    #[must_use]
    pub fn with_reranker(mut self, reranker: RerankerService) -> Self {
        self.reranker = Some(reranker);
        self
    }

    /// Set the ACL filter.
    #[must_use]
    pub fn with_acl_filter(mut self, filter: ACLFilter) -> Self {
        self.acl_filter = Some(filter);
        self
    }

    /// Set the query cache.
    #[must_use]
    pub fn with_query_cache(mut self, cache: QueryCache) -> Self {
        self.query_cache = Some(cache);
        self
    }

    /// Set the retrieval cache.
    #[must_use]
    pub fn with_retrieval_cache(mut self, cache: RetrievalCache) -> Self {
        self.retrieval_cache = Some(cache);
        self
    }

    /// Set the pipeline configuration.
    #[must_use]
    pub fn with_config(mut self, config: PipelineConfig) -> Self {
        self.config = config;
        self
    }

    /// Build the search pipeline.
    ///
    /// # Errors
    ///
    /// Returns an error if required components are missing.
    pub fn build(self) -> Result<SearchPipeline> {
        let hybrid_searcher = self
            .hybrid_searcher
            .ok_or_else(|| RetrievalError::config("Hybrid searcher is required"))?;

        let embedding_client = self
            .embedding_client
            .ok_or_else(|| RetrievalError::config("Embedding client is required"))?;

        Ok(SearchPipeline {
            hybrid_searcher,
            embedding_client,
            preprocessor: self.preprocessor,
            expander: self.expander,
            hyde: self.hyde,
            reranker: self.reranker,
            acl_filter: self.acl_filter,
            query_cache: self.query_cache,
            retrieval_cache: self.retrieval_cache,
            config: self.config,
        })
    }
}

impl Default for SearchPipelineBuilder {
    fn default() -> Self {
        Self::new()
    }
}

/// Full search pipeline that orchestrates all retrieval stages.
///
/// The pipeline executes the following stages:
/// 1. Check cache (if enabled)
/// 2. Preprocess query (normalize, classify)
/// 3. Expand query (optional)
/// 4. Generate HyDE document (optional)
/// 5. Embed query
/// 6. Run hybrid search
/// 7. Apply ACL filter
/// 8. Rerank results (optional)
/// 9. Cache results (if enabled)
/// 10. Return results
pub struct SearchPipeline {
    hybrid_searcher: Arc<HybridSearcher>,
    embedding_client: Arc<EmbeddingClient>,
    preprocessor: Option<QueryPreprocessor>,
    expander: Option<QueryExpander>,
    hyde: Option<HydeGenerator>,
    reranker: Option<RerankerService>,
    acl_filter: Option<ACLFilter>,
    query_cache: Option<QueryCache>,
    retrieval_cache: Option<RetrievalCache>,
    config: PipelineConfig,
}

impl SearchPipeline {
    /// Create a new builder for the search pipeline.
    #[must_use]
    pub fn builder() -> SearchPipelineBuilder {
        SearchPipelineBuilder::new()
    }

    /// Execute the full search pipeline.
    ///
    /// # Arguments
    ///
    /// * `query` - The search query
    /// * `user_context` - User context for ACL filtering
    /// * `options` - Search options
    ///
    /// # Errors
    ///
    /// Returns an error if any stage of the pipeline fails.
    #[instrument(skip(self, user_context, options), fields(query_len = query.len()))]
    pub async fn search(
        &self,
        query: &str,
        user_context: &UserContext,
        options: SearchOptions,
    ) -> Result<SearchPipelineResponse> {
        let start_time = Instant::now();
        let mut metrics = RetrievalMetrics::new();
        let mut debug = RetrievalDebug::new();

        // Determine effective settings
        let _use_cache = self.config.enable_caching && !options.skip_cache && self.retrieval_cache.is_some();
        let use_expansion = options.expand_query.unwrap_or(self.config.enable_query_expansion);
        let use_hyde = options.use_hyde.unwrap_or(self.config.enable_hyde);
        let use_reranking = options.rerank.unwrap_or(self.config.enable_reranking);
        let final_top_k = options.top_k.unwrap_or(self.config.final_top_k);

        debug = debug.with_hyde(use_hyde);

        // Step 1: Check cache
        // TODO: Implement cache lookup with proper key generation
        let cache_hit = false;
        debug = debug.with_cache_hit(cache_hit);

        // Step 2: Preprocess query
        let preprocess_start = Instant::now();
        let processed_query = if let Some(ref preprocessor) = self.preprocessor {
            match preprocessor.preprocess(query) {
                Ok(result) => {
                    debug = debug.with_query_type(result.query_type);
                    debug = debug.with_processed_query(&result.normalized);
                    result.normalized.clone()
                }
                Err(e) => {
                    warn!("Query preprocessing failed: {}", e);
                    query.to_string()
                }
            }
        } else {
            query.to_string()
        };
        metrics.preprocessing_ms = preprocess_start.elapsed().as_millis() as u64;

        // Step 3: Expand query (if enabled)
        let expanded_terms = if use_expansion {
            if let Some(ref expander) = self.expander {
                match expander.expand(&processed_query).await {
                    Ok(terms) => {
                        debug = debug.with_expanded_terms(terms.clone());
                        terms
                    }
                    Err(e) => {
                        warn!("Query expansion failed: {}", e);
                        Vec::new()
                    }
                }
            } else {
                Vec::new()
            }
        } else {
            Vec::new()
        };

        // Suppress unused variable warning
        let _ = &expanded_terms;

        // Step 4: Generate HyDE document (if enabled)
        // TODO: Implement HyDE when hyde generator supports async
        let hyde_document: Option<String> = None;

        // Step 5: Embed query
        let embed_start = Instant::now();
        let query_to_embed = if let Some(ref hyde_doc) = hyde_document {
            hyde_doc.as_str()
        } else {
            &processed_query
        };

        let embedding = self.embedding_client
            .embed_query(query_to_embed)
            .await
            .map_err(|e| RetrievalError::embedding(format!("Failed to embed query: {e}")))?;

        let _embedding_time_ms = embed_start.elapsed().as_millis() as u64;

        // Step 6: Run hybrid search based on mode
        let search_top_k = if use_reranking {
            self.config.rerank_top_k
        } else {
            final_top_k
        };

        let hybrid_response = match options.search_mode {
            SearchMode::Hybrid => {
                self.hybrid_searcher
                    .search(
                        &processed_query,
                        &embedding,
                        Some(search_top_k),
                        options.additional_filters.as_ref(),
                    )
                    .await?
            }
            SearchMode::Semantic => {
                self.hybrid_searcher
                    .search_semantic_only(
                        &embedding,
                        search_top_k,
                        options.additional_filters.as_ref(),
                    )
                    .await?
            }
            SearchMode::Keyword => {
                self.hybrid_searcher
                    .search_keyword_only(
                        &processed_query,
                        search_top_k,
                        options.additional_filters.as_ref(),
                    )
                    .await?
            }
        };

        metrics.semantic_search_ms = hybrid_response.semantic_time_ms;
        metrics.keyword_search_ms = hybrid_response.keyword_time_ms;
        metrics.fusion_ms = hybrid_response.fusion_time_ms;
        metrics.semantic_count = hybrid_response.total_semantic;
        metrics.keyword_count = hybrid_response.total_keyword;
        metrics.fused_count = hybrid_response.results.len();

        debug!(
            semantic_count = metrics.semantic_count,
            keyword_count = metrics.keyword_count,
            fused_count = metrics.fused_count,
            "Hybrid search completed"
        );

        // Step 7: Apply ACL filter
        let acl_start = Instant::now();
        let mut results = hybrid_response.results;

        if let Some(ref acl_filter) = self.acl_filter {
            let before_count = results.len();
            results = apply_acl_filter(&results, user_context, acl_filter);
            debug!(
                before = before_count,
                after = results.len(),
                "ACL filter applied"
            );
        }

        metrics.acl_filter_ms = acl_start.elapsed().as_millis() as u64;

        // Step 8: Rerank (if enabled)
        let rerank_start = Instant::now();

        if use_reranking && self.reranker.is_some() && !results.is_empty() {
            let reranker = self.reranker.as_ref().unwrap();

            // Convert HybridSearchResults to RetrievalResults for reranking
            let retrieval_results: Vec<RetrievalResult> = results
                .iter()
                .map(|r| convert_to_retrieval_result(r.clone()))
                .collect();

            match reranker.rerank_results(&processed_query, retrieval_results, Some(final_top_k)).await {
                Ok(reranked) => {
                    // Reorder results based on rerank scores
                    let mut result_map: std::collections::HashMap<String, HybridSearchResult> =
                        results.into_iter().map(|r| (r.chunk_id.to_string(), r)).collect();

                    results = reranked
                        .into_iter()
                        .filter_map(|rr| {
                            result_map.remove(&rr.chunk_id).map(|mut r| {
                                // Update with rerank score
                                r.fused_score = rr.score;
                                r
                            })
                        })
                        .collect();

                    metrics.reranked_count = results.len();
                    debug!(
                        reranked_count = metrics.reranked_count,
                        "Reranking completed"
                    );
                }
                Err(e) => {
                    warn!("Reranking failed, using fusion scores: {}", e);
                    // Continue with fusion scores
                }
            }
        }

        metrics.rerank_ms = rerank_start.elapsed().as_millis() as u64;

        // Apply final top_k limit
        results.truncate(final_top_k);
        metrics.final_count = results.len();

        // Convert to RetrievalResult
        let final_results: Vec<RetrievalResult> = results
            .into_iter()
            .map(|r| convert_to_retrieval_result(r))
            .collect();

        // Step 9: Cache results (if enabled)
        // TODO: Implement cache storage

        // Calculate total time
        metrics.total_ms = start_time.elapsed().as_millis() as u64;

        Ok(SearchPipelineResponse::new(final_results, metrics, debug))
    }

    /// Get the pipeline configuration.
    #[must_use]
    pub const fn config(&self) -> &PipelineConfig {
        &self.config
    }
}

impl std::fmt::Debug for SearchPipeline {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SearchPipeline")
            .field("config", &self.config)
            .field("has_preprocessor", &self.preprocessor.is_some())
            .field("has_expander", &self.expander.is_some())
            .field("has_hyde", &self.hyde.is_some())
            .field("has_reranker", &self.reranker.is_some())
            .field("has_acl_filter", &self.acl_filter.is_some())
            .field("has_query_cache", &self.query_cache.is_some())
            .field("has_retrieval_cache", &self.retrieval_cache.is_some())
            .finish()
    }
}

/// Apply ACL filtering to results.
fn apply_acl_filter(
    results: &[HybridSearchResult],
    user_context: &UserContext,
    _acl_filter: &ACLFilter,
) -> Vec<HybridSearchResult> {
    // Filter results based on user context
    results
        .iter()
        .filter(|r| {
            // Admin can access everything
            if user_context.is_admin {
                return true;
            }

            // Check visibility-based access
            user_context.can_access(r.visibility, &r.allowed_groups)
        })
        .cloned()
        .collect()
}

/// Convert HybridSearchResult to RetrievalResult.
fn convert_to_retrieval_result(result: HybridSearchResult) -> RetrievalResult {
    let mut r = RetrievalResult::new(
        result.chunk_id.to_string(),
        result.document_id.to_string(),
        result.content,
        result.fused_score,
    );

    if let Some(title) = result.title {
        r = r.with_title(title);
    }

    if let Some(uri) = result.source_uri {
        r = r.with_source_uri(uri);
    }

    if let Some(score) = result.semantic_score {
        r = r.with_semantic_score(score);
    }

    if let Some(score) = result.keyword_score {
        r = r.with_keyword_score(score);
    }

    r.chunk_index = result.chunk_index;
    r.visibility = result.visibility;
    r.allowed_groups = result.allowed_groups;
    r.highlights = result.highlights;
    r.metadata = result.metadata;

    r
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pipeline_config_default() {
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

    #[test]
    fn test_pipeline_config_from_env() {
        std::env::set_var("PIPELINE_ENABLE_EXPANSION", "true");
        std::env::set_var("PIPELINE_ENABLE_HYDE", "true");
        std::env::set_var("PIPELINE_RERANK_TOP_K", "25");
        std::env::set_var("PIPELINE_FINAL_TOP_K", "12");

        let config = PipelineConfig::from_env();

        assert!(config.enable_query_expansion);
        assert!(config.enable_hyde);
        assert_eq!(config.rerank_top_k, 25);
        assert_eq!(config.final_top_k, 12);

        // Clean up
        std::env::remove_var("PIPELINE_ENABLE_EXPANSION");
        std::env::remove_var("PIPELINE_ENABLE_HYDE");
        std::env::remove_var("PIPELINE_RERANK_TOP_K");
        std::env::remove_var("PIPELINE_FINAL_TOP_K");
    }

    #[test]
    fn test_search_options_default() {
        let options = SearchOptions::default();

        assert!(options.top_k.is_none());
        assert_eq!(options.search_mode, SearchMode::Hybrid);
        assert!(options.additional_filters.is_none());
        assert!(!options.skip_cache);
        assert!(options.rerank.is_none());
        assert!(options.use_hyde.is_none());
        assert!(options.expand_query.is_none());
    }

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

    #[test]
    fn test_search_pipeline_response() {
        let results = vec![RetrievalResult::new(
            "chunk_1".into(),
            "doc_1".into(),
            "Test content".into(),
            0.95,
        )];
        let metrics = RetrievalMetrics::new();
        let debug = RetrievalDebug::new();

        let response = SearchPipelineResponse::new(results, metrics, debug);

        assert_eq!(response.len(), 1);
        assert!(!response.is_empty());
    }

    #[test]
    fn test_pipeline_config_serialization() {
        let config = PipelineConfig::new()
            .with_rerank_top_k(25)
            .with_final_top_k(15);

        let json = serde_json::to_string(&config).unwrap();
        assert!(json.contains("\"rerank_top_k\":25"));
        assert!(json.contains("\"final_top_k\":15"));

        let deserialized: PipelineConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.rerank_top_k, 25);
        assert_eq!(deserialized.final_top_k, 15);
    }
}

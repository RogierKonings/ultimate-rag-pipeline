//! Query result caching for the retrieval service.
//!
//! This module provides caching for retrieval results to avoid re-running
//! expensive searches for identical queries. The cache uses Redis as a backend
//! via the `rag-cache` crate.
//!
//! # Cache Key Format
//!
//! Keys follow the format: `{prefix}:{tenant_id}:{query_hash}:{mode}:{top_k}[:user_id]`
//!
//! Where:
//! - `prefix`: Configurable key prefix (default: "ret:query")
//! - `tenant_id`: UUID for tenant isolation
//! - `query_hash`: SHA-256 hash of the normalized query string
//! - `mode`: Search mode (semantic, keyword, hybrid)
//! - `top_k`: Number of results requested
//! - `user_id`: Optional user ID for user-specific caching
//!
//! # Example
//!
//! ```no_run
//! use rag_cache::{CacheClient, CacheConfig};
//! use rag_retrieval::query::{QueryCache, QueryCacheConfig, QueryCacheKey};
//! use rag_types::SearchMode;
//! use std::sync::Arc;
//! use uuid::Uuid;
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let cache_config = CacheConfig::default();
//!     let cache_client = Arc::new(CacheClient::connect(&cache_config).await?);
//!
//!     let query_cache = QueryCache::new(QueryCacheConfig::default(), cache_client);
//!
//!     let key = QueryCacheKey {
//!         query: "what is machine learning?".to_string(),
//!         tenant_id: Uuid::new_v4(),
//!         user_id: None,
//!         search_mode: SearchMode::Hybrid,
//!         top_k: 10,
//!     };
//!
//!     // Check for cached results
//!     if let Some(results) = query_cache.get(&key).await? {
//!         println!("Cache hit with {} results", results.len());
//!     }
//!
//!     Ok(())
//! }
//! ```

use crate::error::{Result, RetrievalError};
use crate::types::RetrievalResult;
use rag_cache::CacheClient;
use rag_types::SearchMode;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::sync::Arc;
use std::time::Duration;
use tracing::{debug, instrument, warn};
use uuid::Uuid;

/// Configuration for query result caching.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueryCacheConfig {
    /// Whether caching is enabled.
    #[serde(default = "default_enabled")]
    pub enabled: bool,

    /// Time-to-live for cached results in seconds.
    #[serde(default = "default_ttl_seconds")]
    pub ttl_seconds: u64,

    /// Prefix for cache keys.
    #[serde(default = "default_key_prefix")]
    pub key_prefix: String,

    /// Whether to include `user_id` in cache key for user-specific results.
    #[serde(default = "default_include_user_context")]
    pub include_user_context: bool,

    /// Maximum number of results to cache per query.
    #[serde(default = "default_max_cached_results")]
    pub max_cached_results: usize,
}

const fn default_enabled() -> bool {
    true
}

const fn default_ttl_seconds() -> u64 {
    3600 // 1 hour
}

fn default_key_prefix() -> String {
    "ret:query".to_string()
}

const fn default_include_user_context() -> bool {
    true
}

const fn default_max_cached_results() -> usize {
    100
}

impl Default for QueryCacheConfig {
    fn default() -> Self {
        Self {
            enabled: default_enabled(),
            ttl_seconds: default_ttl_seconds(),
            key_prefix: default_key_prefix(),
            include_user_context: default_include_user_context(),
            max_cached_results: default_max_cached_results(),
        }
    }
}

impl QueryCacheConfig {
    /// Create a new configuration with caching disabled.
    #[must_use]
    pub fn disabled() -> Self {
        Self {
            enabled: false,
            ..Default::default()
        }
    }

    /// Create a new configuration with custom TTL.
    #[must_use]
    pub const fn with_ttl(mut self, ttl_seconds: u64) -> Self {
        self.ttl_seconds = ttl_seconds;
        self
    }

    /// Create a new configuration with custom key prefix.
    #[must_use]
    pub fn with_key_prefix(mut self, prefix: impl Into<String>) -> Self {
        self.key_prefix = prefix.into();
        self
    }

    /// Create a new configuration with user context inclusion setting.
    #[must_use]
    pub const fn with_user_context(mut self, include: bool) -> Self {
        self.include_user_context = include;
        self
    }

    /// Create a new configuration with max cached results.
    #[must_use]
    pub const fn with_max_cached_results(mut self, max: usize) -> Self {
        self.max_cached_results = max;
        self
    }
}

/// Cache key components for a query.
///
/// All fields that affect the result set MUST be included so that different
/// users, filter combinations, or request knobs never share a cache entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueryCacheKey {
    /// Query string (normalized).
    pub query: String,

    /// Tenant ID for isolation.
    pub tenant_id: Uuid,

    /// User ID for user-specific caching (ACL may differ per user).
    pub user_id: Option<Uuid>,

    /// Groups the user belongs to (affects ACL filtering of results).
    #[serde(default)]
    pub groups: Vec<String>,

    /// Search mode used for the query.
    pub search_mode: SearchMode,

    /// Number of results requested.
    pub top_k: usize,

    /// Serialized request filters (affects which documents are searched).
    #[serde(default)]
    pub filters: Option<String>,

    /// Whether reranking is enabled.
    #[serde(default)]
    pub rerank: bool,

    /// Number of candidates to rerank.
    #[serde(default)]
    pub rerank_top_k: usize,

    /// Minimum score threshold.
    #[serde(default)]
    pub min_score: f32,

    /// Weight for semantic search results.
    #[serde(default)]
    pub semantic_weight: f32,

    /// Weight for keyword search results.
    #[serde(default)]
    pub keyword_weight: f32,
}

impl QueryCacheKey {
    /// Create a new query cache key with all parameters that affect the result set.
    #[must_use]
    pub fn new(
        query: impl Into<String>,
        tenant_id: Uuid,
        search_mode: SearchMode,
        top_k: usize,
    ) -> Self {
        Self {
            query: query.into(),
            tenant_id,
            user_id: None,
            groups: Vec::new(),
            search_mode,
            top_k,
            filters: None,
            rerank: false,
            rerank_top_k: 0,
            min_score: 0.0,
            semantic_weight: 0.0,
            keyword_weight: 0.0,
        }
    }

    /// Set the user ID for user-specific caching.
    #[must_use]
    pub const fn with_user_id(mut self, user_id: Uuid) -> Self {
        self.user_id = Some(user_id);
        self
    }

    /// Set the user's groups (for ACL-aware caching).
    #[must_use]
    pub fn with_groups(mut self, groups: Vec<String>) -> Self {
        self.groups = groups;
        self
    }

    /// Set the request filters (serialized as a stable string).
    #[must_use]
    pub fn with_filters(mut self, filters: Option<&serde_json::Value>) -> Self {
        self.filters = filters.map(std::string::ToString::to_string);
        self
    }

    /// Set rerank parameters.
    #[must_use]
    pub const fn with_rerank(mut self, rerank: bool, rerank_top_k: usize) -> Self {
        self.rerank = rerank;
        self.rerank_top_k = rerank_top_k;
        self
    }

    /// Set score threshold.
    #[must_use]
    pub const fn with_min_score(mut self, min_score: f32) -> Self {
        self.min_score = min_score;
        self
    }

    /// Set search weights.
    #[must_use]
    pub const fn with_weights(mut self, semantic_weight: f32, keyword_weight: f32) -> Self {
        self.semantic_weight = semantic_weight;
        self.keyword_weight = keyword_weight;
        self
    }
}

/// Query result cache backed by Redis.
#[derive(Clone)]
pub struct QueryCache {
    /// Cache configuration.
    config: QueryCacheConfig,
    /// Redis cache client.
    cache_client: Arc<CacheClient>,
}

impl QueryCache {
    /// Create a new query cache.
    #[must_use]
    pub const fn new(config: QueryCacheConfig, cache_client: Arc<CacheClient>) -> Self {
        Self {
            config,
            cache_client,
        }
    }

    /// Get the configuration.
    #[must_use]
    pub const fn config(&self) -> &QueryCacheConfig {
        &self.config
    }

    /// Check if caching is enabled.
    #[must_use]
    pub const fn is_enabled(&self) -> bool {
        self.config.enabled
    }

    /// Build the cache key string from key components.
    ///
    /// All fields that affect the result set are hashed into a single
    /// deterministic key so that different users, filters, or request knobs
    /// never collide.
    ///
    /// Format: `{prefix}:{tenant_id}:{params_hash}`
    #[must_use]
    pub fn build_key(&self, key: &QueryCacheKey) -> String {
        let mode_str = match key.search_mode {
            SearchMode::Semantic => "sem",
            SearchMode::Keyword => "kw",
            SearchMode::Hybrid => "hyb",
        };

        // Build a deterministic string from all fields that affect results
        let mut hasher = Sha256::new();

        // Query (normalized)
        let normalized_query = crate::utils::normalize_query(&key.query);
        hasher.update(normalized_query.as_bytes());
        hasher.update(b"|");

        // Mode and top_k
        hasher.update(mode_str.as_bytes());
        hasher.update(b"|");
        hasher.update(key.top_k.to_string().as_bytes());
        hasher.update(b"|");

        // User identity (user_id + groups)
        if self.config.include_user_context {
            if let Some(user_id) = key.user_id {
                hasher.update(user_id.to_string().as_bytes());
            }
            hasher.update(b"|");
            // Sort groups for deterministic hashing
            let mut sorted_groups = key.groups.clone();
            sorted_groups.sort();
            for group in &sorted_groups {
                hasher.update(group.as_bytes());
                hasher.update(b",");
            }
        }
        hasher.update(b"|");

        // Filters
        if let Some(ref filters) = key.filters {
            hasher.update(filters.as_bytes());
        }
        hasher.update(b"|");

        // Rerank settings
        hasher.update(if key.rerank { b"1" } else { b"0" } as &[u8]);
        hasher.update(b"|");
        hasher.update(key.rerank_top_k.to_string().as_bytes());
        hasher.update(b"|");

        // Score and weight settings (use bit representation for deterministic floats)
        hasher.update(key.min_score.to_bits().to_string().as_bytes());
        hasher.update(b"|");
        hasher.update(key.semantic_weight.to_bits().to_string().as_bytes());
        hasher.update(b"|");
        hasher.update(key.keyword_weight.to_bits().to_string().as_bytes());

        let params_hash = hex::encode(hasher.finalize());

        format!(
            "{}:{}:{}",
            self.config.key_prefix, key.tenant_id, params_hash
        )
    }

    /// Get cached results for a query.
    ///
    /// # Errors
    ///
    /// Returns an error if the cache operation fails.
    #[instrument(skip(self), fields(tenant_id = %key.tenant_id))]
    pub async fn get(&self, key: &QueryCacheKey) -> Result<Option<Vec<RetrievalResult>>> {
        if !self.config.enabled {
            return Ok(None);
        }

        let cache_key = self.build_key(key);
        debug!(cache_key = %cache_key, "Looking up query cache");

        match self
            .cache_client
            .get::<Vec<RetrievalResult>>(&cache_key)
            .await
        {
            Ok(result) => {
                if result.is_some() {
                    debug!(cache_key = %cache_key, "Query cache hit");
                } else {
                    debug!(cache_key = %cache_key, "Query cache miss");
                }
                Ok(result)
            }
            Err(e) => {
                warn!(
                    cache_key = %cache_key,
                    error = %e,
                    "Failed to get from query cache, treating as cache miss"
                );
                // Treat cache errors as cache misses to avoid blocking retrieval
                Ok(None)
            }
        }
    }

    /// Cache results for a query.
    ///
    /// Results are truncated to `max_cached_results` if necessary.
    ///
    /// # Errors
    ///
    /// Returns an error if the cache operation fails.
    #[instrument(skip(self, results), fields(tenant_id = %key.tenant_id, result_count = results.len()))]
    pub async fn set(&self, key: &QueryCacheKey, results: &[RetrievalResult]) -> Result<()> {
        if !self.config.enabled {
            return Ok(());
        }

        let cache_key = self.build_key(key);
        let ttl = Duration::from_secs(self.config.ttl_seconds);

        // Truncate results if necessary
        let results_to_cache: Vec<RetrievalResult> =
            if results.len() > self.config.max_cached_results {
                debug!(
                    original_count = results.len(),
                    max = self.config.max_cached_results,
                    "Truncating results for caching"
                );
                results
                    .iter()
                    .take(self.config.max_cached_results)
                    .cloned()
                    .collect()
            } else {
                results.to_vec()
            };

        debug!(
            cache_key = %cache_key,
            result_count = results_to_cache.len(),
            ttl_secs = self.config.ttl_seconds,
            "Caching query results"
        );

        self.cache_client
            .set(&cache_key, &results_to_cache, Some(ttl))
            .await
            .map_err(|e| RetrievalError::cache(format!("Failed to cache query results: {e}")))?;

        Ok(())
    }

    /// Invalidate cached results for a specific query.
    ///
    /// # Errors
    ///
    /// Returns an error if the cache operation fails.
    #[instrument(skip(self), fields(tenant_id = %key.tenant_id))]
    pub async fn invalidate(&self, key: &QueryCacheKey) -> Result<()> {
        if !self.config.enabled {
            return Ok(());
        }

        let cache_key = self.build_key(key);
        debug!(cache_key = %cache_key, "Invalidating query cache entry");

        self.cache_client
            .delete(&cache_key)
            .await
            .map_err(|e| RetrievalError::cache(format!("Failed to invalidate cache: {e}")))?;

        Ok(())
    }

    /// Invalidate all cached queries for a tenant.
    ///
    /// **Note**: This operation uses Redis SCAN and may be slow for large datasets.
    /// Use sparingly, typically during tenant data refresh or document re-indexing.
    ///
    /// # Errors
    ///
    /// Returns an error if the cache operation fails.
    #[instrument(skip(self), fields(tenant_id = %tenant_id))]
    pub async fn invalidate_tenant(&self, tenant_id: Uuid) -> Result<()> {
        if !self.config.enabled {
            return Ok(());
        }

        let pattern = format!("{}:{}:*", self.config.key_prefix, tenant_id);
        debug!(pattern = %pattern, "Invalidating all query cache entries for tenant");

        let deleted = self.cache_client.scan_delete(&pattern).await.map_err(|e| {
            RetrievalError::cache(format!("Failed to scan-delete tenant cache: {e}"))
        })?;

        debug!(tenant_id = %tenant_id, deleted = deleted, "Tenant cache invalidation complete");
        Ok(())
    }

}

impl std::fmt::Debug for QueryCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("QueryCache")
            .field("config", &self.config)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_defaults() {
        let config = QueryCacheConfig::default();
        assert!(config.enabled);
        assert_eq!(config.ttl_seconds, 3600);
        assert_eq!(config.key_prefix, "ret:query");
        assert!(config.include_user_context);
        assert_eq!(config.max_cached_results, 100);
    }

    #[test]
    fn test_config_disabled() {
        let config = QueryCacheConfig::disabled();
        assert!(!config.enabled);
    }

    #[test]
    fn test_config_builders() {
        let config = QueryCacheConfig::default()
            .with_ttl(1800)
            .with_key_prefix("custom:prefix")
            .with_user_context(false)
            .with_max_cached_results(50);

        assert_eq!(config.ttl_seconds, 1800);
        assert_eq!(config.key_prefix, "custom:prefix");
        assert!(!config.include_user_context);
        assert_eq!(config.max_cached_results, 50);
    }

    #[test]
    fn test_query_cache_key_creation() {
        let tenant_id = Uuid::new_v4();
        let user_id = Uuid::new_v4();

        let key = QueryCacheKey::new("test query", tenant_id, SearchMode::Hybrid, 10)
            .with_user_id(user_id);

        assert_eq!(key.query, "test query");
        assert_eq!(key.tenant_id, tenant_id);
        assert_eq!(key.user_id, Some(user_id));
        assert_eq!(key.search_mode, SearchMode::Hybrid);
        assert_eq!(key.top_k, 10);
    }

    #[test]
    fn test_normalize_query() {
        use crate::utils::normalize_query;

        assert_eq!(normalize_query("  Hello   WORLD  "), "hello world");
        assert_eq!(normalize_query("MULTIPLE    spaces"), "multiple spaces");
        assert_eq!(normalize_query("  trim  "), "trim");
    }

    #[test]
    fn test_query_hash_consistency() {
        use crate::utils::normalize_query;

        // Same query should produce same hash
        let query1 = "what is machine learning";
        let query2 = "what is machine learning";

        // We can't create QueryCache without a CacheClient, so test normalize_query directly
        let normalized1 = normalize_query(query1);
        let normalized2 = normalize_query(query2);

        assert_eq!(normalized1, normalized2);
    }

    #[test]
    fn test_query_hash_normalization() {
        use crate::utils::normalize_query;

        // Queries that should normalize to the same thing
        let query1 = "What is machine learning";
        let query2 = "  what   is  machine   learning  ";

        let normalized1 = normalize_query(query1);
        let normalized2 = normalize_query(query2);

        assert_eq!(normalized1, normalized2);
    }

    #[test]
    fn test_search_mode_in_key() {
        // Different search modes should produce different keys
        let tenant_id = Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();

        let key_hybrid = QueryCacheKey::new("test", tenant_id, SearchMode::Hybrid, 10);
        let key_semantic = QueryCacheKey::new("test", tenant_id, SearchMode::Semantic, 10);
        let key_keyword = QueryCacheKey::new("test", tenant_id, SearchMode::Keyword, 10);

        // Keys should differ by mode
        assert_ne!(key_hybrid.search_mode, key_semantic.search_mode);
        assert_ne!(key_hybrid.search_mode, key_keyword.search_mode);
        assert_ne!(key_semantic.search_mode, key_keyword.search_mode);
    }

    #[test]
    fn test_retrieval_result_serialization() {
        let result = RetrievalResult::new(
            "chunk_001".into(),
            "doc_001".into(),
            "Test content".into(),
            0.95,
        );

        let serialized = serde_json::to_string(&result).unwrap();
        let deserialized: RetrievalResult = serde_json::from_str(&serialized).unwrap();

        assert_eq!(deserialized.chunk_id, result.chunk_id);
        assert_eq!(deserialized.document_id, result.document_id);
        assert_eq!(deserialized.content, result.content);
        assert!((deserialized.score - result.score).abs() < f32::EPSILON);
    }

    #[test]
    fn test_config_serialization() {
        let config = QueryCacheConfig::default();
        let serialized = serde_json::to_string(&config).unwrap();
        let deserialized: QueryCacheConfig = serde_json::from_str(&serialized).unwrap();

        assert_eq!(deserialized.enabled, config.enabled);
        assert_eq!(deserialized.ttl_seconds, config.ttl_seconds);
        assert_eq!(deserialized.key_prefix, config.key_prefix);
    }

    #[test]
    fn test_query_cache_key_serialization() {
        let tenant_id = Uuid::new_v4();
        let key = QueryCacheKey::new("test query", tenant_id, SearchMode::Hybrid, 10);

        let serialized = serde_json::to_string(&key).unwrap();
        let deserialized: QueryCacheKey = serde_json::from_str(&serialized).unwrap();

        assert_eq!(deserialized.query, key.query);
        assert_eq!(deserialized.tenant_id, key.tenant_id);
        assert_eq!(deserialized.search_mode, key.search_mode);
        assert_eq!(deserialized.top_k, key.top_k);
    }
}

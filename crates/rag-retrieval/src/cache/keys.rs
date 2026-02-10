//! Cache key building utilities.
//!
//! This module provides a builder for creating deterministic cache keys that
//! include query parameters, filters, and user context.

use crate::acl::UnifiedFilter;
use crate::query::QueryCacheKey;
use rag_types::SearchMode;
use sha2::{Digest, Sha256};
use uuid::Uuid;

/// Builds deterministic cache keys for retrieval operations.
///
/// The builder pattern allows for flexible key construction with optional
/// components like filters and user context.
///
/// # Cache Key Format
///
/// Keys follow the format: `{prefix}:{tenant_id}:{query_hash}:{mode}:{top_k}[:user_id][:filter_hash]`
///
/// Where:
/// - `prefix`: Configurable key prefix (default: "ret")
/// - `tenant_id`: UUID for tenant isolation
/// - `query_hash`: SHA-256 hash of the normalized query string
/// - `mode`: Search mode (sem, kw, hyb)
/// - `top_k`: Number of results requested
/// - `user_id`: Optional user ID for user-specific caching
/// - `filter_hash`: Optional hash of serialized filters
///
/// # Example
///
/// ```
/// use rag_retrieval::cache::CacheKeyBuilder;
/// use rag_types::SearchMode;
/// use uuid::Uuid;
///
/// let tenant_id = Uuid::new_v4();
/// let key = CacheKeyBuilder::new(tenant_id, "what is machine learning?")
///     .with_search_mode(SearchMode::Hybrid)
///     .with_top_k(10)
///     .build();
///
/// assert!(key.starts_with("ret:"));
/// ```
#[derive(Debug, Clone)]
pub struct CacheKeyBuilder {
    prefix: String,
    tenant_id: Uuid,
    query: String,
    search_mode: SearchMode,
    top_k: usize,
    user_id: Option<Uuid>,
    filter_hash: Option<String>,
}

impl CacheKeyBuilder {
    /// Create a new cache key builder with required fields.
    ///
    /// # Arguments
    ///
    /// * `tenant_id` - The tenant UUID for isolation
    /// * `query` - The query string (will be normalized)
    ///
    /// # Example
    ///
    /// ```
    /// use rag_retrieval::cache::CacheKeyBuilder;
    /// use uuid::Uuid;
    ///
    /// let builder = CacheKeyBuilder::new(Uuid::new_v4(), "search query");
    /// ```
    #[must_use]
    pub fn new(tenant_id: Uuid, query: impl Into<String>) -> Self {
        Self {
            prefix: "ret".to_string(),
            tenant_id,
            query: query.into(),
            search_mode: SearchMode::default(),
            top_k: 10,
            user_id: None,
            filter_hash: None,
        }
    }

    /// Set the search mode.
    ///
    /// # Arguments
    ///
    /// * `mode` - The search mode (Semantic, Keyword, or Hybrid)
    #[must_use]
    pub const fn with_search_mode(mut self, mode: SearchMode) -> Self {
        self.search_mode = mode;
        self
    }

    /// Set the number of results.
    ///
    /// # Arguments
    ///
    /// * `top_k` - The number of results to return
    #[must_use]
    pub const fn with_top_k(mut self, top_k: usize) -> Self {
        self.top_k = top_k;
        self
    }

    /// Set the user ID for user-specific caching.
    ///
    /// # Arguments
    ///
    /// * `user_id` - The user UUID
    #[must_use]
    pub const fn with_user_id(mut self, user_id: Uuid) -> Self {
        self.user_id = Some(user_id);
        self
    }

    /// Set the filters to include in the cache key.
    ///
    /// The filters are serialized and hashed to ensure cache keys differ
    /// when different filters are applied.
    ///
    /// # Arguments
    ///
    /// * `filters` - The unified filter to include
    ///
    /// # Example
    ///
    /// ```
    /// use rag_retrieval::cache::CacheKeyBuilder;
    /// use rag_retrieval::acl::{UnifiedFilter, FilterCondition};
    /// use uuid::Uuid;
    ///
    /// let filter = UnifiedFilter::new()
    ///     .must(FilterCondition::value("source_type", "pdf"));
    ///
    /// let key = CacheKeyBuilder::new(Uuid::new_v4(), "query")
    ///     .with_filters(&filter)
    ///     .build();
    /// ```
    #[must_use]
    pub fn with_filters(mut self, filters: &UnifiedFilter) -> Self {
        // Only include filter hash if filters are non-empty
        if !filters.is_empty() {
            let filter_json = serde_json::to_string(filters).unwrap_or_default();
            let hash = Self::hash_string(&filter_json);
            self.filter_hash = Some(hash);
        }
        self
    }

    /// Set a custom key prefix.
    ///
    /// # Arguments
    ///
    /// * `prefix` - The prefix to use (default: "ret")
    #[must_use]
    pub fn with_prefix(mut self, prefix: impl Into<String>) -> Self {
        self.prefix = prefix.into();
        self
    }

    /// Build the cache key string.
    ///
    /// # Returns
    ///
    /// A deterministic cache key string.
    ///
    /// # Example
    ///
    /// ```
    /// use rag_retrieval::cache::CacheKeyBuilder;
    /// use rag_types::SearchMode;
    /// use uuid::Uuid;
    ///
    /// let key = CacheKeyBuilder::new(Uuid::new_v4(), "query")
    ///     .with_search_mode(SearchMode::Semantic)
    ///     .with_top_k(20)
    ///     .build();
    ///
    /// // Key format: ret:{tenant_id}:{query_hash}:sem:20
    /// assert!(key.contains(":sem:20"));
    /// ```
    #[must_use]
    pub fn build(&self) -> String {
        let query_hash = Self::hash_query(&self.query);
        let mode_str = Self::mode_to_string(self.search_mode);

        let mut key = format!(
            "{}:{}:{}:{}:{}",
            self.prefix, self.tenant_id, query_hash, mode_str, self.top_k
        );

        // Append optional components
        if let Some(user_id) = self.user_id {
            key = format!("{key}:{user_id}");
        }

        if let Some(ref filter_hash) = self.filter_hash {
            // Use first 16 chars of filter hash for reasonable key length
            key = format!("{key}:f{}", &filter_hash[..16.min(filter_hash.len())]);
        }

        key
    }

    /// Build a cache key from an existing `QueryCacheKey`.
    ///
    /// This provides compatibility with the existing query cache system.
    ///
    /// # Arguments
    ///
    /// * `key` - The query cache key to convert
    ///
    /// # Returns
    ///
    /// A cache key string compatible with the query cache format.
    ///
    /// # Example
    ///
    /// ```
    /// use rag_retrieval::cache::CacheKeyBuilder;
    /// use rag_retrieval::query::QueryCacheKey;
    /// use rag_types::SearchMode;
    /// use uuid::Uuid;
    ///
    /// let query_key = QueryCacheKey::new("test", Uuid::new_v4(), SearchMode::Hybrid, 10);
    /// let key_str = CacheKeyBuilder::from_query_key(&query_key);
    /// ```
    #[must_use]
    pub fn from_query_key(key: &QueryCacheKey) -> String {
        let mut builder = Self::new(key.tenant_id, &key.query)
            .with_search_mode(key.search_mode)
            .with_top_k(key.top_k)
            .with_prefix("ret:query");

        if let Some(user_id) = key.user_id {
            builder = builder.with_user_id(user_id);
        }

        builder.build()
    }

    /// Convert search mode to a short string.
    fn mode_to_string(mode: SearchMode) -> &'static str {
        match mode {
            SearchMode::Semantic => "sem",
            SearchMode::Keyword => "kw",
            SearchMode::Hybrid => "hyb",
        }
    }

    /// Normalize and hash a query string.
    fn hash_query(query: &str) -> String {
        let normalized = crate::utils::normalize_query(query);
        Self::hash_string(&normalized)
    }

    /// Compute SHA-256 hash of a string.
    fn hash_string(s: &str) -> String {
        let mut hasher = Sha256::new();
        hasher.update(s.as_bytes());
        hex::encode(hasher.finalize())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::acl::FilterCondition;

    #[test]
    fn test_cache_key_builder_basic() {
        let tenant_id = Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let key = CacheKeyBuilder::new(tenant_id, "test query")
            .with_search_mode(SearchMode::Hybrid)
            .with_top_k(10)
            .build();

        assert!(key.starts_with("ret:"));
        assert!(key.contains(&tenant_id.to_string()));
        assert!(key.contains(":hyb:10"));
    }

    #[test]
    fn test_cache_key_builder_with_user_id() {
        let tenant_id = Uuid::new_v4();
        let user_id = Uuid::new_v4();

        let key = CacheKeyBuilder::new(tenant_id, "test")
            .with_user_id(user_id)
            .build();

        assert!(key.contains(&user_id.to_string()));
    }

    #[test]
    fn test_cache_key_builder_with_filters() {
        let tenant_id = Uuid::new_v4();

        let filter = UnifiedFilter::new().must(FilterCondition::value("source_type", "pdf"));

        let key_with_filter = CacheKeyBuilder::new(tenant_id, "test")
            .with_filters(&filter)
            .build();

        let key_without_filter = CacheKeyBuilder::new(tenant_id, "test").build();

        // Keys should differ when filters are present
        assert_ne!(key_with_filter, key_without_filter);
        assert!(key_with_filter.contains(":f")); // Filter hash prefix
    }

    #[test]
    fn test_cache_key_builder_empty_filter_ignored() {
        let tenant_id = Uuid::new_v4();
        let empty_filter = UnifiedFilter::new();

        let key_with_empty = CacheKeyBuilder::new(tenant_id, "test")
            .with_filters(&empty_filter)
            .build();

        let key_without = CacheKeyBuilder::new(tenant_id, "test").build();

        // Empty filters should not affect the key
        assert_eq!(key_with_empty, key_without);
    }

    #[test]
    fn test_cache_key_deterministic() {
        let tenant_id = Uuid::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();

        let key1 = CacheKeyBuilder::new(tenant_id, "what is machine learning?")
            .with_search_mode(SearchMode::Hybrid)
            .with_top_k(10)
            .build();

        let key2 = CacheKeyBuilder::new(tenant_id, "what is machine learning?")
            .with_search_mode(SearchMode::Hybrid)
            .with_top_k(10)
            .build();

        assert_eq!(key1, key2);
    }

    #[test]
    fn test_cache_key_query_normalization() {
        let tenant_id = Uuid::new_v4();

        // Different whitespace/casing should produce same key
        let key1 = CacheKeyBuilder::new(tenant_id, "  HELLO   world  ").build();
        let key2 = CacheKeyBuilder::new(tenant_id, "hello world").build();

        assert_eq!(key1, key2);
    }

    #[test]
    fn test_cache_key_different_modes() {
        let tenant_id = Uuid::new_v4();

        let key_semantic = CacheKeyBuilder::new(tenant_id, "test")
            .with_search_mode(SearchMode::Semantic)
            .build();

        let key_keyword = CacheKeyBuilder::new(tenant_id, "test")
            .with_search_mode(SearchMode::Keyword)
            .build();

        let key_hybrid = CacheKeyBuilder::new(tenant_id, "test")
            .with_search_mode(SearchMode::Hybrid)
            .build();

        assert!(key_semantic.contains(":sem:"));
        assert!(key_keyword.contains(":kw:"));
        assert!(key_hybrid.contains(":hyb:"));

        assert_ne!(key_semantic, key_keyword);
        assert_ne!(key_semantic, key_hybrid);
        assert_ne!(key_keyword, key_hybrid);
    }

    #[test]
    fn test_cache_key_different_top_k() {
        let tenant_id = Uuid::new_v4();

        let key_10 = CacheKeyBuilder::new(tenant_id, "test")
            .with_top_k(10)
            .build();

        let key_20 = CacheKeyBuilder::new(tenant_id, "test")
            .with_top_k(20)
            .build();

        assert_ne!(key_10, key_20);
    }

    #[test]
    fn test_cache_key_custom_prefix() {
        let tenant_id = Uuid::new_v4();

        let key = CacheKeyBuilder::new(tenant_id, "test")
            .with_prefix("custom:prefix")
            .build();

        assert!(key.starts_with("custom:prefix:"));
    }

    #[test]
    fn test_from_query_key() {
        let tenant_id = Uuid::new_v4();
        let user_id = Uuid::new_v4();

        let query_key = QueryCacheKey::new("test query", tenant_id, SearchMode::Hybrid, 10)
            .with_user_id(user_id);

        let key_str = CacheKeyBuilder::from_query_key(&query_key);

        assert!(key_str.starts_with("ret:query:"));
        assert!(key_str.contains(&tenant_id.to_string()));
        assert!(key_str.contains(&user_id.to_string()));
        assert!(key_str.contains(":hyb:10"));
    }

    #[test]
    fn test_from_query_key_without_user() {
        let tenant_id = Uuid::new_v4();

        let query_key = QueryCacheKey::new("test", tenant_id, SearchMode::Semantic, 5);

        let key_str = CacheKeyBuilder::from_query_key(&query_key);

        assert!(key_str.contains(":sem:5"));
        // Should not have extra segments for user_id
        assert_eq!(key_str.split(':').count(), 6); // prefix:query:tenant:hash:mode:top_k
    }

    #[test]
    fn test_filter_hash_consistency() {
        let tenant_id = Uuid::new_v4();

        let filter1 = UnifiedFilter::new()
            .must(FilterCondition::value("type", "pdf"))
            .should(FilterCondition::value("status", "active"));

        let filter2 = UnifiedFilter::new()
            .must(FilterCondition::value("type", "pdf"))
            .should(FilterCondition::value("status", "active"));

        let key1 = CacheKeyBuilder::new(tenant_id, "test")
            .with_filters(&filter1)
            .build();

        let key2 = CacheKeyBuilder::new(tenant_id, "test")
            .with_filters(&filter2)
            .build();

        // Same filters should produce same key
        assert_eq!(key1, key2);
    }

    #[test]
    fn test_different_filters_different_keys() {
        let tenant_id = Uuid::new_v4();

        let filter1 = UnifiedFilter::new().must(FilterCondition::value("type", "pdf"));

        let filter2 = UnifiedFilter::new().must(FilterCondition::value("type", "docx"));

        let key1 = CacheKeyBuilder::new(tenant_id, "test")
            .with_filters(&filter1)
            .build();

        let key2 = CacheKeyBuilder::new(tenant_id, "test")
            .with_filters(&filter2)
            .build();

        // Different filters should produce different keys
        assert_ne!(key1, key2);
    }
}

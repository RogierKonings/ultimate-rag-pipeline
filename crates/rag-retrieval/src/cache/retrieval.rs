//! High-level retrieval cache with statistics tracking.
//!
//! This module provides `RetrievalCache`, a wrapper around `QueryCache` that
//! adds automatic statistics tracking for cache operations.

use crate::error::Result;
use crate::query::{QueryCache, QueryCacheConfig, QueryCacheKey};
use crate::types::RetrievalResult;

use super::stats::CacheStats;
use rag_cache::CacheClient;
use std::sync::Arc;
use std::time::Instant;
use tracing::{debug, instrument};

/// High-level retrieval cache with automatic statistics tracking.
///
/// `RetrievalCache` wraps `QueryCache` and automatically tracks cache hits,
/// misses, latencies, and errors. Statistics can be accessed via the `stats()`
/// method.
///
/// # Example
///
/// ```no_run
/// use rag_cache::{CacheClient, CacheConfig};
/// use rag_retrieval::cache::{RetrievalCache, CacheStats};
/// use rag_retrieval::query::{QueryCacheConfig, QueryCacheKey};
/// use rag_retrieval::SearchMode;
/// use std::sync::Arc;
/// use uuid::Uuid;
///
/// #[tokio::main]
/// async fn main() -> Result<(), Box<dyn std::error::Error>> {
///     let cache_config = CacheConfig::default();
///     let cache_client = Arc::new(CacheClient::connect(&cache_config).await?);
///
///     let retrieval_cache = RetrievalCache::new(
///         QueryCacheConfig::default(),
///         cache_client,
///     );
///
///     let key = QueryCacheKey::new("test query", Uuid::new_v4(), SearchMode::Hybrid, 10);
///
///     // Get with stats tracking
///     if let Some(results) = retrieval_cache.get(&key).await? {
///         println!("Got {} results", results.len());
///     }
///
///     // Check stats
///     let stats = retrieval_cache.stats();
///     println!("Hit rate: {:.2}%", stats.hit_rate() * 100.0);
///
///     Ok(())
/// }
/// ```
#[derive(Clone)]
pub struct RetrievalCache {
    /// The underlying query cache.
    inner: QueryCache,
    /// Statistics tracker.
    stats: Arc<CacheStats>,
}

impl RetrievalCache {
    /// Create a new retrieval cache with statistics tracking.
    ///
    /// # Arguments
    ///
    /// * `config` - Configuration for the underlying query cache
    /// * `cache_client` - The Redis cache client
    ///
    /// # Returns
    ///
    /// A new `RetrievalCache` instance with fresh statistics.
    #[must_use]
    pub fn new(config: QueryCacheConfig, cache_client: Arc<CacheClient>) -> Self {
        Self {
            inner: QueryCache::new(config, cache_client),
            stats: Arc::new(CacheStats::new()),
        }
    }

    /// Create a new retrieval cache with existing statistics tracker.
    ///
    /// This allows sharing statistics across multiple cache instances.
    ///
    /// # Arguments
    ///
    /// * `config` - Configuration for the underlying query cache
    /// * `cache_client` - The Redis cache client
    /// * `stats` - Shared statistics tracker
    #[must_use]
    pub fn with_stats(
        config: QueryCacheConfig,
        cache_client: Arc<CacheClient>,
        stats: Arc<CacheStats>,
    ) -> Self {
        Self {
            inner: QueryCache::new(config, cache_client),
            stats,
        }
    }

    /// Get cached results with statistics tracking.
    ///
    /// This method wraps `QueryCache::get()` and automatically tracks:
    /// - Cache hits (with latency)
    /// - Cache misses (with latency)
    /// - Errors
    ///
    /// # Arguments
    ///
    /// * `key` - The cache key to look up
    ///
    /// # Returns
    ///
    /// `Ok(Some(results))` if cached, `Ok(None)` on cache miss, or `Err` on error.
    ///
    /// # Errors
    ///
    /// Returns an error if the cache operation fails.
    #[instrument(skip(self), fields(tenant_id = %key.tenant_id))]
    pub async fn get(&self, key: &QueryCacheKey) -> Result<Option<Vec<RetrievalResult>>> {
        let start = Instant::now();

        let result = self.inner.get(key).await;
        let latency_us = start.elapsed().as_micros() as u64;

        match &result {
            Ok(Some(_)) => {
                debug!("Cache hit ({}us)", latency_us);
                self.stats.record_hit(latency_us);
            }
            Ok(None) => {
                debug!("Cache miss ({}us)", latency_us);
                self.stats.record_miss(latency_us);
            }
            Err(_) => {
                debug!("Cache error ({}us)", latency_us);
                self.stats.record_error();
            }
        }

        result
    }

    /// Set cached results with statistics tracking.
    ///
    /// This method wraps `QueryCache::set()` and tracks:
    /// - Set operations
    /// - Errors
    ///
    /// # Arguments
    ///
    /// * `key` - The cache key
    /// * `results` - The results to cache
    ///
    /// # Errors
    ///
    /// Returns an error if the cache operation fails.
    #[instrument(skip(self, results), fields(tenant_id = %key.tenant_id, result_count = results.len()))]
    pub async fn set(&self, key: &QueryCacheKey, results: &[RetrievalResult]) -> Result<()> {
        let result = self.inner.set(key, results).await;

        match &result {
            Ok(()) => {
                debug!("Cache set successful");
                self.stats.record_set();
            }
            Err(_) => {
                debug!("Cache set error");
                self.stats.record_error();
            }
        }

        result
    }

    /// Invalidate a cache entry with statistics tracking.
    ///
    /// This method wraps `QueryCache::invalidate()` and tracks:
    /// - Invalidation operations
    /// - Errors
    ///
    /// # Arguments
    ///
    /// * `key` - The cache key to invalidate
    ///
    /// # Errors
    ///
    /// Returns an error if the cache operation fails.
    #[instrument(skip(self), fields(tenant_id = %key.tenant_id))]
    pub async fn invalidate(&self, key: &QueryCacheKey) -> Result<()> {
        let result = self.inner.invalidate(key).await;

        match &result {
            Ok(()) => {
                debug!("Cache invalidation successful");
                self.stats.record_invalidation();
            }
            Err(_) => {
                debug!("Cache invalidation error");
                self.stats.record_error();
            }
        }

        result
    }

    /// Get the statistics tracker.
    ///
    /// # Returns
    ///
    /// A reference to the `CacheStats` instance.
    #[must_use]
    pub fn stats(&self) -> &CacheStats {
        &self.stats
    }

    /// Check if caching is enabled.
    ///
    /// # Returns
    ///
    /// `true` if the cache is enabled, `false` otherwise.
    #[must_use]
    pub fn is_enabled(&self) -> bool {
        self.inner.is_enabled()
    }

    /// Get the underlying query cache configuration.
    ///
    /// # Returns
    ///
    /// A reference to the `QueryCacheConfig`.
    #[must_use]
    pub fn config(&self) -> &QueryCacheConfig {
        self.inner.config()
    }

    /// Get a reference to the underlying query cache.
    ///
    /// This allows direct access to the query cache if needed.
    #[must_use]
    pub fn inner(&self) -> &QueryCache {
        &self.inner
    }
}

impl std::fmt::Debug for RetrievalCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RetrievalCache")
            .field("inner", &self.inner)
            .field("stats", &self.stats.snapshot())
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Note: Integration tests with actual CacheClient would require
    // a Redis connection. Unit tests focus on the structure and
    // stats tracking behavior.

    #[test]
    fn test_cache_stats_tracking_contract() {
        // Verify the stats tracking contract
        let stats = CacheStats::new();

        // Hit recording
        stats.record_hit(1000);
        assert_eq!(stats.hits(), 1);

        // Miss recording
        stats.record_miss(2000);
        assert_eq!(stats.misses(), 1);

        // Set recording
        stats.record_set();
        assert_eq!(stats.sets(), 1);

        // Invalidation recording
        stats.record_invalidation();
        assert_eq!(stats.invalidations(), 1);

        // Error recording
        stats.record_error();
        assert_eq!(stats.errors(), 1);
    }

    #[test]
    fn test_stats_calculations() {
        let stats = CacheStats::new();

        // 3 hits, 1 miss
        stats.record_hit(100);
        stats.record_hit(200);
        stats.record_hit(300);
        stats.record_miss(1000);

        // Hit rate: 3/4 = 0.75
        assert!((stats.hit_rate() - 0.75).abs() < 0.001);

        // Average hit latency: (100 + 200 + 300) / 3 = 200us
        assert!((stats.avg_hit_latency_us() - 200.0).abs() < 0.001);

        // Average miss latency: 1000us
        assert!((stats.avg_miss_latency_us() - 1000.0).abs() < 0.001);
    }

    #[test]
    fn test_shared_stats() {
        // Verify that stats can be shared across instances
        let stats = Arc::new(CacheStats::new());

        // Simulate two sources recording to same stats
        stats.record_hit(100);
        stats.record_hit(100);
        stats.record_miss(100);

        assert_eq!(stats.hits(), 2);
        assert_eq!(stats.misses(), 1);
        assert_eq!(stats.total_requests(), 3);
    }
}

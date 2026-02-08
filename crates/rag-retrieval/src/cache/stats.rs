//! Cache statistics tracking.
//!
//! This module provides thread-safe statistics tracking for cache operations,
//! including hit/miss counts, latency metrics, and computed rates.

use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Instant;

/// Thread-safe cache statistics tracker.
///
/// Uses atomic operations for lock-free updates, making it safe to use
/// from multiple threads without external synchronization.
///
/// # Example
///
/// ```
/// use rag_retrieval::cache::CacheStats;
///
/// let stats = CacheStats::new();
///
/// // Record some operations
/// stats.record_hit(5);  // 5ms latency
/// stats.record_hit(3);
/// stats.record_miss(10);
/// stats.record_set();
///
/// // Check metrics
/// assert_eq!(stats.hits(), 2);
/// assert_eq!(stats.misses(), 1);
/// assert_eq!(stats.total_requests(), 3);
/// assert!((stats.hit_rate() - 0.666).abs() < 0.01);
/// ```
#[derive(Debug)]
pub struct CacheStats {
    hits: AtomicU64,
    misses: AtomicU64,
    sets: AtomicU64,
    invalidations: AtomicU64,
    errors: AtomicU64,
    total_hit_latency_us: AtomicU64,
    total_miss_latency_us: AtomicU64,
    start_time: Instant,
}

impl Default for CacheStats {
    fn default() -> Self {
        Self::new()
    }
}

impl CacheStats {
    /// Create a new cache stats tracker.
    ///
    /// The start time is recorded for uptime calculation.
    #[must_use]
    pub fn new() -> Self {
        Self {
            hits: AtomicU64::new(0),
            misses: AtomicU64::new(0),
            sets: AtomicU64::new(0),
            invalidations: AtomicU64::new(0),
            errors: AtomicU64::new(0),
            total_hit_latency_us: AtomicU64::new(0),
            total_miss_latency_us: AtomicU64::new(0),
            start_time: Instant::now(),
        }
    }

    /// Record a cache hit with latency.
    ///
    /// # Arguments
    ///
    /// * `latency_us` - The latency in microseconds
    pub fn record_hit(&self, latency_us: u64) {
        self.hits.fetch_add(1, Ordering::Relaxed);
        self.total_hit_latency_us
            .fetch_add(latency_us, Ordering::Relaxed);
    }

    /// Record a cache miss with latency.
    ///
    /// # Arguments
    ///
    /// * `latency_us` - The latency in microseconds
    pub fn record_miss(&self, latency_us: u64) {
        self.misses.fetch_add(1, Ordering::Relaxed);
        self.total_miss_latency_us
            .fetch_add(latency_us, Ordering::Relaxed);
    }

    /// Record a cache set operation.
    pub fn record_set(&self) {
        self.sets.fetch_add(1, Ordering::Relaxed);
    }

    /// Record a cache invalidation.
    pub fn record_invalidation(&self) {
        self.invalidations.fetch_add(1, Ordering::Relaxed);
    }

    /// Record a cache error.
    pub fn record_error(&self) {
        self.errors.fetch_add(1, Ordering::Relaxed);
    }

    /// Get the number of cache hits.
    #[must_use]
    pub fn hits(&self) -> u64 {
        self.hits.load(Ordering::Relaxed)
    }

    /// Get the number of cache misses.
    #[must_use]
    pub fn misses(&self) -> u64 {
        self.misses.load(Ordering::Relaxed)
    }

    /// Get the number of cache sets.
    #[must_use]
    pub fn sets(&self) -> u64 {
        self.sets.load(Ordering::Relaxed)
    }

    /// Get the number of invalidations.
    #[must_use]
    pub fn invalidations(&self) -> u64 {
        self.invalidations.load(Ordering::Relaxed)
    }

    /// Get the number of errors.
    #[must_use]
    pub fn errors(&self) -> u64 {
        self.errors.load(Ordering::Relaxed)
    }

    /// Get the total number of requests (hits + misses).
    #[must_use]
    pub fn total_requests(&self) -> u64 {
        self.hits() + self.misses()
    }

    /// Calculate the hit rate as a ratio (0.0 to 1.0).
    ///
    /// Returns 0.0 if no requests have been made.
    #[must_use]
    pub fn hit_rate(&self) -> f64 {
        let total = self.total_requests();
        if total == 0 {
            return 0.0;
        }
        self.hits() as f64 / total as f64
    }

    /// Calculate the miss rate as a ratio (0.0 to 1.0).
    ///
    /// Returns 0.0 if no requests have been made.
    #[must_use]
    pub fn miss_rate(&self) -> f64 {
        let total = self.total_requests();
        if total == 0 {
            return 0.0;
        }
        self.misses() as f64 / total as f64
    }

    /// Get the average hit latency in microseconds.
    ///
    /// Returns 0.0 if no hits have been recorded.
    #[must_use]
    pub fn avg_hit_latency_us(&self) -> f64 {
        let hits = self.hits();
        if hits == 0 {
            return 0.0;
        }
        self.total_hit_latency_us.load(Ordering::Relaxed) as f64 / hits as f64
    }

    /// Get the average miss latency in microseconds.
    ///
    /// Returns 0.0 if no misses have been recorded.
    #[must_use]
    pub fn avg_miss_latency_us(&self) -> f64 {
        let misses = self.misses();
        if misses == 0 {
            return 0.0;
        }
        self.total_miss_latency_us.load(Ordering::Relaxed) as f64 / misses as f64
    }

    /// Get the average hit latency in milliseconds.
    ///
    /// Returns 0.0 if no hits have been recorded.
    #[must_use]
    pub fn avg_hit_latency_ms(&self) -> f64 {
        self.avg_hit_latency_us() / 1000.0
    }

    /// Get the average miss latency in milliseconds.
    ///
    /// Returns 0.0 if no misses have been recorded.
    #[must_use]
    pub fn avg_miss_latency_ms(&self) -> f64 {
        self.avg_miss_latency_us() / 1000.0
    }

    /// Get the uptime in seconds since the stats tracker was created.
    #[must_use]
    pub fn uptime_seconds(&self) -> u64 {
        self.start_time.elapsed().as_secs()
    }

    /// Get a snapshot of the current stats for serialization.
    ///
    /// # Example
    ///
    /// ```
    /// use rag_retrieval::cache::CacheStats;
    ///
    /// let stats = CacheStats::new();
    /// stats.record_hit(1000);
    /// stats.record_miss(2000);
    ///
    /// let snapshot = stats.snapshot();
    /// println!("Stats: {}", serde_json::to_string_pretty(&snapshot).unwrap());
    /// ```
    #[must_use]
    pub fn snapshot(&self) -> CacheStatsSnapshot {
        CacheStatsSnapshot {
            hits: self.hits(),
            misses: self.misses(),
            sets: self.sets(),
            invalidations: self.invalidations(),
            errors: self.errors(),
            total_requests: self.total_requests(),
            hit_rate: self.hit_rate(),
            miss_rate: self.miss_rate(),
            avg_hit_latency_us: self.avg_hit_latency_us(),
            avg_miss_latency_us: self.avg_miss_latency_us(),
            avg_hit_latency_ms: self.avg_hit_latency_ms(),
            avg_miss_latency_ms: self.avg_miss_latency_ms(),
            uptime_seconds: self.uptime_seconds(),
        }
    }

    /// Reset all statistics to zero.
    ///
    /// Note: This does not reset the start time, so uptime will continue
    /// from the original creation time.
    pub fn reset(&self) {
        self.hits.store(0, Ordering::Relaxed);
        self.misses.store(0, Ordering::Relaxed);
        self.sets.store(0, Ordering::Relaxed);
        self.invalidations.store(0, Ordering::Relaxed);
        self.errors.store(0, Ordering::Relaxed);
        self.total_hit_latency_us.store(0, Ordering::Relaxed);
        self.total_miss_latency_us.store(0, Ordering::Relaxed);
    }
}

/// A serializable snapshot of cache statistics.
///
/// This struct captures the current state of cache statistics at a point in time,
/// suitable for JSON serialization and API responses.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CacheStatsSnapshot {
    /// Number of cache hits.
    pub hits: u64,
    /// Number of cache misses.
    pub misses: u64,
    /// Number of cache set operations.
    pub sets: u64,
    /// Number of cache invalidations.
    pub invalidations: u64,
    /// Number of cache errors.
    pub errors: u64,
    /// Total number of requests (hits + misses).
    pub total_requests: u64,
    /// Hit rate as a ratio (0.0 to 1.0).
    pub hit_rate: f64,
    /// Miss rate as a ratio (0.0 to 1.0).
    pub miss_rate: f64,
    /// Average hit latency in microseconds.
    pub avg_hit_latency_us: f64,
    /// Average miss latency in microseconds.
    pub avg_miss_latency_us: f64,
    /// Average hit latency in milliseconds.
    pub avg_hit_latency_ms: f64,
    /// Average miss latency in milliseconds.
    pub avg_miss_latency_ms: f64,
    /// Uptime in seconds since stats tracker creation.
    pub uptime_seconds: u64,
}

impl Default for CacheStatsSnapshot {
    fn default() -> Self {
        Self {
            hits: 0,
            misses: 0,
            sets: 0,
            invalidations: 0,
            errors: 0,
            total_requests: 0,
            hit_rate: 0.0,
            miss_rate: 0.0,
            avg_hit_latency_us: 0.0,
            avg_miss_latency_us: 0.0,
            avg_hit_latency_ms: 0.0,
            avg_miss_latency_ms: 0.0,
            uptime_seconds: 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cache_stats_new() {
        let stats = CacheStats::new();
        assert_eq!(stats.hits(), 0);
        assert_eq!(stats.misses(), 0);
        assert_eq!(stats.sets(), 0);
        assert_eq!(stats.invalidations(), 0);
        assert_eq!(stats.errors(), 0);
    }

    #[test]
    fn test_cache_stats_tracking() {
        let stats = CacheStats::new();

        stats.record_hit(1000);
        stats.record_hit(2000);
        stats.record_miss(3000);
        stats.record_set();
        stats.record_set();
        stats.record_invalidation();
        stats.record_error();

        assert_eq!(stats.hits(), 2);
        assert_eq!(stats.misses(), 1);
        assert_eq!(stats.sets(), 2);
        assert_eq!(stats.invalidations(), 1);
        assert_eq!(stats.errors(), 1);
    }

    #[test]
    fn test_cache_stats_total_requests() {
        let stats = CacheStats::new();

        stats.record_hit(100);
        stats.record_hit(100);
        stats.record_miss(100);

        assert_eq!(stats.total_requests(), 3);
    }

    #[test]
    fn test_cache_stats_hit_rate() {
        let stats = CacheStats::new();

        // No requests: hit rate should be 0
        assert!((stats.hit_rate() - 0.0).abs() < f64::EPSILON);

        // 2 hits, 1 miss = 66.67% hit rate
        stats.record_hit(100);
        stats.record_hit(100);
        stats.record_miss(100);

        let hit_rate = stats.hit_rate();
        assert!((hit_rate - 0.6666666666666666).abs() < 0.0001);
    }

    #[test]
    fn test_cache_stats_miss_rate() {
        let stats = CacheStats::new();

        // No requests: miss rate should be 0
        assert!((stats.miss_rate() - 0.0).abs() < f64::EPSILON);

        // 1 hit, 3 misses = 75% miss rate
        stats.record_hit(100);
        stats.record_miss(100);
        stats.record_miss(100);
        stats.record_miss(100);

        let miss_rate = stats.miss_rate();
        assert!((miss_rate - 0.75).abs() < 0.0001);
    }

    #[test]
    fn test_cache_stats_avg_latency() {
        let stats = CacheStats::new();

        // No hits: avg should be 0
        assert!((stats.avg_hit_latency_us() - 0.0).abs() < f64::EPSILON);

        // Record hits with 1000us, 2000us, 3000us latencies
        stats.record_hit(1000);
        stats.record_hit(2000);
        stats.record_hit(3000);

        // Average should be 2000us
        let avg = stats.avg_hit_latency_us();
        assert!((avg - 2000.0).abs() < 0.001);

        // In ms: 2.0
        let avg_ms = stats.avg_hit_latency_ms();
        assert!((avg_ms - 2.0).abs() < 0.001);
    }

    #[test]
    fn test_cache_stats_avg_miss_latency() {
        let stats = CacheStats::new();

        // No misses: avg should be 0
        assert!((stats.avg_miss_latency_us() - 0.0).abs() < f64::EPSILON);

        // Record misses with 5000us, 10000us latencies
        stats.record_miss(5000);
        stats.record_miss(10000);

        // Average should be 7500us
        let avg = stats.avg_miss_latency_us();
        assert!((avg - 7500.0).abs() < 0.001);

        // In ms: 7.5
        let avg_ms = stats.avg_miss_latency_ms();
        assert!((avg_ms - 7.5).abs() < 0.001);
    }

    #[test]
    fn test_cache_stats_snapshot() {
        let stats = CacheStats::new();

        stats.record_hit(1000);
        stats.record_hit(2000);
        stats.record_miss(3000);
        stats.record_set();
        stats.record_invalidation();
        stats.record_error();

        let snapshot = stats.snapshot();

        assert_eq!(snapshot.hits, 2);
        assert_eq!(snapshot.misses, 1);
        assert_eq!(snapshot.sets, 1);
        assert_eq!(snapshot.invalidations, 1);
        assert_eq!(snapshot.errors, 1);
        assert_eq!(snapshot.total_requests, 3);
        assert!((snapshot.hit_rate - 0.6666666666666666).abs() < 0.0001);
        assert!((snapshot.miss_rate - 0.3333333333333333).abs() < 0.0001);
        assert!((snapshot.avg_hit_latency_us - 1500.0).abs() < 0.001);
        assert!((snapshot.avg_miss_latency_us - 3000.0).abs() < 0.001);
    }

    #[test]
    fn test_cache_stats_snapshot_serialization() {
        let snapshot = CacheStatsSnapshot {
            hits: 100,
            misses: 20,
            sets: 50,
            invalidations: 5,
            errors: 2,
            total_requests: 120,
            hit_rate: 0.8333,
            miss_rate: 0.1667,
            avg_hit_latency_us: 500.0,
            avg_miss_latency_us: 2000.0,
            avg_hit_latency_ms: 0.5,
            avg_miss_latency_ms: 2.0,
            uptime_seconds: 3600,
        };

        let json = serde_json::to_string(&snapshot).unwrap();
        let deserialized: CacheStatsSnapshot = serde_json::from_str(&json).unwrap();

        assert_eq!(snapshot, deserialized);
    }

    #[test]
    fn test_cache_stats_reset() {
        let stats = CacheStats::new();

        stats.record_hit(1000);
        stats.record_miss(2000);
        stats.record_set();
        stats.record_invalidation();
        stats.record_error();

        // Verify non-zero
        assert!(stats.hits() > 0);

        stats.reset();

        // All should be zero
        assert_eq!(stats.hits(), 0);
        assert_eq!(stats.misses(), 0);
        assert_eq!(stats.sets(), 0);
        assert_eq!(stats.invalidations(), 0);
        assert_eq!(stats.errors(), 0);
        assert!((stats.avg_hit_latency_us() - 0.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_cache_stats_thread_safe() {
        use std::sync::Arc;
        use std::thread;

        let stats = Arc::new(CacheStats::new());
        let mut handles = vec![];

        // Spawn 10 threads, each recording 100 hits
        for _ in 0..10 {
            let stats_clone = Arc::clone(&stats);
            handles.push(thread::spawn(move || {
                for _ in 0..100 {
                    stats_clone.record_hit(100);
                }
            }));
        }

        for handle in handles {
            handle.join().unwrap();
        }

        // Should have exactly 1000 hits
        assert_eq!(stats.hits(), 1000);
    }

    #[test]
    fn test_cache_stats_default() {
        let stats = CacheStats::default();
        assert_eq!(stats.hits(), 0);
        assert_eq!(stats.total_requests(), 0);
    }

    #[test]
    fn test_cache_stats_snapshot_default() {
        let snapshot = CacheStatsSnapshot::default();
        assert_eq!(snapshot.hits, 0);
        assert_eq!(snapshot.misses, 0);
        assert!((snapshot.hit_rate - 0.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_100_percent_hit_rate() {
        let stats = CacheStats::new();

        stats.record_hit(100);
        stats.record_hit(100);
        stats.record_hit(100);

        assert!((stats.hit_rate() - 1.0).abs() < f64::EPSILON);
        assert!((stats.miss_rate() - 0.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_100_percent_miss_rate() {
        let stats = CacheStats::new();

        stats.record_miss(100);
        stats.record_miss(100);
        stats.record_miss(100);

        assert!((stats.hit_rate() - 0.0).abs() < f64::EPSILON);
        assert!((stats.miss_rate() - 1.0).abs() < f64::EPSILON);
    }
}

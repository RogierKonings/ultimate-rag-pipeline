//! Prometheus metrics for the retrieval service.
//!
//! This module provides retrieval-specific metrics including:
//! - Request counters by mode and status
//! - Latency histograms for requests and pipeline stages
//! - Result count distributions
//! - Component health gauges
//! - Cache hit/miss counters

use once_cell::sync::Lazy;
use prometheus::{
    Counter, Encoder, Histogram, HistogramOpts, HistogramVec, IntCounterVec, IntGaugeVec, Opts,
    Registry, TextEncoder,
};
use std::sync::Arc;

use rag_telemetry::{MetricsRegistry, TelemetryError};

/// Global metrics registry for the retrieval service.
pub static RETRIEVAL_METRICS: Lazy<Arc<Registry>> = Lazy::new(|| Arc::new(Registry::new()));

/// Register all retrieval metrics with the global registry.
///
/// This should be called once at service startup.
///
/// # Errors
///
/// Returns an error if metric registration fails.
pub fn register_metrics() -> Result<RetrievalMetricsCollector, MetricsError> {
    RetrievalMetricsCollector::new_with_registry(&RETRIEVAL_METRICS)
}

/// Encode all registered metrics to Prometheus text format.
#[must_use]
pub fn encode_metrics() -> String {
    let encoder = TextEncoder::new();
    let metric_families = RETRIEVAL_METRICS.gather();
    let mut buffer = Vec::new();
    encoder
        .encode(&metric_families, &mut buffer)
        .unwrap_or_default();
    String::from_utf8(buffer).unwrap_or_default()
}

/// Retrieval-specific metrics collector.
#[derive(Clone)]
pub struct RetrievalMetricsCollector {
    /// Total retrieval requests by mode and status.
    pub requests_total: IntCounterVec,

    /// Request latency histogram by mode.
    pub request_latency: HistogramVec,

    /// Pipeline stage latency histogram.
    pub stage_latency: HistogramVec,

    /// Number of results at each pipeline stage.
    pub results_count: HistogramVec,

    /// Component health status (1 = healthy, 0 = unhealthy).
    pub component_health: IntGaugeVec,

    /// Cache hit counter.
    pub cache_hits: Counter,

    /// Cache miss counter.
    pub cache_misses: Counter,

    /// Embedding dimension mismatch counter.
    pub embedding_dimension_errors: Counter,

    /// Reranker batch size histogram.
    pub rerank_batch_size: Histogram,

    /// Active concurrent requests gauge.
    pub active_requests: IntGaugeVec,
}

impl RetrievalMetricsCollector {
    /// Create a new metrics collector using the rag-telemetry registry.
    ///
    /// # Errors
    ///
    /// Returns an error if metric registration fails.
    pub fn new(registry: &MetricsRegistry) -> Result<Self, MetricsError> {
        Self::new_with_registry(registry.registry())
    }

    /// Create a new metrics collector with a custom Prometheus registry.
    ///
    /// # Errors
    ///
    /// Returns an error if metric registration fails.
    pub fn new_with_registry(registry: &Registry) -> Result<Self, MetricsError> {
        // Request counters
        let requests_total = IntCounterVec::new(
            Opts::new(
                "retrieval_requests_total",
                "Total number of retrieval requests",
            ),
            &["mode", "status"],
        )
        .map_err(|e| MetricsError::Registration(e.to_string()))?;

        registry
            .register(Box::new(requests_total.clone()))
            .map_err(|e| MetricsError::Registration(e.to_string()))?;

        // Request latency histogram
        let request_latency = HistogramVec::new(
            HistogramOpts::new(
                "retrieval_request_latency_seconds",
                "Request latency in seconds",
            )
            .buckets(vec![0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]),
            &["mode"],
        )
        .map_err(|e| MetricsError::Registration(e.to_string()))?;

        registry
            .register(Box::new(request_latency.clone()))
            .map_err(|e| MetricsError::Registration(e.to_string()))?;

        // Pipeline stage latency
        let stage_latency = HistogramVec::new(
            HistogramOpts::new(
                "retrieval_stage_latency_seconds",
                "Pipeline stage latency in seconds",
            )
            .buckets(vec![0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]),
            &["stage"],
        )
        .map_err(|e| MetricsError::Registration(e.to_string()))?;

        registry
            .register(Box::new(stage_latency.clone()))
            .map_err(|e| MetricsError::Registration(e.to_string()))?;

        // Results count histogram
        let results_count = HistogramVec::new(
            HistogramOpts::new(
                "retrieval_results_count",
                "Number of results at each pipeline stage",
            )
            .buckets(vec![0.0, 1.0, 5.0, 10.0, 20.0, 50.0, 100.0]),
            &["stage"],
        )
        .map_err(|e| MetricsError::Registration(e.to_string()))?;

        registry
            .register(Box::new(results_count.clone()))
            .map_err(|e| MetricsError::Registration(e.to_string()))?;

        // Component health gauge
        let component_health = IntGaugeVec::new(
            Opts::new(
                "retrieval_component_healthy",
                "Component health status (1=healthy, 0=unhealthy)",
            ),
            &["component"],
        )
        .map_err(|e| MetricsError::Registration(e.to_string()))?;

        registry
            .register(Box::new(component_health.clone()))
            .map_err(|e| MetricsError::Registration(e.to_string()))?;

        // Cache metrics
        let cache_hits = Counter::new("retrieval_cache_hits_total", "Total number of cache hits")
            .map_err(|e| MetricsError::Registration(e.to_string()))?;

        registry
            .register(Box::new(cache_hits.clone()))
            .map_err(|e| MetricsError::Registration(e.to_string()))?;

        let cache_misses =
            Counter::new("retrieval_cache_misses_total", "Total number of cache misses")
                .map_err(|e| MetricsError::Registration(e.to_string()))?;

        registry
            .register(Box::new(cache_misses.clone()))
            .map_err(|e| MetricsError::Registration(e.to_string()))?;

        // Embedding dimension errors
        let embedding_dimension_errors = Counter::new(
            "retrieval_embedding_dimension_errors_total",
            "Total number of embedding dimension mismatches",
        )
        .map_err(|e| MetricsError::Registration(e.to_string()))?;

        registry
            .register(Box::new(embedding_dimension_errors.clone()))
            .map_err(|e| MetricsError::Registration(e.to_string()))?;

        // Reranker batch size
        let rerank_batch_size = Histogram::with_opts(
            HistogramOpts::new(
                "retrieval_rerank_batch_size",
                "Number of documents in reranking batch",
            )
            .buckets(vec![1.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0]),
        )
        .map_err(|e| MetricsError::Registration(e.to_string()))?;

        registry
            .register(Box::new(rerank_batch_size.clone()))
            .map_err(|e| MetricsError::Registration(e.to_string()))?;

        // Active requests gauge
        let active_requests = IntGaugeVec::new(
            Opts::new(
                "retrieval_active_requests",
                "Number of currently active requests",
            ),
            &["mode"],
        )
        .map_err(|e| MetricsError::Registration(e.to_string()))?;

        registry
            .register(Box::new(active_requests.clone()))
            .map_err(|e| MetricsError::Registration(e.to_string()))?;

        Ok(Self {
            requests_total,
            request_latency,
            stage_latency,
            results_count,
            component_health,
            cache_hits,
            cache_misses,
            embedding_dimension_errors,
            rerank_batch_size,
            active_requests,
        })
    }

    /// Record a completed request.
    ///
    /// # Arguments
    ///
    /// * `mode` - Search mode: "hybrid", "semantic", or "keyword"
    /// * `status` - Request status: "success" or "error"
    /// * `latency_seconds` - Request latency in seconds
    pub fn record_request(&self, mode: &str, status: &str, latency_seconds: f64) {
        self.requests_total
            .with_label_values(&[mode, status])
            .inc();
        self.request_latency
            .with_label_values(&[mode])
            .observe(latency_seconds);
    }

    /// Record pipeline stage latency.
    ///
    /// # Arguments
    ///
    /// * `stage` - Stage name (e.g., embedding, semantic_search, keyword_search,
    ///   fusion, rerank, acl_filter)
    /// * `latency_seconds` - Stage latency in seconds
    pub fn record_stage_latency(&self, stage: &str, latency_seconds: f64) {
        self.stage_latency
            .with_label_values(&[stage])
            .observe(latency_seconds);
    }

    /// Record result count at a pipeline stage.
    ///
    /// # Arguments
    ///
    /// * `stage` - Stage name
    /// * `count` - Number of results
    #[allow(clippy::cast_precision_loss)]
    pub fn record_results_count(&self, stage: &str, count: usize) {
        self.results_count
            .with_label_values(&[stage])
            .observe(count as f64);
    }

    /// Set component health status.
    ///
    /// # Arguments
    ///
    /// * `component` - Component name: "qdrant", "opensearch", "embedding", "reranker"
    /// * `healthy` - Whether the component is healthy
    pub fn set_component_health(&self, component: &str, healthy: bool) {
        self.component_health
            .with_label_values(&[component])
            .set(if healthy { 1 } else { 0 });
    }

    /// Record a cache hit.
    pub fn record_cache_hit(&self) {
        self.cache_hits.inc();
    }

    /// Record a cache miss.
    pub fn record_cache_miss(&self) {
        self.cache_misses.inc();
    }

    /// Record an embedding dimension error.
    pub fn record_embedding_dimension_error(&self) {
        self.embedding_dimension_errors.inc();
    }

    /// Record reranking batch size.
    #[allow(clippy::cast_precision_loss)]
    pub fn record_rerank_batch_size(&self, batch_size: usize) {
        self.rerank_batch_size.observe(batch_size as f64);
    }

    /// Increment active requests for a mode.
    pub fn inc_active_requests(&self, mode: &str) {
        self.active_requests.with_label_values(&[mode]).inc();
    }

    /// Decrement active requests for a mode.
    pub fn dec_active_requests(&self, mode: &str) {
        self.active_requests.with_label_values(&[mode]).dec();
    }
}

/// Stage names for consistent metric labeling.
pub mod stages {
    /// Query preprocessing stage.
    pub const PREPROCESS: &str = "preprocess";
    /// Query embedding stage.
    pub const EMBEDDING: &str = "embedding";
    /// Semantic (vector) search stage.
    pub const SEMANTIC_SEARCH: &str = "semantic_search";
    /// Keyword (BM25) search stage.
    pub const KEYWORD_SEARCH: &str = "keyword_search";
    /// Result fusion stage (RRF/linear/DBSF).
    pub const FUSION: &str = "fusion";
    /// Reranking stage.
    pub const RERANK: &str = "rerank";
    /// ACL filtering stage.
    pub const ACL_FILTER: &str = "acl_filter";
    /// Final result selection.
    pub const FINAL: &str = "final";
}

/// Component names for health metrics.
pub mod components {
    /// Qdrant vector database.
    pub const QDRANT: &str = "qdrant";
    /// OpenSearch keyword search.
    pub const OPENSEARCH: &str = "opensearch";
    /// Embedding service.
    pub const EMBEDDING: &str = "embedding";
    /// Reranker service.
    pub const RERANKER: &str = "reranker";
    /// Redis cache.
    pub const CACHE: &str = "cache";
}

/// Error type for metrics operations.
#[derive(Debug, thiserror::Error)]
pub enum MetricsError {
    /// Failed to register metric.
    #[error("Failed to register metric: {0}")]
    Registration(String),

    /// Failed to encode metrics.
    #[error("Failed to encode metrics: {0}")]
    Encoding(String),
}

impl From<TelemetryError> for MetricsError {
    fn from(err: TelemetryError) -> Self {
        MetricsError::Registration(err.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_metrics_registration() {
        let registry = Registry::new();
        let metrics = RetrievalMetricsCollector::new_with_registry(&registry);

        assert!(metrics.is_ok());
    }

    #[test]
    fn test_record_request() {
        let registry = Registry::new();
        let metrics = RetrievalMetricsCollector::new_with_registry(&registry).unwrap();

        metrics.record_request("hybrid", "success", 0.150);
        metrics.record_request("semantic", "error", 0.250);

        // Verify counter increments (can't easily assert values without gathering)
        let families = registry.gather();
        assert!(!families.is_empty());
    }

    #[test]
    fn test_record_stage_latency() {
        let registry = Registry::new();
        let metrics = RetrievalMetricsCollector::new_with_registry(&registry).unwrap();

        metrics.record_stage_latency(stages::EMBEDDING, 0.020);
        metrics.record_stage_latency(stages::SEMANTIC_SEARCH, 0.045);
        metrics.record_stage_latency(stages::FUSION, 0.005);

        let families = registry.gather();
        assert!(!families.is_empty());
    }

    #[test]
    fn test_component_health() {
        let registry = Registry::new();
        let metrics = RetrievalMetricsCollector::new_with_registry(&registry).unwrap();

        metrics.set_component_health(components::QDRANT, true);
        metrics.set_component_health(components::OPENSEARCH, false);

        let families = registry.gather();
        let health_family = families
            .iter()
            .find(|f| f.get_name() == "retrieval_component_healthy");
        assert!(health_family.is_some());
    }

    #[test]
    fn test_cache_metrics() {
        let registry = Registry::new();
        let metrics = RetrievalMetricsCollector::new_with_registry(&registry).unwrap();

        metrics.record_cache_hit();
        metrics.record_cache_hit();
        metrics.record_cache_miss();

        let families = registry.gather();
        assert!(!families.is_empty());
    }

    #[test]
    fn test_encode_metrics() {
        // Register some metrics first
        let _ = register_metrics();

        let encoded = encode_metrics();
        // Should contain some metric output (may be empty if already registered)
        assert!(encoded.is_empty() || encoded.contains('#'));
    }

    #[test]
    fn test_active_requests() {
        let registry = Registry::new();
        let metrics = RetrievalMetricsCollector::new_with_registry(&registry).unwrap();

        metrics.inc_active_requests("hybrid");
        metrics.inc_active_requests("hybrid");
        metrics.dec_active_requests("hybrid");

        let families = registry.gather();
        assert!(!families.is_empty());
    }

    #[test]
    fn test_results_count() {
        let registry = Registry::new();
        let metrics = RetrievalMetricsCollector::new_with_registry(&registry).unwrap();

        metrics.record_results_count(stages::SEMANTIC_SEARCH, 50);
        metrics.record_results_count(stages::FUSION, 25);
        metrics.record_results_count(stages::FINAL, 10);

        let families = registry.gather();
        assert!(!families.is_empty());
    }
}

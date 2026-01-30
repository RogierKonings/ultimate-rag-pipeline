//! Prometheus metrics for the gateway.

use once_cell::sync::Lazy;
use prometheus::{Counter, CounterVec, GaugeVec, HistogramOpts, HistogramVec, Opts, Registry};

/// Global metrics registry.
pub static REGISTRY: Lazy<Registry> = Lazy::new(Registry::new);

/// Request counter.
pub static REQUEST_TOTAL: Lazy<CounterVec> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_requests_total", "Total requests")
        .namespace("rag")
        .subsystem("gateway");
    let counter = CounterVec::new(opts, &["service", "endpoint", "status"]).unwrap();
    REGISTRY.register(Box::new(counter.clone())).unwrap();
    counter
});

/// Request latency histogram.
pub static REQUEST_LATENCY: Lazy<HistogramVec> = Lazy::new(|| {
    let opts = HistogramOpts::new("llm_gateway_request_latency_seconds", "Request latency")
        .namespace("rag")
        .subsystem("gateway")
        .buckets(vec![0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]);
    let histogram = HistogramVec::new(opts, &["service", "endpoint"]).unwrap();
    REGISTRY.register(Box::new(histogram.clone())).unwrap();
    histogram
});

/// Active requests gauge.
pub static ACTIVE_REQUESTS: Lazy<GaugeVec> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_active_requests", "Active requests")
        .namespace("rag")
        .subsystem("gateway");
    let gauge = GaugeVec::new(opts, &["service"]).unwrap();
    REGISTRY.register(Box::new(gauge.clone())).unwrap();
    gauge
});

/// Tokens processed counter.
pub static TOKENS_PROCESSED: Lazy<CounterVec> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_tokens_total", "Tokens processed")
        .namespace("rag")
        .subsystem("gateway");
    let counter = CounterVec::new(opts, &["service", "type"]).unwrap();
    REGISTRY.register(Box::new(counter.clone())).unwrap();
    counter
});

/// Embeddings generated counter.
pub static EMBEDDINGS_GENERATED: Lazy<Counter> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_embeddings_total", "Embeddings generated")
        .namespace("rag")
        .subsystem("gateway");
    let counter = Counter::with_opts(opts).unwrap();
    REGISTRY.register(Box::new(counter.clone())).unwrap();
    counter
});

/// Rate limit hits counter.
pub static RATE_LIMIT_HITS: Lazy<CounterVec> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_rate_limit_hits_total", "Rate limit hits")
        .namespace("rag")
        .subsystem("gateway");
    let counter = CounterVec::new(opts, &["tenant_id"]).unwrap();
    REGISTRY.register(Box::new(counter.clone())).unwrap();
    counter
});

/// Auth failures counter.
pub static AUTH_FAILURES: Lazy<CounterVec> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_auth_failures_total", "Authentication failures")
        .namespace("rag")
        .subsystem("gateway");
    let counter = CounterVec::new(opts, &["reason"]).unwrap();
    REGISTRY.register(Box::new(counter.clone())).unwrap();
    counter
});

/// Model loaded gauge.
pub static MODEL_LOADED: Lazy<GaugeVec> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_model_loaded", "Model loaded status")
        .namespace("rag")
        .subsystem("gateway");
    let gauge = GaugeVec::new(opts, &["model_type", "model_name"]).unwrap();
    REGISTRY.register(Box::new(gauge.clone())).unwrap();
    gauge
});

/// Get metrics as text for Prometheus scraping.
pub fn gather_metrics() -> String {
    use prometheus::Encoder;
    let encoder = prometheus::TextEncoder::new();
    let metric_families = REGISTRY.gather();
    let mut buffer = Vec::new();
    encoder.encode(&metric_families, &mut buffer).unwrap();
    String::from_utf8(buffer).unwrap()
}

/// Helper to record a request.
pub fn record_request(service: &str, endpoint: &str, status: &str, latency_secs: f64) {
    REQUEST_TOTAL
        .with_label_values(&[service, endpoint, status])
        .inc();
    REQUEST_LATENCY
        .with_label_values(&[service, endpoint])
        .observe(latency_secs);
}

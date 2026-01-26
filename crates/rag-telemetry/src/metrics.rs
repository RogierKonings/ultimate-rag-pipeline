//! Prometheus metrics registry and helpers.

use prometheus::{
    Counter, CounterVec, Histogram, HistogramOpts, HistogramVec, IntCounter, IntCounterVec,
    IntGauge, IntGaugeVec, Opts, Registry,
};
use std::sync::Arc;

use crate::{Result, TelemetryError};

/// Metrics registry wrapper.
#[derive(Debug, Clone)]
pub struct MetricsRegistry {
    registry: Arc<Registry>,
}

impl MetricsRegistry {
    /// Create a new metrics registry.
    #[must_use]
    pub fn new() -> Self {
        Self {
            registry: Arc::new(Registry::new()),
        }
    }

    /// Get the underlying Prometheus registry.
    #[must_use]
    pub fn registry(&self) -> &Registry {
        &self.registry
    }

    /// Register a counter.
    ///
    /// # Errors
    ///
    /// Returns an error if registration fails.
    pub fn register_counter(&self, name: &str, help: &str) -> Result<IntCounter> {
        let counter = IntCounter::new(name, help)
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        self.registry
            .register(Box::new(counter.clone()))
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        Ok(counter)
    }

    /// Register a counter with labels.
    ///
    /// # Errors
    ///
    /// Returns an error if registration fails.
    pub fn register_counter_vec(
        &self,
        name: &str,
        help: &str,
        labels: &[&str],
    ) -> Result<IntCounterVec> {
        let counter = IntCounterVec::new(Opts::new(name, help), labels)
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        self.registry
            .register(Box::new(counter.clone()))
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        Ok(counter)
    }

    /// Register a float counter.
    ///
    /// # Errors
    ///
    /// Returns an error if registration fails.
    pub fn register_float_counter(&self, name: &str, help: &str) -> Result<Counter> {
        let counter = Counter::new(name, help)
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        self.registry
            .register(Box::new(counter.clone()))
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        Ok(counter)
    }

    /// Register a float counter with labels.
    ///
    /// # Errors
    ///
    /// Returns an error if registration fails.
    pub fn register_float_counter_vec(
        &self,
        name: &str,
        help: &str,
        labels: &[&str],
    ) -> Result<CounterVec> {
        let counter = CounterVec::new(Opts::new(name, help), labels)
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        self.registry
            .register(Box::new(counter.clone()))
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        Ok(counter)
    }

    /// Register a gauge.
    ///
    /// # Errors
    ///
    /// Returns an error if registration fails.
    pub fn register_gauge(&self, name: &str, help: &str) -> Result<IntGauge> {
        let gauge = IntGauge::new(name, help)
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        self.registry
            .register(Box::new(gauge.clone()))
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        Ok(gauge)
    }

    /// Register a gauge with labels.
    ///
    /// # Errors
    ///
    /// Returns an error if registration fails.
    pub fn register_gauge_vec(
        &self,
        name: &str,
        help: &str,
        labels: &[&str],
    ) -> Result<IntGaugeVec> {
        let gauge = IntGaugeVec::new(Opts::new(name, help), labels)
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        self.registry
            .register(Box::new(gauge.clone()))
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        Ok(gauge)
    }

    /// Register a histogram with default buckets.
    ///
    /// # Errors
    ///
    /// Returns an error if registration fails.
    pub fn register_histogram(&self, name: &str, help: &str) -> Result<Histogram> {
        let histogram = Histogram::with_opts(HistogramOpts::new(name, help))
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        self.registry
            .register(Box::new(histogram.clone()))
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        Ok(histogram)
    }

    /// Register a histogram with custom buckets.
    ///
    /// # Errors
    ///
    /// Returns an error if registration fails.
    pub fn register_histogram_with_buckets(
        &self,
        name: &str,
        help: &str,
        buckets: Vec<f64>,
    ) -> Result<Histogram> {
        let histogram = Histogram::with_opts(HistogramOpts::new(name, help).buckets(buckets))
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        self.registry
            .register(Box::new(histogram.clone()))
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        Ok(histogram)
    }

    /// Register a histogram with labels.
    ///
    /// # Errors
    ///
    /// Returns an error if registration fails.
    pub fn register_histogram_vec(
        &self,
        name: &str,
        help: &str,
        labels: &[&str],
    ) -> Result<HistogramVec> {
        let histogram = HistogramVec::new(HistogramOpts::new(name, help), labels)
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        self.registry
            .register(Box::new(histogram.clone()))
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        Ok(histogram)
    }

    /// Register a histogram with labels and custom buckets.
    ///
    /// # Errors
    ///
    /// Returns an error if registration fails.
    pub fn register_histogram_vec_with_buckets(
        &self,
        name: &str,
        help: &str,
        labels: &[&str],
        buckets: Vec<f64>,
    ) -> Result<HistogramVec> {
        let histogram =
            HistogramVec::new(HistogramOpts::new(name, help).buckets(buckets), labels)
                .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        self.registry
            .register(Box::new(histogram.clone()))
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        Ok(histogram)
    }

    /// Encode metrics to Prometheus text format.
    ///
    /// # Errors
    ///
    /// Returns an error if encoding fails.
    pub fn encode(&self) -> Result<String> {
        use prometheus::Encoder;
        let encoder = prometheus::TextEncoder::new();
        let metric_families = self.registry.gather();
        let mut buffer = Vec::new();
        encoder
            .encode(&metric_families, &mut buffer)
            .map_err(|e| TelemetryError::Metrics(e.to_string()))?;
        String::from_utf8(buffer).map_err(|e| TelemetryError::Metrics(e.to_string()))
    }
}

impl Default for MetricsRegistry {
    fn default() -> Self {
        Self::new()
    }
}

/// Common metrics for RAG services.
#[derive(Clone)]
pub struct Metrics {
    /// Request counter by endpoint and status.
    pub requests_total: IntCounterVec,
    /// Request latency histogram by endpoint.
    pub request_duration_seconds: HistogramVec,
    /// Active requests gauge.
    pub requests_in_flight: IntGauge,
    /// Error counter by type.
    pub errors_total: IntCounterVec,
}

impl Metrics {
    /// Create common service metrics.
    ///
    /// # Errors
    ///
    /// Returns an error if metric registration fails.
    pub fn new(registry: &MetricsRegistry, prefix: &str) -> Result<Self> {
        let requests_total = registry.register_counter_vec(
            &format!("{prefix}_requests_total"),
            "Total number of requests",
            &["endpoint", "method", "status"],
        )?;

        let request_duration_seconds = registry.register_histogram_vec_with_buckets(
            &format!("{prefix}_request_duration_seconds"),
            "Request duration in seconds",
            &["endpoint", "method"],
            vec![0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
        )?;

        let requests_in_flight = registry.register_gauge(
            &format!("{prefix}_requests_in_flight"),
            "Number of requests currently being processed",
        )?;

        let errors_total = registry.register_counter_vec(
            &format!("{prefix}_errors_total"),
            "Total number of errors",
            &["type"],
        )?;

        Ok(Self {
            requests_total,
            request_duration_seconds,
            requests_in_flight,
            errors_total,
        })
    }

    /// Record a request.
    pub fn record_request(&self, endpoint: &str, method: &str, status: u16, duration_secs: f64) {
        self.requests_total
            .with_label_values(&[endpoint, method, &status.to_string()])
            .inc();
        self.request_duration_seconds
            .with_label_values(&[endpoint, method])
            .observe(duration_secs);
    }

    /// Increment in-flight requests.
    pub fn inc_in_flight(&self) {
        self.requests_in_flight.inc();
    }

    /// Decrement in-flight requests.
    pub fn dec_in_flight(&self) {
        self.requests_in_flight.dec();
    }

    /// Record an error.
    pub fn record_error(&self, error_type: &str) {
        self.errors_total.with_label_values(&[error_type]).inc();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_metrics_registry() {
        let registry = MetricsRegistry::new();

        let counter = registry.register_counter("test_counter", "A test counter").unwrap();
        counter.inc();
        assert_eq!(counter.get(), 1);

        let gauge = registry.register_gauge("test_gauge", "A test gauge").unwrap();
        gauge.set(42);
        assert_eq!(gauge.get(), 42);

        let histogram = registry.register_histogram("test_histogram", "A test histogram").unwrap();
        histogram.observe(0.5);

        let encoded = registry.encode().unwrap();
        assert!(encoded.contains("test_counter"));
        assert!(encoded.contains("test_gauge"));
        assert!(encoded.contains("test_histogram"));
    }

    #[test]
    fn test_service_metrics() {
        let registry = MetricsRegistry::new();
        let metrics = Metrics::new(&registry, "test_service").unwrap();

        metrics.inc_in_flight();
        metrics.record_request("/api/search", "POST", 200, 0.123);
        metrics.dec_in_flight();
        metrics.record_error("timeout");

        let encoded = registry.encode().unwrap();
        assert!(encoded.contains("test_service_requests_total"));
        assert!(encoded.contains("test_service_request_duration_seconds"));
    }
}

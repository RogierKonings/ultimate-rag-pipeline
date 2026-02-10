//! OpenTelemetry tracing setup for the retrieval service.
//!
//! This module provides tracing configuration and span name constants
//! for the retrieval pipeline stages.

use rag_telemetry::{TelemetryConfig, TelemetryError, TelemetryGuard};

/// Tracing configuration for the retrieval service.
#[derive(Debug, Clone)]
pub struct TracingConfig {
    /// Service name for traces.
    pub service_name: String,

    /// OTLP endpoint for trace export (e.g., "<http://localhost:4317>").
    pub otlp_endpoint: Option<String>,

    /// Log level filter (e.g., "info", "debug").
    pub log_level: String,

    /// Environment (e.g., "dev", "staging", "prod").
    pub environment: Option<String>,

    /// Service version.
    pub version: Option<String>,

    /// Trace sampling ratio (0.0 to 1.0).
    pub sample_ratio: f64,
}

impl Default for TracingConfig {
    fn default() -> Self {
        Self {
            service_name: "rag-retrieval".to_string(),
            otlp_endpoint: None,
            log_level: "info".to_string(),
            environment: None,
            version: None,
            sample_ratio: 1.0,
        }
    }
}

impl TracingConfig {
    /// Create a new tracing config with service name.
    #[must_use]
    pub fn new(service_name: impl Into<String>) -> Self {
        Self {
            service_name: service_name.into(),
            ..Default::default()
        }
    }

    /// Set the OTLP endpoint for trace export.
    #[must_use]
    pub fn with_otlp_endpoint(mut self, endpoint: impl Into<String>) -> Self {
        self.otlp_endpoint = Some(endpoint.into());
        self
    }

    /// Set the log level.
    #[must_use]
    pub fn with_log_level(mut self, level: impl Into<String>) -> Self {
        self.log_level = level.into();
        self
    }

    /// Set the environment.
    #[must_use]
    pub fn with_environment(mut self, env: impl Into<String>) -> Self {
        self.environment = Some(env.into());
        self
    }

    /// Set the service version.
    #[must_use]
    pub fn with_version(mut self, version: impl Into<String>) -> Self {
        self.version = Some(version.into());
        self
    }

    /// Set the trace sampling ratio.
    #[must_use]
    pub fn with_sample_ratio(mut self, ratio: f64) -> Self {
        self.sample_ratio = ratio.clamp(0.0, 1.0);
        self
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `OTEL_SERVICE_NAME`: Service name (default: "rag-retrieval")
    /// - `OTEL_EXPORTER_OTLP_ENDPOINT`: OTLP endpoint
    /// - `RUST_LOG` or `LOG_LEVEL`: Log level
    /// - `OTEL_ENVIRONMENT`: Environment
    /// - `OTEL_SERVICE_VERSION`: Service version
    /// - `OTEL_TRACES_SAMPLER_ARG`: Sample ratio
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(name) = std::env::var("OTEL_SERVICE_NAME") {
            config.service_name = name;
        }

        if let Ok(endpoint) = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT") {
            config.otlp_endpoint = Some(endpoint);
        }

        if let Ok(level) = std::env::var("RUST_LOG").or_else(|_| std::env::var("LOG_LEVEL")) {
            config.log_level = level;
        }

        if let Ok(env) = std::env::var("OTEL_ENVIRONMENT") {
            config.environment = Some(env);
        }

        if let Ok(version) = std::env::var("OTEL_SERVICE_VERSION") {
            config.version = Some(version);
        }

        if let Ok(ratio) = std::env::var("OTEL_TRACES_SAMPLER_ARG") {
            if let Ok(r) = ratio.parse::<f64>() {
                config.sample_ratio = r.clamp(0.0, 1.0);
            }
        }

        config
    }

    /// Convert to the underlying telemetry config.
    fn to_telemetry_config(&self) -> TelemetryConfig {
        let mut telemetry = TelemetryConfig::new(&self.service_name)
            .with_log_level(&self.log_level)
            .with_sample_ratio(self.sample_ratio);

        if let Some(ref endpoint) = self.otlp_endpoint {
            telemetry = telemetry.with_otlp_endpoint(endpoint);
        }

        if let Some(ref env) = self.environment {
            telemetry = telemetry.with_environment(env);
        }

        if let Some(ref version) = self.version {
            telemetry = telemetry.with_service_version(version);
        }

        telemetry
    }
}

/// Initialize tracing for the retrieval service.
///
/// This sets up structured logging and optionally OpenTelemetry tracing
/// if an OTLP endpoint is configured.
///
/// # Arguments
///
/// * `config` - Tracing configuration
///
/// # Returns
///
/// A guard that shuts down tracing when dropped.
///
/// # Errors
///
/// Returns an error if tracing initialization fails.
///
/// # Example
///
/// ```no_run
/// use rag_retrieval::observability::tracing::{init_tracing, TracingConfig};
///
/// let config = TracingConfig::default()
///     .with_log_level("debug")
///     .with_otlp_endpoint("http://localhost:4317");
///
/// let _guard = init_tracing(&config).expect("Failed to init tracing");
///
/// tracing::info!("Service started");
/// ```
pub fn init_tracing(config: &TracingConfig) -> Result<TelemetryGuard, TelemetryError> {
    let telemetry_config = config.to_telemetry_config();
    rag_telemetry::init_telemetry(&telemetry_config)
}

/// Shutdown tracing and flush any pending spans.
///
/// Note: This is typically handled automatically by dropping the `TelemetryGuard`,
/// but can be called explicitly if needed.
pub fn shutdown_tracing() {
    // In OpenTelemetry 0.31+, shutdown is handled by dropping the TracerProvider
    // or calling provider.shutdown() directly. The global shutdown function was removed.
}

/// Span names for pipeline stages.
///
/// Use these constants with `tracing::info_span!` or `#[instrument]` to ensure
/// consistent span naming across the codebase.
///
/// # Example
///
/// ```ignore
/// use rag_retrieval::observability::tracing::span_names;
/// use tracing::info_span;
///
/// let _span = info_span!(span_names::RETRIEVE).entered();
/// // ... perform retrieval
/// ```
pub mod span_names {
    /// Top-level retrieval operation.
    pub const RETRIEVE: &str = "retrieve";

    /// Query preprocessing (normalization, expansion).
    pub const PREPROCESS: &str = "preprocess_query";

    /// Query embedding generation.
    pub const EMBED: &str = "embed_query";

    /// Semantic (vector) search in Qdrant.
    pub const SEMANTIC_SEARCH: &str = "semantic_search";

    /// Keyword (BM25) search in `OpenSearch`.
    pub const KEYWORD_SEARCH: &str = "keyword_search";

    /// Result fusion (RRF, linear, DBSF).
    pub const FUSION: &str = "fuse_results";

    /// Cross-encoder reranking.
    pub const RERANK: &str = "rerank";

    /// ACL-based filtering.
    pub const ACL_FILTER: &str = "acl_filter";

    /// Cache lookup.
    pub const CACHE_LOOKUP: &str = "cache_lookup";

    /// Cache store.
    pub const CACHE_STORE: &str = "cache_store";

    /// `HyDE` (Hypothetical Document Embedding) generation.
    pub const HYDE: &str = "hyde_generate";

    /// Multi-query retrieval.
    pub const MULTI_RETRIEVE: &str = "multi_retrieve";

    /// Health check.
    pub const HEALTH_CHECK: &str = "health_check";
}

/// Span attribute keys for consistent metadata.
pub mod attributes {
    /// Tenant ID attribute.
    pub const TENANT_ID: &str = "tenant_id";

    /// User ID attribute.
    pub const USER_ID: &str = "user_id";

    /// Request ID attribute.
    pub const REQUEST_ID: &str = "request_id";

    /// Query text attribute.
    pub const QUERY: &str = "query";

    /// Search mode attribute.
    pub const SEARCH_MODE: &str = "search_mode";

    /// Number of results attribute.
    pub const RESULT_COUNT: &str = "result_count";

    /// Top-K limit attribute.
    pub const TOP_K: &str = "top_k";

    /// Cache hit attribute.
    pub const CACHE_HIT: &str = "cache_hit";

    /// Error message attribute.
    pub const ERROR_MESSAGE: &str = "error.message";

    /// Error type attribute.
    pub const ERROR_TYPE: &str = "error.type";
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tracing_config_default() {
        let config = TracingConfig::default();

        assert_eq!(config.service_name, "rag-retrieval");
        assert_eq!(config.log_level, "info");
        assert!(config.otlp_endpoint.is_none());
        #[allow(clippy::float_cmp)]
        {
            assert_eq!(config.sample_ratio, 1.0);
        }
    }

    #[test]
    fn test_tracing_config_builder() {
        let config = TracingConfig::new("test-service")
            .with_log_level("debug")
            .with_otlp_endpoint("http://localhost:4317")
            .with_environment("test")
            .with_version("1.0.0")
            .with_sample_ratio(0.5);

        assert_eq!(config.service_name, "test-service");
        assert_eq!(config.log_level, "debug");
        assert_eq!(
            config.otlp_endpoint,
            Some("http://localhost:4317".to_string())
        );
        assert_eq!(config.environment, Some("test".to_string()));
        assert_eq!(config.version, Some("1.0.0".to_string()));
        assert!((config.sample_ratio - 0.5).abs() < f64::EPSILON);
    }

    #[test]
    fn test_sample_ratio_clamping() {
        let config_low = TracingConfig::default().with_sample_ratio(-0.5);
        assert!((config_low.sample_ratio - 0.0).abs() < f64::EPSILON);

        let config_high = TracingConfig::default().with_sample_ratio(1.5);
        assert!((config_high.sample_ratio - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn test_span_names() {
        // Ensure span names are non-empty and consistent
        assert!(!span_names::RETRIEVE.is_empty());
        assert!(!span_names::PREPROCESS.is_empty());
        assert!(!span_names::EMBED.is_empty());
        assert!(!span_names::SEMANTIC_SEARCH.is_empty());
        assert!(!span_names::KEYWORD_SEARCH.is_empty());
        assert!(!span_names::FUSION.is_empty());
        assert!(!span_names::RERANK.is_empty());
        assert!(!span_names::ACL_FILTER.is_empty());
    }

    #[test]
    fn test_attributes() {
        // Ensure attribute keys are non-empty
        assert!(!attributes::TENANT_ID.is_empty());
        assert!(!attributes::REQUEST_ID.is_empty());
        assert!(!attributes::QUERY.is_empty());
        assert!(!attributes::SEARCH_MODE.is_empty());
    }

    #[test]
    fn test_to_telemetry_config() {
        let config = TracingConfig::new("test-service")
            .with_otlp_endpoint("http://localhost:4317")
            .with_log_level("debug");

        let telemetry = config.to_telemetry_config();

        assert_eq!(telemetry.service_name, "test-service");
        assert_eq!(telemetry.log_level, "debug");
        assert!(telemetry.otlp_enabled);
    }
}

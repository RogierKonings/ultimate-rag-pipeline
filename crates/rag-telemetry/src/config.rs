//! Telemetry configuration.

use serde::{Deserialize, Serialize};

/// Log output format.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum LogFormat {
    /// Human-readable format.
    #[default]
    Pretty,
    /// JSON format for log aggregation.
    Json,
    /// Compact single-line format.
    Compact,
}

/// Telemetry configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TelemetryConfig {
    /// Service name for tracing.
    pub service_name: String,

    /// Service version.
    pub service_version: Option<String>,

    /// Environment (dev, staging, prod).
    pub environment: Option<String>,

    /// Log level filter (e.g., "info", "debug", "warn,my_crate=trace").
    pub log_level: String,

    /// Log output format.
    #[serde(default)]
    pub log_format: LogFormat,

    /// OTLP endpoint for traces (e.g., "http://localhost:4317").
    pub otlp_endpoint: Option<String>,

    /// Whether to enable OTLP tracing.
    #[serde(default)]
    pub otlp_enabled: bool,

    /// Prometheus metrics enabled.
    #[serde(default = "default_true")]
    pub metrics_enabled: bool,

    /// Sampling ratio for traces (0.0 to 1.0).
    #[serde(default = "default_sample_ratio")]
    pub trace_sample_ratio: f64,

    /// Whether to log to stdout.
    #[serde(default = "default_true")]
    pub log_to_stdout: bool,
}

fn default_true() -> bool {
    true
}

fn default_sample_ratio() -> f64 {
    1.0
}

impl Default for TelemetryConfig {
    fn default() -> Self {
        Self {
            service_name: "rag-service".into(),
            service_version: None,
            environment: None,
            log_level: "info".into(),
            log_format: LogFormat::Pretty,
            otlp_endpoint: None,
            otlp_enabled: false,
            metrics_enabled: true,
            trace_sample_ratio: 1.0,
            log_to_stdout: true,
        }
    }
}

impl TelemetryConfig {
    /// Create a new config with service name.
    #[must_use]
    pub fn new(service_name: impl Into<String>) -> Self {
        Self {
            service_name: service_name.into(),
            ..Default::default()
        }
    }

    /// Set the service name.
    #[must_use]
    pub fn with_service_name(mut self, name: impl Into<String>) -> Self {
        self.service_name = name.into();
        self
    }

    /// Set the service version.
    #[must_use]
    pub fn with_service_version(mut self, version: impl Into<String>) -> Self {
        self.service_version = Some(version.into());
        self
    }

    /// Set the environment.
    #[must_use]
    pub fn with_environment(mut self, env: impl Into<String>) -> Self {
        self.environment = Some(env.into());
        self
    }

    /// Set the log level.
    #[must_use]
    pub fn with_log_level(mut self, level: impl Into<String>) -> Self {
        self.log_level = level.into();
        self
    }

    /// Set the log format.
    #[must_use]
    pub const fn with_log_format(mut self, format: LogFormat) -> Self {
        self.log_format = format;
        self
    }

    /// Enable OTLP tracing with endpoint.
    #[must_use]
    pub fn with_otlp_endpoint(mut self, endpoint: impl Into<String>) -> Self {
        self.otlp_endpoint = Some(endpoint.into());
        self.otlp_enabled = true;
        self
    }

    /// Set the trace sampling ratio.
    #[must_use]
    pub fn with_sample_ratio(mut self, ratio: f64) -> Self {
        self.trace_sample_ratio = ratio.clamp(0.0, 1.0);
        self
    }

    /// Disable metrics.
    #[must_use]
    pub const fn without_metrics(mut self) -> Self {
        self.metrics_enabled = false;
        self
    }

    /// Disable stdout logging.
    #[must_use]
    pub const fn without_stdout(mut self) -> Self {
        self.log_to_stdout = false;
        self
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `OTEL_SERVICE_NAME`: Service name
    /// - `OTEL_SERVICE_VERSION`: Service version
    /// - `OTEL_ENVIRONMENT`: Environment
    /// - `RUST_LOG` or `LOG_LEVEL`: Log level
    /// - `LOG_FORMAT`: Log format (pretty, json, compact)
    /// - `OTEL_EXPORTER_OTLP_ENDPOINT`: OTLP endpoint
    /// - `OTEL_TRACES_SAMPLER_ARG`: Sample ratio
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(name) = std::env::var("OTEL_SERVICE_NAME") {
            config.service_name = name;
        }

        if let Ok(version) = std::env::var("OTEL_SERVICE_VERSION") {
            config.service_version = Some(version);
        }

        if let Ok(env) = std::env::var("OTEL_ENVIRONMENT") {
            config.environment = Some(env);
        }

        if let Ok(level) = std::env::var("RUST_LOG").or_else(|_| std::env::var("LOG_LEVEL")) {
            config.log_level = level;
        }

        if let Ok(format) = std::env::var("LOG_FORMAT") {
            config.log_format = match format.to_lowercase().as_str() {
                "json" => LogFormat::Json,
                "compact" => LogFormat::Compact,
                _ => LogFormat::Pretty,
            };
        }

        if let Ok(endpoint) = std::env::var("OTEL_EXPORTER_OTLP_ENDPOINT") {
            config.otlp_endpoint = Some(endpoint);
            config.otlp_enabled = true;
        }

        if let Ok(ratio) = std::env::var("OTEL_TRACES_SAMPLER_ARG") {
            if let Ok(r) = ratio.parse::<f64>() {
                config.trace_sample_ratio = r.clamp(0.0, 1.0);
            }
        }

        config
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = TelemetryConfig::default();
        assert_eq!(config.service_name, "rag-service");
        assert_eq!(config.log_level, "info");
        assert_eq!(config.log_format, LogFormat::Pretty);
        assert!(!config.otlp_enabled);
        assert!(config.metrics_enabled);
    }

    #[test]
    fn test_builder_pattern() {
        let config = TelemetryConfig::new("my-service")
            .with_log_level("debug")
            .with_log_format(LogFormat::Json)
            .with_otlp_endpoint("http://localhost:4317")
            .with_sample_ratio(0.5);

        assert_eq!(config.service_name, "my-service");
        assert_eq!(config.log_level, "debug");
        assert_eq!(config.log_format, LogFormat::Json);
        assert!(config.otlp_enabled);
        assert_eq!(config.trace_sample_ratio, 0.5);
    }
}

//! Telemetry initialization.

use opentelemetry_sdk::{
    runtime,
    trace::{Config as TraceConfig, Sampler},
    Resource,
};
use opentelemetry_otlp::WithExportConfig;
use tracing_subscriber::{
    fmt,
    layer::SubscriberExt,
    util::SubscriberInitExt,
    EnvFilter, Layer,
};

use crate::{LogFormat, Result, TelemetryConfig, TelemetryError};

/// Guard that shuts down telemetry on drop.
pub struct TelemetryGuard {
    _private: (),
}

impl Drop for TelemetryGuard {
    fn drop(&mut self) {
        // Shutdown OpenTelemetry
        opentelemetry::global::shutdown_tracer_provider();
    }
}

/// Initialize telemetry with the given configuration.
///
/// Returns a guard that will shut down telemetry providers when dropped.
///
/// # Errors
///
/// Returns an error if initialization fails.
pub fn init_telemetry(config: &TelemetryConfig) -> Result<TelemetryGuard> {
    // Build the env filter
    let filter = EnvFilter::try_new(&config.log_level)
        .map_err(|e| TelemetryError::TracingInit(format!("Invalid log filter: {e}")))?;

    // Build format layer based on configuration
    let fmt_layer = if config.log_to_stdout {
        Some(build_fmt_layer(config))
    } else {
        None
    };

    // Build OpenTelemetry layer if enabled
    let otel_layer = if config.otlp_enabled {
        if let Some(endpoint) = &config.otlp_endpoint {
            Some(build_otel_layer(config, endpoint)?)
        } else {
            None
        }
    } else {
        None
    };

    // Compose and initialize subscriber
    tracing_subscriber::registry()
        .with(filter)
        .with(fmt_layer)
        .with(otel_layer)
        .try_init()
        .map_err(|e| TelemetryError::TracingInit(e.to_string()))?;

    Ok(TelemetryGuard { _private: () })
}

fn build_fmt_layer<S>(config: &TelemetryConfig) -> Box<dyn Layer<S> + Send + Sync + 'static>
where
    S: tracing::Subscriber + for<'a> tracing_subscriber::registry::LookupSpan<'a>,
{
    match config.log_format {
        LogFormat::Json => Box::new(
            fmt::layer()
                .json()
                .with_current_span(true)
                .with_target(true),
        ),
        LogFormat::Compact => Box::new(
            fmt::layer()
                .compact()
                .with_target(true),
        ),
        LogFormat::Pretty => Box::new(
            fmt::layer()
                .pretty()
                .with_target(true)
                .with_thread_names(true),
        ),
    }
}

fn build_otel_layer<S>(
    config: &TelemetryConfig,
    endpoint: &str,
) -> Result<tracing_opentelemetry::OpenTelemetryLayer<S, opentelemetry_sdk::trace::Tracer>>
where
    S: tracing::Subscriber + for<'a> tracing_subscriber::registry::LookupSpan<'a>,
{
    // Build resource attributes
    let mut resource_attrs = vec![
        opentelemetry::KeyValue::new("service.name", config.service_name.clone()),
    ];

    if let Some(version) = &config.service_version {
        resource_attrs.push(opentelemetry::KeyValue::new("service.version", version.clone()));
    }

    if let Some(env) = &config.environment {
        resource_attrs.push(opentelemetry::KeyValue::new("deployment.environment", env.clone()));
    }

    let resource = Resource::new(resource_attrs);

    // Configure sampler
    let sampler = if config.trace_sample_ratio >= 1.0 {
        Sampler::AlwaysOn
    } else if config.trace_sample_ratio <= 0.0 {
        Sampler::AlwaysOff
    } else {
        Sampler::TraceIdRatioBased(config.trace_sample_ratio)
    };

    let trace_config = TraceConfig::default()
        .with_sampler(sampler)
        .with_resource(resource);

    // Build OTLP exporter
    let exporter = opentelemetry_otlp::new_exporter()
        .tonic()
        .with_endpoint(endpoint);

    // Build and install tracer - install_batch returns a Tracer directly
    let tracer = opentelemetry_otlp::new_pipeline()
        .tracing()
        .with_exporter(exporter)
        .with_trace_config(trace_config)
        .install_batch(runtime::Tokio)
        .map_err(|e| TelemetryError::OpenTelemetry(e.to_string()))?;

    Ok(tracing_opentelemetry::layer().with_tracer(tracer))
}

/// Initialize telemetry from environment variables.
///
/// Convenience function that calls `init_telemetry` with `TelemetryConfig::from_env()`.
///
/// # Errors
///
/// Returns an error if initialization fails.
#[allow(dead_code)] // Used by consuming crates
pub fn init_telemetry_from_env() -> Result<TelemetryGuard> {
    let config = TelemetryConfig::from_env();
    init_telemetry(&config)
}

#[cfg(test)]
mod tests {
    use super::*;

    // Note: These tests are limited because tracing can only be initialized once per process.
    // In real tests, you'd use a test subscriber.

    #[test]
    fn test_config_from_env() {
        // Just verify it doesn't panic
        let _config = TelemetryConfig::from_env();
    }
}

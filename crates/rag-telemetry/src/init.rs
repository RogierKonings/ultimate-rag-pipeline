//! Telemetry initialization.

use opentelemetry::trace::TracerProvider as _;
use opentelemetry_sdk::{
    trace::{Sampler, SdkTracerProvider},
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
    provider: Option<SdkTracerProvider>,
}

impl Drop for TelemetryGuard {
    fn drop(&mut self) {
        // Shutdown OpenTelemetry tracer provider
        if let Some(provider) = self.provider.take() {
            if let Err(e) = provider.shutdown() {
                eprintln!("Error shutting down tracer provider: {e}");
            }
        }
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
    let (otel_layer, provider) = if config.otlp_enabled {
        if let Some(endpoint) = &config.otlp_endpoint {
            let (layer, prov) = build_otel_layer(config, endpoint)?;
            (Some(layer), Some(prov))
        } else {
            (None, None)
        }
    } else {
        (None, None)
    };

    // Compose and initialize subscriber
    tracing_subscriber::registry()
        .with(filter)
        .with(fmt_layer)
        .with(otel_layer)
        .try_init()
        .map_err(|e| TelemetryError::TracingInit(e.to_string()))?;

    Ok(TelemetryGuard { provider })
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
) -> Result<(
    tracing_opentelemetry::OpenTelemetryLayer<S, opentelemetry_sdk::trace::Tracer>,
    SdkTracerProvider,
)>
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

    let resource = Resource::builder_empty()
        .with_attributes(resource_attrs)
        .build();

    // Configure sampler
    let sampler = if config.trace_sample_ratio >= 1.0 {
        Sampler::AlwaysOn
    } else if config.trace_sample_ratio <= 0.0 {
        Sampler::AlwaysOff
    } else {
        Sampler::TraceIdRatioBased(config.trace_sample_ratio)
    };

    // Build OTLP exporter
    let exporter = opentelemetry_otlp::SpanExporter::builder()
        .with_tonic()
        .with_endpoint(endpoint)
        .build()
        .map_err(|e| TelemetryError::OpenTelemetry(e.to_string()))?;

    // Build tracer provider
    let tracer_provider = SdkTracerProvider::builder()
        .with_batch_exporter(exporter)
        .with_sampler(sampler)
        .with_resource(resource)
        .build();

    opentelemetry::global::set_tracer_provider(tracer_provider.clone());
    let tracer = tracer_provider.tracer(config.service_name.clone());

    Ok((tracing_opentelemetry::layer().with_tracer(tracer), tracer_provider))
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

//! Error types for telemetry.

use thiserror::Error;

/// Result type for telemetry operations.
pub type Result<T> = std::result::Result<T, TelemetryError>;

/// Telemetry errors.
#[derive(Debug, Error)]
pub enum TelemetryError {
    /// Failed to initialize tracing subscriber.
    #[error("Failed to initialize tracing: {0}")]
    TracingInit(String),

    /// Failed to initialize OpenTelemetry.
    #[error("Failed to initialize OpenTelemetry: {0}")]
    OpenTelemetry(String),

    /// Failed to initialize metrics.
    #[error("Failed to initialize metrics: {0}")]
    Metrics(String),

    /// Configuration error.
    #[error("Configuration error: {0}")]
    Config(String),
}

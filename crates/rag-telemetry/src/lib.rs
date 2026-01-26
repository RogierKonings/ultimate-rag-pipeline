//! OpenTelemetry and tracing for the RAG Pipeline.
//!
//! This crate provides observability primitives:
//! - Structured logging with `tracing`
//! - Distributed tracing with OpenTelemetry (OTLP export)
//! - Prometheus metrics
//! - Request ID propagation
//!
//! # Example
//!
//! ```no_run
//! use rag_telemetry::{TelemetryConfig, init_telemetry};
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = TelemetryConfig::default()
//!         .with_service_name("my-service")
//!         .with_log_level("info");
//!
//!     let _guard = init_telemetry(&config)?;
//!
//!     tracing::info!("Service started");
//!
//!     Ok(())
//! }
//! ```

mod config;
mod error;
mod init;
mod metrics;
mod tracing_layer;

pub use config::{LogFormat, TelemetryConfig};
pub use error::{TelemetryError, Result};
pub use init::{init_telemetry, TelemetryGuard};
pub use metrics::{Metrics, MetricsRegistry};
pub use tracing_layer::request_id_layer;

/// Re-export tracing macros for convenience.
pub use tracing::{debug, error, info, trace, warn};
pub use tracing::{debug_span, error_span, info_span, trace_span, warn_span, span, Span};
pub use tracing::instrument;

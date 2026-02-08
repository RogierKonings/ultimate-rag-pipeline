//! Observability layer for the retrieval service.
//!
//! This module provides comprehensive observability for the retrieval pipeline:
//!
//! - **Metrics**: Prometheus metrics for requests, latency, cache, and component health
//! - **Tracing**: OpenTelemetry span definitions for pipeline stages
//! - **Logging**: Structured logging with request context propagation
//!
//! # Example
//!
//! ```no_run
//! use rag_retrieval::observability::{
//!     RetrievalMetricsCollector, TracingConfig, RequestContext,
//!     init_tracing, span_names,
//! };
//! use rag_telemetry::MetricsRegistry;
//! use uuid::Uuid;
//!
//! // Initialize tracing
//! let tracing_config = TracingConfig::default();
//! init_tracing(&tracing_config).expect("Failed to init tracing");
//!
//! // Create metrics
//! let registry = MetricsRegistry::new();
//! let metrics = RetrievalMetricsCollector::new(&registry).expect("Failed to create metrics");
//!
//! // Create request context
//! let ctx = RequestContext::new(Uuid::new_v4());
//!
//! // Record metrics
//! metrics.record_request("hybrid", "success", 0.150);
//! metrics.record_stage_latency("semantic_search", 0.045);
//! ```

pub mod logging;
pub mod metrics;
pub mod tracing;

// Re-export main types
pub use logging::{
    log_error, log_request_complete, log_request_start, log_stage_complete, RequestContext,
};
pub use metrics::{encode_metrics, register_metrics, RetrievalMetricsCollector, RETRIEVAL_METRICS};
pub use tracing::{init_tracing, shutdown_tracing, span_names, TracingConfig};

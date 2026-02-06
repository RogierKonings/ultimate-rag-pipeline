//! API request and response types for the retrieval service.
//!
//! This module re-exports types from focused sub-modules:
//! - [`requests`](super::requests) — Request types and validation
//! - [`responses`](super::responses) — Response types, metrics, and debug info
//! - [`validation`](super::validation) — Validation error type

// Re-export all public types for backward compatibility
pub use super::requests::{MultiQueryRequest, RetrieveRequest};
pub use super::responses::{
    ComponentHealth, DebugInfo, HealthResponse, LivenessResponse, ReadinessResponse,
    RetrieveResponse, RetrievedDocument, SearchMetrics,
};
pub use super::validation::ValidationError;

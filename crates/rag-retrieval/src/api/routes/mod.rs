//! Route handlers for the retrieval service API.
//!
//! This module organizes all HTTP route handlers:
//! - `search`: Main document retrieval endpoint
//! - `multi`: Multi-query retrieval endpoint
//! - `health`: Health check endpoints for Kubernetes probes
//! - `metrics`: Prometheus metrics endpoint

pub mod health;
pub mod metrics;
pub mod multi;
pub mod search;

// Re-export route handlers for convenient imports
pub use health::{health, liveness, readiness};
pub use metrics::metrics;
pub use multi::retrieve_multi;
pub use search::retrieve;

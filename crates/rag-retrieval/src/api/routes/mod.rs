//! Route handlers for the retrieval service API.
//!
//! This module organizes all HTTP route handlers:
//! - `search`: Main document retrieval endpoint
//! - `multi`: Multi-query retrieval endpoint
//! - `health`: Health check endpoints for Kubernetes probes

pub mod health;
pub mod multi;
pub mod search;

// Re-export route handlers for convenient imports
pub use health::{health, liveness, readiness};
pub use multi::retrieve_multi;
pub use search::retrieve;

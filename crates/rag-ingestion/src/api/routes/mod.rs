//! API route handlers for the ingestion service.

pub mod health;

pub use health::{health, liveness, readiness};

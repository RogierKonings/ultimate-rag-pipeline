//! HTTP API for the ingestion service.
//!
//! This module provides the Axum-based REST API for document ingestion,
//! job management, and document CRUD operations.

pub mod error;
pub mod jobs;
pub mod state;
pub mod types;

pub use error::{ApiError, ApiResult, ErrorBody, ErrorResponse};
pub use jobs::{JobState, JobTracker};
pub use state::{AppState, AppStateBuilder, AppStateBuilderError};
pub use types::*;

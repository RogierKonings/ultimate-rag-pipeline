//! HTTP API for the ingestion service.
//!
//! This module provides the Axum-based REST API for document ingestion,
//! job management, and document CRUD operations.

pub mod error;
pub mod types;

pub use error::{ApiError, ApiResult, ErrorBody, ErrorResponse};
pub use types::*;

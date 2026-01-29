//! HTTP API for the ingestion service.
//!
//! This module provides the Axum-based REST API for document ingestion,
//! job management, and document CRUD operations.

pub mod error;

pub use error::{ApiError, ApiResult, ErrorBody, ErrorResponse};

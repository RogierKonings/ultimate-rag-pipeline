//! HTTP API for the ingestion service.
//!
//! This module provides the Axum-based REST API for document ingestion,
//! job management, and document CRUD operations.
//!
//! # Routes
//!
//! ## Ingest Routes (`/api/v1/ingest`)
//!
//! - `POST /api/v1/ingest` - Start batch ingestion job
//! - `GET /api/v1/ingest` - List active jobs
//! - `POST /api/v1/ingest/single` - Ingest single document
//! - `POST /api/v1/ingest/sync` - Start incremental sync
//! - `POST /api/v1/ingest/reembed` - Start re-embedding job
//! - `GET /api/v1/ingest/{job_id}` - Get job status
//! - `DELETE /api/v1/ingest/{job_id}` - Cancel job
//!
//! ## Document Routes (`/api/v1/documents`)
//!
//! - `GET /api/v1/documents` - List documents
//! - `GET /api/v1/documents/sync-status` - Get sync status
//! - `GET /api/v1/documents/{document_id}` - Get document
//! - `DELETE /api/v1/documents/{document_id}` - Delete document
//! - `POST /api/v1/documents/{document_id}/reindex` - Reindex document
//! - `POST /api/v1/documents/batch-delete` - Batch delete
//!
//! ## Health Routes
//!
//! - `GET /health` - Full health check
//! - `GET /health/live` - Liveness probe
//! - `GET /health/ready` - Readiness probe

pub mod error;
pub mod jobs;
pub mod routes;
pub mod server;
pub mod state;
pub mod types;

pub use error::{ApiError, ApiResult, ErrorBody, ErrorResponse};
pub use jobs::{JobState, JobTracker};
pub use server::{
    create_router, create_router_with_config, run_server, run_server_with_config,
    run_server_with_shutdown, ServerConfig, ServerError,
};
pub use state::{AppState, AppStateBuilder, AppStateBuilderError};
pub use types::*;

//! API route handlers for the ingestion service.

pub mod health;
pub mod ingest;

pub use health::{health, liveness, readiness};
pub use ingest::{
    cancel_job, get_job_status, ingest_single_document, list_active_jobs, start_ingestion,
    start_reembed, start_sync,
};

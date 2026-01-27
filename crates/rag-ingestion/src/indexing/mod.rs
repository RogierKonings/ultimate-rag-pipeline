//! Index coordination for writing to multiple stores.
//!
//! This module provides the IndexCoordinator which orchestrates
//! parallel writes to Qdrant (vectors), OpenSearch (keywords),
//! and PostgreSQL (metadata).

// mod coordinator; // TODO: implement coordinator
mod models;
mod status;

// pub use coordinator::IndexCoordinator; // TODO: uncomment when coordinator is implemented
pub use models::{DocumentRecord, IndexedChunk, WriteResult};
pub use status::IndexStatus;

//! Index coordination for writing to multiple stores.
//!
//! This module provides the `IndexCoordinator` which orchestrates
//! parallel writes to Qdrant (vectors), `OpenSearch` (keywords),
//! and `PostgreSQL` (metadata).

mod coordinator;
mod models;

pub use coordinator::{IndexCoordinator, IndexCoordinatorConfig};
pub use models::{DocumentRecord, IndexedChunk, WriteResult};
pub use rag_types::IndexStatus;

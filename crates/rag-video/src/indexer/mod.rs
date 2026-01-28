//! Video indexing module.
//!
//! Provides video chunk indexing capabilities for Qdrant vector database.

pub mod config;
pub mod types;

pub use config::VideoIndexerConfig;
pub use types::{CollectionInfo, IndexResult, SearchFilters, SearchHit, VideoChunkPayload};

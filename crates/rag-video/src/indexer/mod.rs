//! Video indexing module.
//!
//! Provides video chunk indexing capabilities for Qdrant vector database.

pub mod config;
pub mod service;
pub mod types;

pub use config::VideoIndexerConfig;
pub use service::{ProgressCallback, VideoQdrantIndexer};
pub use types::{CollectionInfo, IndexResult, SearchFilters, SearchHit, VideoChunkPayload};

//! Core types for the RAG Pipeline.
//!
//! This crate provides the foundational types used throughout the RAG system:
//! - Newtype wrappers for type-safe IDs ([`TenantId`], [`DocumentId`], [`ChunkId`])
//! - Core domain models ([`Document`], [`Chunk`], [`Embedding`])
//! - Enums for status values and configuration options
//! - Error types for the entire pipeline

pub mod document;
pub mod embedding;
pub mod error;
pub mod ids;
pub mod search;
pub mod video;

// Re-export commonly used types at crate root
pub use document::{Chunk, Document, IndexStatus, SourceType, Visibility};
pub use embedding::Embedding;
pub use error::{Error, Result};
pub use ids::{ChunkId, DocumentId, TenantId, UserId, VideoId};
pub use search::{RetrievedChunk, SearchMode, SearchResult};
pub use video::{ProcessingStage, VideoStatus};

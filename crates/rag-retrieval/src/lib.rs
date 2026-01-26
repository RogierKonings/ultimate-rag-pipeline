//! Retrieval algorithms for the RAG Pipeline.
//!
//! This crate provides core retrieval functionality:
//! - Reciprocal Rank Fusion (RRF) for combining search results
//! - Score normalization
//! - Result deduplication
//! - Core types for retrieval operations
//! - Error handling
//!
//! # Example
//!
//! ```
//! use rag_retrieval::rrf::{RrfConfig, reciprocal_rank_fusion};
//! use rag_retrieval::ScoredItem;
//!
//! let semantic_results = vec![
//!     ScoredItem::new("doc1", 0.9),
//!     ScoredItem::new("doc2", 0.8),
//!     ScoredItem::new("doc3", 0.7),
//! ];
//!
//! let keyword_results = vec![
//!     ScoredItem::new("doc2", 0.95),
//!     ScoredItem::new("doc4", 0.85),
//!     ScoredItem::new("doc1", 0.75),
//! ];
//!
//! let config = RrfConfig::default();
//! let fused = reciprocal_rank_fusion(&[&semantic_results, &keyword_results], &config).unwrap();
//!
//! // doc2 appears in both lists, so it should rank highly
//! assert_eq!(fused[0].id, "doc2");
//! ```

pub mod error;
pub mod rrf;
pub mod types;

// Re-export key types from rrf module
pub use rrf::{reciprocal_rank_fusion, RrfConfig, RrfError, ScoredItem};

// Re-export error types
pub use error::{RetrievalError, Result};

// Re-export core types
pub use types::{
    QueryType, RetrievalDebug, RetrievalMetrics, RetrievalResult, SearchMode, UserContext,
    Visibility,
};

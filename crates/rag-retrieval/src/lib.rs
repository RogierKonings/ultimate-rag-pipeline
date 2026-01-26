//! Retrieval algorithms for the RAG Pipeline.
//!
//! This crate provides core retrieval functionality:
//!
//! - **Fusion algorithms**: Multiple methods for combining search results
//!   - Reciprocal Rank Fusion (RRF) for combining ranked lists
//!   - Linear weighted fusion with score normalization
//!   - Distribution-Based Score Fusion (DBSF) using z-score normalization
//! - Score normalization and result deduplication
//! - Core types for retrieval operations
//! - Error handling
//!
//! # Fusion Methods
//!
//! The crate supports three fusion methods:
//!
//! - **RRF (Reciprocal Rank Fusion)**: Best for cases where score distributions
//!   differ significantly between search methods. Uses only rank information.
//! - **Linear**: Simple weighted combination of normalized scores. Best when
//!   score distributions are similar and well-calibrated.
//! - **DBSF**: Uses z-score normalization to account for different score
//!   distributions. Best when distributions have different means/std devs.
//!
//! # Example
//!
//! ```
//! use rag_retrieval::fusion::{fuse, FusionConfig, FusionMethod};
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
//! // Use RRF (default)
//! let config = FusionConfig::default();
//! let fused = fuse(&semantic_results, &keyword_results, &config).unwrap();
//!
//! // doc1 ranks first (best semantic rank with moderate keyword rank)
//! // doc2 ranks second (appears in both with good combined ranks)
//! assert_eq!(fused[0].id, "doc1");
//! assert_eq!(fused[1].id, "doc2");
//!
//! // Use Linear fusion
//! let config = FusionConfig::new(FusionMethod::Linear);
//! let fused = fuse(&semantic_results, &keyword_results, &config).unwrap();
//!
//! // Use DBSF (Distribution-Based Score Fusion)
//! let config = FusionConfig::new(FusionMethod::Dbsf);
//! let fused = fuse(&semantic_results, &keyword_results, &config).unwrap();
//! ```
//!
//! # Legacy RRF API
//!
//! For backward compatibility, the RRF functions are still available at the
//! crate root level:
//!
//! ```
//! use rag_retrieval::rrf::{RrfConfig, reciprocal_rank_fusion};
//! use rag_retrieval::ScoredItem;
//!
//! let semantic_results = vec![
//!     ScoredItem::new("doc1", 0.9),
//!     ScoredItem::new("doc2", 0.8),
//! ];
//!
//! let keyword_results = vec![
//!     ScoredItem::new("doc2", 0.95),
//!     ScoredItem::new("doc3", 0.85),
//! ];
//!
//! let config = RrfConfig::default();
//! let fused = reciprocal_rank_fusion(&[&semantic_results, &keyword_results], &config).unwrap();
//! ```

pub mod embedding;
pub mod error;
pub mod fusion;
pub mod query;
pub mod reranking;
pub mod search;
pub mod types;

// Re-export fusion module as `rrf` for backward compatibility
pub use fusion as rrf;

// Re-export key types from fusion module
pub use fusion::{
    fuse, reciprocal_rank_fusion, FusedResult, FusionConfig, FusionError, FusionMethod, RrfConfig,
    RrfError, ScoredItem,
};

// Re-export error types
pub use error::{RetrievalError, Result};

// Re-export core types
pub use types::{
    QueryType, RetrievalDebug, RetrievalMetrics, RetrievalResult, SearchMode, UserContext,
    Visibility,
};

// Re-export search types
pub use search::{
    KeywordResult, KeywordSearchConfig, KeywordSearchFilters, KeywordSearcher, SearchConfig,
    SemanticResult, SemanticSearchConfig, SemanticSearcher,
};

// Re-export embedding types
pub use embedding::{EmbeddingClient, EmbeddingConfig};

// Re-export reranking types
pub use reranking::{RerankerClient, RerankerConfig, RerankResponse, RerankResult};

// Re-export query types
pub use query::{
    HydeConfig, HydeGenerator, HydeResult, PreprocessedQuery, QueryCache, QueryCacheConfig,
    QueryCacheKey, QueryExpander, QueryExpanderConfig, QueryPreprocessor, QueryPreprocessorConfig,
};

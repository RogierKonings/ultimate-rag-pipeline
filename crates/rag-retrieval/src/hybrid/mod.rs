//! Hybrid search combining semantic and keyword search.
//!
//! This module provides hybrid search functionality that combines semantic (vector)
//! search with keyword (BM25) search and applies result fusion algorithms.
//!
//! # Features
//!
//! - **Parallel execution**: Semantic and keyword search run concurrently
//! - **Configurable fusion**: Support for RRF, Linear, and DBSF fusion methods
//! - **Score threshold filtering**: Filter results below a minimum score
//! - **Deduplication**: Remove duplicate results by document ID
//! - **Reranking and ACL**: Optional cross-encoder reranking and ACL filtering via route handlers
//!
//! # Example
//!
//! ```no_run
//! use std::sync::Arc;
//! use rag_retrieval::hybrid::{HybridSearcher, HybridSearchConfig};
//! use rag_retrieval::search::{SemanticSearcher, KeywordSearcher, SemanticSearchConfig, KeywordSearchConfig};
//! use rag_retrieval::UserContext;
//! use uuid::Uuid;
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     // Set up searchers
//!     let semantic_config = SemanticSearchConfig::default();
//!     let semantic = Arc::new(SemanticSearcher::new(&semantic_config).await?);
//!
//!     let keyword_config = KeywordSearchConfig::default();
//!     let keyword = Arc::new(KeywordSearcher::new(&keyword_config)?);
//!
//!     // Create hybrid searcher
//!     let config = HybridSearchConfig::default();
//!     let hybrid = HybridSearcher::new(semantic, keyword, config);
//!
//!     // Execute search
//!     let user_ctx = UserContext::new(Uuid::new_v4(), Uuid::new_v4());
//!     let embedding = vec![0.1; 384];
//!
//!     let response = hybrid
//!         .search("my query", &embedding, Some(10), None, None)
//!         .await?;
//!
//!     println!("Found {} results in {}ms",
//!         response.results.len(),
//!         response.search_time_ms
//!     );
//!
//!     Ok(())
//! }
//! ```

mod config;
mod pipeline_config;
mod response;
mod searcher;

pub use config::HybridSearchConfig;
pub use pipeline_config::{PipelineConfig, SearchOptions, SearchPipelineResponse};
pub use response::{HybridSearchResponse, HybridSearchResult};
pub use searcher::HybridSearcher;

//! Search implementations for semantic and keyword search.
//!
//! This module provides search functionality:
//!
//! - **Semantic search**: Vector similarity search using Qdrant
//! - **Keyword search**: BM25 search using `OpenSearch`
//! - **Configuration**: Unified search configuration for both methods
//!
//! # Example
//!
//! ```no_run
//! use rag_retrieval::search::{SemanticSearcher, SemanticSearchConfig, SearchConfig};
//! use rag_retrieval::search::{KeywordSearcher, KeywordSearchConfig};
//! use rag_retrieval::UserContext;
//! use uuid::Uuid;
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     // Semantic search example
//!     let semantic_config = SemanticSearchConfig::default();
//!     let semantic_searcher = SemanticSearcher::new(&semantic_config).await?;
//!
//!     let user_ctx = UserContext::new(Uuid::new_v4(), Uuid::new_v4());
//!     let embedding = vec![0.1; 384];
//!
//!     let semantic_results = semantic_searcher
//!         .search(&embedding, &user_ctx, None, None)
//!         .await?;
//!
//!     for result in semantic_results {
//!         println!("Semantic - Chunk {}: score {:.3}", result.chunk_id, result.score);
//!     }
//!
//!     // Keyword search example
//!     let keyword_config = KeywordSearchConfig::default();
//!     let keyword_searcher = KeywordSearcher::new(&keyword_config)?;
//!
//!     let keyword_results = keyword_searcher
//!         .search("search query", &user_ctx, None, None)
//!         .await?;
//!
//!     for result in keyword_results {
//!         println!("Keyword - Chunk {}: score {:.3}", result.chunk_id, result.score);
//!     }
//!
//!     Ok(())
//! }
//! ```

mod config;
mod keyword;
mod semantic;

pub use config::{KeywordSearchConfig, SearchConfig, SemanticSearchConfig};
pub use keyword::{KeywordResult, KeywordSearchFilters, KeywordSearcher};
pub use semantic::{SearchFilters, SemanticResult, SemanticSearcher};

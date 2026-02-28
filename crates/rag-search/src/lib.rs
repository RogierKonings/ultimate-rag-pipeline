//! OpenSearch client for the RAG Pipeline.
//!
//! This crate provides keyword search functionality:
//! - Index management (create, delete, refresh)
//! - Document indexing (single and bulk)
//! - BM25 search with filters
//! - Scroll API for large result sets
//! - Highlighting support
//!
//! # Example
//!
//! ```no_run
//! use rag_search::{SearchClient, SearchConfig, BM25Request};
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = SearchConfig::new("http://localhost:9200");
//!     let client = SearchClient::new(config)?;
//!
//!     // Index a document
//!     let doc = serde_json::json!({
//!         "content": "Hello world",
//!         "tenant_id": "tenant-1"
//!     });
//!     client.index_document("documents", "doc-1", doc).await?;
//!
//!     // Search
//!     let request = BM25Request::new("hello")
//!         .with_field("content")
//!         .with_limit(10);
//!     let results = client.search("documents", &request).await?;
//!
//!     Ok(())
//! }
//! ```

mod client;
mod config;
mod error;
mod models;
mod query;

pub use client::SearchClient;
pub use config::SearchConfig;
pub use error::{Result, SearchError};
pub use models::{BM25Request, SearchHit, SearchResponse};
pub use query::{HighlightBuilder, QueryBuilder};

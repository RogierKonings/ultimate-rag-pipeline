//! Qdrant vector store client for the RAG Pipeline.
//!
//! This crate provides vector database functionality:
//! - Collection management (create, delete, info)
//! - Point operations (upsert, search, delete)
//! - Batch operations with retry logic
//! - Filter building for multi-tenant search
//!
//! # Example
//!
//! ```no_run
//! use rag_vectorstore::{VectorStoreClient, VectorStoreConfig, SearchRequest};
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = VectorStoreConfig::new("http://localhost:6333");
//!     let client = VectorStoreClient::connect(&config).await?;
//!
//!     // Create a collection
//!     client.create_collection("documents", 384).await?;
//!
//!     // Upsert vectors
//!     let vectors = vec![vec![0.1; 384]];
//!     let ids = vec!["doc-1".to_string()];
//!     let payloads = vec![serde_json::json!({"tenant_id": "tenant-1"})];
//!     client.upsert("documents", ids, vectors, payloads).await?;
//!
//!     // Search
//!     let request = SearchRequest::new(vec![0.1; 384])
//!         .with_limit(10);
//!     let results = client.search("documents", request).await?;
//!
//!     Ok(())
//! }
//! ```

mod client;
mod config;
mod error;
mod filter;
mod models;

pub use client::VectorStoreClient;
pub use config::VectorStoreConfig;
pub use error::{VectorStoreError, Result};
pub use filter::FilterBuilder;
pub use models::{SearchParams, SearchRequest, SearchResult, ScoredPoint};

// Re-export qdrant types that users may need for filtering
pub use qdrant_client;
pub use qdrant_client::qdrant::{Condition, Filter};

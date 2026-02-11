//! Reranker client and service for cross-encoder reranking.
//!
//! This module provides both a low-level HTTP client and a high-level
//! service for the reranker that performs cross-encoder reranking on
//! query-document pairs.
//!
//! # Components
//!
//! - [`RerankerClient`]: Low-level HTTP client that communicates with the
//!   LLM Gateway's `/v1/rerank` endpoint using the Cohere API format.
//! - [`RerankerService`]: High-level service that integrates with
//!   `FusedResult` and `RetrievalResult` types for convenient reranking.
//!
//! # Example (Low-level Client)
//!
//! ```no_run
//! use rag_retrieval::reranking::{RerankerClient, RerankerConfig};
//! use uuid::Uuid;
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = RerankerConfig::default();
//!     let client = RerankerClient::new(config)?;
//!
//!     // Rerank documents by relevance to a query
//!     let query = "What is machine learning?";
//!     let documents = vec![
//!         "Machine learning is a subset of artificial intelligence.".to_string(),
//!         "Python is a programming language.".to_string(),
//!         "Deep learning uses neural networks.".to_string(),
//!     ];
//!     let document_ids: Vec<Uuid> = (0..3).map(|_| Uuid::new_v4()).collect();
//!
//!     let response = client.rerank(query, &documents, &document_ids).await?;
//!
//!     for result in &response.results {
//!         println!("Document {}: score {:.3}", result.index, result.relevance_score);
//!     }
//!
//!     Ok(())
//! }
//! ```
//!
//! # Example (High-level Service)
//!
//! ```no_run
//! use rag_retrieval::reranking::{RerankerService, RerankerConfig};
//! use rag_retrieval::RetrievalResult;
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let service = RerankerService::new(RerankerConfig::default())?;
//!
//!     let results = vec![
//!         RetrievalResult::new(
//!             "chunk1".into(),
//!             "doc1".into(),
//!             "Machine learning is AI.".into(),
//!             0.85,
//!         ),
//!     ];
//!
//!     let reranked = service.rerank_results("What is ML?", &results, Some(10)).await?;
//!
//!     for r in &reranked {
//!         println!("{}: {:.3}", r.chunk_id, r.score);
//!     }
//!
//!     Ok(())
//! }
//! ```
//!
//! # Cross-Encoder Reranking
//!
//! Cross-encoder models jointly encode the query and document together,
//! allowing them to capture fine-grained relevance signals that bi-encoder
//! models (used for initial retrieval) cannot. This makes them more accurate
//! but slower, so they are typically used only on a small set of top candidates.
//!
//! # Cohere API Format
//!
//! The client communicates with the LLM Gateway's `/v1/rerank` endpoint,
//! which implements the Cohere rerank API format.

mod client;
mod config;
mod service;

pub use client::{RerankResponse, RerankResult, RerankerClient};
pub use config::RerankerConfig;
pub use service::RerankerService;

//! Embedding client for query embedding generation.
//!
//! This module provides an HTTP client for the embedding service
//! that generates vector embeddings for queries and texts.
//!
//! # Example
//!
//! ```no_run
//! use rag_retrieval::embedding::{EmbeddingClient, EmbeddingConfig};
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = EmbeddingConfig::default();
//!     let client = EmbeddingClient::new(config)?;
//!
//!     // Embed a single query
//!     let embedding = client.embed_query("What is RAG?").await?;
//!     println!("Embedding dimension: {}", embedding.len());
//!
//!     // Embed multiple texts
//!     let texts = vec![
//!         "First document".to_string(),
//!         "Second document".to_string(),
//!     ];
//!     let embeddings = client.embed_texts(&texts).await?;
//!     println!("Generated {} embeddings", embeddings.len());
//!
//!     Ok(())
//! }
//! ```

mod client;
mod config;

pub use client::EmbeddingClient;
pub use config::EmbeddingConfig;

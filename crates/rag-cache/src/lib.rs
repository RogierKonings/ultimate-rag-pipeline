//! Redis cache client for the RAG Pipeline.
//!
//! This crate provides caching functionality for:
//! - Embedding vectors (by content hash)
//! - Query results
//! - General key-value storage
//!
//! # Key Format
//!
//! Keys follow the pattern: `{service}:{type}:{tenant_id}:{identifier}`
//!
//! Examples:
//! - `ing:emb:tenant-123:abc123def456` - Embedding cache
//! - `ret:query:tenant-123:hash123` - Query cache
//!
//! # Example
//!
//! ```no_run
//! use rag_cache::{CacheClient, CacheConfig};
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = CacheConfig::default();
//!     let client = CacheClient::connect(&config).await?;
//!
//!     // Store and retrieve a value
//!     client.set("my-key", &"hello world", None).await?;
//!     let value: Option<String> = client.get("my-key").await?;
//!
//!     Ok(())
//! }
//! ```

mod client;
mod config;
mod embedding;
mod error;
mod keys;

pub use client::CacheClient;
pub use config::CacheConfig;
pub use embedding::EmbeddingCache;
pub use error::{CacheError, Result};
pub use keys::{CacheKey, KeyType, ServicePrefix};

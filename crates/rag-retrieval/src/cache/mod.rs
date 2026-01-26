//! Caching layer for the retrieval service.
//!
//! This module provides high-level caching abstractions that build on top of
//! the lower-level `QueryCache` from the query module. It adds:
//!
//! - **Cache key building**: Deterministic key generation with filter support
//! - **Statistics tracking**: Hit/miss rates, latency metrics
//! - **Retrieval cache**: High-level wrapper combining caching with stats
//!
//! # Architecture
//!
//! ```text
//! ┌─────────────────┐
//! │ RetrievalCache  │  High-level API with stats
//! ├─────────────────┤
//! │   QueryCache    │  Core caching logic (from query module)
//! ├─────────────────┤
//! │   CacheClient   │  Redis backend (from rag-cache)
//! └─────────────────┘
//! ```
//!
//! # Example
//!
//! ```no_run
//! use rag_cache::{CacheClient, CacheConfig};
//! use rag_retrieval::cache::{CacheKeyBuilder, CacheStats, RetrievalCache};
//! use rag_retrieval::query::{QueryCacheConfig, QueryCacheKey};
//! use rag_retrieval::SearchMode;
//! use std::sync::Arc;
//! use uuid::Uuid;
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     // Build cache key
//!     let key_str = CacheKeyBuilder::new(Uuid::new_v4(), "what is machine learning?")
//!         .with_search_mode(SearchMode::Hybrid)
//!         .with_top_k(10)
//!         .build();
//!
//!     println!("Cache key: {}", key_str);
//!
//!     // Track stats
//!     let stats = CacheStats::new();
//!     stats.record_hit(5);
//!     println!("Hit rate: {:.2}%", stats.hit_rate() * 100.0);
//!
//!     Ok(())
//! }
//! ```
//!
//! # Re-exports
//!
//! This module re-exports `QueryCache`, `QueryCacheConfig`, and `QueryCacheKey`
//! from the query module for convenience.

mod keys;
mod retrieval;
mod stats;

pub use keys::CacheKeyBuilder;
pub use retrieval::RetrievalCache;
pub use stats::{CacheStats, CacheStatsSnapshot};

// Re-export query cache types for convenience
pub use crate::query::{QueryCache, QueryCacheConfig, QueryCacheKey};

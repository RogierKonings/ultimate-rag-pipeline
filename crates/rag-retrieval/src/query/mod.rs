//! Query preprocessing for the retrieval service.
//!
//! This module provides query preprocessing functionality including:
//! - Query normalization (whitespace, unicode, case)
//! - Query type classification
//! - Token extraction
//! - Query expansion with synonym support
//! - Hypothetical Document Embeddings (HyDE) generation
//! - Query result caching

mod cache;
mod expander;
mod hyde;
mod preprocessor;

pub use cache::{QueryCache, QueryCacheConfig, QueryCacheKey};
pub use expander::{QueryExpander, QueryExpanderConfig};
pub use hyde::{HydeConfig, HydeGenerator, HydeResult};
pub use preprocessor::{PreprocessedQuery, QueryPreprocessor, QueryPreprocessorConfig};

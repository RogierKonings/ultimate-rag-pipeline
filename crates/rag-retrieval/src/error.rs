//! Error types for retrieval operations.
//!
//! This module provides a comprehensive error type that covers all retrieval
//! operations including semantic search, keyword search, embedding, reranking,
//! caching, and LLM interactions.

use thiserror::Error;

use rag_cache::CacheError;
use rag_search::SearchError;
use rag_vectorstore::VectorStoreError;

/// Result type for retrieval operations.
pub type Result<T> = std::result::Result<T, RetrievalError>;

/// Errors that can occur during retrieval operations.
#[derive(Debug, Error)]
pub enum RetrievalError {
    /// Semantic (vector) search failed.
    #[error("Semantic search error: {0}")]
    SemanticSearch(String),

    /// Keyword (BM25) search failed.
    #[error("Keyword search error: {0}")]
    KeywordSearch(String),

    /// Embedding generation failed.
    #[error("Embedding error: {0}")]
    Embedding(String),

    /// Reranking operation failed.
    #[error("Reranking error: {0}")]
    Reranking(String),

    /// Cache operation failed.
    #[error("Cache error: {0}")]
    Cache(String),

    /// LLM operation failed (e.g., HyDE generation).
    #[error("LLM error: {0}")]
    Llm(String),

    /// Configuration error.
    #[error("Configuration error: {0}")]
    Config(String),

    /// Operation timed out.
    #[error("Operation timed out: {0}")]
    Timeout(String),

    /// Invalid request parameters.
    #[error("Invalid request: {0}")]
    InvalidRequest(String),

    /// Authorization failed.
    #[error("Unauthorized: {0}")]
    Unauthorized(String),

    /// Internal error.
    #[error("Internal error: {0}")]
    Internal(String),
}

impl RetrievalError {
    /// Create a semantic search error.
    pub fn semantic_search(msg: impl Into<String>) -> Self {
        Self::SemanticSearch(msg.into())
    }

    /// Create a keyword search error.
    pub fn keyword_search(msg: impl Into<String>) -> Self {
        Self::KeywordSearch(msg.into())
    }

    /// Create an embedding error.
    pub fn embedding(msg: impl Into<String>) -> Self {
        Self::Embedding(msg.into())
    }

    /// Create a reranking error.
    pub fn reranking(msg: impl Into<String>) -> Self {
        Self::Reranking(msg.into())
    }

    /// Create a cache error.
    pub fn cache(msg: impl Into<String>) -> Self {
        Self::Cache(msg.into())
    }

    /// Create an LLM error.
    pub fn llm(msg: impl Into<String>) -> Self {
        Self::Llm(msg.into())
    }

    /// Create a config error.
    pub fn config(msg: impl Into<String>) -> Self {
        Self::Config(msg.into())
    }

    /// Create a timeout error.
    pub fn timeout(msg: impl Into<String>) -> Self {
        Self::Timeout(msg.into())
    }

    /// Create an invalid request error.
    pub fn invalid_request(msg: impl Into<String>) -> Self {
        Self::InvalidRequest(msg.into())
    }

    /// Create an unauthorized error.
    pub fn unauthorized(msg: impl Into<String>) -> Self {
        Self::Unauthorized(msg.into())
    }

    /// Create an internal error.
    pub fn internal(msg: impl Into<String>) -> Self {
        Self::Internal(msg.into())
    }

    /// Check if this error is retriable.
    #[must_use]
    pub const fn is_retriable(&self) -> bool {
        matches!(
            self,
            Self::Timeout(_) | Self::Cache(_) | Self::SemanticSearch(_) | Self::KeywordSearch(_)
        )
    }

    /// Check if this is a client error (4xx equivalent).
    #[must_use]
    pub const fn is_client_error(&self) -> bool {
        matches!(self, Self::InvalidRequest(_) | Self::Unauthorized(_))
    }
}

impl From<VectorStoreError> for RetrievalError {
    fn from(err: VectorStoreError) -> Self {
        match err {
            VectorStoreError::Timeout => Self::Timeout("Vector store operation timed out".into()),
            VectorStoreError::Config(msg) => Self::Config(msg),
            _ => Self::SemanticSearch(err.to_string()),
        }
    }
}

impl From<SearchError> for RetrievalError {
    fn from(err: SearchError) -> Self {
        match err {
            SearchError::Timeout => Self::Timeout("Search operation timed out".into()),
            SearchError::Config(msg) => Self::Config(msg),
            SearchError::Query(msg) => Self::InvalidRequest(msg),
            _ => Self::KeywordSearch(err.to_string()),
        }
    }
}

impl From<CacheError> for RetrievalError {
    fn from(err: CacheError) -> Self {
        match err {
            CacheError::Timeout(ms) => Self::Timeout(format!("Cache operation timed out after {ms}ms")),
            _ => Self::Cache(err.to_string()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_error_creation() {
        let err = RetrievalError::semantic_search("test error");
        assert!(err.to_string().contains("Semantic search error"));
        assert!(err.to_string().contains("test error"));
    }

    #[test]
    fn test_is_retriable() {
        assert!(RetrievalError::timeout("test").is_retriable());
        assert!(RetrievalError::cache("test").is_retriable());
        assert!(RetrievalError::semantic_search("test").is_retriable());
        assert!(RetrievalError::keyword_search("test").is_retriable());

        assert!(!RetrievalError::invalid_request("test").is_retriable());
        assert!(!RetrievalError::unauthorized("test").is_retriable());
        assert!(!RetrievalError::config("test").is_retriable());
    }

    #[test]
    fn test_is_client_error() {
        assert!(RetrievalError::invalid_request("test").is_client_error());
        assert!(RetrievalError::unauthorized("test").is_client_error());

        assert!(!RetrievalError::timeout("test").is_client_error());
        assert!(!RetrievalError::internal("test").is_client_error());
    }

    #[test]
    fn test_from_vector_store_error() {
        let vs_err = VectorStoreError::Timeout;
        let retrieval_err: RetrievalError = vs_err.into();
        assert!(matches!(retrieval_err, RetrievalError::Timeout(_)));

        let vs_err = VectorStoreError::Config("bad config".into());
        let retrieval_err: RetrievalError = vs_err.into();
        assert!(matches!(retrieval_err, RetrievalError::Config(_)));

        let vs_err = VectorStoreError::CollectionNotFound("test".into());
        let retrieval_err: RetrievalError = vs_err.into();
        assert!(matches!(retrieval_err, RetrievalError::SemanticSearch(_)));
    }

    #[test]
    fn test_from_search_error() {
        let search_err = SearchError::Timeout;
        let retrieval_err: RetrievalError = search_err.into();
        assert!(matches!(retrieval_err, RetrievalError::Timeout(_)));

        let search_err = SearchError::Query("bad query".into());
        let retrieval_err: RetrievalError = search_err.into();
        assert!(matches!(retrieval_err, RetrievalError::InvalidRequest(_)));

        let search_err = SearchError::IndexNotFound("test".into());
        let retrieval_err: RetrievalError = search_err.into();
        assert!(matches!(retrieval_err, RetrievalError::KeywordSearch(_)));
    }

    #[test]
    fn test_from_cache_error() {
        let cache_err = CacheError::Timeout(5000);
        let retrieval_err: RetrievalError = cache_err.into();
        assert!(matches!(retrieval_err, RetrievalError::Timeout(_)));
        assert!(retrieval_err.to_string().contains("5000ms"));

        let cache_err = CacheError::NotFound("key".into());
        let retrieval_err: RetrievalError = cache_err.into();
        assert!(matches!(retrieval_err, RetrievalError::Cache(_)));
    }
}

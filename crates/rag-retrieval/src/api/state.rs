//! Application state for the retrieval service.
//!
//! This module provides the `AppState` struct that holds all shared components
//! required by the API endpoints. The state is shared across all request handlers
//! using Axum's state extraction.

use std::sync::Arc;

use crate::acl::ACLFilter;
use crate::cache::RetrievalCache;
use crate::embedding::EmbeddingClient;
use crate::hybrid::HybridSearcher;
use crate::query::{HydeGenerator, QueryExpander};
use crate::reranking::RerankerService;

/// Application state shared across all request handlers.
///
/// This struct holds references to all components required by the API endpoints.
/// It is wrapped in an `Arc` and shared via Axum's state extraction mechanism.
///
/// # Example
///
/// ```ignore
/// use std::sync::Arc;
/// use rag_retrieval::api::AppState;
///
/// // Create the state (typically in main.rs)
/// let state = Arc::new(AppState {
///     hybrid: Arc::new(hybrid_searcher),
///     embedding: Arc::new(embedding_client),
///     reranker: Some(Arc::new(reranker)),
///     acl_filter: Arc::new(acl_filter),
///     version: "1.0.0".into(),
/// });
///
/// // Create the router with state
/// let app = create_router(state);
/// ```
pub struct AppState {
    /// The hybrid searcher for executing searches.
    pub hybrid: Arc<HybridSearcher>,

    /// The embedding client for generating query embeddings.
    pub embedding: Arc<EmbeddingClient>,

    /// The reranker service (optional).
    pub reranker: Option<Arc<RerankerService>>,

    /// Query expansion service (optional).
    pub query_expander: Option<Arc<QueryExpander>>,

    /// `HyDE` generator service (optional).
    pub hyde_generator: Option<Arc<HydeGenerator>>,

    /// The ACL filter for access control.
    pub acl_filter: Arc<ACLFilter>,

    /// The retrieval cache for caching search results (optional).
    pub retrieval_cache: Option<Arc<RetrievalCache>>,

    /// Service version string.
    pub version: String,
}

impl AppState {
    /// Create a new `AppState` builder.
    #[must_use]
    pub fn builder() -> AppStateBuilder {
        AppStateBuilder::new()
    }

    /// Get the service version.
    #[must_use]
    pub fn version(&self) -> &str {
        &self.version
    }

    /// Check if the reranker is available.
    #[must_use]
    pub fn has_reranker(&self) -> bool {
        self.reranker.is_some()
    }

    /// Check if query expansion is available.
    #[must_use]
    pub fn has_query_expander(&self) -> bool {
        self.query_expander.is_some()
    }

    /// Check if `HyDE` generation is available.
    #[must_use]
    pub fn has_hyde_generator(&self) -> bool {
        self.hyde_generator.is_some()
    }

    /// Check if the retrieval cache is available.
    #[must_use]
    pub fn has_retrieval_cache(&self) -> bool {
        self.retrieval_cache.is_some()
    }
}

#[allow(clippy::missing_fields_in_debug)]
impl std::fmt::Debug for AppState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AppState")
            .field("has_reranker", &self.reranker.is_some())
            .field("has_query_expander", &self.query_expander.is_some())
            .field("has_hyde_generator", &self.hyde_generator.is_some())
            .field("has_retrieval_cache", &self.retrieval_cache.is_some())
            .field("version", &self.version)
            .finish_non_exhaustive()
    }
}

/// Builder for constructing `AppState`.
///
/// # Example
///
/// ```ignore
/// let state = AppState::builder()
///     .hybrid(Arc::new(hybrid_searcher))
///     .embedding(Arc::new(embedding_client))
///     .acl_filter(Arc::new(acl_filter))
///     .version("1.0.0")
///     .build()?;
/// ```
pub struct AppStateBuilder {
    hybrid: Option<Arc<HybridSearcher>>,
    embedding: Option<Arc<EmbeddingClient>>,
    reranker: Option<Arc<RerankerService>>,
    query_expander: Option<Arc<QueryExpander>>,
    hyde_generator: Option<Arc<HydeGenerator>>,
    acl_filter: Option<Arc<ACLFilter>>,
    retrieval_cache: Option<Arc<RetrievalCache>>,
    version: String,
}

impl AppStateBuilder {
    /// Create a new builder with default values.
    #[must_use]
    pub fn new() -> Self {
        Self {
            hybrid: None,
            embedding: None,
            reranker: None,
            query_expander: None,
            hyde_generator: None,
            acl_filter: None,
            retrieval_cache: None,
            version: env!("CARGO_PKG_VERSION").to_string(),
        }
    }

    /// Set the hybrid searcher.
    #[must_use]
    pub fn hybrid(mut self, hybrid: Arc<HybridSearcher>) -> Self {
        self.hybrid = Some(hybrid);
        self
    }

    /// Set the embedding client.
    #[must_use]
    pub fn embedding(mut self, embedding: Arc<EmbeddingClient>) -> Self {
        self.embedding = Some(embedding);
        self
    }

    /// Set the reranker service.
    #[must_use]
    pub fn reranker(mut self, reranker: Arc<RerankerService>) -> Self {
        self.reranker = Some(reranker);
        self
    }

    /// Set the query expander service.
    #[must_use]
    pub fn query_expander(mut self, query_expander: Arc<QueryExpander>) -> Self {
        self.query_expander = Some(query_expander);
        self
    }

    /// Set the `HyDE` generator service.
    #[must_use]
    pub fn hyde_generator(mut self, hyde_generator: Arc<HydeGenerator>) -> Self {
        self.hyde_generator = Some(hyde_generator);
        self
    }

    /// Set the ACL filter.
    #[must_use]
    pub fn acl_filter(mut self, acl_filter: Arc<ACLFilter>) -> Self {
        self.acl_filter = Some(acl_filter);
        self
    }

    /// Set the retrieval cache.
    #[must_use]
    pub fn retrieval_cache(mut self, retrieval_cache: Arc<RetrievalCache>) -> Self {
        self.retrieval_cache = Some(retrieval_cache);
        self
    }

    /// Set the service version.
    #[must_use]
    pub fn version(mut self, version: impl Into<String>) -> Self {
        self.version = version.into();
        self
    }

    /// Build the `AppState`.
    ///
    /// # Errors
    ///
    /// Returns an error if required components are missing.
    pub fn build(self) -> Result<AppState, AppStateBuilderError> {
        let hybrid = self
            .hybrid
            .ok_or(AppStateBuilderError::MissingComponent("hybrid"))?;

        let embedding = self
            .embedding
            .ok_or(AppStateBuilderError::MissingComponent("embedding"))?;

        let acl_filter = self
            .acl_filter
            .ok_or(AppStateBuilderError::MissingComponent("acl_filter"))?;

        Ok(AppState {
            hybrid,
            embedding,
            reranker: self.reranker,
            query_expander: self.query_expander,
            hyde_generator: self.hyde_generator,
            acl_filter,
            retrieval_cache: self.retrieval_cache,
            version: self.version,
        })
    }
}

impl Default for AppStateBuilder {
    fn default() -> Self {
        Self::new()
    }
}

/// Error when building `AppState`.
#[derive(Debug, Clone)]
pub enum AppStateBuilderError {
    /// A required component is missing.
    MissingComponent(&'static str),
}

impl std::fmt::Display for AppStateBuilderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::MissingComponent(name) => {
                write!(f, "Missing required component: {name}")
            }
        }
    }
}

impl std::error::Error for AppStateBuilderError {}

#[cfg(test)]
mod tests {
    use super::*;

    // Note: Full tests would require mocking the components
    // These tests verify the builder pattern works

    #[test]
    fn test_app_state_builder_default() {
        let builder = AppStateBuilder::default();
        assert!(builder.hybrid.is_none());
        assert!(builder.embedding.is_none());
        assert!(builder.reranker.is_none());
        assert!(builder.query_expander.is_none());
        assert!(builder.hyde_generator.is_none());
        assert!(builder.acl_filter.is_none());
        assert!(builder.retrieval_cache.is_none());
    }

    #[test]
    fn test_app_state_builder_missing_hybrid() {
        let result = AppStateBuilder::new().build();
        assert!(result.is_err());

        let Err(AppStateBuilderError::MissingComponent(name)) = result else {
            panic!("Expected MissingComponent error, got: {result:?}");
        };
        assert_eq!(name, "hybrid");
    }

    #[test]
    fn test_app_state_builder_error_display() {
        let err = AppStateBuilderError::MissingComponent("test");
        assert_eq!(err.to_string(), "Missing required component: test");
    }
}

//! Application state.

use std::sync::Arc;

use rag_embedding::EmbeddingModelWrapper;

use crate::auth::JwtValidator;
use crate::clients::VllmClient;
use crate::config::GatewayConfig;
use crate::rate_limit::RateLimiter;
use crate::reranker::RerankerModel;

/// Shared application state.
pub struct AppState {
    /// Gateway configuration.
    pub config: GatewayConfig,
    /// Embedding model (optional).
    pub embedding_model: Option<Arc<EmbeddingModelWrapper>>,
    /// Reranker model (optional).
    pub reranker_model: Option<Arc<RerankerModel>>,
    /// vLLM client (optional).
    pub vllm_client: Option<VllmClient>,
    /// JWT validator.
    pub jwt_validator: Arc<JwtValidator>,
    /// Rate limiter.
    pub rate_limiter: Arc<RateLimiter>,
}

impl AppState {
    /// Create new application state.
    ///
    /// # Errors
    ///
    /// Returns an error if JWT validator initialization fails.
    pub fn new(config: GatewayConfig) -> crate::Result<Self> {
        let jwt_validator = Arc::new(JwtValidator::new(&config.auth)?);
        let rate_limiter = Arc::new(RateLimiter::new(config.rate_limit.clone()));

        let vllm_client = if config.vllm.enabled {
            Some(VllmClient::new(config.vllm.clone())?)
        } else {
            None
        };

        Ok(Self {
            config,
            embedding_model: None,
            reranker_model: None,
            vllm_client,
            jwt_validator,
            rate_limiter,
        })
    }

    /// Set the embedding model.
    #[must_use]
    pub fn with_embedding_model(mut self, model: EmbeddingModelWrapper) -> Self {
        self.embedding_model = Some(Arc::new(model));
        self
    }

    /// Set the reranker model.
    #[must_use]
    pub fn with_reranker_model(mut self, model: RerankerModel) -> Self {
        self.reranker_model = Some(Arc::new(model));
        self
    }
}

impl std::fmt::Debug for AppState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AppState")
            .field("embedding_model", &self.embedding_model.is_some())
            .field("reranker_model", &self.reranker_model.is_some())
            .field("vllm_client", &self.vllm_client.is_some())
            .finish_non_exhaustive()
    }
}

//! Application state for the embedding service.

use std::sync::Arc;

use crate::config::EmbeddingConfig;
use crate::model::EmbeddingModelWrapper;

/// Application state shared across request handlers.
#[derive(Clone)]
pub struct AppState {
    /// The embedding model.
    pub model: Arc<EmbeddingModelWrapper>,
    /// Service configuration.
    pub config: Arc<EmbeddingConfig>,
}

impl AppState {
    /// Create a new application state.
    #[must_use]
    pub fn new(model: EmbeddingModelWrapper, config: EmbeddingConfig) -> Self {
        Self {
            model: Arc::new(model),
            config: Arc::new(config),
        }
    }

    /// Get the model ID.
    #[must_use]
    pub fn model_id(&self) -> &str {
        self.model.model_id()
    }

    /// Get the embedding dimensions.
    #[must_use]
    pub fn dimensions(&self) -> usize {
        self.model.dimensions()
    }

    /// Get the max batch size.
    #[must_use]
    pub fn max_batch_size(&self) -> usize {
        self.config.max_batch_size
    }
}

impl std::fmt::Debug for AppState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AppState")
            .field("model_id", &self.model_id())
            .field("dimensions", &self.dimensions())
            .field("max_batch_size", &self.max_batch_size())
            .finish()
    }
}

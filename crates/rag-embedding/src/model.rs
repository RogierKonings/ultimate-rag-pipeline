//! Embedding model wrapper using fastembed.

use std::sync::Arc;

use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use tracing::{info, instrument};

use crate::config::{EmbeddingConfig, ModelType};
use crate::error::{EmbeddingError, Result};

/// Thread-safe wrapper around the fastembed model.
#[derive(Clone)]
pub struct EmbeddingModelWrapper {
    inner: Arc<TextEmbedding>,
    model_id: String,
    dimensions: usize,
}

impl EmbeddingModelWrapper {
    /// Load the embedding model based on configuration.
    ///
    /// This is a blocking operation that downloads and loads the model.
    /// Call from a blocking context or use `spawn_blocking`.
    ///
    /// # Errors
    ///
    /// Returns an error if model loading fails.
    #[instrument(skip_all, fields(model = %config.model.model_id()))]
    pub fn load(config: &EmbeddingConfig) -> Result<Self> {
        info!("Loading embedding model: {}", config.model.model_id());

        let start = std::time::Instant::now();

        let embedding_model = model_type_to_fastembed(config.model);

        let model = TextEmbedding::try_new(
            InitOptions::new(embedding_model).with_show_download_progress(true),
        )
        .map_err(|e| EmbeddingError::model_load(e.to_string()))?;

        let elapsed = start.elapsed();
        info!(
            "Model loaded in {:.2}s. Embedding dimension: {}",
            elapsed.as_secs_f64(),
            config.model.dimensions()
        );

        Ok(Self {
            inner: Arc::new(model),
            model_id: config.model.model_id().to_string(),
            dimensions: config.model.dimensions(),
        })
    }

    /// Generate embeddings for the given texts.
    ///
    /// Embeddings are L2-normalized by fastembed.
    ///
    /// # Errors
    ///
    /// Returns an error if embedding generation fails.
    #[instrument(skip(self, texts), fields(num_texts = texts.len()))]
    pub fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }

        let text_refs: Vec<&str> = texts.iter().map(String::as_str).collect();

        self.inner
            .embed(text_refs, None)
            .map_err(|e| EmbeddingError::inference(e.to_string()))
    }

    /// Get the model identifier.
    #[must_use]
    pub fn model_id(&self) -> &str {
        &self.model_id
    }

    /// Get the embedding dimensions.
    #[must_use]
    pub const fn dimensions(&self) -> usize {
        self.dimensions
    }
}

/// Convert our [`ModelType`] to fastembed's [`EmbeddingModel`] enum.
const fn model_type_to_fastembed(model_type: ModelType) -> EmbeddingModel {
    match model_type {
        ModelType::AllMiniLmL6V2 => EmbeddingModel::AllMiniLML6V2,
        ModelType::BgeSmallEnV15 => EmbeddingModel::BGESmallENV15,
    }
}

impl std::fmt::Debug for EmbeddingModelWrapper {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EmbeddingModelWrapper")
            .field("model_id", &self.model_id)
            .field("dimensions", &self.dimensions)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_model_type_to_fastembed() {
        // Just verify the mapping compiles and doesn't panic
        let _ = model_type_to_fastembed(ModelType::AllMiniLmL6V2);
        let _ = model_type_to_fastembed(ModelType::BgeSmallEnV15);
    }
}

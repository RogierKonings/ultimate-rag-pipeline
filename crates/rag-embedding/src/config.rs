//! Configuration for the embedding service.

use std::env;

/// Supported embedding models.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModelType {
    /// all-MiniLM-L6-v2 (384 dimensions)
    AllMiniLmL6V2,
    /// BAAI/bge-small-en-v1.5 (384 dimensions)
    BgeSmallEnV15,
}

impl ModelType {
    /// Get the HuggingFace model ID.
    #[must_use]
    pub const fn model_id(&self) -> &'static str {
        match self {
            Self::AllMiniLmL6V2 => "sentence-transformers/all-MiniLM-L6-v2",
            Self::BgeSmallEnV15 => "BAAI/bge-small-en-v1.5",
        }
    }

    /// Get the embedding dimensions.
    #[must_use]
    pub const fn dimensions(&self) -> usize {
        match self {
            Self::AllMiniLmL6V2 | Self::BgeSmallEnV15 => 384,
        }
    }

    /// Parse from model ID string.
    #[must_use]
    pub fn from_model_id(id: &str) -> Option<Self> {
        match id {
            "sentence-transformers/all-MiniLM-L6-v2" | "all-MiniLM-L6-v2" => {
                Some(Self::AllMiniLmL6V2)
            }
            "BAAI/bge-small-en-v1.5" | "bge-small-en-v1.5" => Some(Self::BgeSmallEnV15),
            _ => None,
        }
    }
}

impl Default for ModelType {
    fn default() -> Self {
        Self::AllMiniLmL6V2
    }
}

/// Configuration for the embedding service.
#[derive(Debug, Clone)]
pub struct EmbeddingConfig {
    /// Model to use for embeddings.
    pub model: ModelType,
    /// Maximum batch size per request.
    pub max_batch_size: usize,
    /// Server host.
    pub host: String,
    /// Server port.
    pub port: u16,
}

impl EmbeddingConfig {
    /// Create configuration from environment variables.
    ///
    /// Environment variables:
    /// - `EMBEDDING_MODEL`: Model ID (default: "sentence-transformers/all-MiniLM-L6-v2")
    /// - `EMBEDDING_BATCH_SIZE`: Max batch size (default: 32)
    /// - `EMBEDDING_HOST`: Server host (default: "0.0.0.0")
    /// - `EMBEDDING_PORT`: Server port (default: 8080)
    #[must_use]
    pub fn from_env() -> Self {
        let model_id = env::var("EMBEDDING_MODEL")
            .unwrap_or_else(|_| "sentence-transformers/all-MiniLM-L6-v2".into());

        let model = ModelType::from_model_id(&model_id).unwrap_or_default();

        let max_batch_size = env::var("EMBEDDING_BATCH_SIZE")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(32);

        let host = env::var("EMBEDDING_HOST").unwrap_or_else(|_| "0.0.0.0".into());

        let port = env::var("EMBEDDING_PORT")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(8080);

        Self {
            model,
            max_batch_size,
            host,
            port,
        }
    }

    /// Get the socket address for the server.
    #[must_use]
    pub fn addr(&self) -> std::net::SocketAddr {
        format!("{}:{}", self.host, self.port)
            .parse()
            .expect("Invalid socket address")
    }
}

impl Default for EmbeddingConfig {
    fn default() -> Self {
        Self {
            model: ModelType::default(),
            max_batch_size: 32,
            host: "0.0.0.0".into(),
            port: 8080,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_model_type_dimensions() {
        assert_eq!(ModelType::AllMiniLmL6V2.dimensions(), 384);
        assert_eq!(ModelType::BgeSmallEnV15.dimensions(), 384);
    }

    #[test]
    fn test_model_type_from_model_id() {
        assert_eq!(
            ModelType::from_model_id("sentence-transformers/all-MiniLM-L6-v2"),
            Some(ModelType::AllMiniLmL6V2)
        );
        assert_eq!(
            ModelType::from_model_id("all-MiniLM-L6-v2"),
            Some(ModelType::AllMiniLmL6V2)
        );
        assert_eq!(
            ModelType::from_model_id("BAAI/bge-small-en-v1.5"),
            Some(ModelType::BgeSmallEnV15)
        );
        assert_eq!(ModelType::from_model_id("unknown-model"), None);
    }

    #[test]
    fn test_config_default() {
        let config = EmbeddingConfig::default();
        assert_eq!(config.model, ModelType::AllMiniLmL6V2);
        assert_eq!(config.max_batch_size, 32);
        assert_eq!(config.port, 8080);
    }

    #[test]
    fn test_config_addr() {
        let config = EmbeddingConfig::default();
        let addr = config.addr();
        assert_eq!(addr.port(), 8080);
    }
}

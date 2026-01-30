//! Embedding service for RAG Pipeline.
//!
//! Provides text embeddings using fastembed ONNX-based inference
//! with an OpenAI-compatible REST API.
//!
//! # Architecture
//!
//! The service wraps the `fastembed` library to provide
//! efficient ONNX-based text embeddings. It supports:
//!
//! - `all-MiniLM-L6-v2` (384 dimensions)
//! - `BAAI/bge-small-en-v1.5` (384 dimensions)
//!
//! # API Endpoints
//!
//! - `POST /v1/embeddings` - Generate embeddings (OpenAI-compatible)
//! - `GET /v1/models` - List available models
//! - `GET /health` - Health check
//! - `GET /` - Service info
//!
//! # Example
//!
//! ```ignore
//! use rag_embedding::config::EmbeddingConfig;
//! use rag_embedding::model::EmbeddingModelWrapper;
//!
//! let config = EmbeddingConfig::from_env();
//! let model = EmbeddingModelWrapper::load(&config)?;
//!
//! let embeddings = model.embed(&["Hello world".into()])?;
//! println!("Embedding dimension: {}", embeddings[0].len());
//! ```

pub mod api;
pub mod config;
pub mod error;
pub mod model;

// Re-export main types
pub use config::{EmbeddingConfig, ModelType};
pub use error::{EmbeddingError, Result};
pub use model::EmbeddingModelWrapper;

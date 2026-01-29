# Rust Embedding Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the Python embedding service with a Rust implementation using Candle for ML inference.

**Architecture:** Standalone Axum HTTP service wrapping `sentence-transformers-rs` (Candle-based) for embedding generation. OpenAI-compatible API for drop-in replacement of Python service.

**Tech Stack:** Rust, Axum, sentence-transformers-rs, Candle, tokio, serde

---

## Task 1: Create Crate Scaffold

**Files:**
- Create: `crates/rag-embedding/Cargo.toml`
- Create: `crates/rag-embedding/src/lib.rs`
- Modify: `crates/Cargo.toml` (add to workspace members)

**Step 1: Create Cargo.toml**

```toml
[package]
name = "rag-embedding"
description = "Embedding service for RAG Pipeline - Candle-based text embeddings"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
repository.workspace = true

[dependencies]
# ML inference
sentence-transformers = "0.3"

# HTTP server
axum = "0.7"
tower = "0.4"
tower-http = { version = "0.5", features = ["trace", "cors", "timeout"] }

# Async runtime
tokio = { workspace = true }

# Serialization
serde = { workspace = true }
serde_json = { workspace = true }

# Error handling
thiserror = { workspace = true }

# Logging
tracing = { workspace = true }
tracing-subscriber = { version = "0.3", features = ["env-filter"] }

[dev-dependencies]
tokio-test = { workspace = true }

[[bin]]
name = "embedding-service"
path = "src/bin/main.rs"

[lints]
workspace = true
```

**Step 2: Create minimal lib.rs**

```rust
//! Embedding service for RAG Pipeline.
//!
//! Provides text embeddings using Candle-based sentence transformers
//! with an OpenAI-compatible REST API.

pub mod config;
pub mod error;
pub mod model;
pub mod api;
```

**Step 3: Add to workspace Cargo.toml**

In `crates/Cargo.toml`, add `"rag-embedding"` to the `members` array.

**Step 4: Verify crate compiles**

Run: `cd crates && cargo check -p rag-embedding`
Expected: Compilation errors about missing modules (this is expected, we'll create them next)

**Step 5: Commit scaffold**

```bash
git add crates/rag-embedding/Cargo.toml crates/rag-embedding/src/lib.rs crates/Cargo.toml
git commit -m "feat(rag-embedding): add crate scaffold"
```

---

## Task 2: Implement Error Types

**Files:**
- Create: `crates/rag-embedding/src/error.rs`
- Test: Unit tests inline

**Step 1: Write the error module**

```rust
//! Error types for embedding operations.

use thiserror::Error;

/// Result type for embedding operations.
pub type Result<T> = std::result::Result<T, EmbeddingError>;

/// Errors that can occur during embedding operations.
#[derive(Debug, Error)]
pub enum EmbeddingError {
    /// Model loading failed.
    #[error("Failed to load model: {0}")]
    ModelLoad(String),

    /// Embedding generation failed.
    #[error("Embedding generation failed: {0}")]
    Inference(String),

    /// Invalid input provided.
    #[error("Invalid input: {0}")]
    InvalidInput(String),

    /// Model not ready (still loading).
    #[error("Model not ready: {0}")]
    NotReady(String),

    /// Configuration error.
    #[error("Configuration error: {0}")]
    Config(String),
}

impl EmbeddingError {
    /// Create a model load error.
    pub fn model_load(msg: impl Into<String>) -> Self {
        Self::ModelLoad(msg.into())
    }

    /// Create an inference error.
    pub fn inference(msg: impl Into<String>) -> Self {
        Self::Inference(msg.into())
    }

    /// Create an invalid input error.
    pub fn invalid_input(msg: impl Into<String>) -> Self {
        Self::InvalidInput(msg.into())
    }

    /// Create a not ready error.
    pub fn not_ready(msg: impl Into<String>) -> Self {
        Self::NotReady(msg.into())
    }

    /// Create a config error.
    pub fn config(msg: impl Into<String>) -> Self {
        Self::Config(msg.into())
    }

    /// Check if this is a client error (4xx equivalent).
    #[must_use]
    pub const fn is_client_error(&self) -> bool {
        matches!(self, Self::InvalidInput(_))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_error_creation() {
        let err = EmbeddingError::model_load("test error");
        assert!(err.to_string().contains("Failed to load model"));
        assert!(err.to_string().contains("test error"));
    }

    #[test]
    fn test_is_client_error() {
        assert!(EmbeddingError::invalid_input("test").is_client_error());
        assert!(!EmbeddingError::model_load("test").is_client_error());
        assert!(!EmbeddingError::inference("test").is_client_error());
    }
}
```

**Step 2: Run tests**

Run: `cd crates && cargo test -p rag-embedding`
Expected: PASS (2 tests)

**Step 3: Commit**

```bash
git add crates/rag-embedding/src/error.rs
git commit -m "feat(rag-embedding): add error types"
```

---

## Task 3: Implement Configuration

**Files:**
- Create: `crates/rag-embedding/src/config.rs`
- Test: Unit tests inline

**Step 1: Write the config module**

```rust
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
```

**Step 2: Run tests**

Run: `cd crates && cargo test -p rag-embedding`
Expected: PASS (all tests)

**Step 3: Commit**

```bash
git add crates/rag-embedding/src/config.rs
git commit -m "feat(rag-embedding): add configuration module"
```

---

## Task 4: Implement Model Wrapper

**Files:**
- Create: `crates/rag-embedding/src/model.rs`
- Test: Unit tests inline (model loading tested in integration)

**Step 1: Write the model wrapper**

```rust
//! Embedding model wrapper using sentence-transformers-rs.

use std::sync::Arc;

use sentence_transformers::{SentenceTransformer, SentenceTransformerBuilder, Which};
use tracing::{info, instrument};

use crate::config::{EmbeddingConfig, ModelType};
use crate::error::{EmbeddingError, Result};

/// Thread-safe wrapper around the sentence transformer model.
#[derive(Clone)]
pub struct EmbeddingModel {
    inner: Arc<SentenceTransformer>,
    model_id: String,
    dimensions: usize,
}

impl EmbeddingModel {
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

        let which = model_type_to_which(config.model);

        let model = SentenceTransformerBuilder::with_sentence_transformer(&which)
            .build()
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
    /// Embeddings are L2-normalized.
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
            .embed(&text_refs)
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

/// Convert our ModelType to sentence-transformers Which enum.
fn model_type_to_which(model_type: ModelType) -> Which {
    match model_type {
        ModelType::AllMiniLmL6V2 => Which::AllMiniLML6v2,
        ModelType::BgeSmallEnV15 => Which::BgeSmallEnV1_5,
    }
}

impl std::fmt::Debug for EmbeddingModel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EmbeddingModel")
            .field("model_id", &self.model_id)
            .field("dimensions", &self.dimensions)
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_model_type_to_which() {
        // Just verify the mapping compiles and doesn't panic
        let _ = model_type_to_which(ModelType::AllMiniLmL6V2);
        let _ = model_type_to_which(ModelType::BgeSmallEnV15);
    }
}
```

**Step 2: Run tests**

Run: `cd crates && cargo test -p rag-embedding`
Expected: PASS

**Step 3: Commit**

```bash
git add crates/rag-embedding/src/model.rs
git commit -m "feat(rag-embedding): add model wrapper"
```

---

## Task 5: Implement API Types

**Files:**
- Create: `crates/rag-embedding/src/api/mod.rs`
- Create: `crates/rag-embedding/src/api/types.rs`
- Test: Unit tests inline

**Step 1: Create api/mod.rs**

```rust
//! HTTP API for the embedding service.

pub mod error;
pub mod routes;
pub mod state;
pub mod types;

pub use error::{ApiError, ApiResult};
pub use routes::create_router;
pub use state::AppState;
pub use types::{EmbeddingRequest, EmbeddingResponse};
```

**Step 2: Create api/types.rs**

```rust
//! Request and response types for the embedding API.
//!
//! These types are OpenAI-compatible for drop-in replacement.

use serde::{Deserialize, Serialize};

/// Input can be a single string or array of strings.
#[derive(Debug, Clone, Deserialize)]
#[serde(untagged)]
pub enum StringOrArray {
    /// Single string input.
    Single(String),
    /// Array of string inputs.
    Array(Vec<String>),
}

impl StringOrArray {
    /// Convert to a vector of strings.
    #[must_use]
    pub fn into_vec(self) -> Vec<String> {
        match self {
            Self::Single(s) => vec![s],
            Self::Array(v) => v,
        }
    }

    /// Check if empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        match self {
            Self::Single(s) => s.is_empty(),
            Self::Array(v) => v.is_empty() || v.iter().all(String::is_empty),
        }
    }

    /// Get the number of items.
    #[must_use]
    pub fn len(&self) -> usize {
        match self {
            Self::Single(_) => 1,
            Self::Array(v) => v.len(),
        }
    }
}

/// OpenAI-compatible embedding request.
#[derive(Debug, Clone, Deserialize)]
pub struct EmbeddingRequest {
    /// Input text(s) to embed.
    pub input: StringOrArray,
    /// Model to use (ignored, uses configured model).
    #[serde(default)]
    pub model: Option<String>,
    /// Encoding format (only "float" supported).
    #[serde(default = "default_encoding_format")]
    pub encoding_format: String,
}

fn default_encoding_format() -> String {
    "float".into()
}

/// Single embedding result.
#[derive(Debug, Clone, Serialize)]
pub struct EmbeddingData {
    /// The embedding vector.
    pub embedding: Vec<f32>,
    /// Index of the input text.
    pub index: usize,
    /// Object type (always "embedding").
    pub object: &'static str,
}

impl EmbeddingData {
    /// Create a new embedding data object.
    #[must_use]
    pub fn new(embedding: Vec<f32>, index: usize) -> Self {
        Self {
            embedding,
            index,
            object: "embedding",
        }
    }
}

/// Token usage information.
#[derive(Debug, Clone, Serialize)]
pub struct Usage {
    /// Number of tokens in the input prompts.
    pub prompt_tokens: usize,
    /// Total tokens used.
    pub total_tokens: usize,
}

impl Usage {
    /// Estimate token count from texts.
    ///
    /// Uses rough approximation: ~0.75 tokens per word.
    #[must_use]
    pub fn estimate(texts: &[String]) -> Self {
        let total: usize = texts
            .iter()
            .map(|t| (t.split_whitespace().count() as f64 * 0.75).ceil() as usize)
            .sum();

        Self {
            prompt_tokens: total,
            total_tokens: total,
        }
    }
}

/// OpenAI-compatible embedding response.
#[derive(Debug, Clone, Serialize)]
pub struct EmbeddingResponse {
    /// Embedding data for each input.
    pub data: Vec<EmbeddingData>,
    /// Model used for generation.
    pub model: String,
    /// Object type (always "list").
    pub object: &'static str,
    /// Token usage.
    pub usage: Usage,
}

impl EmbeddingResponse {
    /// Create a new embedding response.
    #[must_use]
    pub fn new(embeddings: Vec<Vec<f32>>, model: String, texts: &[String]) -> Self {
        let data = embeddings
            .into_iter()
            .enumerate()
            .map(|(i, emb)| EmbeddingData::new(emb, i))
            .collect();

        Self {
            data,
            model,
            object: "list",
            usage: Usage::estimate(texts),
        }
    }
}

/// Health check response.
#[derive(Debug, Clone, Serialize)]
pub struct HealthResponse {
    /// Service status.
    pub status: String,
    /// Model identifier.
    pub model: String,
    /// Embedding dimensions (None if still loading).
    pub dimension: Option<usize>,
    /// Maximum batch size.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_batch_size: Option<usize>,
    /// Additional message.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

/// Model information for /v1/models endpoint.
#[derive(Debug, Clone, Serialize)]
pub struct ModelInfo {
    /// Model identifier.
    pub id: String,
    /// Object type.
    pub object: &'static str,
    /// Creation timestamp.
    pub created: i64,
    /// Owner.
    pub owned_by: &'static str,
    /// Permissions (empty).
    pub permission: Vec<()>,
    /// Root model.
    pub root: String,
    /// Parent model.
    pub parent: Option<String>,
    /// Model metadata.
    pub metadata: ModelMetadata,
}

/// Model metadata.
#[derive(Debug, Clone, Serialize)]
pub struct ModelMetadata {
    /// Embedding dimensions.
    pub dimension: usize,
    /// Maximum batch size.
    pub max_batch_size: usize,
}

/// List models response.
#[derive(Debug, Clone, Serialize)]
pub struct ModelsResponse {
    /// Object type.
    pub object: &'static str,
    /// Available models.
    pub data: Vec<ModelInfo>,
}

/// Service info response for root endpoint.
#[derive(Debug, Clone, Serialize)]
pub struct ServiceInfo {
    /// Service name.
    pub service: &'static str,
    /// Service version.
    pub version: &'static str,
    /// Loaded model.
    pub model: String,
    /// Available endpoints.
    pub endpoints: ServiceEndpoints,
}

/// Available endpoints.
#[derive(Debug, Clone, Serialize)]
pub struct ServiceEndpoints {
    /// Embeddings endpoint.
    pub embeddings: &'static str,
    /// Models endpoint.
    pub models: &'static str,
    /// Health endpoint.
    pub health: &'static str,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_string_or_array_single() {
        let input = StringOrArray::Single("hello".into());
        assert_eq!(input.len(), 1);
        assert!(!input.is_empty());
        assert_eq!(input.into_vec(), vec!["hello"]);
    }

    #[test]
    fn test_string_or_array_array() {
        let input = StringOrArray::Array(vec!["hello".into(), "world".into()]);
        assert_eq!(input.len(), 2);
        assert!(!input.is_empty());
        assert_eq!(input.into_vec(), vec!["hello", "world"]);
    }

    #[test]
    fn test_usage_estimate() {
        let texts = vec!["hello world".into(), "foo bar baz".into()];
        let usage = Usage::estimate(&texts);
        // 2 words + 3 words = 5 words * 0.75 ≈ 4 tokens
        assert!(usage.total_tokens >= 3);
        assert!(usage.total_tokens <= 5);
    }

    #[test]
    fn test_embedding_response_creation() {
        let embeddings = vec![vec![0.1, 0.2], vec![0.3, 0.4]];
        let texts = vec!["hello".into(), "world".into()];
        let response = EmbeddingResponse::new(embeddings, "test-model".into(), &texts);

        assert_eq!(response.data.len(), 2);
        assert_eq!(response.data[0].index, 0);
        assert_eq!(response.data[1].index, 1);
        assert_eq!(response.object, "list");
        assert_eq!(response.model, "test-model");
    }

    #[test]
    fn test_deserialize_embedding_request_single() {
        let json = r#"{"input": "hello world"}"#;
        let request: EmbeddingRequest = serde_json::from_str(json).unwrap();
        assert_eq!(request.input.len(), 1);
    }

    #[test]
    fn test_deserialize_embedding_request_array() {
        let json = r#"{"input": ["hello", "world"], "model": "test"}"#;
        let request: EmbeddingRequest = serde_json::from_str(json).unwrap();
        assert_eq!(request.input.len(), 2);
        assert_eq!(request.model, Some("test".into()));
    }
}
```

**Step 3: Run tests**

Run: `cd crates && cargo test -p rag-embedding`
Expected: PASS

**Step 4: Commit**

```bash
git add crates/rag-embedding/src/api/mod.rs crates/rag-embedding/src/api/types.rs
git commit -m "feat(rag-embedding): add API types"
```

---

## Task 6: Implement API State

**Files:**
- Create: `crates/rag-embedding/src/api/state.rs`

**Step 1: Write the state module**

```rust
//! Application state for the embedding service.

use std::sync::Arc;

use crate::config::EmbeddingConfig;
use crate::model::EmbeddingModel;

/// Application state shared across request handlers.
#[derive(Clone)]
pub struct AppState {
    /// The embedding model.
    pub model: Arc<EmbeddingModel>,
    /// Service configuration.
    pub config: Arc<EmbeddingConfig>,
}

impl AppState {
    /// Create a new application state.
    #[must_use]
    pub fn new(model: EmbeddingModel, config: EmbeddingConfig) -> Self {
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
```

**Step 2: Run check**

Run: `cd crates && cargo check -p rag-embedding`
Expected: Success (with warnings about unused imports, that's fine)

**Step 3: Commit**

```bash
git add crates/rag-embedding/src/api/state.rs
git commit -m "feat(rag-embedding): add API state"
```

---

## Task 7: Implement API Errors

**Files:**
- Create: `crates/rag-embedding/src/api/error.rs`

**Step 1: Write the API error module**

```rust
//! API error handling for the embedding service.

use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Serialize;

use crate::error::EmbeddingError;

/// Result type for API operations.
pub type ApiResult<T> = std::result::Result<T, ApiError>;

/// API error with HTTP status and JSON body.
#[derive(Debug)]
pub struct ApiError {
    status: StatusCode,
    message: String,
}

impl ApiError {
    /// Create a bad request error (400).
    pub fn bad_request(msg: impl Into<String>) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            message: msg.into(),
        }
    }

    /// Create a service unavailable error (503).
    pub fn service_unavailable(msg: impl Into<String>) -> Self {
        Self {
            status: StatusCode::SERVICE_UNAVAILABLE,
            message: msg.into(),
        }
    }

    /// Create an internal server error (500).
    pub fn internal(msg: impl Into<String>) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            message: msg.into(),
        }
    }
}

impl From<EmbeddingError> for ApiError {
    fn from(err: EmbeddingError) -> Self {
        match &err {
            EmbeddingError::InvalidInput(_) => Self::bad_request(err.to_string()),
            EmbeddingError::NotReady(_) => Self::service_unavailable(err.to_string()),
            _ => Self::internal(err.to_string()),
        }
    }
}

/// Error response body.
#[derive(Debug, Serialize)]
struct ErrorBody {
    error: ErrorDetail,
}

#[derive(Debug, Serialize)]
struct ErrorDetail {
    message: String,
    r#type: &'static str,
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let error_type = match self.status {
            StatusCode::BAD_REQUEST => "invalid_request_error",
            StatusCode::SERVICE_UNAVAILABLE => "service_unavailable",
            _ => "internal_error",
        };

        let body = ErrorBody {
            error: ErrorDetail {
                message: self.message,
                r#type: error_type,
            },
        };

        (self.status, Json(body)).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_api_error_from_embedding_error() {
        let err = EmbeddingError::invalid_input("test");
        let api_err: ApiError = err.into();
        assert_eq!(api_err.status, StatusCode::BAD_REQUEST);

        let err = EmbeddingError::not_ready("loading");
        let api_err: ApiError = err.into();
        assert_eq!(api_err.status, StatusCode::SERVICE_UNAVAILABLE);

        let err = EmbeddingError::inference("failed");
        let api_err: ApiError = err.into();
        assert_eq!(api_err.status, StatusCode::INTERNAL_SERVER_ERROR);
    }
}
```

**Step 2: Run tests**

Run: `cd crates && cargo test -p rag-embedding`
Expected: PASS

**Step 3: Commit**

```bash
git add crates/rag-embedding/src/api/error.rs
git commit -m "feat(rag-embedding): add API error handling"
```

---

## Task 8: Implement API Routes

**Files:**
- Create: `crates/rag-embedding/src/api/routes.rs`

**Step 1: Write the routes module**

```rust
//! HTTP routes for the embedding service.

use std::sync::Arc;
use std::time::Instant;

use axum::{
    extract::State,
    routing::{get, post},
    Json, Router,
};
use tracing::{info, instrument};

use super::error::{ApiError, ApiResult};
use super::state::AppState;
use super::types::{
    EmbeddingRequest, EmbeddingResponse, HealthResponse, ModelInfo, ModelMetadata,
    ModelsResponse, ServiceEndpoints, ServiceInfo,
};

/// Create the Axum router with all routes.
pub fn create_router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/", get(root))
        .route("/health", get(health))
        .route("/v1/embeddings", post(create_embeddings))
        .route("/v1/models", get(list_models))
        .with_state(state)
}

/// Root endpoint with service info.
async fn root(State(state): State<Arc<AppState>>) -> Json<ServiceInfo> {
    Json(ServiceInfo {
        service: "embedding-service",
        version: env!("CARGO_PKG_VERSION"),
        model: state.model_id().to_string(),
        endpoints: ServiceEndpoints {
            embeddings: "/v1/embeddings",
            models: "/v1/models",
            health: "/health",
        },
    })
}

/// Health check endpoint.
async fn health(State(state): State<Arc<AppState>>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "healthy".into(),
        model: state.model_id().to_string(),
        dimension: Some(state.dimensions()),
        max_batch_size: Some(state.max_batch_size()),
        message: None,
    })
}

/// Create embeddings endpoint (OpenAI-compatible).
#[instrument(skip(state, request), fields(num_inputs = request.input.len()))]
async fn create_embeddings(
    State(state): State<Arc<AppState>>,
    Json(request): Json<EmbeddingRequest>,
) -> ApiResult<Json<EmbeddingResponse>> {
    // Validate input
    if request.input.is_empty() {
        return Err(ApiError::bad_request("Input cannot be empty"));
    }

    let texts = request.input.into_vec();

    if texts.len() > state.max_batch_size() {
        return Err(ApiError::bad_request(format!(
            "Batch size {} exceeds maximum {}",
            texts.len(),
            state.max_batch_size()
        )));
    }

    let start = Instant::now();

    // Run embedding in blocking task to avoid blocking the runtime
    let model = state.model.clone();
    let texts_clone = texts.clone();

    let embeddings = tokio::task::spawn_blocking(move || model.embed(&texts_clone))
        .await
        .map_err(|e| ApiError::internal(format!("Task failed: {e}")))?
        .map_err(ApiError::from)?;

    let elapsed_ms = start.elapsed().as_secs_f64() * 1000.0;
    info!(
        num_embeddings = embeddings.len(),
        elapsed_ms = format!("{:.2}", elapsed_ms),
        per_text_ms = format!("{:.2}", elapsed_ms / texts.len() as f64),
        "Generated embeddings"
    );

    let response = EmbeddingResponse::new(embeddings, state.model_id().to_string(), &texts);

    Ok(Json(response))
}

/// List available models endpoint (OpenAI-compatible).
async fn list_models(State(state): State<Arc<AppState>>) -> Json<ModelsResponse> {
    Json(ModelsResponse {
        object: "list",
        data: vec![ModelInfo {
            id: state.model_id().to_string(),
            object: "model",
            created: 0,
            owned_by: "local",
            permission: vec![],
            root: state.model_id().to_string(),
            parent: None,
            metadata: ModelMetadata {
                dimension: state.dimensions(),
                max_batch_size: state.max_batch_size(),
            },
        }],
    })
}
```

**Step 2: Run check**

Run: `cd crates && cargo check -p rag-embedding`
Expected: Success

**Step 3: Commit**

```bash
git add crates/rag-embedding/src/api/routes.rs
git commit -m "feat(rag-embedding): add API routes"
```

---

## Task 9: Implement Service Binary

**Files:**
- Create: `crates/rag-embedding/src/bin/main.rs`

**Step 1: Write the main binary**

```rust
//! Embedding Service - Rust HTTP Binary
//!
//! Provides OpenAI-compatible text embeddings using Candle-based
//! sentence transformers.
//!
//! # API Endpoints
//!
//! - `POST /v1/embeddings` - Generate embeddings
//! - `GET /v1/models` - List available models
//! - `GET /health` - Health check
//! - `GET /` - Service info

use std::sync::Arc;

use tokio::signal;
use tracing::{error, info};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};

use rag_embedding::api::{create_router, AppState};
use rag_embedding::config::EmbeddingConfig;
use rag_embedding::model::EmbeddingModel;

#[tokio::main]
async fn main() {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(EnvFilter::try_from_default_env().unwrap_or_else(|_| {
            "embedding_service=info,rag_embedding=info,tower_http=info".into()
        }))
        .with(tracing_subscriber::fmt::layer())
        .init();

    info!(
        "Starting Rust Embedding Service v{}",
        env!("CARGO_PKG_VERSION")
    );

    // Load configuration
    let config = EmbeddingConfig::from_env();
    info!(
        model = %config.model.model_id(),
        max_batch_size = config.max_batch_size,
        "Configuration loaded"
    );

    // Load model (blocking operation)
    info!("Loading embedding model: {}", config.model.model_id());
    let model = match EmbeddingModel::load(&config) {
        Ok(model) => model,
        Err(e) => {
            error!("Failed to load model: {}", e);
            std::process::exit(1);
        }
    };

    info!(
        "Model loaded. Embedding dimension: {}",
        model.dimensions()
    );

    // Create application state
    let state = Arc::new(AppState::new(model, config.clone()));

    // Create router
    let app = create_router(state);

    // Bind and serve
    let addr = config.addr();
    info!("Embedding service listening on {}", addr);

    let listener = match tokio::net::TcpListener::bind(addr).await {
        Ok(listener) => listener,
        Err(e) => {
            error!("Failed to bind to {}: {}", addr, e);
            std::process::exit(1);
        }
    };

    // Run with graceful shutdown
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .unwrap_or_else(|e| {
            error!("Server error: {}", e);
            std::process::exit(1);
        });

    info!("Server shut down successfully");
}

async fn shutdown_signal() {
    let ctrl_c = async {
        signal::ctrl_c()
            .await
            .expect("Failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        signal::unix::signal(signal::unix::SignalKind::terminate())
            .expect("Failed to install SIGTERM handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        () = ctrl_c => info!("Received Ctrl+C, shutting down"),
        () = terminate => info!("Received SIGTERM, shutting down"),
    }
}
```

**Step 2: Run check**

Run: `cd crates && cargo check -p rag-embedding`
Expected: Success

**Step 3: Commit**

```bash
git add crates/rag-embedding/src/bin/main.rs
git commit -m "feat(rag-embedding): add service binary"
```

---

## Task 10: Update lib.rs Exports

**Files:**
- Modify: `crates/rag-embedding/src/lib.rs`

**Step 1: Update lib.rs with proper exports**

```rust
//! Embedding service for RAG Pipeline.
//!
//! Provides text embeddings using Candle-based sentence transformers
//! with an OpenAI-compatible REST API.
//!
//! # Architecture
//!
//! The service wraps the `sentence-transformers-rs` library to provide
//! efficient CPU-based text embeddings. It supports:
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
//! use rag_embedding::model::EmbeddingModel;
//!
//! let config = EmbeddingConfig::from_env();
//! let model = EmbeddingModel::load(&config)?;
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
pub use model::EmbeddingModel;
```

**Step 2: Run check and tests**

Run: `cd crates && cargo test -p rag-embedding`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add crates/rag-embedding/src/lib.rs
git commit -m "feat(rag-embedding): update lib.rs exports"
```

---

## Task 11: Build and Verify

**Files:**
- None (verification only)

**Step 1: Build the crate**

Run: `cd crates && cargo build -p rag-embedding`
Expected: Successful build

**Step 2: Run all tests**

Run: `cd crates && cargo test -p rag-embedding`
Expected: All tests PASS

**Step 3: Run clippy**

Run: `cd crates && cargo clippy -p rag-embedding -- -D warnings`
Expected: No warnings

**Step 4: Verify binary exists**

Run: `ls -la crates/target/debug/embedding-service`
Expected: Binary exists

---

## Task 12: Create Dockerfile

**Files:**
- Create: `crates/rag-embedding/Dockerfile`

**Step 1: Write the Dockerfile**

```dockerfile
# Build stage
FROM rust:1.75-bookworm AS builder

WORKDIR /app

# Install dependencies for ML
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy workspace files
COPY Cargo.toml Cargo.lock ./
COPY rag-types ./rag-types
COPY rag-config ./rag-config
COPY rag-embedding ./rag-embedding

# Build release binary
RUN cargo build --release -p rag-embedding

# Runtime stage
FROM debian:bookworm-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    libssl3 \
    && rm -rf /var/lib/apt/lists/*

# Copy binary
COPY --from=builder /app/target/release/embedding-service /app/embedding-service

# Set environment variables
ENV EMBEDDING_HOST=0.0.0.0
ENV EMBEDDING_PORT=8080
ENV RUST_LOG=info

EXPOSE 8080

CMD ["/app/embedding-service"]
```

**Step 2: Commit**

```bash
git add crates/rag-embedding/Dockerfile
git commit -m "feat(rag-embedding): add Dockerfile"
```

---

## Task 13: Update Docker Compose

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Update docker-compose.yml**

Replace the Python embedding service with the Rust version. Find the existing `embedding-service` entry and replace with:

```yaml
  embedding-service:
    build:
      context: ./crates
      dockerfile: rag-embedding/Dockerfile
    ports:
      - "8080:8080"
    environment:
      - EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
      - EMBEDDING_BATCH_SIZE=32
      - EMBEDDING_HOST=0.0.0.0
      - EMBEDDING_PORT=8080
      - RUST_LOG=info
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    restart: unless-stopped
```

**Step 2: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: update docker-compose to use Rust embedding service"
```

---

## Task 14: Delete Python Service Files

**Files:**
- Delete: `services/embedding/main.py`
- Delete: `services/embedding/Dockerfile.cpu`

**Step 1: Remove Python service files**

```bash
rm -f services/embedding/main.py services/embedding/Dockerfile.cpu
rmdir services/embedding 2>/dev/null || true
```

**Step 2: Commit**

```bash
git add -A
git commit -m "feat!: remove Python embedding service, replaced by Rust"
```

---

## Task 15: Update Documentation

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Update CLAUDE.md**

Find the "Embedding Service" section and update to reflect Rust implementation:

```markdown
5. **Embedding Service** (port 8080) - **Rust** (`crates/rag-embedding/`)
   - OpenAI-compatible embedding API (`/v1/embeddings`)
   - Candle-based sentence transformers (via `sentence-transformers-rs`)
   - Supports `all-MiniLM-L6-v2` (384 dimensions, default) and BGE models
   - Thread pool for async CPU-bound operations via `spawn_blocking`
   - Batch processing support (max 32 texts per request)
   - Used by Retrieval Service for query embeddings
```

Also update the Technology Stack section to remove Python from Embedding Service.

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for Rust embedding service"
```

---

## Task 16: Integration Test

**Files:**
- None (manual verification)

**Step 1: Build and run the service**

```bash
cd crates && cargo run -p rag-embedding
```

Expected output:
```
INFO Starting Rust Embedding Service v0.1.0
INFO Loading embedding model: sentence-transformers/all-MiniLM-L6-v2
INFO Model loaded in X.XXs. Embedding dimension: 384
INFO Embedding service listening on 0.0.0.0:8080
```

**Step 2: Test health endpoint**

```bash
curl http://localhost:8080/health | jq
```

Expected:
```json
{
  "status": "healthy",
  "model": "sentence-transformers/all-MiniLM-L6-v2",
  "dimension": 384,
  "max_batch_size": 32
}
```

**Step 3: Test embeddings endpoint**

```bash
curl -X POST http://localhost:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"input": ["Hello world", "How are you?"]}' | jq '.data | length, .data[0].embedding | length'
```

Expected:
```
2
384
```

**Step 4: Test error handling**

```bash
curl -X POST http://localhost:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"input": []}' | jq
```

Expected: 400 error response

---

## Summary

This plan creates the `rag-embedding` crate in 16 tasks:

1. **Tasks 1-4:** Core crate scaffold (Cargo.toml, lib.rs, error.rs, config.rs, model.rs)
2. **Tasks 5-8:** API layer (types.rs, state.rs, error.rs, routes.rs)
3. **Task 9-10:** Service binary and lib exports
4. **Task 11:** Build verification
5. **Tasks 12-13:** Docker integration
6. **Tasks 14-15:** Cleanup and documentation
7. **Task 16:** Integration testing

Each task is self-contained with explicit file paths and commit messages.

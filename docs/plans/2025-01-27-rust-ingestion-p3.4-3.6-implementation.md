# Rust Ingestion P3.4-3.6 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement Embedding Client, Index Coordinator, and Filesystem/S3 Connectors for the rag-ingestion crate.

**Architecture:** The three components extend the existing rag-ingestion crate. The Embedding Client is a thin HTTP wrapper using reqwest. The Index Coordinator orchestrates parallel writes to Qdrant, OpenSearch, and PostgreSQL using existing crate clients. Connectors abstract local filesystem and S3/MinIO document sources behind a common trait.

**Tech Stack:** Rust 1.75+, reqwest, aws-sdk-s3, tokio (fs feature), mime_guess, wiremock (testing)

---

## Task 1: Update Cargo.toml with New Dependencies

**Files:**
- Modify: `crates/rag-ingestion/Cargo.toml`

**Step 1: Add dependencies for embedding, indexing, and connectors**

Update `crates/rag-ingestion/Cargo.toml`:

```toml
[package]
name = "rag-ingestion"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
description = "Document parsing, chunking, embedding, and indexing for RAG pipeline"

[dependencies]
# Internal crates
rag-types = { path = "../rag-types" }
rag-vectorstore = { path = "../rag-vectorstore" }
rag-search = { path = "../rag-search" }
rag-database = { path = "../rag-database" }

# Parsing
scraper = "0.20"
ego-tree = "0.6"
pulldown-cmark = "0.12"
serde_yaml = "0.9"

# Tokenization
tiktoken-rs = "0.6"

# Serialization
serde = { workspace = true }
serde_json = { workspace = true }

# Error handling
thiserror = { workspace = true }

# Async runtime
tokio = { workspace = true, features = ["fs"] }

# HTTP client for embedding service
reqwest = { version = "0.11", default-features = false, features = ["json", "rustls-tls"] }

# AWS SDK for S3/MinIO
aws-sdk-s3 = "1.65"
aws-config = { version = "1.5", features = ["behavior-version-latest"] }

# Utilities
uuid = { workspace = true }
chrono = { workspace = true }
bytes = "1.5"
mime_guess = "2.0"
async-trait = "0.1"
tracing = { workspace = true }

[dev-dependencies]
pretty_assertions = "1.4"
wiremock = "0.6"
tempfile = "3.10"
tokio-test = { workspace = true }

[lints]
workspace = true
```

**Step 2: Verify compilation**

Run: `cargo check -p rag-ingestion`

Expected: Compiles with new dependencies

**Step 3: Commit**

```bash
git add crates/rag-ingestion/Cargo.toml
git commit -m "chore(ingestion): add dependencies for P3.4-P3.6

- Add reqwest for embedding HTTP client
- Add aws-sdk-s3/aws-config for S3 connector
- Add internal crate dependencies (rag-vectorstore, rag-search, rag-database)
- Add tokio fs, bytes, mime_guess, async-trait utilities

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Extend Error Types

**Files:**
- Modify: `crates/rag-ingestion/src/error.rs`

**Step 1: Add new error variants for embedding, indexing, and connectors**

Replace `crates/rag-ingestion/src/error.rs`:

```rust
//! Error types for the ingestion crate.

use thiserror::Error;

/// Errors that can occur during ingestion operations.
#[derive(Debug, Error)]
pub enum Error {
    /// Failed to parse document content.
    #[error("Parse error: {0}")]
    Parse(String),

    /// Failed to chunk document.
    #[error("Chunking error: {0}")]
    Chunking(String),

    /// Invalid configuration provided.
    #[error("Configuration error: {0}")]
    Config(String),

    /// IO error during file operations.
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    /// Serialization/deserialization error.
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),

    /// Embedding service error.
    #[error("Embedding error: {0}")]
    Embedding(String),

    /// HTTP request error.
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),

    /// Vector store (Qdrant) error.
    #[error("Vector store error: {0}")]
    VectorStore(String),

    /// Keyword store (OpenSearch) error.
    #[error("Search store error: {0}")]
    SearchStore(String),

    /// Database (PostgreSQL) error.
    #[error("Database error: {0}")]
    Database(String),

    /// Indexing coordination error.
    #[error("Indexing error: {0}")]
    Indexing(String),

    /// Connector error.
    #[error("Connector error: {0}")]
    Connector(String),

    /// S3/storage error.
    #[error("Storage error: {0}")]
    Storage(String),

    /// Document not found.
    #[error("Not found: {0}")]
    NotFound(String),

    /// Operation timeout.
    #[error("Timeout: {0}")]
    Timeout(String),
}

impl From<rag_vectorstore::VectorStoreError> for Error {
    fn from(e: rag_vectorstore::VectorStoreError) -> Self {
        Error::VectorStore(e.to_string())
    }
}

impl From<rag_search::SearchError> for Error {
    fn from(e: rag_search::SearchError) -> Self {
        Error::SearchStore(e.to_string())
    }
}

impl From<rag_database::DatabaseError> for Error {
    fn from(e: rag_database::DatabaseError) -> Self {
        Error::Database(e.to_string())
    }
}

/// Result type alias for ingestion operations.
pub type Result<T> = std::result::Result<T, Error>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_error_display() {
        let err = Error::Embedding("connection refused".to_string());
        assert_eq!(err.to_string(), "Embedding error: connection refused");
    }

    #[test]
    fn test_error_from_io() {
        let io_err = std::io::Error::new(std::io::ErrorKind::NotFound, "file not found");
        let err: Error = io_err.into();
        assert!(matches!(err, Error::Io(_)));
    }
}
```

**Step 2: Run tests**

Run: `cargo test -p rag-ingestion error`

Expected: 2 tests pass

**Step 3: Commit**

```bash
git add crates/rag-ingestion/src/error.rs
git commit -m "feat(ingestion): extend error types for P3.4-P3.6

- Add Embedding, Http, VectorStore, SearchStore, Database errors
- Add Indexing, Connector, Storage, NotFound, Timeout errors
- Add From implementations for crate errors
- Add unit tests

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Embedding Client Configuration

**Files:**
- Create: `crates/rag-ingestion/src/embedding/mod.rs`
- Create: `crates/rag-ingestion/src/embedding/config.rs`

**Step 1: Create embedding module**

Create `crates/rag-ingestion/src/embedding/mod.rs`:

```rust
//! Embedding client for generating vector embeddings.
//!
//! This module provides an HTTP client for the embedding service
//! using the OpenAI-compatible API format.

mod client;
mod config;

pub use client::EmbeddingClient;
pub use config::EmbeddingClientConfig;
```

**Step 2: Create configuration with tests**

Create `crates/rag-ingestion/src/embedding/config.rs`:

```rust
//! Configuration for the embedding client.

use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Configuration for the embedding client.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EmbeddingClientConfig {
    /// Base URL of the embedding service (e.g., "http://localhost:8080").
    pub url: String,

    /// API endpoint for embeddings (default: "/v1/embeddings").
    #[serde(default = "default_endpoint")]
    pub endpoint: String,

    /// Model name to use (default: "all-MiniLM-L6-v2").
    #[serde(default = "default_model")]
    pub model: String,

    /// Request timeout (default: 30 seconds).
    #[serde(default = "default_timeout", with = "humantime_serde")]
    pub timeout: Duration,

    /// Maximum number of retry attempts (default: 3).
    #[serde(default = "default_max_retries")]
    pub max_retries: u32,

    /// Base delay between retries (default: 1 second).
    #[serde(default = "default_retry_delay", with = "humantime_serde")]
    pub retry_delay: Duration,
}

fn default_endpoint() -> String {
    "/v1/embeddings".to_string()
}

fn default_model() -> String {
    "all-MiniLM-L6-v2".to_string()
}

fn default_timeout() -> Duration {
    Duration::from_secs(30)
}

fn default_max_retries() -> u32 {
    3
}

fn default_retry_delay() -> Duration {
    Duration::from_secs(1)
}

impl EmbeddingClientConfig {
    /// Create a new configuration with the given URL.
    #[must_use]
    pub fn new(url: impl Into<String>) -> Self {
        Self {
            url: url.into(),
            endpoint: default_endpoint(),
            model: default_model(),
            timeout: default_timeout(),
            max_retries: default_max_retries(),
            retry_delay: default_retry_delay(),
        }
    }

    /// Set the API endpoint.
    #[must_use]
    pub fn with_endpoint(mut self, endpoint: impl Into<String>) -> Self {
        self.endpoint = endpoint.into();
        self
    }

    /// Set the model name.
    #[must_use]
    pub fn with_model(mut self, model: impl Into<String>) -> Self {
        self.model = model.into();
        self
    }

    /// Set the request timeout.
    #[must_use]
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    /// Set the maximum retry attempts.
    #[must_use]
    pub fn with_max_retries(mut self, max_retries: u32) -> Self {
        self.max_retries = max_retries;
        self
    }

    /// Get the full URL for the embeddings endpoint.
    #[must_use]
    pub fn embeddings_url(&self) -> String {
        format!("{}{}", self.url.trim_end_matches('/'), self.endpoint)
    }
}

impl Default for EmbeddingClientConfig {
    fn default() -> Self {
        Self::new("http://localhost:8080")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_defaults() {
        let config = EmbeddingClientConfig::default();
        assert_eq!(config.url, "http://localhost:8080");
        assert_eq!(config.endpoint, "/v1/embeddings");
        assert_eq!(config.model, "all-MiniLM-L6-v2");
        assert_eq!(config.timeout, Duration::from_secs(30));
        assert_eq!(config.max_retries, 3);
    }

    #[test]
    fn test_config_builder() {
        let config = EmbeddingClientConfig::new("http://embed:8080")
            .with_model("custom-model")
            .with_timeout(Duration::from_secs(60))
            .with_max_retries(5);

        assert_eq!(config.url, "http://embed:8080");
        assert_eq!(config.model, "custom-model");
        assert_eq!(config.timeout, Duration::from_secs(60));
        assert_eq!(config.max_retries, 5);
    }

    #[test]
    fn test_embeddings_url() {
        let config = EmbeddingClientConfig::new("http://localhost:8080/");
        assert_eq!(config.embeddings_url(), "http://localhost:8080/v1/embeddings");

        let config2 = EmbeddingClientConfig::new("http://localhost:8080");
        assert_eq!(config2.embeddings_url(), "http://localhost:8080/v1/embeddings");
    }
}
```

**Step 3: Run tests**

Run: `cargo test -p rag-ingestion embedding::config`

Expected: 3 tests pass

**Step 4: Commit**

```bash
git add crates/rag-ingestion/src/embedding/
git commit -m "feat(ingestion): add embedding client configuration

- Add EmbeddingClientConfig with builder pattern
- Add default values for endpoint, model, timeout, retries
- Add embeddings_url() helper for URL construction
- Add unit tests

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Embedding Client Implementation

**Files:**
- Create: `crates/rag-ingestion/src/embedding/client.rs`
- Modify: `crates/rag-ingestion/src/embedding/mod.rs`

**Step 1: Create the embedding client with tests**

Create `crates/rag-ingestion/src/embedding/client.rs`:

```rust
//! HTTP client for the embedding service.

use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tracing::{debug, instrument, warn};

use crate::error::{Error, Result};
use super::config::EmbeddingClientConfig;

/// Request body for the embedding API (OpenAI-compatible format).
#[derive(Debug, Serialize)]
struct EmbeddingRequest<'a> {
    input: &'a [String],
    model: &'a str,
}

/// Response from the embedding API.
#[derive(Debug, Deserialize)]
pub struct EmbeddingResponse {
    /// List of embedding results.
    pub data: Vec<EmbeddingData>,
    /// Token usage information.
    pub usage: Option<Usage>,
}

/// Single embedding result.
#[derive(Debug, Deserialize)]
pub struct EmbeddingData {
    /// The embedding vector.
    pub embedding: Vec<f32>,
    /// Index in the input array.
    pub index: usize,
}

/// Token usage information.
#[derive(Debug, Deserialize)]
pub struct Usage {
    /// Total tokens processed.
    pub total_tokens: u32,
}

/// HTTP client for generating embeddings.
///
/// Uses the OpenAI-compatible API format supported by the embedding service.
///
/// # Example
///
/// ```no_run
/// use rag_ingestion::embedding::{EmbeddingClient, EmbeddingClientConfig};
///
/// #[tokio::main]
/// async fn main() -> Result<(), Box<dyn std::error::Error>> {
///     let config = EmbeddingClientConfig::new("http://localhost:8080");
///     let client = EmbeddingClient::new(config)?;
///
///     let texts = vec!["Hello world".to_string()];
///     let (embeddings, tokens) = client.embed_batch(&texts).await?;
///
///     println!("Generated {} embeddings using {} tokens", embeddings.len(), tokens);
///     Ok(())
/// }
/// ```
#[derive(Debug, Clone)]
pub struct EmbeddingClient {
    client: Client,
    config: EmbeddingClientConfig,
}

impl EmbeddingClient {
    /// Create a new embedding client.
    ///
    /// # Errors
    ///
    /// Returns an error if the HTTP client cannot be created.
    pub fn new(config: EmbeddingClientConfig) -> Result<Self> {
        let client = Client::builder()
            .timeout(config.timeout)
            .build()
            .map_err(|e| Error::Config(format!("Failed to create HTTP client: {e}")))?;

        Ok(Self { client, config })
    }

    /// Embed a batch of texts.
    ///
    /// Returns a tuple of (embeddings, total_tokens).
    ///
    /// # Arguments
    ///
    /// * `texts` - Slice of text strings to embed.
    ///
    /// # Errors
    ///
    /// Returns an error if the request fails after all retries.
    #[instrument(skip(self, texts), fields(batch_size = texts.len()))]
    pub async fn embed_batch(&self, texts: &[String]) -> Result<(Vec<Vec<f32>>, u32)> {
        if texts.is_empty() {
            return Ok((Vec::new(), 0));
        }

        let url = self.config.embeddings_url();
        let request_body = EmbeddingRequest {
            input: texts,
            model: &self.config.model,
        };

        let mut last_error = None;
        let mut delay = self.config.retry_delay;

        for attempt in 0..=self.config.max_retries {
            if attempt > 0 {
                debug!(attempt, "Retrying embedding request after {:?}", delay);
                tokio::time::sleep(delay).await;
                delay = delay.saturating_mul(2); // Exponential backoff
            }

            match self.send_request(&url, &request_body).await {
                Ok(response) => {
                    let total_tokens = response.usage.map(|u| u.total_tokens).unwrap_or(0);

                    // Sort by index to maintain order
                    let mut embeddings: Vec<_> = response.data.into_iter().collect();
                    embeddings.sort_by_key(|e| e.index);
                    let embeddings: Vec<Vec<f32>> = embeddings.into_iter().map(|e| e.embedding).collect();

                    debug!(
                        embeddings = embeddings.len(),
                        tokens = total_tokens,
                        "Embedding request succeeded"
                    );
                    return Ok((embeddings, total_tokens));
                }
                Err(e) => {
                    // Don't retry on client errors (4xx)
                    if Self::is_client_error(&e) {
                        return Err(e);
                    }
                    warn!(attempt, error = %e, "Embedding request failed");
                    last_error = Some(e);
                }
            }
        }

        Err(last_error.unwrap_or_else(|| Error::Embedding("Unknown error".to_string())))
    }

    /// Send a single embedding request.
    async fn send_request(
        &self,
        url: &str,
        body: &EmbeddingRequest<'_>,
    ) -> Result<EmbeddingResponse> {
        let response = self
            .client
            .post(url)
            .json(body)
            .send()
            .await?;

        let status = response.status();
        if !status.is_success() {
            let error_text = response.text().await.unwrap_or_default();
            return Err(Error::Embedding(format!(
                "HTTP {}: {}",
                status.as_u16(),
                error_text
            )));
        }

        let embedding_response: EmbeddingResponse = response.json().await?;
        Ok(embedding_response)
    }

    /// Check if an error is a client error (should not retry).
    fn is_client_error(error: &Error) -> bool {
        if let Error::Embedding(msg) = error {
            msg.starts_with("HTTP 4")
        } else {
            false
        }
    }

    /// Check if the embedding service is healthy.
    ///
    /// # Returns
    ///
    /// `true` if the service responds to health check, `false` otherwise.
    #[instrument(skip(self))]
    pub async fn health_check(&self) -> Result<bool> {
        let url = format!("{}/health", self.config.url.trim_end_matches('/'));

        match self.client.get(&url).send().await {
            Ok(response) => Ok(response.status().is_success()),
            Err(e) => {
                debug!(error = %e, "Health check failed");
                Ok(false)
            }
        }
    }

    /// Get the configuration.
    #[must_use]
    pub fn config(&self) -> &EmbeddingClientConfig {
        &self.config
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{body_json, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[tokio::test]
    async fn test_embed_batch_success() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "data": [
                    {"embedding": [0.1, 0.2, 0.3], "index": 0},
                    {"embedding": [0.4, 0.5, 0.6], "index": 1}
                ],
                "usage": {"total_tokens": 10}
            })))
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(mock_server.uri());
        let client = EmbeddingClient::new(config).unwrap();

        let texts = vec!["hello".to_string(), "world".to_string()];
        let (embeddings, tokens) = client.embed_batch(&texts).await.unwrap();

        assert_eq!(embeddings.len(), 2);
        assert_eq!(embeddings[0], vec![0.1, 0.2, 0.3]);
        assert_eq!(embeddings[1], vec![0.4, 0.5, 0.6]);
        assert_eq!(tokens, 10);
    }

    #[tokio::test]
    async fn test_embed_batch_empty() {
        let config = EmbeddingClientConfig::new("http://localhost:9999");
        let client = EmbeddingClient::new(config).unwrap();

        let (embeddings, tokens) = client.embed_batch(&[]).await.unwrap();
        assert!(embeddings.is_empty());
        assert_eq!(tokens, 0);
    }

    #[tokio::test]
    async fn test_embed_batch_client_error_no_retry() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(400).set_body_string("Bad request"))
            .expect(1) // Should only be called once (no retry on 4xx)
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(mock_server.uri())
            .with_max_retries(3);
        let client = EmbeddingClient::new(config).unwrap();

        let texts = vec!["test".to_string()];
        let result = client.embed_batch(&texts).await;

        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), Error::Embedding(_)));
    }

    #[tokio::test]
    async fn test_embed_batch_retry_on_server_error() {
        let mock_server = MockServer::start().await;

        // First two calls fail, third succeeds
        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(500).set_body_string("Server error"))
            .up_to_n_times(2)
            .mount(&mock_server)
            .await;

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "data": [{"embedding": [0.1], "index": 0}],
                "usage": {"total_tokens": 5}
            })))
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(mock_server.uri())
            .with_max_retries(3)
            .with_timeout(Duration::from_millis(100));
        let client = EmbeddingClient::new(config).unwrap();

        let texts = vec!["test".to_string()];
        let result = client.embed_batch(&texts).await;

        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_health_check_healthy() {
        let mock_server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/health"))
            .respond_with(ResponseTemplate::new(200))
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(mock_server.uri());
        let client = EmbeddingClient::new(config).unwrap();

        assert!(client.health_check().await.unwrap());
    }

    #[tokio::test]
    async fn test_health_check_unhealthy() {
        let mock_server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/health"))
            .respond_with(ResponseTemplate::new(503))
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(mock_server.uri());
        let client = EmbeddingClient::new(config).unwrap();

        assert!(!client.health_check().await.unwrap());
    }
}
```

**Step 2: Update module exports**

Update `crates/rag-ingestion/src/embedding/mod.rs`:

```rust
//! Embedding client for generating vector embeddings.
//!
//! This module provides an HTTP client for the embedding service
//! using the OpenAI-compatible API format.
//!
//! # Example
//!
//! ```no_run
//! use rag_ingestion::embedding::{EmbeddingClient, EmbeddingClientConfig};
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = EmbeddingClientConfig::new("http://localhost:8080");
//!     let client = EmbeddingClient::new(config)?;
//!
//!     let texts = vec!["Hello".to_string(), "World".to_string()];
//!     let (embeddings, tokens) = client.embed_batch(&texts).await?;
//!
//!     println!("Generated {} embeddings", embeddings.len());
//!     Ok(())
//! }
//! ```

mod client;
mod config;

pub use client::{EmbeddingClient, EmbeddingData, EmbeddingResponse, Usage};
pub use config::EmbeddingClientConfig;
```

**Step 3: Run tests**

Run: `cargo test -p rag-ingestion embedding::client`

Expected: 6 tests pass

**Step 4: Commit**

```bash
git add crates/rag-ingestion/src/embedding/
git commit -m "feat(ingestion): implement embedding HTTP client

- Add EmbeddingClient with embed_batch() and health_check()
- Add OpenAI-compatible request/response types
- Implement exponential backoff retry logic
- Skip retry on 4xx client errors
- Add comprehensive tests with wiremock

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Indexing Status and Models

**Files:**
- Create: `crates/rag-ingestion/src/indexing/mod.rs`
- Create: `crates/rag-ingestion/src/indexing/status.rs`
- Create: `crates/rag-ingestion/src/indexing/models.rs`

**Step 1: Create indexing module**

Create `crates/rag-ingestion/src/indexing/mod.rs`:

```rust
//! Multi-store index coordination.
//!
//! This module provides the [`IndexCoordinator`] for writing documents
//! to Qdrant, OpenSearch, and PostgreSQL in parallel.

mod coordinator;
mod models;
mod status;

pub use coordinator::{IndexCoordinator, IndexCoordinatorConfig};
pub use models::{DocumentRecord, IndexedChunk, WriteResult};
pub use status::IndexStatus;
```

**Step 2: Create status enum**

Create `crates/rag-ingestion/src/indexing/status.rs`:

```rust
//! Index status tracking for documents.

use serde::{Deserialize, Serialize};
use std::fmt;

/// Status of a document's indexing in an external store.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IndexStatus {
    /// Indexing is pending or in progress.
    Pending,
    /// Successfully indexed.
    Ok,
    /// Indexing failed.
    Error,
    /// Document was updated and needs re-indexing.
    Stale,
}

impl IndexStatus {
    /// Check if the status indicates successful indexing.
    #[must_use]
    pub const fn is_ok(&self) -> bool {
        matches!(self, Self::Ok)
    }

    /// Check if the status indicates a problem.
    #[must_use]
    pub const fn is_error(&self) -> bool {
        matches!(self, Self::Error)
    }

    /// Check if the document needs (re-)indexing.
    #[must_use]
    pub const fn needs_indexing(&self) -> bool {
        matches!(self, Self::Pending | Self::Stale | Self::Error)
    }
}

impl fmt::Display for IndexStatus {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Pending => write!(f, "pending"),
            Self::Ok => write!(f, "ok"),
            Self::Error => write!(f, "error"),
            Self::Stale => write!(f, "stale"),
        }
    }
}

impl Default for IndexStatus {
    fn default() -> Self {
        Self::Pending
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_status_is_ok() {
        assert!(IndexStatus::Ok.is_ok());
        assert!(!IndexStatus::Pending.is_ok());
        assert!(!IndexStatus::Error.is_ok());
        assert!(!IndexStatus::Stale.is_ok());
    }

    #[test]
    fn test_status_needs_indexing() {
        assert!(IndexStatus::Pending.needs_indexing());
        assert!(IndexStatus::Stale.needs_indexing());
        assert!(IndexStatus::Error.needs_indexing());
        assert!(!IndexStatus::Ok.needs_indexing());
    }

    #[test]
    fn test_status_serde() {
        let status = IndexStatus::Ok;
        let json = serde_json::to_string(&status).unwrap();
        assert_eq!(json, "\"ok\"");

        let parsed: IndexStatus = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed, IndexStatus::Ok);
    }

    #[test]
    fn test_status_display() {
        assert_eq!(IndexStatus::Pending.to_string(), "pending");
        assert_eq!(IndexStatus::Ok.to_string(), "ok");
        assert_eq!(IndexStatus::Error.to_string(), "error");
        assert_eq!(IndexStatus::Stale.to_string(), "stale");
    }
}
```

**Step 3: Create models**

Create `crates/rag-ingestion/src/indexing/models.rs`:

```rust
//! Data models for index coordination.

use rag_types::{ChunkId, DocumentId, TenantId};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::time::Duration;

/// Record for a document to be indexed.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentRecord {
    /// Unique document identifier.
    pub document_id: DocumentId,
    /// Tenant this document belongs to.
    pub tenant_id: TenantId,
    /// Source identifier (file path, URL, etc.).
    pub source_id: String,
    /// Document title.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    /// Additional metadata.
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, Value>,
}

impl DocumentRecord {
    /// Create a new document record.
    #[must_use]
    pub fn new(document_id: DocumentId, tenant_id: TenantId, source_id: impl Into<String>) -> Self {
        Self {
            document_id,
            tenant_id,
            source_id: source_id.into(),
            title: None,
            metadata: HashMap::new(),
        }
    }

    /// Set the document title.
    #[must_use]
    pub fn with_title(mut self, title: impl Into<String>) -> Self {
        self.title = Some(title.into());
        self
    }

    /// Add metadata.
    #[must_use]
    pub fn with_metadata(mut self, key: impl Into<String>, value: Value) -> Self {
        self.metadata.insert(key.into(), value);
        self
    }
}

/// A chunk ready for indexing with its embedding.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndexedChunk {
    /// Unique chunk identifier.
    pub chunk_id: ChunkId,
    /// Parent document identifier.
    pub document_id: DocumentId,
    /// Tenant this chunk belongs to.
    pub tenant_id: TenantId,
    /// Chunk text content.
    pub content: String,
    /// Embedding vector.
    pub embedding: Vec<f32>,
    /// Position within the document (0-indexed).
    pub chunk_index: u32,
    /// Additional metadata.
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, Value>,
}

impl IndexedChunk {
    /// Create a new indexed chunk.
    #[must_use]
    pub fn new(
        chunk_id: ChunkId,
        document_id: DocumentId,
        tenant_id: TenantId,
        content: impl Into<String>,
        embedding: Vec<f32>,
        chunk_index: u32,
    ) -> Self {
        Self {
            chunk_id,
            document_id,
            tenant_id,
            content: content.into(),
            embedding,
            chunk_index,
            metadata: HashMap::new(),
        }
    }

    /// Add metadata.
    #[must_use]
    pub fn with_metadata(mut self, key: impl Into<String>, value: Value) -> Self {
        self.metadata.insert(key.into(), value);
        self
    }
}

/// Result of a write operation to a single store.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WriteResult {
    /// Whether the operation succeeded.
    pub success: bool,
    /// Number of items successfully written.
    pub items_written: usize,
    /// Number of items that failed to write.
    pub items_failed: usize,
    /// Error messages if any failures occurred.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub errors: Vec<String>,
    /// Time taken for the operation.
    #[serde(with = "humantime_serde")]
    pub duration: Duration,
}

impl WriteResult {
    /// Create a successful write result.
    #[must_use]
    pub fn success(items_written: usize, duration: Duration) -> Self {
        Self {
            success: true,
            items_written,
            items_failed: 0,
            errors: Vec::new(),
            duration,
        }
    }

    /// Create a failed write result.
    #[must_use]
    pub fn failure(items_failed: usize, errors: Vec<String>, duration: Duration) -> Self {
        Self {
            success: false,
            items_written: 0,
            items_failed,
            errors,
            duration,
        }
    }

    /// Create a partial success result.
    #[must_use]
    pub fn partial(
        items_written: usize,
        items_failed: usize,
        errors: Vec<String>,
        duration: Duration,
    ) -> Self {
        Self {
            success: items_failed == 0,
            items_written,
            items_failed,
            errors,
            duration,
        }
    }
}

impl Default for WriteResult {
    fn default() -> Self {
        Self {
            success: true,
            items_written: 0,
            items_failed: 0,
            errors: Vec::new(),
            duration: Duration::ZERO,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_document_record_builder() {
        let doc = DocumentRecord::new(
            DocumentId::new(),
            TenantId::new(),
            "s3://bucket/doc.pdf",
        )
        .with_title("Test Document")
        .with_metadata("author", serde_json::json!("Alice"));

        assert_eq!(doc.source_id, "s3://bucket/doc.pdf");
        assert_eq!(doc.title, Some("Test Document".to_string()));
        assert!(doc.metadata.contains_key("author"));
    }

    #[test]
    fn test_indexed_chunk_builder() {
        let chunk = IndexedChunk::new(
            ChunkId::new(),
            DocumentId::new(),
            TenantId::new(),
            "Hello world",
            vec![0.1, 0.2, 0.3],
            0,
        )
        .with_metadata("section", serde_json::json!("intro"));

        assert_eq!(chunk.content, "Hello world");
        assert_eq!(chunk.embedding.len(), 3);
        assert_eq!(chunk.chunk_index, 0);
    }

    #[test]
    fn test_write_result_success() {
        let result = WriteResult::success(10, Duration::from_millis(50));
        assert!(result.success);
        assert_eq!(result.items_written, 10);
        assert_eq!(result.items_failed, 0);
        assert!(result.errors.is_empty());
    }

    #[test]
    fn test_write_result_failure() {
        let result = WriteResult::failure(5, vec!["Connection failed".to_string()], Duration::from_millis(10));
        assert!(!result.success);
        assert_eq!(result.items_written, 0);
        assert_eq!(result.items_failed, 5);
        assert_eq!(result.errors.len(), 1);
    }

    #[test]
    fn test_write_result_partial() {
        let result = WriteResult::partial(8, 2, vec!["Timeout".to_string()], Duration::from_millis(100));
        assert!(!result.success); // Has failures
        assert_eq!(result.items_written, 8);
        assert_eq!(result.items_failed, 2);
    }
}
```

**Step 4: Run tests**

Run: `cargo test -p rag-ingestion indexing`

Expected: 9 tests pass (4 status + 5 models)

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/indexing/
git commit -m "feat(ingestion): add indexing status and models

- Add IndexStatus enum (Pending, Ok, Error, Stale)
- Add DocumentRecord for document metadata
- Add IndexedChunk for chunks with embeddings
- Add WriteResult for tracking write outcomes
- Add builder patterns and unit tests

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Index Coordinator Implementation

**Files:**
- Create: `crates/rag-ingestion/src/indexing/coordinator.rs`

**Step 1: Create the coordinator**

Create `crates/rag-ingestion/src/indexing/coordinator.rs`:

```rust
//! Multi-store index coordinator.

use rag_database::{DatabasePool, PgPool};
use rag_search::{SearchClient, SearchConfig};
use rag_types::{DocumentId, TenantId};
use rag_vectorstore::{VectorStoreClient, VectorStoreConfig};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tracing::{debug, error, info, instrument, warn};

use crate::error::{Error, Result};
use super::models::{DocumentRecord, IndexedChunk, WriteResult};
use super::status::IndexStatus;

/// Configuration for the index coordinator.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndexCoordinatorConfig {
    /// Qdrant configuration.
    pub qdrant_url: String,
    /// Qdrant collection name.
    #[serde(default = "default_collection")]
    pub qdrant_collection: String,
    /// OpenSearch configuration.
    pub opensearch_url: String,
    /// OpenSearch index name.
    #[serde(default = "default_index")]
    pub opensearch_index: String,
    /// PostgreSQL connection string.
    pub database_url: String,
}

fn default_collection() -> String {
    "documents".to_string()
}

fn default_index() -> String {
    "documents".to_string()
}

impl IndexCoordinatorConfig {
    /// Create a new configuration.
    #[must_use]
    pub fn new(qdrant_url: &str, opensearch_url: &str, database_url: &str) -> Self {
        Self {
            qdrant_url: qdrant_url.to_string(),
            qdrant_collection: default_collection(),
            opensearch_url: opensearch_url.to_string(),
            opensearch_index: default_index(),
            database_url: database_url.to_string(),
        }
    }
}

/// Coordinates writes to Qdrant, OpenSearch, and PostgreSQL.
///
/// Performs writes in parallel and tracks indexing status.
pub struct IndexCoordinator {
    qdrant: Arc<VectorStoreClient>,
    opensearch: Arc<SearchClient>,
    database: Arc<DatabasePool>,
    config: IndexCoordinatorConfig,
}

impl IndexCoordinator {
    /// Create a new index coordinator.
    ///
    /// # Errors
    ///
    /// Returns an error if any connection fails.
    pub async fn new(config: IndexCoordinatorConfig) -> Result<Self> {
        let qdrant_config = VectorStoreConfig::new(&config.qdrant_url)
            .with_default_collection(&config.qdrant_collection);
        let qdrant = VectorStoreClient::connect(&qdrant_config).await?;

        let opensearch_config = SearchConfig::new(&config.opensearch_url)
            .with_default_index(&config.opensearch_index);
        let opensearch = SearchClient::connect(&opensearch_config).await?;

        let db_config = rag_database::DatabaseConfig::new(&config.database_url);
        let database = DatabasePool::connect(&db_config).await?;

        Ok(Self {
            qdrant: Arc::new(qdrant),
            opensearch: Arc::new(opensearch),
            database: Arc::new(database),
            config,
        })
    }

    /// Create from existing clients (for testing).
    #[must_use]
    pub fn from_clients(
        qdrant: Arc<VectorStoreClient>,
        opensearch: Arc<SearchClient>,
        database: Arc<DatabasePool>,
        config: IndexCoordinatorConfig,
    ) -> Self {
        Self {
            qdrant,
            opensearch,
            database,
            config,
        }
    }

    /// Index a document and its chunks to all stores.
    ///
    /// Writes happen in parallel:
    /// - Chunks with embeddings → Qdrant
    /// - Chunks with text → OpenSearch
    /// - Document record → PostgreSQL (status tracking)
    #[instrument(skip(self, document, chunks), fields(
        document_id = %document.document_id,
        tenant_id = %document.tenant_id,
        chunk_count = chunks.len()
    ))]
    pub async fn index_document(
        &self,
        document: DocumentRecord,
        chunks: Vec<IndexedChunk>,
    ) -> Result<HashMap<String, WriteResult>> {
        info!("Starting document indexing");

        // Set status to pending
        self.update_index_status(
            document.document_id,
            IndexStatus::Pending,
            IndexStatus::Pending,
            None,
        )
        .await?;

        // Execute writes in parallel
        let (qdrant_result, opensearch_result) = tokio::join!(
            self.write_to_qdrant(&chunks),
            self.write_to_opensearch(&document, &chunks),
        );

        // Build results map
        let mut results = HashMap::new();

        let qdrant_write = match qdrant_result {
            Ok(r) => r,
            Err(e) => {
                error!(error = %e, "Qdrant write failed");
                WriteResult::failure(chunks.len(), vec![e.to_string()], Duration::ZERO)
            }
        };
        results.insert("qdrant".to_string(), qdrant_write.clone());

        let opensearch_write = match opensearch_result {
            Ok(r) => r,
            Err(e) => {
                error!(error = %e, "OpenSearch write failed");
                WriteResult::failure(chunks.len(), vec![e.to_string()], Duration::ZERO)
            }
        };
        results.insert("opensearch".to_string(), opensearch_write.clone());

        // Update final status
        let qdrant_status = if qdrant_write.success {
            IndexStatus::Ok
        } else {
            IndexStatus::Error
        };
        let opensearch_status = if opensearch_write.success {
            IndexStatus::Ok
        } else {
            IndexStatus::Error
        };

        let errors: Vec<String> = results
            .values()
            .flat_map(|r| r.errors.clone())
            .collect();
        let error_msg = if errors.is_empty() {
            None
        } else {
            Some(errors.join("; "))
        };

        self.update_index_status(document.document_id, qdrant_status, opensearch_status, error_msg)
            .await?;

        info!(
            qdrant_success = qdrant_write.success,
            opensearch_success = opensearch_write.success,
            "Document indexing completed"
        );

        Ok(results)
    }

    /// Delete a document from all stores.
    #[instrument(skip(self), fields(%document_id, %tenant_id))]
    pub async fn delete_document(
        &self,
        document_id: DocumentId,
        tenant_id: TenantId,
    ) -> Result<HashMap<String, WriteResult>> {
        info!("Starting document deletion");

        let (qdrant_result, opensearch_result) = tokio::join!(
            self.delete_from_qdrant(document_id, tenant_id),
            self.delete_from_opensearch(document_id),
        );

        let mut results = HashMap::new();

        results.insert(
            "qdrant".to_string(),
            qdrant_result.unwrap_or_else(|e| {
                WriteResult::failure(1, vec![e.to_string()], Duration::ZERO)
            }),
        );

        results.insert(
            "opensearch".to_string(),
            opensearch_result.unwrap_or_else(|e| {
                WriteResult::failure(1, vec![e.to_string()], Duration::ZERO)
            }),
        );

        info!("Document deletion completed");
        Ok(results)
    }

    /// Re-index a document (delete existing, then write new).
    #[instrument(skip(self, document, chunks), fields(
        document_id = %document.document_id,
        tenant_id = %document.tenant_id
    ))]
    pub async fn reindex_document(
        &self,
        document: DocumentRecord,
        chunks: Vec<IndexedChunk>,
    ) -> Result<HashMap<String, WriteResult>> {
        info!("Starting document re-indexing");

        // Delete existing chunks
        let _ = self
            .delete_document(document.document_id, document.tenant_id)
            .await;

        // Index new chunks
        self.index_document(document, chunks).await
    }

    /// Write chunks to Qdrant.
    async fn write_to_qdrant(&self, chunks: &[IndexedChunk]) -> Result<WriteResult> {
        if chunks.is_empty() {
            return Ok(WriteResult::success(0, Duration::ZERO));
        }

        let start = Instant::now();

        let ids: Vec<String> = chunks.iter().map(|c| c.chunk_id.to_string()).collect();
        let vectors: Vec<Vec<f32>> = chunks.iter().map(|c| c.embedding.clone()).collect();
        let payloads: Vec<serde_json::Value> = chunks
            .iter()
            .map(|c| {
                json!({
                    "chunk_id": c.chunk_id.to_string(),
                    "document_id": c.document_id.to_string(),
                    "tenant_id": c.tenant_id.to_string(),
                    "content": c.content,
                    "chunk_index": c.chunk_index,
                    "metadata": c.metadata,
                })
            })
            .collect();

        self.qdrant
            .upsert(Some(&self.config.qdrant_collection), ids, vectors, payloads)
            .await?;

        let duration = start.elapsed();
        debug!(chunks = chunks.len(), ?duration, "Qdrant write completed");

        Ok(WriteResult::success(chunks.len(), duration))
    }

    /// Write document and chunks to OpenSearch.
    async fn write_to_opensearch(
        &self,
        document: &DocumentRecord,
        chunks: &[IndexedChunk],
    ) -> Result<WriteResult> {
        if chunks.is_empty() {
            return Ok(WriteResult::success(0, Duration::ZERO));
        }

        let start = Instant::now();

        // Index each chunk as a separate document
        for chunk in chunks {
            let doc = json!({
                "chunk_id": chunk.chunk_id.to_string(),
                "document_id": chunk.document_id.to_string(),
                "tenant_id": chunk.tenant_id.to_string(),
                "content": chunk.content,
                "title": document.title,
                "source_id": document.source_id,
                "chunk_index": chunk.chunk_index,
                "metadata": chunk.metadata,
            });

            self.opensearch
                .index_document(
                    &self.config.opensearch_index,
                    &chunk.chunk_id.to_string(),
                    doc,
                )
                .await?;
        }

        let duration = start.elapsed();
        debug!(chunks = chunks.len(), ?duration, "OpenSearch write completed");

        Ok(WriteResult::success(chunks.len(), duration))
    }

    /// Delete chunks from Qdrant by document ID.
    async fn delete_from_qdrant(
        &self,
        document_id: DocumentId,
        _tenant_id: TenantId,
    ) -> Result<WriteResult> {
        let start = Instant::now();

        self.qdrant
            .delete_by_filter(
                Some(&self.config.qdrant_collection),
                rag_vectorstore::FilterBuilder::new()
                    .must_match("document_id", document_id.to_string())
                    .build(),
            )
            .await?;

        Ok(WriteResult::success(1, start.elapsed()))
    }

    /// Delete chunks from OpenSearch by document ID.
    async fn delete_from_opensearch(&self, document_id: DocumentId) -> Result<WriteResult> {
        let start = Instant::now();

        self.opensearch
            .delete_by_query(
                &self.config.opensearch_index,
                json!({
                    "query": {
                        "term": {
                            "document_id": document_id.to_string()
                        }
                    }
                }),
            )
            .await?;

        Ok(WriteResult::success(1, start.elapsed()))
    }

    /// Update index status in PostgreSQL.
    async fn update_index_status(
        &self,
        document_id: DocumentId,
        qdrant_status: IndexStatus,
        opensearch_status: IndexStatus,
        error_msg: Option<String>,
    ) -> Result<()> {
        let pool = self.database.inner();

        sqlx::query(
            r#"
            UPDATE documents
            SET qdrant_status = $1,
                opensearch_status = $2,
                last_index_error = $3,
                last_indexed_at = CASE WHEN $1 = 'ok' AND $2 = 'ok' THEN NOW() ELSE last_indexed_at END,
                index_attempts = index_attempts + 1,
                updated_at = NOW()
            WHERE id = $4
            "#,
        )
        .bind(qdrant_status.to_string())
        .bind(opensearch_status.to_string())
        .bind(error_msg)
        .bind(document_id.as_uuid())
        .execute(pool)
        .await
        .map_err(|e| Error::Database(e.to_string()))?;

        debug!(%document_id, %qdrant_status, %opensearch_status, "Index status updated");
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_defaults() {
        let config = IndexCoordinatorConfig::new(
            "http://localhost:6333",
            "http://localhost:9200",
            "postgres://localhost/test",
        );
        assert_eq!(config.qdrant_collection, "documents");
        assert_eq!(config.opensearch_index, "documents");
    }
}
```

**Step 2: Run tests**

Run: `cargo test -p rag-ingestion indexing::coordinator`

Expected: 1 test passes (config test)

**Step 3: Commit**

```bash
git add crates/rag-ingestion/src/indexing/
git commit -m "feat(ingestion): implement index coordinator

- Add IndexCoordinator for parallel writes to Qdrant, OpenSearch, PostgreSQL
- Add index_document(), delete_document(), reindex_document() methods
- Implement status tracking in PostgreSQL
- Use tokio::join! for parallel writes
- Add tracing instrumentation

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Connector Base Types and Trait

**Files:**
- Create: `crates/rag-ingestion/src/connectors/mod.rs`
- Create: `crates/rag-ingestion/src/connectors/base.rs`

**Step 1: Create connectors module**

Create `crates/rag-ingestion/src/connectors/mod.rs`:

```rust
//! Document source connectors.
//!
//! This module provides connectors for reading documents from various sources:
//! - [`FilesystemConnector`]: Local filesystem
//! - [`S3Connector`]: S3-compatible storage (AWS S3, MinIO)

mod base;
mod filesystem;
mod s3;

pub use base::{Connector, DocumentMetadata, RawDocument, SourceType};
pub use filesystem::{FilesystemConfig, FilesystemConnector};
pub use s3::{S3Config, S3Connector};
```

**Step 2: Create base types**

Create `crates/rag-ingestion/src/connectors/base.rs`:

```rust
//! Base types for document connectors.

use async_trait::async_trait;
use bytes::Bytes;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

use crate::error::Result;

/// Source type for a document.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceType {
    /// Local filesystem.
    Local,
    /// S3-compatible storage.
    S3,
}

impl std::fmt::Display for SourceType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Local => write!(f, "local"),
            Self::S3 => write!(f, "s3"),
        }
    }
}

/// Metadata about a document from its source.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentMetadata {
    /// Source identifier (relative path or S3 key).
    pub source_id: String,
    /// Type of source.
    pub source_type: SourceType,
    /// File name.
    pub filename: String,
    /// MIME type if known.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mime_type: Option<String>,
    /// File size in bytes.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub size_bytes: Option<u64>,
    /// Creation timestamp.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub created_at: Option<DateTime<Utc>>,
    /// Last modification timestamp.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub modified_at: Option<DateTime<Utc>>,
    /// Additional source-specific metadata.
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub extra: HashMap<String, Value>,
}

impl DocumentMetadata {
    /// Create new document metadata.
    #[must_use]
    pub fn new(
        source_id: impl Into<String>,
        source_type: SourceType,
        filename: impl Into<String>,
    ) -> Self {
        Self {
            source_id: source_id.into(),
            source_type,
            filename: filename.into(),
            mime_type: None,
            size_bytes: None,
            created_at: None,
            modified_at: None,
            extra: HashMap::new(),
        }
    }

    /// Set the MIME type.
    #[must_use]
    pub fn with_mime_type(mut self, mime_type: impl Into<String>) -> Self {
        self.mime_type = Some(mime_type.into());
        self
    }

    /// Set the file size.
    #[must_use]
    pub fn with_size(mut self, size_bytes: u64) -> Self {
        self.size_bytes = Some(size_bytes);
        self
    }

    /// Set the modification time.
    #[must_use]
    pub fn with_modified_at(mut self, modified_at: DateTime<Utc>) -> Self {
        self.modified_at = Some(modified_at);
        self
    }

    /// Add extra metadata.
    #[must_use]
    pub fn with_extra(mut self, key: impl Into<String>, value: Value) -> Self {
        self.extra.insert(key.into(), value);
        self
    }
}

/// A raw document fetched from a source.
#[derive(Debug, Clone)]
pub struct RawDocument {
    /// Document content as bytes.
    pub content: Bytes,
    /// Document metadata.
    pub metadata: DocumentMetadata,
}

impl RawDocument {
    /// Create a new raw document.
    #[must_use]
    pub fn new(content: impl Into<Bytes>, metadata: DocumentMetadata) -> Self {
        Self {
            content: content.into(),
            metadata,
        }
    }

    /// Get the content as a UTF-8 string (if valid).
    pub fn content_as_str(&self) -> Option<&str> {
        std::str::from_utf8(&self.content).ok()
    }
}

/// Trait for document source connectors.
#[async_trait]
pub trait Connector: Send + Sync {
    /// Connect to the source.
    async fn connect(&mut self) -> Result<()>;

    /// Disconnect from the source.
    async fn disconnect(&mut self) -> Result<()>;

    /// List documents at the given path.
    ///
    /// # Arguments
    ///
    /// * `path` - Optional path/prefix to list. If None, lists from the root.
    async fn list_documents(&self, path: Option<&str>) -> Result<Vec<DocumentMetadata>>;

    /// Fetch a single document by its source ID.
    async fn fetch_document(&self, source_id: &str) -> Result<RawDocument>;

    /// Check if the connector is connected.
    fn is_connected(&self) -> bool;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_source_type_display() {
        assert_eq!(SourceType::Local.to_string(), "local");
        assert_eq!(SourceType::S3.to_string(), "s3");
    }

    #[test]
    fn test_document_metadata_builder() {
        let meta = DocumentMetadata::new("path/to/file.pdf", SourceType::Local, "file.pdf")
            .with_mime_type("application/pdf")
            .with_size(1024)
            .with_extra("custom", serde_json::json!("value"));

        assert_eq!(meta.source_id, "path/to/file.pdf");
        assert_eq!(meta.filename, "file.pdf");
        assert_eq!(meta.mime_type, Some("application/pdf".to_string()));
        assert_eq!(meta.size_bytes, Some(1024));
        assert!(meta.extra.contains_key("custom"));
    }

    #[test]
    fn test_raw_document_content_as_str() {
        let meta = DocumentMetadata::new("test.txt", SourceType::Local, "test.txt");
        let doc = RawDocument::new(Bytes::from("Hello, World!"), meta);

        assert_eq!(doc.content_as_str(), Some("Hello, World!"));
    }

    #[test]
    fn test_raw_document_binary_content() {
        let meta = DocumentMetadata::new("test.bin", SourceType::Local, "test.bin");
        let doc = RawDocument::new(Bytes::from(vec![0xFF, 0xFE, 0x00]), meta);

        // Invalid UTF-8 should return None
        assert!(doc.content_as_str().is_none());
    }
}
```

**Step 3: Run tests**

Run: `cargo test -p rag-ingestion connectors::base`

Expected: 4 tests pass

**Step 4: Commit**

```bash
git add crates/rag-ingestion/src/connectors/
git commit -m "feat(ingestion): add connector base types and trait

- Add SourceType enum (Local, S3)
- Add DocumentMetadata with builder pattern
- Add RawDocument for fetched content
- Add Connector async trait
- Add unit tests

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Filesystem Connector

**Files:**
- Create: `crates/rag-ingestion/src/connectors/filesystem.rs`

**Step 1: Create filesystem connector**

Create `crates/rag-ingestion/src/connectors/filesystem.rs`:

```rust
//! Local filesystem connector.

use async_trait::async_trait;
use bytes::Bytes;
use chrono::{DateTime, TimeZone, Utc};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use tokio::fs;
use tracing::{debug, instrument};

use crate::error::{Error, Result};
use super::base::{Connector, DocumentMetadata, RawDocument, SourceType};

/// Configuration for the filesystem connector.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FilesystemConfig {
    /// Base path for file operations.
    pub base_path: PathBuf,
    /// Whether to scan directories recursively.
    #[serde(default = "default_true")]
    pub recursive: bool,
    /// File extensions to include (e.g., [".pdf", ".md"]).
    /// If None, all files are included.
    #[serde(default)]
    pub file_extensions: Option<Vec<String>>,
}

fn default_true() -> bool {
    true
}

impl FilesystemConfig {
    /// Create a new configuration.
    #[must_use]
    pub fn new(base_path: impl Into<PathBuf>) -> Self {
        Self {
            base_path: base_path.into(),
            recursive: true,
            file_extensions: None,
        }
    }

    /// Set whether to scan recursively.
    #[must_use]
    pub fn with_recursive(mut self, recursive: bool) -> Self {
        self.recursive = recursive;
        self
    }

    /// Set file extension filter.
    #[must_use]
    pub fn with_extensions(mut self, extensions: Vec<String>) -> Self {
        self.file_extensions = Some(extensions);
        self
    }
}

/// Connector for local filesystem.
pub struct FilesystemConnector {
    config: FilesystemConfig,
    connected: bool,
}

impl FilesystemConnector {
    /// Create a new filesystem connector.
    #[must_use]
    pub fn new(config: FilesystemConfig) -> Self {
        Self {
            config,
            connected: false,
        }
    }

    /// Check if a file should be included based on extension filter.
    fn should_include(&self, path: &Path) -> bool {
        if let Some(extensions) = &self.config.file_extensions {
            if let Some(ext) = path.extension() {
                let ext_str = format!(".{}", ext.to_string_lossy().to_lowercase());
                return extensions.iter().any(|e| e.to_lowercase() == ext_str);
            }
            false
        } else {
            true
        }
    }

    /// Detect MIME type from file path.
    fn detect_mime_type(path: &Path) -> Option<String> {
        mime_guess::from_path(path)
            .first()
            .map(|m| m.to_string())
    }

    /// Convert system time to DateTime<Utc>.
    fn system_time_to_datetime(time: std::time::SystemTime) -> Option<DateTime<Utc>> {
        time.duration_since(std::time::UNIX_EPOCH)
            .ok()
            .and_then(|d| Utc.timestamp_opt(d.as_secs() as i64, d.subsec_nanos()).single())
    }

    /// List files recursively.
    async fn list_recursive(&self, dir: &Path, base: &Path) -> Result<Vec<DocumentMetadata>> {
        let mut results = Vec::new();
        let mut stack = vec![dir.to_path_buf()];

        while let Some(current_dir) = stack.pop() {
            let mut entries = fs::read_dir(&current_dir)
                .await
                .map_err(|e| Error::Connector(format!("Failed to read directory: {e}")))?;

            while let Some(entry) = entries
                .next_entry()
                .await
                .map_err(|e| Error::Connector(format!("Failed to read entry: {e}")))?
            {
                let path = entry.path();
                let file_type = entry
                    .file_type()
                    .await
                    .map_err(|e| Error::Connector(format!("Failed to get file type: {e}")))?;

                if file_type.is_dir() && self.config.recursive {
                    stack.push(path);
                } else if file_type.is_file() && self.should_include(&path) {
                    if let Some(meta) = self.metadata_from_path(&path, base).await? {
                        results.push(meta);
                    }
                }
            }
        }

        Ok(results)
    }

    /// List files non-recursively.
    async fn list_flat(&self, dir: &Path, base: &Path) -> Result<Vec<DocumentMetadata>> {
        let mut results = Vec::new();
        let mut entries = fs::read_dir(dir)
            .await
            .map_err(|e| Error::Connector(format!("Failed to read directory: {e}")))?;

        while let Some(entry) = entries
            .next_entry()
            .await
            .map_err(|e| Error::Connector(format!("Failed to read entry: {e}")))?
        {
            let path = entry.path();
            let file_type = entry
                .file_type()
                .await
                .map_err(|e| Error::Connector(format!("Failed to get file type: {e}")))?;

            if file_type.is_file() && self.should_include(&path) {
                if let Some(meta) = self.metadata_from_path(&path, base).await? {
                    results.push(meta);
                }
            }
        }

        Ok(results)
    }

    /// Create metadata from a file path.
    async fn metadata_from_path(
        &self,
        path: &Path,
        base: &Path,
    ) -> Result<Option<DocumentMetadata>> {
        let file_meta = fs::metadata(path)
            .await
            .map_err(|e| Error::Connector(format!("Failed to get metadata: {e}")))?;

        let source_id = path
            .strip_prefix(base)
            .unwrap_or(path)
            .to_string_lossy()
            .to_string();

        let filename = path
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default();

        let mut meta = DocumentMetadata::new(source_id, SourceType::Local, filename)
            .with_size(file_meta.len());

        if let Some(mime) = Self::detect_mime_type(path) {
            meta = meta.with_mime_type(mime);
        }

        if let Ok(modified) = file_meta.modified() {
            if let Some(dt) = Self::system_time_to_datetime(modified) {
                meta = meta.with_modified_at(dt);
            }
        }

        meta = meta.with_extra("absolute_path", serde_json::json!(path.to_string_lossy()));

        Ok(Some(meta))
    }
}

#[async_trait]
impl Connector for FilesystemConnector {
    #[instrument(skip(self))]
    async fn connect(&mut self) -> Result<()> {
        // Verify base path exists
        if !self.config.base_path.exists() {
            return Err(Error::Connector(format!(
                "Base path does not exist: {}",
                self.config.base_path.display()
            )));
        }

        self.connected = true;
        debug!(path = %self.config.base_path.display(), "Filesystem connector connected");
        Ok(())
    }

    async fn disconnect(&mut self) -> Result<()> {
        self.connected = false;
        Ok(())
    }

    #[instrument(skip(self))]
    async fn list_documents(&self, path: Option<&str>) -> Result<Vec<DocumentMetadata>> {
        if !self.connected {
            return Err(Error::Connector("Not connected".to_string()));
        }

        let dir = if let Some(p) = path {
            self.config.base_path.join(p)
        } else {
            self.config.base_path.clone()
        };

        if !dir.exists() {
            return Ok(Vec::new());
        }

        if dir.is_file() {
            // Single file
            if self.should_include(&dir) {
                if let Some(meta) = self.metadata_from_path(&dir, &self.config.base_path).await? {
                    return Ok(vec![meta]);
                }
            }
            return Ok(Vec::new());
        }

        if self.config.recursive {
            self.list_recursive(&dir, &self.config.base_path).await
        } else {
            self.list_flat(&dir, &self.config.base_path).await
        }
    }

    #[instrument(skip(self))]
    async fn fetch_document(&self, source_id: &str) -> Result<RawDocument> {
        if !self.connected {
            return Err(Error::Connector("Not connected".to_string()));
        }

        let path = self.config.base_path.join(source_id);

        if !path.exists() {
            return Err(Error::NotFound(format!("File not found: {source_id}")));
        }

        if !path.is_file() {
            return Err(Error::Connector(format!("Not a file: {source_id}")));
        }

        let content = fs::read(&path)
            .await
            .map_err(|e| Error::Connector(format!("Failed to read file: {e}")))?;

        let meta = self
            .metadata_from_path(&path, &self.config.base_path)
            .await?
            .ok_or_else(|| Error::Connector("Failed to get metadata".to_string()))?;

        debug!(source_id, size = content.len(), "Document fetched");

        Ok(RawDocument::new(Bytes::from(content), meta))
    }

    fn is_connected(&self) -> bool {
        self.connected
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    use tokio::fs::File;
    use tokio::io::AsyncWriteExt;

    async fn setup_test_dir() -> TempDir {
        let dir = TempDir::new().unwrap();

        // Create test files
        let mut file1 = File::create(dir.path().join("test.txt")).await.unwrap();
        file1.write_all(b"Hello, World!").await.unwrap();

        let mut file2 = File::create(dir.path().join("doc.md")).await.unwrap();
        file2.write_all(b"# Markdown").await.unwrap();

        // Create subdirectory with file
        fs::create_dir(dir.path().join("subdir")).await.unwrap();
        let mut file3 = File::create(dir.path().join("subdir/nested.txt"))
            .await
            .unwrap();
        file3.write_all(b"Nested content").await.unwrap();

        dir
    }

    #[tokio::test]
    async fn test_connect_success() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path());
        let mut connector = FilesystemConnector::new(config);

        assert!(!connector.is_connected());
        connector.connect().await.unwrap();
        assert!(connector.is_connected());
    }

    #[tokio::test]
    async fn test_connect_nonexistent_path() {
        let config = FilesystemConfig::new("/nonexistent/path");
        let mut connector = FilesystemConnector::new(config);

        let result = connector.connect().await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_list_documents_recursive() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path()).with_recursive(true);
        let mut connector = FilesystemConnector::new(config);
        connector.connect().await.unwrap();

        let docs = connector.list_documents(None).await.unwrap();
        assert_eq!(docs.len(), 3); // test.txt, doc.md, subdir/nested.txt
    }

    #[tokio::test]
    async fn test_list_documents_non_recursive() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path()).with_recursive(false);
        let mut connector = FilesystemConnector::new(config);
        connector.connect().await.unwrap();

        let docs = connector.list_documents(None).await.unwrap();
        assert_eq!(docs.len(), 2); // test.txt, doc.md (no nested)
    }

    #[tokio::test]
    async fn test_list_documents_with_extension_filter() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path())
            .with_extensions(vec![".txt".to_string()]);
        let mut connector = FilesystemConnector::new(config);
        connector.connect().await.unwrap();

        let docs = connector.list_documents(None).await.unwrap();
        assert_eq!(docs.len(), 2); // test.txt, subdir/nested.txt
        assert!(docs.iter().all(|d| d.filename.ends_with(".txt")));
    }

    #[tokio::test]
    async fn test_fetch_document() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path());
        let mut connector = FilesystemConnector::new(config);
        connector.connect().await.unwrap();

        let doc = connector.fetch_document("test.txt").await.unwrap();
        assert_eq!(doc.content_as_str(), Some("Hello, World!"));
        assert_eq!(doc.metadata.filename, "test.txt");
        assert_eq!(doc.metadata.source_type, SourceType::Local);
    }

    #[tokio::test]
    async fn test_fetch_document_not_found() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path());
        let mut connector = FilesystemConnector::new(config);
        connector.connect().await.unwrap();

        let result = connector.fetch_document("nonexistent.txt").await;
        assert!(matches!(result, Err(Error::NotFound(_))));
    }

    #[tokio::test]
    async fn test_mime_type_detection() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path());
        let mut connector = FilesystemConnector::new(config);
        connector.connect().await.unwrap();

        let doc = connector.fetch_document("doc.md").await.unwrap();
        assert!(doc.metadata.mime_type.is_some());
        assert!(doc.metadata.mime_type.unwrap().contains("markdown") ||
                doc.metadata.mime_type.clone().unwrap().contains("text"));
    }
}
```

**Step 2: Run tests**

Run: `cargo test -p rag-ingestion connectors::filesystem`

Expected: 8 tests pass

**Step 3: Commit**

```bash
git add crates/rag-ingestion/src/connectors/
git commit -m "feat(ingestion): implement filesystem connector

- Add FilesystemConfig with recursive and extension filter options
- Add FilesystemConnector implementing Connector trait
- Support listing files recursively or flat
- Implement MIME type detection with mime_guess
- Add comprehensive tests with tempfile

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 9: S3 Connector

**Files:**
- Create: `crates/rag-ingestion/src/connectors/s3.rs`

**Step 1: Create S3 connector**

Create `crates/rag-ingestion/src/connectors/s3.rs`:

```rust
//! S3-compatible storage connector.

use async_trait::async_trait;
use aws_config::BehaviorVersion;
use aws_sdk_s3::config::Credentials;
use aws_sdk_s3::Client;
use bytes::Bytes;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use tracing::{debug, instrument};

use crate::error::{Error, Result};
use super::base::{Connector, DocumentMetadata, RawDocument, SourceType};

/// Configuration for the S3 connector.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct S3Config {
    /// S3 bucket name.
    pub bucket: String,
    /// Optional key prefix to filter objects.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub prefix: Option<String>,
    /// Custom endpoint URL (for MinIO or LocalStack).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub endpoint_url: Option<String>,
    /// AWS region.
    #[serde(default = "default_region")]
    pub region: String,
    /// Access key ID (optional, uses AWS credentials chain if not set).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub access_key_id: Option<String>,
    /// Secret access key (optional).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub secret_access_key: Option<String>,
    /// File extensions to include.
    #[serde(default)]
    pub file_extensions: Option<Vec<String>>,
}

fn default_region() -> String {
    "us-east-1".to_string()
}

impl S3Config {
    /// Create a new S3 configuration.
    #[must_use]
    pub fn new(bucket: impl Into<String>) -> Self {
        Self {
            bucket: bucket.into(),
            prefix: None,
            endpoint_url: None,
            region: default_region(),
            access_key_id: None,
            secret_access_key: None,
            file_extensions: None,
        }
    }

    /// Set the key prefix.
    #[must_use]
    pub fn with_prefix(mut self, prefix: impl Into<String>) -> Self {
        self.prefix = Some(prefix.into());
        self
    }

    /// Set a custom endpoint URL (for MinIO).
    #[must_use]
    pub fn with_endpoint(mut self, endpoint: impl Into<String>) -> Self {
        self.endpoint_url = Some(endpoint.into());
        self
    }

    /// Set the AWS region.
    #[must_use]
    pub fn with_region(mut self, region: impl Into<String>) -> Self {
        self.region = region.into();
        self
    }

    /// Set credentials.
    #[must_use]
    pub fn with_credentials(
        mut self,
        access_key_id: impl Into<String>,
        secret_access_key: impl Into<String>,
    ) -> Self {
        self.access_key_id = Some(access_key_id.into());
        self.secret_access_key = Some(secret_access_key.into());
        self
    }

    /// Set file extension filter.
    #[must_use]
    pub fn with_extensions(mut self, extensions: Vec<String>) -> Self {
        self.file_extensions = Some(extensions);
        self
    }
}

/// Connector for S3-compatible storage.
pub struct S3Connector {
    config: S3Config,
    client: Option<Client>,
}

impl S3Connector {
    /// Create a new S3 connector.
    #[must_use]
    pub fn new(config: S3Config) -> Self {
        Self {
            config,
            client: None,
        }
    }

    /// Check if a key should be included based on extension filter.
    fn should_include(&self, key: &str) -> bool {
        // Skip "directory" markers
        if key.ends_with('/') {
            return false;
        }

        if let Some(extensions) = &self.config.file_extensions {
            let key_lower = key.to_lowercase();
            extensions.iter().any(|ext| key_lower.ends_with(&ext.to_lowercase()))
        } else {
            true
        }
    }

    /// Extract filename from S3 key.
    fn filename_from_key(key: &str) -> String {
        key.rsplit('/').next().unwrap_or(key).to_string()
    }

    /// Detect MIME type from filename.
    fn detect_mime_type(filename: &str) -> Option<String> {
        mime_guess::from_path(filename)
            .first()
            .map(|m| m.to_string())
    }

    /// Get the S3 client, erroring if not connected.
    fn client(&self) -> Result<&Client> {
        self.client
            .as_ref()
            .ok_or_else(|| Error::Connector("Not connected".to_string()))
    }
}

#[async_trait]
impl Connector for S3Connector {
    #[instrument(skip(self), fields(bucket = %self.config.bucket))]
    async fn connect(&mut self) -> Result<()> {
        let mut config_builder = aws_sdk_s3::config::Builder::new()
            .behavior_version(BehaviorVersion::latest())
            .region(aws_sdk_s3::config::Region::new(self.config.region.clone()));

        // Set custom endpoint for MinIO/LocalStack
        if let Some(endpoint) = &self.config.endpoint_url {
            config_builder = config_builder
                .endpoint_url(endpoint)
                .force_path_style(true);
        }

        // Set explicit credentials if provided
        if let (Some(access_key), Some(secret_key)) =
            (&self.config.access_key_id, &self.config.secret_access_key)
        {
            let creds = Credentials::new(access_key, secret_key, None, None, "static");
            config_builder = config_builder.credentials_provider(creds);
        } else {
            // Use default credentials chain
            let aws_config = aws_config::defaults(BehaviorVersion::latest())
                .region(aws_sdk_s3::config::Region::new(self.config.region.clone()))
                .load()
                .await;
            config_builder =
                config_builder.credentials_provider(aws_config.credentials_provider().unwrap());
        }

        let client = Client::from_conf(config_builder.build());

        // Verify bucket access
        client
            .head_bucket()
            .bucket(&self.config.bucket)
            .send()
            .await
            .map_err(|e| Error::Connector(format!("Failed to access bucket: {e}")))?;

        self.client = Some(client);
        debug!(bucket = %self.config.bucket, "S3 connector connected");
        Ok(())
    }

    async fn disconnect(&mut self) -> Result<()> {
        self.client = None;
        Ok(())
    }

    #[instrument(skip(self))]
    async fn list_documents(&self, path: Option<&str>) -> Result<Vec<DocumentMetadata>> {
        let client = self.client()?;

        // Determine prefix: use provided path, or config prefix, or empty
        let prefix = path
            .map(String::from)
            .or_else(|| self.config.prefix.clone())
            .unwrap_or_default();

        let mut results = Vec::new();
        let mut continuation_token: Option<String> = None;

        loop {
            let mut request = client
                .list_objects_v2()
                .bucket(&self.config.bucket)
                .prefix(&prefix);

            if let Some(token) = &continuation_token {
                request = request.continuation_token(token);
            }

            let response = request
                .send()
                .await
                .map_err(|e| Error::Connector(format!("Failed to list objects: {e}")))?;

            if let Some(contents) = response.contents() {
                for obj in contents {
                    let key = obj.key().unwrap_or("");
                    if !self.should_include(key) {
                        continue;
                    }

                    let filename = Self::filename_from_key(key);
                    let mut meta = DocumentMetadata::new(key, SourceType::S3, filename.clone());

                    if let Some(size) = obj.size() {
                        meta = meta.with_size(size as u64);
                    }

                    if let Some(modified) = obj.last_modified() {
                        if let Ok(dt) = DateTime::parse_from_rfc3339(&modified.fmt(aws_sdk_s3::primitives::DateTimeFormat::DateTime).unwrap()) {
                            meta = meta.with_modified_at(dt.with_timezone(&Utc));
                        }
                    }

                    if let Some(mime) = Self::detect_mime_type(&filename) {
                        meta = meta.with_mime_type(mime);
                    }

                    if let Some(etag) = obj.e_tag() {
                        meta = meta.with_extra("etag", serde_json::json!(etag.trim_matches('"')));
                    }

                    meta = meta.with_extra("bucket", serde_json::json!(&self.config.bucket));

                    results.push(meta);
                }
            }

            if response.is_truncated() == Some(true) {
                continuation_token = response.next_continuation_token().map(String::from);
            } else {
                break;
            }
        }

        debug!(count = results.len(), "Listed S3 objects");
        Ok(results)
    }

    #[instrument(skip(self))]
    async fn fetch_document(&self, source_id: &str) -> Result<RawDocument> {
        let client = self.client()?;

        let response = client
            .get_object()
            .bucket(&self.config.bucket)
            .key(source_id)
            .send()
            .await
            .map_err(|e| {
                if e.to_string().contains("NoSuchKey") || e.to_string().contains("404") {
                    Error::NotFound(format!("Object not found: {source_id}"))
                } else {
                    Error::Connector(format!("Failed to get object: {e}"))
                }
            })?;

        let content = response
            .body
            .collect()
            .await
            .map_err(|e| Error::Connector(format!("Failed to read body: {e}")))?
            .into_bytes();

        let filename = Self::filename_from_key(source_id);
        let mut meta = DocumentMetadata::new(source_id, SourceType::S3, filename.clone())
            .with_size(content.len() as u64);

        if let Some(content_type) = response.content_type() {
            meta = meta.with_mime_type(content_type);
        } else if let Some(mime) = Self::detect_mime_type(&filename) {
            meta = meta.with_mime_type(mime);
        }

        if let Some(etag) = response.e_tag() {
            meta = meta.with_extra("etag", serde_json::json!(etag.trim_matches('"')));
        }

        meta = meta.with_extra("bucket", serde_json::json!(&self.config.bucket));

        debug!(source_id, size = content.len(), "S3 document fetched");

        Ok(RawDocument::new(Bytes::from(content), meta))
    }

    fn is_connected(&self) -> bool {
        self.client.is_some()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_builder() {
        let config = S3Config::new("my-bucket")
            .with_prefix("documents/")
            .with_endpoint("http://localhost:9000")
            .with_region("eu-west-1")
            .with_credentials("access", "secret")
            .with_extensions(vec![".pdf".to_string()]);

        assert_eq!(config.bucket, "my-bucket");
        assert_eq!(config.prefix, Some("documents/".to_string()));
        assert_eq!(config.endpoint_url, Some("http://localhost:9000".to_string()));
        assert_eq!(config.region, "eu-west-1");
        assert_eq!(config.access_key_id, Some("access".to_string()));
        assert_eq!(config.secret_access_key, Some("secret".to_string()));
    }

    #[test]
    fn test_should_include_extension_filter() {
        let config = S3Config::new("bucket").with_extensions(vec![".pdf".to_string(), ".txt".to_string()]);
        let connector = S3Connector::new(config);

        assert!(connector.should_include("doc.pdf"));
        assert!(connector.should_include("path/to/file.txt"));
        assert!(connector.should_include("UPPER.PDF")); // Case insensitive
        assert!(!connector.should_include("image.png"));
        assert!(!connector.should_include("folder/")); // Directory marker
    }

    #[test]
    fn test_should_include_no_filter() {
        let config = S3Config::new("bucket");
        let connector = S3Connector::new(config);

        assert!(connector.should_include("anything.xyz"));
        assert!(!connector.should_include("folder/")); // Still skip directories
    }

    #[test]
    fn test_filename_from_key() {
        assert_eq!(S3Connector::filename_from_key("a/b/c.txt"), "c.txt");
        assert_eq!(S3Connector::filename_from_key("file.pdf"), "file.pdf");
        assert_eq!(S3Connector::filename_from_key(""), "");
    }

    #[test]
    fn test_not_connected_error() {
        let config = S3Config::new("bucket");
        let connector = S3Connector::new(config);

        assert!(!connector.is_connected());
    }
}
```

**Step 2: Run tests**

Run: `cargo test -p rag-ingestion connectors::s3`

Expected: 5 tests pass

**Step 3: Commit**

```bash
git add crates/rag-ingestion/src/connectors/
git commit -m "feat(ingestion): implement S3 connector

- Add S3Config with endpoint, credentials, and extension filter options
- Add S3Connector implementing Connector trait
- Support custom endpoints for MinIO/LocalStack
- Implement pagination for large buckets
- Add extension-based filtering
- Add unit tests

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 10: Update lib.rs with New Modules

**Files:**
- Modify: `crates/rag-ingestion/src/lib.rs`

**Step 1: Add new module exports**

Replace `crates/rag-ingestion/src/lib.rs`:

```rust
//! Document parsing, chunking, embedding, and indexing for the RAG pipeline.
//!
//! This crate provides components for the ingestion phase of the RAG pipeline:
//!
//! - **Parsers** ([`parsers`]): Extract structured content from documents
//!   - [`parsers::HtmlParser`]: Parse HTML documents using `scraper`
//!   - [`parsers::MarkdownParser`]: Parse Markdown with YAML frontmatter
//!
//! - **Chunking** ([`chunking`]): Split text into chunks for embedding
//!   - [`chunking::RecursiveCharacterSplitter`]: Split by paragraphs, sentences, words
//!
//! - **Embedding** ([`embedding`]): Generate vector embeddings
//!   - [`embedding::EmbeddingClient`]: HTTP client for embedding service
//!
//! - **Indexing** ([`indexing`]): Coordinate writes to multiple stores
//!   - [`indexing::IndexCoordinator`]: Parallel writes to Qdrant, OpenSearch, PostgreSQL
//!
//! - **Connectors** ([`connectors`]): Read documents from various sources
//!   - [`connectors::FilesystemConnector`]: Local filesystem
//!   - [`connectors::S3Connector`]: S3-compatible storage (AWS S3, MinIO)
//!
//! # Example
//!
//! ```rust
//! use rag_ingestion::parsers::{HtmlParser, Parser};
//! use rag_ingestion::chunking::{RecursiveCharacterSplitter, ChunkingStrategy, ChunkingConfig};
//! use rag_types::DocumentId;
//!
//! // Parse an HTML document
//! let html = b"<html><head><title>Title</title></head><body><p>Content here.</p></body></html>";
//! let parser = HtmlParser::default();
//! let doc = parser.parse(html, None).unwrap();
//!
//! assert_eq!(doc.title, Some("Title".to_string()));
//!
//! // Chunk the extracted text
//! let config = ChunkingConfig {
//!     target_tokens: 100,
//!     max_tokens: 200,
//!     ..Default::default()
//! };
//! let chunker = RecursiveCharacterSplitter::new(config).unwrap();
//! let chunks = chunker.chunk(&doc.text, DocumentId::new(), None).unwrap();
//!
//! assert!(!chunks.is_empty());
//! ```

pub mod chunking;
pub mod connectors;
pub mod embedding;
pub mod error;
pub mod indexing;
pub mod parsers;

pub use error::{Error, Result};

// Re-export commonly used types
pub use chunking::{Chunk, ChunkingConfig, ChunkingStrategy, RecursiveCharacterSplitter};
pub use connectors::{
    Connector, DocumentMetadata, FilesystemConfig, FilesystemConnector, RawDocument, S3Config,
    S3Connector, SourceType,
};
pub use embedding::{EmbeddingClient, EmbeddingClientConfig};
pub use indexing::{
    DocumentRecord, IndexCoordinator, IndexCoordinatorConfig, IndexStatus, IndexedChunk,
    WriteResult,
};
pub use parsers::{
    ContentBlock, ContentType, HtmlParser, HtmlParserConfig, MarkdownParser, ParsedDocument, Parser,
    TableContent,
};
```

**Step 2: Add humantime-serde to Cargo.toml**

Update `crates/rag-ingestion/Cargo.toml` to add missing dependency:

```toml
# Add to [dependencies] section after chrono:
humantime-serde = "1.1"
```

**Step 3: Run full test suite**

Run: `cargo test -p rag-ingestion`

Expected: All tests pass (30+ tests)

**Step 4: Run clippy**

Run: `cargo clippy -p rag-ingestion --all-targets`

Expected: No errors (warnings OK)

**Step 5: Commit**

```bash
git add crates/rag-ingestion/
git commit -m "feat(ingestion): complete P3.4-P3.6 implementation

- Update lib.rs with all new module exports
- Add re-exports for commonly used types
- Add humantime-serde dependency
- All tests passing

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 11: Integration Tests

**Files:**
- Modify: `crates/rag-ingestion/tests/integration.rs`

**Step 1: Add integration tests for new components**

Add to `crates/rag-ingestion/tests/integration.rs`:

```rust
// Add these tests after existing integration tests

mod embedding_integration {
    use rag_ingestion::embedding::{EmbeddingClient, EmbeddingClientConfig};
    use std::time::Duration;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[tokio::test]
    async fn test_embedding_pipeline() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "data": [
                    {"embedding": vec![0.1_f32; 384], "index": 0},
                    {"embedding": vec![0.2_f32; 384], "index": 1},
                    {"embedding": vec![0.3_f32; 384], "index": 2}
                ],
                "usage": {"total_tokens": 25}
            })))
            .mount(&mock_server)
            .await;

        let config = EmbeddingClientConfig::new(mock_server.uri())
            .with_timeout(Duration::from_secs(5));
        let client = EmbeddingClient::new(config).unwrap();

        let texts = vec![
            "First chunk of text".to_string(),
            "Second chunk of text".to_string(),
            "Third chunk of text".to_string(),
        ];

        let (embeddings, tokens) = client.embed_batch(&texts).await.unwrap();

        assert_eq!(embeddings.len(), 3);
        assert_eq!(embeddings[0].len(), 384);
        assert_eq!(tokens, 25);
    }
}

mod connector_integration {
    use rag_ingestion::connectors::{Connector, FilesystemConfig, FilesystemConnector};
    use rag_ingestion::parsers::{HtmlParser, MarkdownParser, Parser};
    use tempfile::TempDir;
    use tokio::fs::File;
    use tokio::io::AsyncWriteExt;

    async fn create_test_docs() -> TempDir {
        let dir = TempDir::new().unwrap();

        let mut html = File::create(dir.path().join("page.html")).await.unwrap();
        html.write_all(b"<html><head><title>Test Page</title></head><body><p>Hello HTML</p></body></html>")
            .await
            .unwrap();

        let mut md = File::create(dir.path().join("readme.md")).await.unwrap();
        md.write_all(b"# README\n\nThis is markdown content.")
            .await
            .unwrap();

        dir
    }

    #[tokio::test]
    async fn test_connector_to_parser_pipeline() {
        let dir = create_test_docs().await;
        let config = FilesystemConfig::new(dir.path());
        let mut connector = FilesystemConnector::new(config);
        connector.connect().await.unwrap();

        // List and fetch HTML
        let docs = connector.list_documents(None).await.unwrap();
        assert_eq!(docs.len(), 2);

        let html_meta = docs.iter().find(|d| d.filename == "page.html").unwrap();
        let html_doc = connector.fetch_document(&html_meta.source_id).await.unwrap();

        let html_parser = HtmlParser::default();
        let parsed_html = html_parser.parse(&html_doc.content, None).unwrap();
        assert_eq!(parsed_html.title, Some("Test Page".to_string()));
        assert!(parsed_html.text.contains("Hello HTML"));

        // Fetch and parse Markdown
        let md_meta = docs.iter().find(|d| d.filename == "readme.md").unwrap();
        let md_doc = connector.fetch_document(&md_meta.source_id).await.unwrap();

        let md_parser = MarkdownParser::default();
        let parsed_md = md_parser.parse(&md_doc.content, None).unwrap();
        assert_eq!(parsed_md.title, Some("README".to_string()));
        assert!(parsed_md.text.contains("markdown content"));
    }
}

mod full_pipeline {
    use rag_ingestion::chunking::{ChunkingConfig, ChunkingStrategy, RecursiveCharacterSplitter};
    use rag_ingestion::connectors::{Connector, FilesystemConfig, FilesystemConnector};
    use rag_ingestion::embedding::{EmbeddingClient, EmbeddingClientConfig};
    use rag_ingestion::parsers::{MarkdownParser, Parser};
    use rag_types::DocumentId;
    use tempfile::TempDir;
    use tokio::fs::File;
    use tokio::io::AsyncWriteExt;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[tokio::test]
    async fn test_full_ingestion_pipeline() {
        // Setup: Create test document
        let dir = TempDir::new().unwrap();
        let mut file = File::create(dir.path().join("document.md")).await.unwrap();
        file.write_all(
            b"# Important Document\n\nThis is the first paragraph with some content.\n\nThis is the second paragraph with more content.",
        )
        .await
        .unwrap();

        // Setup: Mock embedding service
        let mock_server = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "data": [
                    {"embedding": vec![0.1_f32; 384], "index": 0}
                ],
                "usage": {"total_tokens": 10}
            })))
            .mount(&mock_server)
            .await;

        // Step 1: Connect and fetch document
        let fs_config = FilesystemConfig::new(dir.path());
        let mut connector = FilesystemConnector::new(fs_config);
        connector.connect().await.unwrap();

        let raw_doc = connector.fetch_document("document.md").await.unwrap();

        // Step 2: Parse document
        let parser = MarkdownParser::default();
        let parsed = parser.parse(&raw_doc.content, None).unwrap();
        assert_eq!(parsed.title, Some("Important Document".to_string()));

        // Step 3: Chunk document
        let chunk_config = ChunkingConfig {
            target_tokens: 50,
            max_tokens: 100,
            chunk_overlap: 10,
            ..Default::default()
        };
        let chunker = RecursiveCharacterSplitter::new(chunk_config).unwrap();
        let chunks = chunker.chunk(&parsed.text, DocumentId::new(), None).unwrap();
        assert!(!chunks.is_empty());

        // Step 4: Generate embeddings
        let embed_config = EmbeddingClientConfig::new(mock_server.uri());
        let embed_client = EmbeddingClient::new(embed_config).unwrap();

        let texts: Vec<String> = chunks.iter().map(|c| c.content.clone()).collect();
        let (embeddings, _) = embed_client.embed_batch(&texts).await.unwrap();
        assert_eq!(embeddings.len(), chunks.len());

        // Pipeline complete!
        println!(
            "Ingestion pipeline: {} chunks with {} embeddings",
            chunks.len(),
            embeddings.len()
        );
    }
}
```

**Step 2: Run integration tests**

Run: `cargo test -p rag-ingestion --test integration`

Expected: All tests pass (6+ integration tests)

**Step 3: Commit**

```bash
git add crates/rag-ingestion/tests/
git commit -m "test(ingestion): add P3.4-P3.6 integration tests

- Add embedding pipeline test
- Add connector-to-parser pipeline test
- Add full ingestion pipeline test (fetch → parse → chunk → embed)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

Plan complete and saved to `docs/plans/2025-01-27-rust-ingestion-p3.4-3.6-implementation.md`.

**Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**

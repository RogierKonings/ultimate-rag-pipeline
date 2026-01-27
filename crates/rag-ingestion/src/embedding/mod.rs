//! Embedding client for generating vector embeddings.
//!
//! This module provides an HTTP client for the embedding service
//! using the OpenAI-compatible API format.

mod client;
mod config;

pub use client::EmbeddingClient;
pub use config::EmbeddingClientConfig;

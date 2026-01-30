//! Embedding service for RAG Pipeline.
//!
//! Provides text embeddings using Candle-based sentence transformers
//! with an OpenAI-compatible REST API.

pub mod config;
pub mod error;
pub mod model;
pub mod api;

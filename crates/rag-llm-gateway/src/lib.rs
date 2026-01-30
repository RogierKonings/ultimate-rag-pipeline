//! Unified LLM Gateway for RAG Pipeline.
//!
//! Provides a single service that handles:
//! - Text embeddings (via fastembed)
//! - Document reranking (cross-encoder)
//! - LLM chat completions (proxy to vLLM)
//! - JWT and API key authentication
//! - Rate limiting
//! - Prometheus metrics

pub mod auth;
pub mod config;
pub mod error;
pub mod rate_limit;

// These modules will be added in subsequent tasks
// pub mod api;
// pub mod clients;
// pub mod metrics;
// pub mod reranker;

pub use auth::{auth_middleware, AuthContext, JwtValidator};
pub use config::GatewayConfig;
pub use error::{GatewayError, Result};
pub use rate_limit::{rate_limit_middleware, RateLimitResult, RateLimiter};

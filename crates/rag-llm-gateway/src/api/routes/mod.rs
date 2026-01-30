//! API routes.

mod chat;
mod embeddings;
mod health;
mod models;
mod rerank;

use std::sync::Arc;

use axum::{
    middleware,
    routing::{get, post},
    Router,
};

use crate::api::AppState;
use crate::rate_limit::rate_limit_middleware;

/// Create the main router with all API routes.
pub fn create_router(state: Arc<AppState>) -> Router {
    let api_routes = Router::new()
        // OpenAI-compatible endpoints
        .route("/v1/embeddings", post(embeddings::create_embeddings))
        .route("/v1/chat/completions", post(chat::create_chat_completion))
        .route("/v1/rerank", post(rerank::create_rerank))
        .route("/v1/rerankings", post(rerank::create_rerank))
        .route("/v1/models", get(models::list_models))
        // Apply rate limiting to API routes
        .layer(middleware::from_fn_with_state(
            state.rate_limiter.clone(),
            rate_limit_middleware,
        ))
        .with_state(state.clone());

    Router::new()
        // Health endpoints (no auth or rate limiting required)
        .route("/", get(health::root))
        .route("/health", get(health::health))
        .route("/health/live", get(health::liveness))
        .route("/health/ready", get(health::readiness))
        .route("/metrics", get(health::metrics))
        // Merge in the rate-limited API routes
        .merge(api_routes)
        .with_state(state)
}

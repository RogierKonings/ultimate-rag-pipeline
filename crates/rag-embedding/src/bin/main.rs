//! Embedding Service - Rust HTTP Binary
//!
//! Provides OpenAI-compatible text embeddings using fastembed
//! ONNX-based inference.
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
use rag_embedding::model::EmbeddingModelWrapper;

#[tokio::main]
async fn main() {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| {
                "embedding_service=info,rag_embedding=info,tower_http=info".into()
            }),
        )
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
    let model = match EmbeddingModelWrapper::load(&config) {
        Ok(model) => model,
        Err(e) => {
            error!("Failed to load model: {}", e);
            std::process::exit(1);
        }
    };

    info!("Model loaded. Embedding dimension: {}", model.dimensions());

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

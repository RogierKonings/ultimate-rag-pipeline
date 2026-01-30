//! LLM Gateway service entry point.

use std::net::SocketAddr;
use std::sync::Arc;

use rag_embedding::{EmbeddingConfig, EmbeddingModelWrapper};
use rag_llm_gateway::{api, GatewayConfig};
use tower_http::trace::TraceLayer;
use tracing::info;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    info!("Starting LLM Gateway v{}", env!("CARGO_PKG_VERSION"));

    // Load configuration
    let config = GatewayConfig::from_env();
    info!("Configuration loaded");

    // Create app state
    let mut state = api::AppState::new(config.clone())?;

    // Load embedding model if enabled
    if config.embedding.enabled {
        info!("Loading embedding model: {}...", config.embedding.model);
        let embed_config = EmbeddingConfig::from_env();
        let model = tokio::task::spawn_blocking(move || EmbeddingModelWrapper::load(&embed_config))
            .await??;
        info!("Embedding model loaded: {}", model.model_id());
        state = state.with_embedding_model(model);
    }

    // Note: Reranker model loading is stubbed for now
    // Would be loaded similarly when ONNX support is complete
    if config.reranker.enabled {
        info!("Reranker enabled but ONNX loading not yet implemented - skipping");
    }

    // Check vLLM connection
    if config.vllm.enabled {
        info!("vLLM proxy enabled, URL: {}", config.vllm.url);
    }

    let state = Arc::new(state);

    // Create router
    let app = api::create_router(state).layer(TraceLayer::new_for_http());

    // Start server
    let addr: SocketAddr = format!("{}:{}", config.server.host, config.server.port)
        .parse()
        .expect("Invalid server address");

    info!("Listening on http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}

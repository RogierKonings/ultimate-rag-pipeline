//! Ingestion API service binary.
//!
//! This is the entry point for the ingestion HTTP server.
//!
//! # Usage
//!
//! ```bash
//! # Run with default settings (0.0.0.0:8001)
//! cargo run --bin ingestion-api
//!
//! # Configure via environment variables
//! INGESTION_HOST=127.0.0.1 INGESTION_PORT=9001 cargo run --bin ingestion-api
//! ```

use std::sync::Arc;

use rag_ingestion::api::{
    run_server_with_shutdown, AppState, JobTracker, ServerConfig,
};
use tokio::signal;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "ingestion_api=info,rag_ingestion=info,tower_http=debug".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    // Load configuration
    let config = ServerConfig::from_env();

    tracing::info!(
        addr = %config.addr,
        timeout_secs = config.timeout_secs,
        "Starting ingestion API server"
    );

    // Build application state
    let state = Arc::new(
        AppState::builder()
            .job_tracker(Arc::new(JobTracker::new()))
            // TODO: Add index_coordinator and embedding_client when available
            .build()?,
    );

    // Run server with graceful shutdown
    run_server_with_shutdown(state, config.addr, shutdown_signal()).await?;

    Ok(())
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
            .expect("Failed to install signal handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        () = ctrl_c => {},
        () = terminate => {},
    }

    tracing::info!("Shutdown signal received, starting graceful shutdown");
}

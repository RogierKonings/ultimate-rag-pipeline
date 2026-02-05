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
//! REDIS_URL=redis://localhost:6379 cargo run --bin ingestion-api
//! ```

use std::sync::Arc;
use tokio::sync::Mutex;

use rag_database::{DatabaseConfig, DatabasePool};
use rag_ingestion::api::{run_server_with_shutdown, AppState, JobTracker, ServerConfig};
use rag_ingestion::embedding::{EmbeddingClient, EmbeddingClientConfig};
use rag_ingestion::indexing::{IndexCoordinator, IndexCoordinatorConfig};
use rag_ingestion::worker::{IngestionJobHandler, JobQueue, WorkerPool, WorkerPoolConfig};
use rag_search::{SearchClient, SearchConfig};
use rag_vectorstore::{VectorStoreClient, VectorStoreConfig};
use tokio::signal;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| {
                "ingestion_api=info,rag_ingestion=info,tower_http=debug".into()
            }),
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

    // Get Redis URL from environment
    let redis_url = std::env::var("REDIS_URL")
        .unwrap_or_else(|_| "redis://:ragredis@localhost:6379".to_string());

    tracing::info!(redis_url = %redis_url, "Connecting to Redis");

    // Create shared job tracker
    let job_tracker = Arc::new(JobTracker::new());

    // Create job queue for enqueueing from API routes
    let api_job_queue = match JobQueue::new(&redis_url, "ingestion").await {
        Ok(queue) => {
            tracing::info!("Connected to Redis for API job queue");
            Some(Arc::new(Mutex::new(queue)))
        }
        Err(e) => {
            tracing::warn!(error = %e, "Failed to connect to Redis - jobs will not be enqueued");
            None
        }
    };

    // Create worker pool job queue (separate connection)
    let worker_job_queue = match JobQueue::new(&redis_url, "ingestion").await {
        Ok(queue) => {
            tracing::info!("Connected to Redis for worker pool");
            Some(queue)
        }
        Err(e) => {
            tracing::warn!(error = %e, "Failed to connect to Redis for workers - background processing disabled");
            None
        }
    };

    // Create embedding client
    let embedding_client = create_embedding_client().await;

    // Create index coordinator
    let index_coordinator = create_index_coordinator().await;

    // Connect to PostgreSQL for document queries
    let database_url = std::env::var("DATABASE_URL")
        .unwrap_or_else(|_| "postgres://raguser:ragpass@localhost:5432/ragpipeline".to_string());

    let db_config = DatabaseConfig::new(&database_url);
    let database = match DatabasePool::connect(&db_config).await {
        Ok(pool) => {
            tracing::info!("Connected to PostgreSQL for API queries");
            Some(pool)
        }
        Err(e) => {
            tracing::warn!(error = %e, "Failed to connect to PostgreSQL for API - document listing will be unavailable");
            None
        }
    };

    // Build application state
    let mut state_builder = AppState::builder()
        .job_tracker(Arc::clone(&job_tracker));

    if let Some(queue) = api_job_queue {
        state_builder = state_builder.job_queue(queue);
    }

    if let Some(db) = database {
        state_builder = state_builder.database(db);
    }

    let state = Arc::new(state_builder.build()?);

    // Start worker pool if we have a Redis connection
    let mut worker_pool = if let Some(queue) = worker_job_queue {
        // Create the ingestion job handler with embedding client and index coordinator
        let handler = IngestionJobHandler::new(
            Arc::clone(&job_tracker),
            embedding_client.map(Arc::new),
            index_coordinator.map(Arc::new),
        );

        // Create and start worker pool
        let worker_config = WorkerPoolConfig {
            concurrency: std::env::var("WORKER_CONCURRENCY")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(4),
            ..Default::default()
        };

        let mut pool = WorkerPool::new(worker_config.clone(), Arc::new(handler));

        match pool.start(queue).await {
            Ok(()) => {
                tracing::info!(
                    concurrency = worker_config.concurrency,
                    "Worker pool started"
                );
                Some(pool)
            }
            Err(e) => {
                tracing::error!(error = %e, "Failed to start worker pool");
                None
            }
        }
    } else {
        tracing::warn!("Worker pool not started - Redis connection unavailable");
        None
    };

    // Run server with graceful shutdown
    run_server_with_shutdown(state, config.addr, shutdown_signal()).await?;

    // Shutdown worker pool gracefully
    if let Some(ref mut pool) = worker_pool {
        tracing::info!("Shutting down worker pool...");
        pool.shutdown().await;
        tracing::info!("Worker pool shutdown complete");
    }

    Ok(())
}

/// Create the embedding client from environment variables.
async fn create_embedding_client() -> Option<EmbeddingClient> {
    let embedding_url = std::env::var("EMBEDDING_SERVICE_URL")
        .unwrap_or_else(|_| "http://localhost:8080".to_string());

    tracing::info!(url = %embedding_url, "Configuring embedding client");

    let config = EmbeddingClientConfig::new(&embedding_url);

    match EmbeddingClient::new(config) {
        Ok(client) => {
            tracing::info!("Embedding client configured");
            Some(client)
        }
        Err(e) => {
            tracing::warn!(error = %e, "Failed to create embedding client - embeddings will be skipped");
            None
        }
    }
}

/// Create the index coordinator from environment variables.
async fn create_index_coordinator() -> Option<IndexCoordinator> {
    // Get configuration from environment
    let qdrant_url = std::env::var("QDRANT_URL")
        .unwrap_or_else(|_| "http://localhost:6333".to_string());
    let opensearch_url = std::env::var("OPENSEARCH_URL")
        .unwrap_or_else(|_| "http://localhost:9200".to_string());
    let database_url = std::env::var("DATABASE_URL")
        .unwrap_or_else(|_| "postgres://raguser:ragpass@localhost:5432/ragpipeline".to_string());

    tracing::info!(
        qdrant_url = %qdrant_url,
        opensearch_url = %opensearch_url,
        "Configuring index coordinator"
    );

    // Connect to Qdrant
    let qdrant_config = VectorStoreConfig {
        url: qdrant_url,
        default_collection: Some("documents".to_string()),
        ..Default::default()
    };

    let qdrant = match VectorStoreClient::connect(&qdrant_config).await {
        Ok(client) => {
            tracing::info!("Connected to Qdrant");
            client
        }
        Err(e) => {
            tracing::warn!(error = %e, "Failed to connect to Qdrant - indexing will be skipped");
            return None;
        }
    };

    // Connect to OpenSearch
    let opensearch_config = SearchConfig {
        url: opensearch_url,
        danger_accept_invalid_certs: true, // For local development
        ..Default::default()
    };

    let opensearch = match SearchClient::new(opensearch_config) {
        Ok(client) => {
            tracing::info!("Connected to OpenSearch");
            client
        }
        Err(e) => {
            tracing::warn!(error = %e, "Failed to connect to OpenSearch - indexing will be skipped");
            return None;
        }
    };

    // Connect to PostgreSQL
    let db_config = DatabaseConfig::new(&database_url);

    let database = match DatabasePool::connect(&db_config).await {
        Ok(pool) => {
            tracing::info!("Connected to PostgreSQL");
            pool
        }
        Err(e) => {
            tracing::warn!(error = %e, "Failed to connect to PostgreSQL - indexing will be skipped");
            return None;
        }
    };

    // Create index coordinator
    let coordinator_config = IndexCoordinatorConfig::default();
    let coordinator = IndexCoordinator::new(qdrant, opensearch, database, coordinator_config);

    tracing::info!("Index coordinator configured");
    Some(coordinator)
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

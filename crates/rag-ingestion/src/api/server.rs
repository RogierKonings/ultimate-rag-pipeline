//! Server setup and configuration for the ingestion service.

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use axum::{
    routing::{delete, get, post},
    Router,
};
use tower::ServiceBuilder;
use tower_http::{
    cors::{Any, CorsLayer},
    timeout::TimeoutLayer,
    trace::{DefaultMakeSpan, DefaultOnRequest, DefaultOnResponse, TraceLayer},
};
use tracing::Level;

use crate::api::routes;
use crate::api::state::AppState;

/// Default request timeout in seconds.
const DEFAULT_TIMEOUT_SECS: u64 = 60;

/// Create the Axum router with all routes configured.
#[must_use]
pub fn create_router(state: Arc<AppState>) -> Router {
    create_router_with_timeout(state, DEFAULT_TIMEOUT_SECS)
}

/// Create the Axum router with a custom timeout.
#[must_use]
pub fn create_router_with_timeout(state: Arc<AppState>, timeout_secs: u64) -> Router {
    // Build middleware stack
    let middleware = ServiceBuilder::new()
        .layer(
            TraceLayer::new_for_http()
                .make_span_with(DefaultMakeSpan::new().level(Level::INFO))
                .on_request(DefaultOnRequest::new().level(Level::INFO))
                .on_response(DefaultOnResponse::new().level(Level::INFO)),
        )
        .layer(
            CorsLayer::new()
                .allow_origin(Any)
                .allow_methods(Any)
                .allow_headers(Any),
        )
        .layer(TimeoutLayer::new(Duration::from_secs(timeout_secs)));

    // Build the router
    Router::new()
        // Ingest routes
        .route("/api/v1/ingest", post(routes::start_ingestion))
        .route("/api/v1/ingest", get(routes::list_active_jobs))
        .route(
            "/api/v1/ingest/single",
            post(routes::ingest_single_document),
        )
        .route("/api/v1/ingest/sync", post(routes::start_sync))
        .route("/api/v1/ingest/reembed", post(routes::start_reembed))
        .route("/api/v1/ingest/:job_id", get(routes::get_job_status))
        .route("/api/v1/ingest/:job_id", delete(routes::cancel_job))
        // Document routes
        .route("/api/v1/documents", get(routes::list_documents))
        .route(
            "/api/v1/documents/sync-status",
            get(routes::get_sync_status),
        )
        .route(
            "/api/v1/documents/batch-delete",
            post(routes::batch_delete_documents),
        )
        .route("/api/v1/documents/:document_id", get(routes::get_document))
        .route(
            "/api/v1/documents/:document_id",
            delete(routes::delete_document),
        )
        .route(
            "/api/v1/documents/:document_id/reindex",
            post(routes::reindex_document),
        )
        // Health routes
        .route("/health", get(routes::health))
        .route("/health/live", get(routes::liveness))
        .route("/health/ready", get(routes::readiness))
        // Apply middleware
        .layer(middleware)
        // Add shared state
        .with_state(state)
}

/// Run the HTTP server.
pub async fn run_server(state: Arc<AppState>, addr: SocketAddr) -> Result<(), ServerError> {
    run_server_with_timeout(state, addr, DEFAULT_TIMEOUT_SECS).await
}

/// Run the HTTP server with a custom timeout.
pub async fn run_server_with_timeout(
    state: Arc<AppState>,
    addr: SocketAddr,
    timeout_secs: u64,
) -> Result<(), ServerError> {
    let app = create_router_with_timeout(state, timeout_secs);

    tracing::info!("Starting ingestion server on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(ServerError::Bind)?;

    axum::serve(listener, app)
        .await
        .map_err(ServerError::Serve)?;

    Ok(())
}

/// Run the HTTP server with graceful shutdown.
pub async fn run_server_with_shutdown<F>(
    state: Arc<AppState>,
    addr: SocketAddr,
    shutdown_signal: F,
) -> Result<(), ServerError>
where
    F: std::future::Future<Output = ()> + Send + 'static,
{
    let app = create_router(state);

    tracing::info!(
        "Starting ingestion server on {} with graceful shutdown",
        addr
    );

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(ServerError::Bind)?;

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal)
        .await
        .map_err(ServerError::Serve)?;

    tracing::info!("Server shut down gracefully");

    Ok(())
}

/// Server configuration.
#[derive(Debug, Clone)]
pub struct ServerConfig {
    /// Address to bind to.
    pub addr: SocketAddr,
    /// Request timeout in seconds.
    pub timeout_secs: u64,
    /// Enable CORS for all origins.
    pub cors_enabled: bool,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            addr: "0.0.0.0:8001".parse().unwrap(),
            timeout_secs: DEFAULT_TIMEOUT_SECS,
            cors_enabled: true,
        }
    }
}

impl ServerConfig {
    /// Create a new server config with default values.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the bind address.
    #[must_use]
    pub fn with_addr(mut self, addr: SocketAddr) -> Self {
        self.addr = addr;
        self
    }

    /// Set the request timeout.
    #[must_use]
    pub const fn with_timeout(mut self, timeout_secs: u64) -> Self {
        self.timeout_secs = timeout_secs;
        self
    }

    /// Load configuration from environment variables.
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        let host = std::env::var("INGESTION_HOST").unwrap_or_else(|_| "0.0.0.0".into());
        let port = std::env::var("INGESTION_PORT")
            .ok()
            .and_then(|p| p.parse().ok())
            .unwrap_or(8001);

        if let Ok(addr) = format!("{host}:{port}").parse() {
            config.addr = addr;
        }

        if let Ok(timeout) = std::env::var("INGESTION_TIMEOUT_SECS") {
            if let Ok(secs) = timeout.parse() {
                config.timeout_secs = secs;
            }
        }

        config
    }
}

/// Server error types.
#[derive(Debug)]
pub enum ServerError {
    /// Failed to bind to address.
    Bind(std::io::Error),
    /// Server error during operation.
    Serve(std::io::Error),
}

impl std::fmt::Display for ServerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Bind(e) => write!(f, "Failed to bind to address: {e}"),
            Self::Serve(e) => write!(f, "Server error: {e}"),
        }
    }
}

impl std::error::Error for ServerError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Bind(e) | Self::Serve(e) => Some(e),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::api::jobs::JobTracker;
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    fn test_state() -> Arc<AppState> {
        Arc::new(
            AppState::builder()
                .job_tracker(Arc::new(JobTracker::new()))
                .build()
                .unwrap(),
        )
    }

    #[tokio::test]
    async fn test_router_health_live() {
        let app = create_router(test_state());

        let response = app
            .oneshot(
                Request::builder()
                    .uri("/health/live")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn test_router_health_ready() {
        let app = create_router(test_state());

        let response = app
            .oneshot(
                Request::builder()
                    .uri("/health/ready")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn test_router_list_documents_requires_tenant_id() {
        let app = create_router(test_state());

        // Without tenant_id, should return 400 Bad Request
        let response = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/documents")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn test_router_list_documents_no_database() {
        let app = create_router(test_state());

        // With tenant_id but no database, should return 500 Internal Server Error
        let response = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/documents?tenant_id=test-tenant")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::INTERNAL_SERVER_ERROR);
    }

    #[tokio::test]
    async fn test_router_list_active_jobs() {
        let app = create_router(test_state());

        let response = app
            .oneshot(
                Request::builder()
                    .uri("/api/v1/ingest")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);
    }

    #[test]
    fn test_server_config_default() {
        let config = ServerConfig::default();
        assert_eq!(config.addr.port(), 8001);
        assert_eq!(config.timeout_secs, 60);
    }

    #[test]
    fn test_server_config_builder() {
        let addr: SocketAddr = "127.0.0.1:9000".parse().unwrap();
        let config = ServerConfig::new().with_addr(addr).with_timeout(120);

        assert_eq!(config.addr.port(), 9000);
        assert_eq!(config.timeout_secs, 120);
    }
}

//! Server setup and configuration for the retrieval service.
//!
//! This module provides functions for creating the Axum router with all
//! routes configured, as well as running the HTTP server.

use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use axum::{
    routing::{get, post},
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
const DEFAULT_TIMEOUT_SECS: u64 = 30;

/// Create the Axum router with all routes configured.
///
/// # Routes
///
/// - `POST /api/v1/retrieve` - Single query retrieval
/// - `POST /api/v1/retrieve/multi` - Multi-query retrieval
/// - `GET /health` - Full health check
/// - `GET /health/live` - Kubernetes liveness probe
/// - `GET /health/ready` - Kubernetes readiness probe
///
/// # Middleware
///
/// - Request/response tracing
/// - CORS support
/// - Request timeout
///
/// # Example
///
/// ```ignore
/// use std::sync::Arc;
/// use rag_retrieval::api::{create_router, AppState};
///
/// let state = Arc::new(create_app_state());
/// let app = create_router(state);
///
/// // Run the server
/// let listener = tokio::net::TcpListener::bind("0.0.0.0:8002").await?;
/// axum::serve(listener, app).await?;
/// ```
#[must_use]
pub fn create_router(state: Arc<AppState>) -> Router {
    create_router_with_timeout(state, DEFAULT_TIMEOUT_SECS)
}

/// Create the Axum router with a custom timeout.
#[must_use]
pub fn create_router_with_timeout(state: Arc<AppState>, timeout_secs: u64) -> Router {
    // Build middleware stack
    let middleware = ServiceBuilder::new()
        // Add tracing for all requests
        .layer(
            TraceLayer::new_for_http()
                .make_span_with(DefaultMakeSpan::new().level(Level::INFO))
                .on_request(DefaultOnRequest::new().level(Level::INFO))
                .on_response(DefaultOnResponse::new().level(Level::INFO)),
        )
        // Add CORS support
        .layer(
            CorsLayer::new()
                .allow_origin(Any)
                .allow_methods(Any)
                .allow_headers(Any),
        )
        // Add request timeout
        .layer(TimeoutLayer::new(Duration::from_secs(timeout_secs)));

    // Build the router
    Router::new()
        // API routes
        .route("/api/v1/retrieve", post(routes::retrieve))
        .route("/api/v1/retrieve/multi", post(routes::retrieve_multi))
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
///
/// # Arguments
///
/// * `state` - Application state to share across handlers
/// * `addr` - Socket address to bind to
///
/// # Errors
///
/// Returns an error if the server fails to start or encounters a fatal error.
///
/// # Example
///
/// ```ignore
/// use std::sync::Arc;
/// use std::net::SocketAddr;
/// use rag_retrieval::api::{run_server, AppState};
///
/// let state = Arc::new(create_app_state());
/// let addr: SocketAddr = "0.0.0.0:8002".parse()?;
///
/// run_server(state, addr).await?;
/// ```
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

    tracing::info!("Starting retrieval server on {}", addr);

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(ServerError::Bind)?;

    axum::serve(listener, app)
        .await
        .map_err(ServerError::Serve)?;

    Ok(())
}

/// Run the HTTP server with graceful shutdown.
///
/// The server will shut down gracefully when a shutdown signal is received.
///
/// # Arguments
///
/// * `state` - Application state to share across handlers
/// * `addr` - Socket address to bind to
/// * `shutdown_signal` - Future that completes when shutdown is requested
///
/// # Example
///
/// ```ignore
/// use tokio::signal;
///
/// let state = Arc::new(create_app_state());
/// let addr: SocketAddr = "0.0.0.0:8002".parse()?;
///
/// run_server_with_shutdown(
///     state,
///     addr,
///     async {
///         signal::ctrl_c().await.expect("Failed to install CTRL+C handler");
///     }
/// ).await?;
/// ```
pub async fn run_server_with_shutdown<F>(
    state: Arc<AppState>,
    addr: SocketAddr,
    shutdown_signal: F,
) -> Result<(), ServerError>
where
    F: std::future::Future<Output = ()> + Send + 'static,
{
    let app = create_router(state);

    tracing::info!("Starting retrieval server on {} with graceful shutdown", addr);

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
            addr: "0.0.0.0:8002".parse().unwrap(),
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

    /// Set whether CORS is enabled.
    #[must_use]
    pub const fn with_cors(mut self, enabled: bool) -> Self {
        self.cors_enabled = enabled;
        self
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `RETRIEVAL_HOST`: Host to bind to (default: 0.0.0.0)
    /// - `RETRIEVAL_PORT`: Port to bind to (default: 8002)
    /// - `RETRIEVAL_TIMEOUT_SECS`: Request timeout (default: 30)
    /// - `RETRIEVAL_CORS_ENABLED`: Enable CORS (default: true)
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        let host = std::env::var("RETRIEVAL_HOST").unwrap_or_else(|_| "0.0.0.0".into());
        let port = std::env::var("RETRIEVAL_PORT")
            .ok()
            .and_then(|p| p.parse().ok())
            .unwrap_or(8002);

        if let Ok(addr) = format!("{host}:{port}").parse() {
            config.addr = addr;
        }

        if let Ok(timeout) = std::env::var("RETRIEVAL_TIMEOUT_SECS") {
            if let Ok(secs) = timeout.parse() {
                config.timeout_secs = secs;
            }
        }

        if let Ok(cors) = std::env::var("RETRIEVAL_CORS_ENABLED") {
            config.cors_enabled = cors.to_lowercase() == "true";
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

    #[test]
    fn test_server_config_default() {
        let config = ServerConfig::default();

        assert_eq!(config.addr.port(), 8002);
        assert_eq!(config.timeout_secs, 30);
        assert!(config.cors_enabled);
    }

    #[test]
    fn test_server_config_builder() {
        let addr: SocketAddr = "127.0.0.1:9000".parse().unwrap();

        let config = ServerConfig::new()
            .with_addr(addr)
            .with_timeout(60)
            .with_cors(false);

        assert_eq!(config.addr.port(), 9000);
        assert_eq!(config.timeout_secs, 60);
        assert!(!config.cors_enabled);
    }

    #[test]
    fn test_server_config_from_env() {
        // Set environment variables
        std::env::set_var("RETRIEVAL_HOST", "127.0.0.1");
        std::env::set_var("RETRIEVAL_PORT", "9001");
        std::env::set_var("RETRIEVAL_TIMEOUT_SECS", "45");
        std::env::set_var("RETRIEVAL_CORS_ENABLED", "false");

        let config = ServerConfig::from_env();

        assert_eq!(config.addr.port(), 9001);
        assert_eq!(config.timeout_secs, 45);
        assert!(!config.cors_enabled);

        // Clean up
        std::env::remove_var("RETRIEVAL_HOST");
        std::env::remove_var("RETRIEVAL_PORT");
        std::env::remove_var("RETRIEVAL_TIMEOUT_SECS");
        std::env::remove_var("RETRIEVAL_CORS_ENABLED");
    }

    #[test]
    fn test_server_error_display() {
        let io_error = std::io::Error::new(std::io::ErrorKind::AddrInUse, "address in use");
        let err = ServerError::Bind(io_error);

        let display = err.to_string();
        assert!(display.contains("Failed to bind"));
        assert!(display.contains("address in use"));
    }
}

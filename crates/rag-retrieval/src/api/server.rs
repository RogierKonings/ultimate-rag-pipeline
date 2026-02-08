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

/// Create the Axum router with all routes configured using default settings.
///
/// # Routes
///
/// - `POST /api/v1/retrieve` - Single query retrieval
/// - `POST /api/v1/retrieve/multi` - Multi-query retrieval
/// - `POST /api/v1/retrieve/explain` - Retrieval pipeline diagnostics (admin-only)
/// - `GET /health` - Full health check
/// - `GET /health/live` - Kubernetes liveness probe
/// - `GET /health/ready` - Kubernetes readiness probe
/// - `GET /metrics` - Prometheus metrics endpoint
///
/// # Middleware
///
/// - Request/response tracing
/// - CORS support (conditionally applied based on config)
/// - Request timeout
#[must_use]
pub fn create_router(state: Arc<AppState>) -> Router {
    let config = ServerConfig::default();
    create_router_with_config(state, &config)
}

/// Create the Axum router with a custom timeout (legacy API, uses permissive CORS).
#[must_use]
pub fn create_router_with_timeout(state: Arc<AppState>, timeout_secs: u64) -> Router {
    let config = ServerConfig {
        timeout_secs,
        ..ServerConfig::default()
    };
    create_router_with_config(state, &config)
}

/// Create the Axum router with full server configuration.
#[must_use]
pub fn create_router_with_config(state: Arc<AppState>, config: &ServerConfig) -> Router {
    // Build base middleware stack (tracing + timeout)
    let base = ServiceBuilder::new()
        .layer(
            TraceLayer::new_for_http()
                .make_span_with(DefaultMakeSpan::new().level(Level::INFO))
                .on_request(DefaultOnRequest::new().level(Level::INFO))
                .on_response(DefaultOnResponse::new().level(Level::INFO)),
        )
        .layer(TimeoutLayer::new(Duration::from_secs(config.timeout_secs)));

    // Build the router
    let router = Router::new()
        // API routes
        .route("/api/v1/retrieve", post(routes::retrieve))
        .route("/api/v1/retrieve/multi", post(routes::retrieve_multi))
        .route("/api/v1/retrieve/explain", post(routes::explain))
        // Health routes
        .route("/health", get(routes::health))
        .route("/health/live", get(routes::liveness))
        .route("/health/ready", get(routes::readiness))
        // Metrics route (Prometheus scraping)
        .route("/metrics", get(routes::metrics));

    // Conditionally apply CORS layer
    let router = if let Some(cors) = config.build_cors_layer() {
        tracing::info!(
            cors_enabled = true,
            environment = %config.environment,
            origins = ?config.allowed_origins,
            "CORS layer applied"
        );
        router.layer(cors)
    } else {
        tracing::info!(cors_enabled = false, "CORS layer disabled");
        router
    };

    // Apply base middleware and state
    router
        .layer(base)
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

/// Run the HTTP server with graceful shutdown using full configuration.
pub async fn run_server_with_config<F>(
    state: Arc<AppState>,
    config: &ServerConfig,
    shutdown_signal: F,
) -> Result<(), ServerError>
where
    F: std::future::Future<Output = ()> + Send + 'static,
{
    let app = create_router_with_config(state, config);

    tracing::info!(
        addr = %config.addr,
        cors_enabled = config.cors_enabled,
        environment = %config.environment,
        "Starting retrieval server with graceful shutdown",
    );

    let listener = tokio::net::TcpListener::bind(config.addr)
        .await
        .map_err(ServerError::Bind)?;

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal)
        .await
        .map_err(ServerError::Serve)?;

    tracing::info!("Server shut down gracefully");

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
pub async fn run_server_with_shutdown<F>(
    state: Arc<AppState>,
    addr: SocketAddr,
    shutdown_signal: F,
) -> Result<(), ServerError>
where
    F: std::future::Future<Output = ()> + Send + 'static,
{
    let config = ServerConfig {
        addr,
        ..ServerConfig::from_env()
    };
    run_server_with_config(state, &config, shutdown_signal).await
}

/// Server configuration.
#[derive(Debug, Clone)]
pub struct ServerConfig {
    /// Address to bind to.
    pub addr: SocketAddr,

    /// Request timeout in seconds.
    pub timeout_secs: u64,

    /// Whether CORS middleware is enabled at all.
    pub cors_enabled: bool,

    /// Deployment environment (e.g. "development", "production").
    /// In production, explicit origins are required (no wildcard fallback).
    pub environment: String,

    /// Allowed origins for CORS. Empty means use environment-based defaults:
    /// - development/local: allow all origins (wildcard)
    /// - production: no origins allowed (CORS effectively blocks cross-origin)
    pub allowed_origins: Vec<String>,

    /// Allowed HTTP methods for CORS. Empty means use defaults
    /// (GET, POST, PUT, DELETE, OPTIONS).
    pub allowed_methods: Vec<String>,

    /// Allowed HTTP headers for CORS. Empty means use defaults
    /// (Content-Type, Authorization, X-Tenant-Id, X-Request-Id).
    pub allowed_headers: Vec<String>,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            addr: "0.0.0.0:8002".parse().unwrap(),
            timeout_secs: DEFAULT_TIMEOUT_SECS,
            cors_enabled: true,
            environment: "development".to_string(),
            allowed_origins: Vec::new(),
            allowed_methods: Vec::new(),
            allowed_headers: Vec::new(),
        }
    }
}

/// Default CORS methods when none are explicitly configured.
const DEFAULT_CORS_METHODS: &[&str] = &["GET", "POST", "PUT", "DELETE", "OPTIONS"];

/// Default CORS headers when none are explicitly configured.
const DEFAULT_CORS_HEADERS: &[&str] = &[
    "Content-Type",
    "Authorization",
    "X-Tenant-Id",
    "X-Request-Id",
];

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

    /// Build the CORS layer based on configuration.
    ///
    /// Returns `None` if CORS is disabled. In production, explicit origins
    /// are required -- if none are configured, the layer will reject all
    /// cross-origin requests by returning an empty origin list.
    #[must_use]
    pub fn build_cors_layer(&self) -> Option<CorsLayer> {
        if !self.cors_enabled {
            return None;
        }

        let is_production = self.environment == "production";

        // Determine origins
        let cors = if self.allowed_origins.is_empty() {
            if is_production {
                tracing::warn!(
                    "CORS enabled in production without CORS_ALLOWED_ORIGINS; \
                     no cross-origin requests will be allowed. \
                     Set CORS_ALLOWED_ORIGINS to allow specific origins."
                );
                CorsLayer::new()
            } else {
                CorsLayer::new().allow_origin(Any)
            }
        } else {
            let origins: Vec<axum::http::HeaderValue> = self
                .allowed_origins
                .iter()
                .filter_map(|o| o.parse().ok())
                .collect();
            CorsLayer::new().allow_origin(origins)
        };

        // Determine methods
        let cors = if self.allowed_methods.is_empty() {
            let methods: Vec<axum::http::Method> = DEFAULT_CORS_METHODS
                .iter()
                .filter_map(|m| m.parse().ok())
                .collect();
            cors.allow_methods(methods)
        } else {
            let methods: Vec<axum::http::Method> = self
                .allowed_methods
                .iter()
                .filter_map(|m| m.parse().ok())
                .collect();
            cors.allow_methods(methods)
        };

        // Determine headers
        let cors = if self.allowed_headers.is_empty() {
            if is_production {
                let headers: Vec<axum::http::HeaderName> = DEFAULT_CORS_HEADERS
                    .iter()
                    .filter_map(|h| h.parse().ok())
                    .collect();
                cors.allow_headers(headers)
            } else {
                cors.allow_headers(Any)
            }
        } else {
            let headers: Vec<axum::http::HeaderName> = self
                .allowed_headers
                .iter()
                .filter_map(|h| h.parse().ok())
                .collect();
            cors.allow_headers(headers)
        };

        Some(cors)
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `RETRIEVAL_HOST`: Host to bind to (default: 0.0.0.0)
    /// - `RETRIEVAL_PORT`: Port to bind to (default: 8002)
    /// - `RETRIEVAL_TIMEOUT_SECS`: Request timeout (default: 30)
    /// - `CORS_ENABLED`: Enable CORS (default: true)
    /// - `CORS_ALLOWED_ORIGINS`: Comma-separated list of allowed origins
    /// - `CORS_ALLOWED_METHODS`: Comma-separated list of allowed methods
    /// - `CORS_ALLOWED_HEADERS`: Comma-separated list of allowed headers
    /// - `ENVIRONMENT`: Deployment environment (default: development)
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

        // CORS configuration -- also accept legacy RETRIEVAL_CORS_ENABLED
        if let Ok(cors) = std::env::var("CORS_ENABLED")
            .or_else(|_| std::env::var("RETRIEVAL_CORS_ENABLED"))
        {
            config.cors_enabled = cors.to_lowercase() == "true";
        }

        if let Ok(env) = std::env::var("ENVIRONMENT") {
            config.environment = env;
        }

        if let Ok(origins) = std::env::var("CORS_ALLOWED_ORIGINS") {
            config.allowed_origins = origins
                .split(',')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect();
        }

        if let Ok(methods) = std::env::var("CORS_ALLOWED_METHODS") {
            config.allowed_methods = methods
                .split(',')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect();
        }

        if let Ok(headers) = std::env::var("CORS_ALLOWED_HEADERS") {
            config.allowed_headers = headers
                .split(',')
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect();
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
        assert_eq!(config.environment, "development");
        assert!(config.allowed_origins.is_empty());
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
    fn test_cors_disabled_returns_none() {
        let config = ServerConfig {
            cors_enabled: false,
            ..ServerConfig::default()
        };
        assert!(config.build_cors_layer().is_none());
    }

    #[test]
    fn test_cors_enabled_dev_returns_some() {
        let config = ServerConfig {
            cors_enabled: true,
            environment: "development".to_string(),
            ..ServerConfig::default()
        };
        assert!(config.build_cors_layer().is_some());
    }

    #[test]
    fn test_cors_enabled_prod_no_origins_returns_some() {
        // Production with no origins still returns a layer, but it will
        // reject cross-origin requests (no origins are allowed).
        let config = ServerConfig {
            cors_enabled: true,
            environment: "production".to_string(),
            allowed_origins: Vec::new(),
            ..ServerConfig::default()
        };
        assert!(config.build_cors_layer().is_some());
    }

    #[test]
    fn test_cors_enabled_prod_with_origins() {
        let config = ServerConfig {
            cors_enabled: true,
            environment: "production".to_string(),
            allowed_origins: vec![
                "https://app.example.com".to_string(),
                "https://admin.example.com".to_string(),
            ],
            ..ServerConfig::default()
        };
        assert!(config.build_cors_layer().is_some());
    }

    #[test]
    fn test_server_config_from_env() {
        // Set environment variables
        std::env::set_var("RETRIEVAL_HOST", "127.0.0.1");
        std::env::set_var("RETRIEVAL_PORT", "9001");
        std::env::set_var("RETRIEVAL_TIMEOUT_SECS", "45");
        std::env::set_var("CORS_ENABLED", "false");
        std::env::set_var("ENVIRONMENT", "production");
        std::env::set_var("CORS_ALLOWED_ORIGINS", "https://a.com, https://b.com");
        std::env::set_var("CORS_ALLOWED_METHODS", "GET, POST");
        std::env::set_var("CORS_ALLOWED_HEADERS", "Content-Type, Authorization");

        let config = ServerConfig::from_env();

        assert_eq!(config.addr.port(), 9001);
        assert_eq!(config.timeout_secs, 45);
        assert!(!config.cors_enabled);
        assert_eq!(config.environment, "production");
        assert_eq!(config.allowed_origins, vec!["https://a.com", "https://b.com"]);
        assert_eq!(config.allowed_methods, vec!["GET", "POST"]);
        assert_eq!(config.allowed_headers, vec!["Content-Type", "Authorization"]);

        // Clean up
        std::env::remove_var("RETRIEVAL_HOST");
        std::env::remove_var("RETRIEVAL_PORT");
        std::env::remove_var("RETRIEVAL_TIMEOUT_SECS");
        std::env::remove_var("CORS_ENABLED");
        std::env::remove_var("ENVIRONMENT");
        std::env::remove_var("CORS_ALLOWED_ORIGINS");
        std::env::remove_var("CORS_ALLOWED_METHODS");
        std::env::remove_var("CORS_ALLOWED_HEADERS");
    }

    #[test]
    fn test_server_config_from_env_legacy_cors_var() {
        // Test backward compatibility with RETRIEVAL_CORS_ENABLED
        std::env::remove_var("CORS_ENABLED");
        std::env::set_var("RETRIEVAL_CORS_ENABLED", "false");

        let config = ServerConfig::from_env();
        assert!(!config.cors_enabled);

        // Clean up
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

//! Axum API layer for the retrieval service.
//!
//! This module provides HTTP endpoints for document retrieval:
//!
//! - `POST /api/v1/retrieve` - Single query retrieval with hybrid search
//! - `POST /api/v1/retrieve/multi` - Multi-query retrieval with result aggregation
//! - `GET /health` - Full health check with component status
//! - `GET /health/live` - Kubernetes liveness probe
//! - `GET /health/ready` - Kubernetes readiness probe
//!
//! # Example
//!
//! ```ignore
//! use std::sync::Arc;
//! use rag_retrieval::api::{create_router, run_server, AppState};
//!
//! // Create application state with required components
//! let state = Arc::new(
//!     AppState::builder()
//!         .hybrid(Arc::new(hybrid_searcher))
//!         .embedding(Arc::new(embedding_client))
//!         .acl_filter(Arc::new(acl_filter))
//!         .version("1.0.0")
//!         .build()?
//! );
//!
//! // Create the router
//! let app = create_router(state.clone());
//!
//! // Or run the server directly
//! let addr: std::net::SocketAddr = "0.0.0.0:8002".parse()?;
//! run_server(state, addr).await?;
//! ```
//!
//! # Request/Response Types
//!
//! The API uses JSON for all requests and responses. Key types:
//!
//! - [`RetrieveRequest`] - Request body for search endpoints
//! - [`RetrieveResponse`] - Response with results and metrics
//! - [`HealthResponse`] - Full health check response
//! - [`LivenessResponse`] - Kubernetes liveness probe response
//! - [`ReadinessResponse`] - Kubernetes readiness probe response
//!
//! # Error Handling
//!
//! All errors are returned as JSON with the following structure:
//!
//! ```json
//! {
//!   "error": {
//!     "code": "ERROR_CODE",
//!     "message": "Human-readable message",
//!     "details": { /* optional additional info */ }
//!   }
//! }
//! ```
//!
//! Error codes follow HTTP status code semantics:
//! - `400 BAD_REQUEST` - Invalid request parameters
//! - `401 UNAUTHORIZED` - Authentication required
//! - `403 FORBIDDEN` - Access denied
//! - `404 NOT_FOUND` - Resource not found
//! - `408 TIMEOUT` - Request timed out
//! - `500 INTERNAL_ERROR` - Server error
//! - `503 SERVICE_UNAVAILABLE` - Service not ready

pub mod error;
pub mod requests;
pub mod responses;
pub mod routes;
pub mod server;
pub mod state;
pub mod types;
pub mod validation;

// Re-export main types for convenient imports
pub use error::{ApiError, ApiResult, ErrorBody, ErrorResponse};
pub use server::{
    create_router, create_router_with_config, run_server, run_server_with_config,
    run_server_with_shutdown, ServerConfig, ServerError,
};
pub use state::{AppState, AppStateBuilder, AppStateBuilderError};
pub use types::{
    ComponentHealth, DebugInfo, HealthResponse, LivenessResponse, MultiQueryRequest,
    ReadinessResponse, RetrieveRequest, RetrieveResponse, RetrievedDocument, SearchMetrics,
    ValidationError,
};

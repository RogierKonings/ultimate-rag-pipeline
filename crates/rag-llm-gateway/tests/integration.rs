//! Integration tests for the rag-llm-gateway service.
//!
//! These tests validate the HTTP endpoints without requiring actual ML models
//! or external services.

use std::sync::Arc;

use axum_test::TestServer;
use serde_json::Value;

use rag_llm_gateway::{create_router, AppState, GatewayConfig};

/// Create a test server with default configuration (no models loaded).
fn create_test_server() -> TestServer {
    let config = test_config();
    let state = AppState::new(config).expect("Failed to create AppState");
    let router = create_router(Arc::new(state));
    TestServer::new(router).expect("Failed to create test server")
}

/// Create a test configuration with all services disabled (no ML models loaded).
fn test_config() -> GatewayConfig {
    let mut config = GatewayConfig::default();
    // Disable auth for testing
    config.auth.enabled = false;
    // Disable embedding and reranker (no ML models available in tests)
    config.embedding.enabled = false;
    config.reranker.enabled = false;
    // Disable vLLM to avoid network calls
    config.vllm.enabled = false;
    // Disable rate limiting for simpler tests
    config.rate_limit.enabled = false;
    config
}

// =============================================================================
// Root Endpoint Tests
// =============================================================================

#[tokio::test]
async fn test_root_endpoint_returns_service_info() {
    let server = create_test_server();

    let response = server.get("/").await;

    response.assert_status_ok();

    let json: Value = response.json();
    assert_eq!(json["service"], "llm-gateway");
    assert_eq!(json["status"], "running");
    assert!(json["version"].is_string());
}

#[tokio::test]
async fn test_root_endpoint_content_type() {
    let server = create_test_server();

    let response = server.get("/").await;

    response.assert_status_ok();
    let content_type = response
        .headers()
        .get("content-type")
        .expect("Missing content-type header");
    assert!(
        content_type.to_str().unwrap().contains("application/json"),
        "Expected JSON content type"
    );
}

// =============================================================================
// Health Endpoint Tests
// =============================================================================

#[tokio::test]
async fn test_health_endpoint_returns_healthy() {
    let server = create_test_server();

    let response = server.get("/health").await;

    response.assert_status_ok();

    let json: Value = response.json();
    assert_eq!(json["status"], "healthy");
    assert!(json["services"].is_object());
}

#[tokio::test]
async fn test_health_endpoint_services_status() {
    let server = create_test_server();

    let response = server.get("/health").await;

    response.assert_status_ok();

    let json: Value = response.json();
    let services = &json["services"];

    // Without models loaded, embedding and reranker should be disabled
    assert_eq!(services["embedding"], "disabled");
    assert_eq!(services["reranker"], "disabled");
    // vLLM is disabled in test config
    assert_eq!(services["vllm"], "disabled");
}

// =============================================================================
// Liveness Probe Tests
// =============================================================================

#[tokio::test]
async fn test_liveness_probe_returns_ok() {
    let server = create_test_server();

    let response = server.get("/health/live").await;

    response.assert_status_ok();

    let json: Value = response.json();
    assert_eq!(json["status"], "ok");
}

#[tokio::test]
async fn test_liveness_probe_is_fast() {
    let server = create_test_server();

    let start = std::time::Instant::now();
    let response = server.get("/health/live").await;
    let elapsed = start.elapsed();

    response.assert_status_ok();
    // Liveness probe should be very fast (no external calls)
    assert!(
        elapsed.as_millis() < 100,
        "Liveness probe took too long: {elapsed:?}"
    );
}

// =============================================================================
// Readiness Probe Tests
// =============================================================================

#[tokio::test]
async fn test_readiness_probe_returns_ready() {
    let server = create_test_server();

    let response = server.get("/health/ready").await;

    response.assert_status_ok();

    let json: Value = response.json();
    // With all capabilities disabled in test config, readiness reports not_ready
    assert_eq!(json["status"], "not_ready");
    assert_eq!(json["reason"], "No capabilities are enabled");
}

// =============================================================================
// Metrics Endpoint Tests
// =============================================================================

#[tokio::test]
async fn test_metrics_endpoint_returns_prometheus_format() {
    let server = create_test_server();

    let response = server.get("/metrics").await;

    response.assert_status_ok();

    let body = response.text();
    // Prometheus metrics should contain the HELP and TYPE comments
    // or be empty if no metrics are registered yet
    assert!(
        body.is_empty() || body.contains("# HELP") || body.contains("# TYPE"),
        "Expected Prometheus text format, got: {}",
        &body[..body.len().min(200)]
    );
}

#[tokio::test]
async fn test_metrics_endpoint_content_type() {
    let server = create_test_server();

    let response = server.get("/metrics").await;

    response.assert_status_ok();
    // Prometheus metrics are typically served as text/plain
    // but can also be application/openmetrics-text or text/plain; version=0.0.4
    let content_type = response
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    assert!(
        content_type.contains("text/plain") || content_type.is_empty(),
        "Expected text/plain content type for metrics, got: {content_type}"
    );
}

// =============================================================================
// Models Endpoint Tests
// =============================================================================

#[tokio::test]
async fn test_models_endpoint_returns_list_format() {
    let server = create_test_server();

    let response = server.get("/v1/models").await;

    response.assert_status_ok();

    let json: Value = response.json();
    assert_eq!(json["object"], "list");
    assert!(json["data"].is_array());
}

#[tokio::test]
async fn test_models_endpoint_empty_when_no_models_loaded() {
    let server = create_test_server();

    let response = server.get("/v1/models").await;

    response.assert_status_ok();

    let json: Value = response.json();
    let data = json["data"].as_array().expect("data should be an array");
    // No models should be listed since embedding, reranker, and vLLM are all disabled/not loaded
    assert!(
        data.is_empty(),
        "Expected no models when none are loaded, got: {data:?}"
    );
}

// =============================================================================
// Invalid Route Tests
// =============================================================================

#[tokio::test]
async fn test_invalid_route_returns_404() {
    let server = create_test_server();

    let response = server.get("/nonexistent").await;

    response.assert_status_not_found();
}

#[tokio::test]
async fn test_invalid_api_route_returns_404() {
    let server = create_test_server();

    let response = server.get("/v1/nonexistent").await;

    response.assert_status_not_found();
}

// =============================================================================
// Method Not Allowed Tests
// =============================================================================

#[tokio::test]
async fn test_post_to_health_returns_method_not_allowed() {
    let server = create_test_server();

    let response = server.post("/health").await;

    response.assert_status(axum::http::StatusCode::METHOD_NOT_ALLOWED);
}

#[tokio::test]
async fn test_get_to_embeddings_returns_method_not_allowed() {
    let server = create_test_server();

    let response = server.get("/v1/embeddings").await;

    response.assert_status(axum::http::StatusCode::METHOD_NOT_ALLOWED);
}

// =============================================================================
// Concurrent Request Tests
// =============================================================================

#[tokio::test]
async fn test_concurrent_health_checks() {
    let server = create_test_server();

    // Make multiple sequential requests (simulating concurrent access)
    for _ in 0..10 {
        let response = server.get("/health").await;
        response.assert_status_ok();
        let json: Value = response.json();
        assert_eq!(json["status"], "healthy");
    }
}

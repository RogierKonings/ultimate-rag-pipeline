//! Metrics endpoint for Prometheus scraping.
//!
//! This endpoint exposes metrics in Prometheus text format for scraping.

use axum::response::IntoResponse;

/// Prometheus metrics endpoint.
///
/// Returns all registered metrics in Prometheus text format.
///
/// # Example Response
///
/// ```text
/// # HELP retrieval_requests_total Total number of retrieval requests
/// # TYPE retrieval_requests_total counter
/// retrieval_requests_total{mode="hybrid",status="success"} 42
/// retrieval_requests_total{mode="semantic",status="error"} 3
/// ```
pub async fn metrics() -> impl IntoResponse {
    let metrics = crate::observability::metrics::encode_metrics();
    (
        [(
            axum::http::header::CONTENT_TYPE,
            "text/plain; charset=utf-8",
        )],
        metrics,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::{Request, StatusCode};
    use tower::ServiceExt;

    #[tokio::test]
    async fn test_metrics_endpoint() {
        use axum::routing::get;
        use axum::Router;

        let app = Router::new().route("/metrics", get(metrics));

        let response = app
            .oneshot(
                Request::builder()
                    .uri("/metrics")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);

        let content_type = response
            .headers()
            .get(axum::http::header::CONTENT_TYPE)
            .unwrap();
        assert!(content_type.to_str().unwrap().contains("text/plain"));
    }
}

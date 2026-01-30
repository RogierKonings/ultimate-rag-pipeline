//! Rate limiting middleware.

use axum::{
    extract::{Request, State},
    middleware::Next,
    response::Response,
};
use std::sync::Arc;

use crate::auth::AuthContext;
use crate::error::GatewayError;

use super::RateLimiter;

/// Rate limiting middleware.
pub async fn rate_limit_middleware(
    State(limiter): State<Arc<RateLimiter>>,
    request: Request,
    next: Next,
) -> Result<Response, GatewayError> {
    let auth_context = request
        .extensions()
        .get::<AuthContext>()
        .cloned()
        .unwrap_or_default();

    let result = limiter
        .check(&auth_context.tenant_id, Some(&auth_context.user_id))
        .await;

    if !result.allowed {
        return Err(GatewayError::RateLimitExceeded {
            retry_after_secs: result.retry_after_secs.unwrap_or(60),
        });
    }

    let mut response = next.run(request).await;

    // Add rate limit headers to response
    for (name, value) in result.to_headers() {
        if let Ok(header_value) = value.parse() {
            response.headers_mut().insert(name, header_value);
        }
    }

    Ok(response)
}

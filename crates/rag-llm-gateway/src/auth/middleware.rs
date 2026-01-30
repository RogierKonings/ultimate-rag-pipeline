//! Authentication middleware.

use axum::{
    extract::{Request, State},
    http::header::AUTHORIZATION,
    middleware::Next,
    response::Response,
};
use std::sync::Arc;
use tracing::debug;

use crate::config::AuthConfig;
use crate::error::GatewayError;

use super::context::AuthContext;
use super::jwt::JwtValidator;

/// Application state for authentication middleware.
#[derive(Clone)]
pub struct AuthState {
    pub validator: Arc<JwtValidator>,
    pub config: Arc<AuthConfig>,
}

/// Authentication middleware.
///
/// # Errors
///
/// Returns an error if authentication is enabled and no valid credentials are provided.
pub async fn auth_middleware(
    State(state): State<AuthState>,
    mut request: Request,
    next: Next,
) -> Result<Response, GatewayError> {
    let path = request.uri().path();

    // Check if path is public
    if state.config.skip_paths.iter().any(|p| path.starts_with(p)) {
        debug!(path, "Skipping auth for public path");
        request.extensions_mut().insert(AuthContext::anonymous());
        return Ok(next.run(request).await);
    }

    // Skip auth if disabled
    if !state.config.enabled {
        request.extensions_mut().insert(AuthContext::anonymous());
        return Ok(next.run(request).await);
    }

    let auth_context = authenticate(&request, &state.validator)?;

    request.extensions_mut().insert(auth_context);
    Ok(next.run(request).await)
}

fn authenticate(request: &Request, validator: &JwtValidator) -> Result<AuthContext, GatewayError> {
    let headers = request.headers();

    // Try API key first
    if let Some(api_key) = headers.get("X-API-Key").and_then(|v| v.to_str().ok()) {
        if let Some(context) = validator.validate_api_key(api_key) {
            return Ok(context);
        }
    }

    // Try Bearer token
    if let Some(auth_header) = headers.get(AUTHORIZATION).and_then(|v| v.to_str().ok()) {
        if let Some(token) = auth_header.strip_prefix("Bearer ") {
            return validator.validate(token);
        }
    }

    Err(GatewayError::Unauthorized(
        "No valid credentials provided".into(),
    ))
}

//! Axum middleware for RBAC.
//!
//! Provides middleware layers for protecting routes with permission and role checks.

use super::{AuthorizationService, Permission, Role};
use crate::{AuthError, TokenClaims};
use axum::{
    body::Body,
    extract::Request,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use std::{
    future::Future,
    pin::Pin,
    sync::Arc,
    task::{Context, Poll},
};
use tower::{Layer, Service};

/// Extension for storing verified claims in the request.
#[derive(Clone)]
pub struct VerifiedClaims(pub TokenClaims);

/// Authentication layer for Axum routes.
///
/// This layer wraps a service and checks for required permissions or roles
/// before forwarding the request.
#[derive(Clone)]
pub struct AuthLayer {
    auth_service: Arc<AuthorizationService>,
    required_permission: Option<Permission>,
    required_role: Option<Role>,
}

impl AuthLayer {
    /// Create a new auth layer with no requirements (just validates token presence).
    #[must_use]
    pub fn new() -> Self {
        Self {
            auth_service: Arc::new(AuthorizationService::new()),
            required_permission: None,
            required_role: None,
        }
    }

    /// Create a layer requiring a specific permission.
    #[must_use]
    pub fn with_permission(permission: Permission) -> Self {
        Self {
            auth_service: Arc::new(AuthorizationService::new()),
            required_permission: Some(permission),
            required_role: None,
        }
    }

    /// Create a layer requiring a specific role.
    #[must_use]
    pub fn with_role(role: Role) -> Self {
        Self {
            auth_service: Arc::new(AuthorizationService::new()),
            required_permission: None,
            required_role: Some(role),
        }
    }

    /// Add a permission requirement.
    #[must_use]
    pub fn require_permission(mut self, permission: Permission) -> Self {
        self.required_permission = Some(permission);
        self
    }

    /// Add a role requirement.
    #[must_use]
    pub fn require_role(mut self, role: Role) -> Self {
        self.required_role = Some(role);
        self
    }
}

impl Default for AuthLayer {
    fn default() -> Self {
        Self::new()
    }
}

impl<S> Layer<S> for AuthLayer {
    type Service = AuthMiddleware<S>;

    fn layer(&self, inner: S) -> Self::Service {
        AuthMiddleware {
            inner,
            auth_service: self.auth_service.clone(),
            required_permission: self.required_permission,
            required_role: self.required_role,
        }
    }
}

/// Middleware service that performs RBAC checks.
#[derive(Clone)]
pub struct AuthMiddleware<S> {
    inner: S,
    auth_service: Arc<AuthorizationService>,
    required_permission: Option<Permission>,
    required_role: Option<Role>,
}

impl<S> Service<Request> for AuthMiddleware<S>
where
    S: Service<Request, Response = Response> + Clone + Send + 'static,
    S::Future: Send + 'static,
{
    type Response = Response;
    type Error = S::Error;
    type Future = Pin<Box<dyn Future<Output = Result<Self::Response, Self::Error>> + Send>>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, mut request: Request) -> Self::Future {
        let mut inner = self.inner.clone();
        let auth_service = self.auth_service.clone();
        let required_permission = self.required_permission;
        let required_role = self.required_role;

        Box::pin(async move {
            // Get claims from request extensions (should be set by JWT middleware)
            let claims = match request.extensions().get::<VerifiedClaims>() {
                Some(VerifiedClaims(claims)) => claims.clone(),
                None => {
                    return Ok(AuthError::MissingToken.into_response());
                }
            };

            // Check permission requirement
            if let Some(permission) = required_permission {
                if let Err(e) = auth_service.check_permission(&claims, permission) {
                    return Ok(e.into_response());
                }
            }

            // Check role requirement
            if let Some(role) = required_role {
                if let Err(e) = auth_service.check_role(&claims, role) {
                    return Ok(e.into_response());
                }
            }

            // Store claims in request extensions for handlers
            request.extensions_mut().insert(VerifiedClaims(claims));

            inner.call(request).await
        })
    }
}

/// Create a layer requiring a specific permission.
///
/// # Example
///
/// ```ignore
/// use rag_auth::rbac::{require_permission, Permission};
///
/// let router = Router::new()
///     .route("/documents", get(list_documents))
///     .layer(require_permission(Permission::DocumentRead));
/// ```
#[must_use]
pub fn require_permission(permission: Permission) -> AuthLayer {
    AuthLayer::with_permission(permission)
}

/// Create a layer requiring a specific role.
///
/// # Example
///
/// ```ignore
/// use rag_auth::rbac::{require_role, Role};
///
/// let router = Router::new()
///     .route("/admin", get(admin_dashboard))
///     .layer(require_role(Role::Admin));
/// ```
#[must_use]
pub fn require_role(role: Role) -> AuthLayer {
    AuthLayer::with_role(role)
}

/// Convert AuthError to HTTP response.
impl IntoResponse for AuthError {
    fn into_response(self) -> Response {
        let (status, message) = match &self {
            AuthError::MissingToken => (StatusCode::UNAUTHORIZED, "Missing authentication token"),
            AuthError::InvalidToken(_) => {
                (StatusCode::UNAUTHORIZED, "Invalid authentication token")
            }
            AuthError::ExpiredToken => (StatusCode::UNAUTHORIZED, "Token has expired"),
            AuthError::PermissionDenied(_) => (StatusCode::FORBIDDEN, "Permission denied"),
            AuthError::InsufficientRole(_) => (StatusCode::FORBIDDEN, "Insufficient role"),
            AuthError::TenantMismatch { .. } => (StatusCode::FORBIDDEN, "Tenant access denied"),
            AuthError::AccessDenied(_) => (StatusCode::FORBIDDEN, "Access denied"),
            _ => (StatusCode::INTERNAL_SERVER_ERROR, "Authentication error"),
        };

        let body = serde_json::json!({
            "error": message,
            "code": status.as_u16(),
        });

        Response::builder()
            .status(status)
            .header("content-type", "application/json")
            .body(Body::from(body.to_string()))
            .unwrap()
    }
}

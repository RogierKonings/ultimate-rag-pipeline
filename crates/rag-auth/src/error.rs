//! Error types for JWT authentication.

use thiserror::Error;
use uuid::Uuid;

/// Result type for authentication operations.
pub type Result<T> = std::result::Result<T, AuthError>;

/// Authentication errors.
#[derive(Debug, Error)]
pub enum AuthError {
    /// Token has expired.
    #[error("Token has expired")]
    TokenExpired,

    /// Token has expired (alias).
    #[error("Token has expired")]
    ExpiredToken,

    /// Token signature is invalid.
    #[error("Invalid token signature")]
    InvalidSignature,

    /// Token format is invalid.
    #[error("Invalid token format: {0}")]
    InvalidFormat(String),

    /// Invalid token.
    #[error("Invalid token: {0}")]
    InvalidToken(String),

    /// Token audience mismatch.
    #[error("Invalid token audience")]
    InvalidAudience,

    /// Token issuer mismatch.
    #[error("Invalid token issuer")]
    InvalidIssuer,

    /// Required claim is missing.
    #[error("Missing required claim: {0}")]
    MissingClaim(String),

    /// Token is missing from request.
    #[error("Missing authentication token")]
    MissingToken,

    /// Token type mismatch.
    #[error("Expected {expected} token, got {actual}")]
    TokenTypeMismatch { expected: String, actual: String },

    /// Token has been revoked.
    #[error("Token has been revoked")]
    TokenRevoked,

    /// Service not authorized for endpoint.
    #[error("Service '{service}' not authorized for endpoint '{endpoint}'")]
    EndpointNotAuthorized { service: String, endpoint: String },

    /// Permission denied.
    #[error("Permission denied: {0}")]
    PermissionDenied(String),

    /// Insufficient role level.
    #[error("Insufficient role: {0} required")]
    InsufficientRole(String),

    /// Tenant mismatch.
    #[error("Tenant access denied: expected {expected}, got {actual}")]
    TenantMismatch { expected: Uuid, actual: Uuid },

    /// General access denied.
    #[error("Access denied: {0}")]
    AccessDenied(String),

    /// Key configuration error.
    #[error("Key configuration error: {0}")]
    KeyConfig(String),

    /// JWKS fetch error.
    #[error("Failed to fetch JWKS: {0}")]
    JwksFetch(String),

    /// Blocklist operation error.
    #[error("Blocklist error: {0}")]
    Blocklist(String),

    /// Internal error from jsonwebtoken crate.
    #[error("JWT error: {0}")]
    Jwt(#[from] jsonwebtoken::errors::Error),
}

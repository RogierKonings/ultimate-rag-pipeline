//! Service-to-service token claims.

use chrono::{DateTime, Utc};
use glob_match::glob_match;
use serde::{Deserialize, Serialize};

use crate::TokenType;

/// JWT claims for service-to-service authentication.
///
/// Unlike user `TokenClaims`, service tokens identify a calling service
/// rather than a user. They are used for internal API authentication.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServiceTokenClaims {
    /// Name of the calling service (e.g., "orchestrator").
    pub service_name: String,
    /// Target service (audience).
    pub target_service: String,
    /// Endpoint patterns the service can access (e.g., "/internal/*").
    #[serde(default)]
    pub allowed_endpoints: Vec<String>,

    // Standard JWT claims
    /// Issuer.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub iss: Option<String>,
    /// Audience.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub aud: Option<String>,
    /// Expiration time (Unix timestamp).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub exp: Option<i64>,
    /// Issued at (Unix timestamp).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub iat: Option<i64>,
    /// JWT ID.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub jti: Option<String>,

    /// Token type (always "service").
    #[serde(default = "default_service_token_type")]
    pub token_type: TokenType,
}

fn default_service_token_type() -> TokenType {
    TokenType::Service
}

impl ServiceTokenClaims {
    /// Create new service token claims.
    #[must_use]
    pub fn new(service_name: impl Into<String>, target_service: impl Into<String>) -> Self {
        Self {
            service_name: service_name.into(),
            target_service: target_service.into(),
            allowed_endpoints: Vec::new(),
            iss: None,
            aud: None,
            exp: None,
            iat: None,
            jti: None,
            token_type: TokenType::Service,
        }
    }

    /// Set the allowed endpoint patterns.
    #[must_use]
    pub fn with_allowed_endpoints(mut self, endpoints: Vec<String>) -> Self {
        self.allowed_endpoints = endpoints;
        self
    }

    /// Check if this service token allows access to the given endpoint.
    ///
    /// Uses glob pattern matching (e.g., "/internal/*" matches "/internal/search").
    #[must_use]
    pub fn can_access_endpoint(&self, endpoint: &str) -> bool {
        // If no endpoints specified, allow all
        if self.allowed_endpoints.is_empty() {
            return true;
        }

        self.allowed_endpoints
            .iter()
            .any(|pattern| glob_match(pattern, endpoint))
    }

    /// Get the expiration time as a DateTime.
    #[must_use]
    pub fn expiration(&self) -> Option<DateTime<Utc>> {
        self.exp.map(|ts| {
            DateTime::from_timestamp(ts, 0).unwrap_or_else(|| DateTime::UNIX_EPOCH)
        })
    }

    /// Check if the token is expired.
    #[must_use]
    pub fn is_expired(&self) -> bool {
        self.exp.map_or(false, |exp| {
            let now = Utc::now().timestamp();
            exp < now
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_service_claims() {
        let claims = ServiceTokenClaims::new("orchestrator", "retrieval");

        assert_eq!(claims.service_name, "orchestrator");
        assert_eq!(claims.target_service, "retrieval");
        assert_eq!(claims.token_type, TokenType::Service);
    }

    #[test]
    fn test_endpoint_authorization() {
        let claims = ServiceTokenClaims::new("orchestrator", "retrieval")
            .with_allowed_endpoints(vec!["/internal/*".into(), "/api/v1/search".into()]);

        // Glob pattern match
        assert!(claims.can_access_endpoint("/internal/search"));
        assert!(claims.can_access_endpoint("/internal/rerank"));

        // Exact match
        assert!(claims.can_access_endpoint("/api/v1/search"));

        // No match
        assert!(!claims.can_access_endpoint("/api/v1/ingest"));
        assert!(!claims.can_access_endpoint("/admin/users"));
    }

    #[test]
    fn test_no_endpoints_allows_all() {
        let claims = ServiceTokenClaims::new("orchestrator", "retrieval");

        assert!(claims.can_access_endpoint("/anything"));
        assert!(claims.can_access_endpoint("/internal/search"));
    }
}

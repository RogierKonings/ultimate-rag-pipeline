//! JWT token claims.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Token type for identifying access vs refresh tokens.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum TokenType {
    /// Access token for API requests.
    #[default]
    Access,
    /// Refresh token for obtaining new access tokens.
    Refresh,
    /// Service token for service-to-service authentication.
    Service,
}

impl std::fmt::Display for TokenType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Access => write!(f, "access"),
            Self::Refresh => write!(f, "refresh"),
            Self::Service => write!(f, "service"),
        }
    }
}

/// JWT token claims for user authentication.
///
/// Contains both standard JWT claims (RFC 7519) and custom claims
/// for the RAG pipeline including tenant isolation, roles, and groups.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenClaims {
    // Standard claims
    /// Subject (user ID).
    pub sub: Uuid,
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
    /// Not before (Unix timestamp).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub nbf: Option<i64>,
    /// JWT ID.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub jti: Option<String>,

    // Custom claims
    /// Tenant identifier for multi-tenancy.
    pub tenant_id: Uuid,
    /// User roles for RBAC.
    #[serde(default)]
    pub roles: Vec<String>,
    /// User groups for document ACL.
    #[serde(default)]
    pub groups: Vec<String>,
    /// Explicit permissions.
    #[serde(default)]
    pub permissions: Vec<String>,
    /// Token type (access/refresh).
    #[serde(default)]
    pub token_type: TokenType,

    // Optional user metadata
    /// User email.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub email: Option<String>,
    /// User display name.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
}

impl TokenClaims {
    /// Create new token claims with required fields.
    #[must_use]
    pub fn new(sub: Uuid, tenant_id: Uuid) -> Self {
        Self {
            sub,
            tenant_id,
            iss: None,
            aud: None,
            exp: None,
            iat: None,
            nbf: None,
            jti: None,
            roles: Vec::new(),
            groups: Vec::new(),
            permissions: Vec::new(),
            token_type: TokenType::Access,
            email: None,
            name: None,
        }
    }

    /// Set the user roles.
    #[must_use]
    pub fn with_roles(mut self, roles: Vec<String>) -> Self {
        self.roles = roles;
        self
    }

    /// Set the user groups.
    #[must_use]
    pub fn with_groups(mut self, groups: Vec<String>) -> Self {
        self.groups = groups;
        self
    }

    /// Set the permissions.
    #[must_use]
    pub fn with_permissions(mut self, permissions: Vec<String>) -> Self {
        self.permissions = permissions;
        self
    }

    /// Set the user email.
    #[must_use]
    pub fn with_email(mut self, email: impl Into<String>) -> Self {
        self.email = Some(email.into());
        self
    }

    /// Set the user display name.
    #[must_use]
    pub fn with_name(mut self, name: impl Into<String>) -> Self {
        self.name = Some(name.into());
        self
    }

    /// Check if the token has a specific role.
    #[must_use]
    pub fn has_role(&self, role: &str) -> bool {
        self.roles.iter().any(|r| r == role)
    }

    /// Check if the token has a specific permission.
    #[must_use]
    pub fn has_permission(&self, permission: &str) -> bool {
        self.permissions.iter().any(|p| p == permission)
    }

    /// Check if the token has admin-level role (admin, super_admin, or tenant_admin).
    #[must_use]
    pub fn is_admin(&self) -> bool {
        self.has_role("admin") || self.has_role("super_admin") || self.has_role("tenant_admin")
    }

    /// Check if the token holder is a member of a group.
    #[must_use]
    pub fn is_member_of(&self, group: &str) -> bool {
        self.groups.iter().any(|g| g == group)
    }

    /// Get the expiration time as a DateTime.
    #[must_use]
    pub fn expiration(&self) -> Option<DateTime<Utc>> {
        self.exp
            .map(|ts| DateTime::from_timestamp(ts, 0).unwrap_or(DateTime::UNIX_EPOCH))
    }

    /// Check if the token is expired.
    #[must_use]
    pub fn is_expired(&self) -> bool {
        self.exp.is_some_and(|exp| {
            let now = Utc::now().timestamp();
            exp < now
        })
    }
}

/// Token pair containing access and refresh tokens.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TokenPair {
    /// JWT access token.
    pub access_token: String,
    /// JWT refresh token.
    pub refresh_token: String,
    /// Token type for Authorization header (always "Bearer").
    pub token_type: String,
    /// Access token expiration in seconds.
    pub expires_in: u64,
    /// Refresh token expiration in seconds.
    pub refresh_expires_in: u64,
}

impl TokenPair {
    /// Create a new token pair.
    #[must_use]
    pub fn new(
        access_token: String,
        refresh_token: String,
        expires_in: u64,
        refresh_expires_in: u64,
    ) -> Self {
        Self {
            access_token,
            refresh_token,
            token_type: "Bearer".into(),
            expires_in,
            refresh_expires_in,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new_claims() {
        let user_id = Uuid::new_v4();
        let tenant_id = Uuid::new_v4();
        let claims = TokenClaims::new(user_id, tenant_id);

        assert_eq!(claims.sub, user_id);
        assert_eq!(claims.tenant_id, tenant_id);
        assert!(claims.roles.is_empty());
        assert!(claims.groups.is_empty());
    }

    #[test]
    fn test_claims_with_roles() {
        let claims = TokenClaims::new(Uuid::new_v4(), Uuid::new_v4())
            .with_roles(vec!["admin".into(), "user".into()]);

        assert!(claims.has_role("admin"));
        assert!(claims.has_role("user"));
        assert!(!claims.has_role("guest"));
        assert!(claims.is_admin());
    }

    #[test]
    fn test_claims_with_groups() {
        let claims = TokenClaims::new(Uuid::new_v4(), Uuid::new_v4())
            .with_groups(vec!["engineering".into(), "product".into()]);

        assert!(claims.is_member_of("engineering"));
        assert!(claims.is_member_of("product"));
        assert!(!claims.is_member_of("sales"));
    }

    #[test]
    fn test_token_type_display() {
        assert_eq!(TokenType::Access.to_string(), "access");
        assert_eq!(TokenType::Refresh.to_string(), "refresh");
        assert_eq!(TokenType::Service.to_string(), "service");
    }
}

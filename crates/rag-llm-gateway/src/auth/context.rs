//! Authentication context.

use serde::{Deserialize, Serialize};

/// Authentication context extracted from JWT or API key.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthContext {
    pub tenant_id: String,
    pub user_id: String,
    pub roles: Vec<String>,
    pub scopes: Vec<String>,
    pub auth_method: AuthMethod,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AuthMethod {
    Jwt,
    ApiKey,
    None,
}

impl Default for AuthContext {
    fn default() -> Self {
        Self {
            tenant_id: "default".into(),
            user_id: "anonymous".into(),
            roles: vec![],
            scopes: vec![],
            auth_method: AuthMethod::None,
        }
    }
}

impl AuthContext {
    /// Create context for anonymous/unauthenticated requests.
    #[must_use]
    pub fn anonymous() -> Self {
        Self::default()
    }

    /// Check if user has a specific role.
    #[must_use]
    pub fn has_role(&self, role: &str) -> bool {
        self.roles.iter().any(|r| r == role)
    }

    /// Check if user has a specific scope.
    #[must_use]
    pub fn has_scope(&self, scope: &str) -> bool {
        self.scopes.iter().any(|s| s == scope)
    }

    /// Convert to HTTP headers for downstream services.
    #[must_use]
    pub fn to_headers(&self) -> Vec<(&'static str, String)> {
        vec![
            ("X-Tenant-ID", self.tenant_id.clone()),
            ("X-User-ID", self.user_id.clone()),
            ("X-Roles", self.roles.join(",")),
            (
                "X-Auth-Method",
                format!("{:?}", self.auth_method).to_lowercase(),
            ),
        ]
    }
}

//! Permission definitions for RBAC.

use serde::{Deserialize, Serialize};
use std::str::FromStr;

/// Permission types for the RAG pipeline.
///
/// Permissions follow a resource:action pattern for fine-grained control.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Permission {
    // Document permissions
    /// Read documents and chunks.
    DocumentRead,
    /// Create/upload documents.
    DocumentWrite,
    /// Update document metadata.
    DocumentUpdate,
    /// Delete documents.
    DocumentDelete,

    // Query permissions
    /// Execute search queries.
    QueryExecute,
    /// View query history.
    QueryHistory,

    // Ingestion permissions
    /// Submit documents for ingestion.
    IngestionSubmit,
    /// View ingestion jobs.
    IngestionView,
    /// Cancel ingestion jobs.
    IngestionCancel,

    // User management permissions
    /// View users in tenant.
    UserRead,
    /// Create users.
    UserCreate,
    /// Update users.
    UserUpdate,
    /// Delete users.
    UserDelete,

    // Role management permissions
    /// View roles.
    RoleRead,
    /// Create/update roles.
    RoleManage,

    // Group management permissions
    /// View groups.
    GroupRead,
    /// Create/update groups.
    GroupManage,

    // Tenant permissions
    /// View tenant settings.
    TenantRead,
    /// Update tenant settings.
    TenantUpdate,

    // Admin permissions
    /// Full administrative access.
    AdminAccess,
    /// Super admin with cross-tenant access.
    SuperAdmin,

    // API key permissions
    /// Create API keys.
    ApiKeyCreate,
    /// View API keys.
    ApiKeyRead,
    /// Revoke API keys.
    ApiKeyRevoke,

    // Audit permissions
    /// View audit logs.
    AuditRead,
    /// Export audit logs.
    AuditExport,

    // Usage/quota permissions
    /// View usage statistics.
    UsageRead,
    /// Manage quotas.
    QuotaManage,
}

impl Permission {
    /// Get the string representation of the permission.
    #[must_use]
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::DocumentRead => "document:read",
            Self::DocumentWrite => "document:write",
            Self::DocumentUpdate => "document:update",
            Self::DocumentDelete => "document:delete",
            Self::QueryExecute => "query:execute",
            Self::QueryHistory => "query:history",
            Self::IngestionSubmit => "ingestion:submit",
            Self::IngestionView => "ingestion:view",
            Self::IngestionCancel => "ingestion:cancel",
            Self::UserRead => "user:read",
            Self::UserCreate => "user:create",
            Self::UserUpdate => "user:update",
            Self::UserDelete => "user:delete",
            Self::RoleRead => "role:read",
            Self::RoleManage => "role:manage",
            Self::GroupRead => "group:read",
            Self::GroupManage => "group:manage",
            Self::TenantRead => "tenant:read",
            Self::TenantUpdate => "tenant:update",
            Self::AdminAccess => "admin:access",
            Self::SuperAdmin => "super:admin",
            Self::ApiKeyCreate => "apikey:create",
            Self::ApiKeyRead => "apikey:read",
            Self::ApiKeyRevoke => "apikey:revoke",
            Self::AuditRead => "audit:read",
            Self::AuditExport => "audit:export",
            Self::UsageRead => "usage:read",
            Self::QuotaManage => "quota:manage",
        }
    }

    /// Get the resource part of the permission.
    #[must_use]
    pub fn resource(&self) -> &'static str {
        let s = self.as_str();
        s.split(':').next().unwrap_or(s)
    }

    /// Get the action part of the permission.
    #[must_use]
    pub fn action(&self) -> &'static str {
        let s = self.as_str();
        s.split(':').nth(1).unwrap_or(s)
    }

    /// Get all permissions for a resource.
    #[must_use]
    pub fn for_resource(resource: &str) -> Vec<Self> {
        Self::all()
            .into_iter()
            .filter(|p| p.resource() == resource)
            .collect()
    }

    /// Get all defined permissions.
    #[must_use]
    pub fn all() -> Vec<Self> {
        vec![
            Self::DocumentRead,
            Self::DocumentWrite,
            Self::DocumentUpdate,
            Self::DocumentDelete,
            Self::QueryExecute,
            Self::QueryHistory,
            Self::IngestionSubmit,
            Self::IngestionView,
            Self::IngestionCancel,
            Self::UserRead,
            Self::UserCreate,
            Self::UserUpdate,
            Self::UserDelete,
            Self::RoleRead,
            Self::RoleManage,
            Self::GroupRead,
            Self::GroupManage,
            Self::TenantRead,
            Self::TenantUpdate,
            Self::AdminAccess,
            Self::SuperAdmin,
            Self::ApiKeyCreate,
            Self::ApiKeyRead,
            Self::ApiKeyRevoke,
            Self::AuditRead,
            Self::AuditExport,
            Self::UsageRead,
            Self::QuotaManage,
        ]
    }
}

impl std::fmt::Display for Permission {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

impl FromStr for Permission {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "document:read" => Ok(Self::DocumentRead),
            "document:write" => Ok(Self::DocumentWrite),
            "document:update" => Ok(Self::DocumentUpdate),
            "document:delete" => Ok(Self::DocumentDelete),
            "query:execute" => Ok(Self::QueryExecute),
            "query:history" => Ok(Self::QueryHistory),
            "ingestion:submit" => Ok(Self::IngestionSubmit),
            "ingestion:view" => Ok(Self::IngestionView),
            "ingestion:cancel" => Ok(Self::IngestionCancel),
            "user:read" => Ok(Self::UserRead),
            "user:create" => Ok(Self::UserCreate),
            "user:update" => Ok(Self::UserUpdate),
            "user:delete" => Ok(Self::UserDelete),
            "role:read" => Ok(Self::RoleRead),
            "role:manage" => Ok(Self::RoleManage),
            "group:read" => Ok(Self::GroupRead),
            "group:manage" => Ok(Self::GroupManage),
            "tenant:read" => Ok(Self::TenantRead),
            "tenant:update" => Ok(Self::TenantUpdate),
            "admin:access" => Ok(Self::AdminAccess),
            "super:admin" => Ok(Self::SuperAdmin),
            "apikey:create" => Ok(Self::ApiKeyCreate),
            "apikey:read" => Ok(Self::ApiKeyRead),
            "apikey:revoke" => Ok(Self::ApiKeyRevoke),
            "audit:read" => Ok(Self::AuditRead),
            "audit:export" => Ok(Self::AuditExport),
            "usage:read" => Ok(Self::UsageRead),
            "quota:manage" => Ok(Self::QuotaManage),
            _ => Err(format!("Unknown permission: {s}")),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_permission_as_str() {
        assert_eq!(Permission::DocumentRead.as_str(), "document:read");
        assert_eq!(Permission::AdminAccess.as_str(), "admin:access");
    }

    #[test]
    fn test_permission_from_str() {
        assert_eq!(
            Permission::from_str("document:read").unwrap(),
            Permission::DocumentRead
        );
        assert!(Permission::from_str("invalid").is_err());
    }

    #[test]
    fn test_permission_resource_action() {
        let perm = Permission::DocumentRead;
        assert_eq!(perm.resource(), "document");
        assert_eq!(perm.action(), "read");
    }

    #[test]
    fn test_for_resource() {
        let doc_perms = Permission::for_resource("document");
        assert!(doc_perms.contains(&Permission::DocumentRead));
        assert!(doc_perms.contains(&Permission::DocumentWrite));
        assert!(!doc_perms.contains(&Permission::QueryExecute));
    }
}

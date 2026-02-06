//! Role definitions for RBAC.
//!
//! Roles are shared between Rust and Python services. Both sides use the same
//! string values in JWT token `roles` claims. When changing this enum, update
//! `services/orchestrator/shared/security/rbac/roles.py` accordingly.

use super::Permission;
use serde::{Deserialize, Serialize};
use std::str::FromStr;

/// Predefined roles in the system.
///
/// Roles form a hierarchy where higher roles inherit permissions from lower roles.
///
/// Hierarchy (linear):
///   Anonymous → User → Analyst → Engineer → TenantAdmin → Admin → SuperAdmin
///
/// Separate branch:
///   Service (inherits from User)
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    /// Unauthenticated / public access.
    Anonymous,
    /// Basic authenticated user (read, search, query).
    User,
    /// Data analyst with enhanced search and evaluation capabilities.
    Analyst,
    /// Data engineer with ingestion and connector management.
    Engineer,
    /// Tenant administrator — full access within a tenant scope.
    TenantAdmin,
    /// System administrator — full access (single tenant).
    Admin,
    /// Full administrative access across tenants.
    SuperAdmin,
    /// Service account for internal service-to-service calls.
    Service,
}

impl Role {
    /// Get the string representation of the role (matches Python `Role.value`).
    #[must_use]
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Anonymous => "anonymous",
            Self::User => "user",
            Self::Analyst => "analyst",
            Self::Engineer => "engineer",
            Self::TenantAdmin => "tenant_admin",
            Self::Admin => "admin",
            Self::SuperAdmin => "super_admin",
            Self::Service => "service",
        }
    }

    /// Get the permissions granted by this role (includes inherited).
    #[must_use]
    pub fn permissions(&self) -> Vec<Permission> {
        match self {
            Self::Anonymous => vec![
                Permission::DocumentRead,
                Permission::QueryExecute,
            ],
            Self::User => {
                let mut perms = Self::Anonymous.permissions();
                perms.extend([
                    Permission::DocumentWrite,
                    Permission::QueryHistory,
                    Permission::IngestionView,
                    Permission::ApiKeyRead,
                ]);
                perms
            }
            Self::Analyst => {
                let mut perms = Self::User.permissions();
                perms.extend([
                    Permission::AuditRead,
                ]);
                perms
            }
            Self::Engineer => {
                let mut perms = Self::Analyst.permissions();
                perms.extend([
                    Permission::DocumentUpdate,
                    Permission::IngestionSubmit,
                    Permission::ApiKeyCreate,
                ]);
                perms
            }
            Self::TenantAdmin => {
                let mut perms = Self::Engineer.permissions();
                perms.extend([
                    Permission::DocumentDelete,
                    Permission::IngestionCancel,
                    Permission::UserRead,
                    Permission::UserCreate,
                    Permission::UserUpdate,
                    Permission::UserDelete,
                    Permission::RoleRead,
                    Permission::RoleManage,
                    Permission::GroupRead,
                    Permission::GroupManage,
                    Permission::TenantRead,
                    Permission::TenantUpdate,
                    Permission::ApiKeyRevoke,
                    Permission::AuditExport,
                    Permission::UsageRead,
                    Permission::QuotaManage,
                ]);
                perms
            }
            Self::Admin => {
                let mut perms = Self::TenantAdmin.permissions();
                perms.push(Permission::AdminAccess);
                perms
            }
            Self::SuperAdmin => {
                let mut perms = Self::Admin.permissions();
                perms.push(Permission::SuperAdmin);
                perms
            }
            Self::Service => {
                // Service accounts get base user permissions for internal API calls.
                let mut perms = Self::User.permissions();
                perms.push(Permission::IngestionSubmit);
                perms
            }
        }
    }

    /// Check if this role has a specific permission.
    #[must_use]
    pub fn has_permission(&self, permission: Permission) -> bool {
        self.permissions().contains(&permission)
    }

    /// Check if this role implies another role (is equal or higher in hierarchy).
    #[must_use]
    pub fn implies(&self, other: Role) -> bool {
        self.level() >= other.level()
    }

    /// Get the hierarchy level (higher = more permissions).
    ///
    /// Service is on a separate branch at level 1 (same as User).
    #[must_use]
    pub fn level(&self) -> u8 {
        match self {
            Self::Anonymous => 0,
            Self::User | Self::Service => 1,
            Self::Analyst => 2,
            Self::Engineer => 3,
            Self::TenantAdmin => 4,
            Self::Admin => 5,
            Self::SuperAdmin => 6,
        }
    }

    /// Get all defined roles.
    #[must_use]
    pub fn all() -> Vec<Self> {
        vec![
            Self::Anonymous,
            Self::User,
            Self::Analyst,
            Self::Engineer,
            Self::TenantAdmin,
            Self::Admin,
            Self::SuperAdmin,
            Self::Service,
        ]
    }
}

impl std::fmt::Display for Role {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

impl FromStr for Role {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "anonymous" => Ok(Self::Anonymous),
            "user" => Ok(Self::User),
            "analyst" => Ok(Self::Analyst),
            "engineer" => Ok(Self::Engineer),
            "tenant_admin" | "tenantadmin" => Ok(Self::TenantAdmin),
            "admin" => Ok(Self::Admin),
            "super_admin" | "superadmin" => Ok(Self::SuperAdmin),
            "service" => Ok(Self::Service),
            // Backward compatibility: map legacy 4-role names
            "reader" => Ok(Self::User),
            "writer" => Ok(Self::Engineer),
            _ => Err(format!("Unknown role: {s}")),
        }
    }
}

impl PartialOrd for Role {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for Role {
    fn cmp(&self, other: &Self) -> std::cmp::Ordering {
        self.level().cmp(&other.level())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_role_hierarchy() {
        assert!(Role::SuperAdmin > Role::Admin);
        assert!(Role::Admin > Role::TenantAdmin);
        assert!(Role::TenantAdmin > Role::Engineer);
        assert!(Role::Engineer > Role::Analyst);
        assert!(Role::Analyst > Role::User);
        assert!(Role::User > Role::Anonymous);
    }

    #[test]
    fn test_role_implies() {
        assert!(Role::SuperAdmin.implies(Role::Admin));
        assert!(Role::Admin.implies(Role::TenantAdmin));
        assert!(Role::TenantAdmin.implies(Role::Engineer));
        assert!(Role::Engineer.implies(Role::Analyst));
        assert!(Role::Analyst.implies(Role::User));
        assert!(Role::User.implies(Role::Anonymous));
        assert!(!Role::Anonymous.implies(Role::User));
        assert!(!Role::User.implies(Role::Engineer));
    }

    #[test]
    fn test_role_permissions() {
        assert!(Role::User.has_permission(Permission::DocumentRead));
        assert!(!Role::User.has_permission(Permission::DocumentDelete));
        assert!(Role::Engineer.has_permission(Permission::DocumentWrite));
        assert!(Role::Engineer.has_permission(Permission::IngestionSubmit));
        assert!(Role::Admin.has_permission(Permission::AdminAccess));
        assert!(Role::SuperAdmin.has_permission(Permission::SuperAdmin));
    }

    #[test]
    fn test_role_from_str() {
        assert_eq!(Role::from_str("admin").unwrap(), Role::Admin);
        assert_eq!(Role::from_str("super_admin").unwrap(), Role::SuperAdmin);
        assert_eq!(Role::from_str("tenant_admin").unwrap(), Role::TenantAdmin);
        assert_eq!(Role::from_str("service").unwrap(), Role::Service);
        assert!(Role::from_str("invalid").is_err());
    }

    #[test]
    fn test_legacy_role_mapping() {
        // Old 4-role names map to new equivalents
        assert_eq!(Role::from_str("reader").unwrap(), Role::User);
        assert_eq!(Role::from_str("writer").unwrap(), Role::Engineer);
    }

    #[test]
    fn test_service_role_level() {
        // Service is on its own branch at User level
        assert_eq!(Role::Service.level(), Role::User.level());
    }
}

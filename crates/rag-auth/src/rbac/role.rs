//! Role definitions for RBAC.

use super::Permission;
use serde::{Deserialize, Serialize};
use std::str::FromStr;

/// Predefined roles in the system.
///
/// Roles form a hierarchy where higher roles inherit permissions from lower roles.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    /// Read-only access to documents and queries.
    Reader,
    /// Can create/update documents and execute queries.
    Writer,
    /// Can manage users and groups within the tenant.
    Admin,
    /// Full administrative access across tenants.
    SuperAdmin,
}

impl Role {
    /// Get the string representation of the role.
    #[must_use]
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Reader => "reader",
            Self::Writer => "writer",
            Self::Admin => "admin",
            Self::SuperAdmin => "super_admin",
        }
    }

    /// Get the permissions granted by this role.
    #[must_use]
    pub fn permissions(&self) -> Vec<Permission> {
        match self {
            Self::Reader => vec![
                Permission::DocumentRead,
                Permission::QueryExecute,
                Permission::QueryHistory,
                Permission::IngestionView,
                Permission::ApiKeyRead,
            ],
            Self::Writer => {
                let mut perms = Self::Reader.permissions();
                perms.extend([
                    Permission::DocumentWrite,
                    Permission::DocumentUpdate,
                    Permission::IngestionSubmit,
                    Permission::ApiKeyCreate,
                ]);
                perms
            }
            Self::Admin => {
                let mut perms = Self::Writer.permissions();
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
                    Permission::AuditRead,
                    Permission::AuditExport,
                    Permission::UsageRead,
                    Permission::QuotaManage,
                    Permission::AdminAccess,
                ]);
                perms
            }
            Self::SuperAdmin => {
                let mut perms = Self::Admin.permissions();
                perms.push(Permission::SuperAdmin);
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
        match (self, other) {
            (Self::SuperAdmin, _) => true,
            (Self::Admin, Role::Admin | Role::Writer | Role::Reader) => true,
            (Self::Writer, Role::Writer | Role::Reader) => true,
            (Self::Reader, Role::Reader) => true,
            _ => false,
        }
    }

    /// Get the hierarchy level (higher = more permissions).
    #[must_use]
    pub fn level(&self) -> u8 {
        match self {
            Self::Reader => 1,
            Self::Writer => 2,
            Self::Admin => 3,
            Self::SuperAdmin => 4,
        }
    }

    /// Get all defined roles.
    #[must_use]
    pub fn all() -> Vec<Self> {
        vec![Self::Reader, Self::Writer, Self::Admin, Self::SuperAdmin]
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
            "reader" => Ok(Self::Reader),
            "writer" => Ok(Self::Writer),
            "admin" => Ok(Self::Admin),
            "super_admin" | "superadmin" => Ok(Self::SuperAdmin),
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
        assert!(Role::Admin > Role::Writer);
        assert!(Role::Writer > Role::Reader);
    }

    #[test]
    fn test_role_implies() {
        assert!(Role::SuperAdmin.implies(Role::Admin));
        assert!(Role::Admin.implies(Role::Writer));
        assert!(Role::Writer.implies(Role::Reader));
        assert!(!Role::Reader.implies(Role::Writer));
    }

    #[test]
    fn test_role_permissions() {
        assert!(Role::Reader.has_permission(Permission::DocumentRead));
        assert!(!Role::Reader.has_permission(Permission::DocumentWrite));
        assert!(Role::Writer.has_permission(Permission::DocumentWrite));
        assert!(Role::Admin.has_permission(Permission::AdminAccess));
        assert!(Role::SuperAdmin.has_permission(Permission::SuperAdmin));
    }

    #[test]
    fn test_role_from_str() {
        assert_eq!(Role::from_str("admin").unwrap(), Role::Admin);
        assert_eq!(Role::from_str("super_admin").unwrap(), Role::SuperAdmin);
        assert!(Role::from_str("invalid").is_err());
    }
}

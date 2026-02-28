//! Authorization service for permission checking.

use super::{Permission, Role};
use crate::{AuthError, Result, TokenClaims};
use std::str::FromStr;
use uuid::Uuid;

/// Authorization service for checking permissions.
///
/// Provides methods for verifying that a token holder has the required
/// permissions to perform actions.
#[derive(Debug, Clone, Default)]
pub struct AuthorizationService;

impl AuthorizationService {
    /// Create a new authorization service.
    #[must_use]
    pub fn new() -> Self {
        Self
    }

    /// Check if the claims have a specific permission.
    ///
    /// # Errors
    ///
    /// Returns `AuthError::PermissionDenied` if the permission is not granted.
    pub fn check_permission(&self, claims: &TokenClaims, permission: Permission) -> Result<()> {
        // Super admin has all permissions
        if self.has_super_admin(claims) {
            return Ok(());
        }

        // Check explicit permissions
        if claims.has_permission(permission.as_str()) {
            return Ok(());
        }

        // Check role-based permissions
        for role_str in &claims.roles {
            if let Ok(role) = Role::from_str(role_str) {
                if role.has_permission(permission) {
                    return Ok(());
                }
            }
        }

        Err(AuthError::PermissionDenied(permission.to_string()))
    }

    /// Check if the claims have a minimum role level.
    ///
    /// # Errors
    ///
    /// Returns `AuthError::InsufficientRole` if the role requirement is not met.
    pub fn check_role(&self, claims: &TokenClaims, required_role: Role) -> Result<()> {
        // Super admin satisfies all role requirements
        if self.has_super_admin(claims) {
            return Ok(());
        }

        // Find the highest role the user has
        let highest_role = claims
            .roles
            .iter()
            .filter_map(|r| Role::from_str(r).ok())
            .max();

        match highest_role {
            Some(user_role) if user_role.implies(required_role) => Ok(()),
            _ => Err(AuthError::InsufficientRole(required_role.to_string())),
        }
    }

    /// Check if the claims belong to a specific tenant.
    ///
    /// # Errors
    ///
    /// Returns `AuthError::TenantMismatch` if the tenant doesn't match.
    pub fn check_tenant(&self, claims: &TokenClaims, tenant_id: Uuid) -> Result<()> {
        // Super admin can access any tenant
        if self.has_super_admin(claims) {
            return Ok(());
        }

        if claims.tenant_id == tenant_id {
            Ok(())
        } else {
            Err(AuthError::TenantMismatch {
                expected: tenant_id,
                actual: claims.tenant_id,
            })
        }
    }

    /// Check if the claims have access to a resource with ACL.
    ///
    /// Access is granted if:
    /// - The resource is public (allowed_groups is empty)
    /// - The user is a member of any allowed group
    /// - The user is the owner of the resource
    /// - The user has admin access
    ///
    /// # Errors
    ///
    /// Returns `AuthError::AccessDenied` if access is not granted.
    pub fn check_resource_access(
        &self,
        claims: &TokenClaims,
        allowed_groups: &[String],
        owner_id: Option<Uuid>,
    ) -> Result<()> {
        // Super admin or admin can access anything
        if self.has_super_admin(claims)
            || claims.has_role("admin")
            || claims.has_permission("admin:access")
        {
            return Ok(());
        }

        // Check if user is the owner
        if let Some(owner) = owner_id {
            if claims.sub == owner {
                return Ok(());
            }
        }

        // If no ACL restrictions, allow access
        if allowed_groups.is_empty() {
            return Ok(());
        }

        // Check group membership
        for group in allowed_groups {
            if claims.is_member_of(group) {
                return Ok(());
            }
        }

        Err(AuthError::AccessDenied(
            "User is not authorized to access this resource".into(),
        ))
    }

    /// Check multiple permissions (all must be granted).
    ///
    /// # Errors
    ///
    /// Returns `AuthError::PermissionDenied` for the first missing permission.
    pub fn check_all_permissions(
        &self,
        claims: &TokenClaims,
        permissions: &[Permission],
    ) -> Result<()> {
        for permission in permissions {
            self.check_permission(claims, *permission)?;
        }
        Ok(())
    }

    /// Check multiple permissions (at least one must be granted).
    ///
    /// # Errors
    ///
    /// Returns `AuthError::PermissionDenied` if none of the permissions are granted.
    pub fn check_any_permission(
        &self,
        claims: &TokenClaims,
        permissions: &[Permission],
    ) -> Result<()> {
        for permission in permissions {
            if self.check_permission(claims, *permission).is_ok() {
                return Ok(());
            }
        }

        Err(AuthError::PermissionDenied(
            "None of the required permissions are granted".into(),
        ))
    }

    /// Get all effective permissions for the claims.
    #[must_use]
    pub fn get_effective_permissions(&self, claims: &TokenClaims) -> Vec<Permission> {
        let mut permissions = Vec::new();

        // Collect permissions from roles
        for role_str in &claims.roles {
            if let Ok(role) = Role::from_str(role_str) {
                permissions.extend(role.permissions());
            }
        }

        // Add explicit permissions
        for perm_str in &claims.permissions {
            if let Ok(perm) = Permission::from_str(perm_str) {
                if !permissions.contains(&perm) {
                    permissions.push(perm);
                }
            }
        }

        permissions
    }

    /// Check if the claims have super admin access.
    fn has_super_admin(&self, claims: &TokenClaims) -> bool {
        claims.has_role("super_admin") || claims.has_permission("super:admin")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_claims() -> TokenClaims {
        TokenClaims::new(Uuid::new_v4(), Uuid::new_v4())
    }

    #[test]
    fn test_check_permission_explicit() {
        let svc = AuthorizationService::new();
        let claims = test_claims().with_permissions(vec!["document:read".into()]);

        assert!(svc
            .check_permission(&claims, Permission::DocumentRead)
            .is_ok());
        assert!(svc
            .check_permission(&claims, Permission::DocumentWrite)
            .is_err());
    }

    #[test]
    fn test_check_permission_role_based() {
        let svc = AuthorizationService::new();
        let claims = test_claims().with_roles(vec!["engineer".into()]);

        assert!(svc
            .check_permission(&claims, Permission::DocumentRead)
            .is_ok());
        assert!(svc
            .check_permission(&claims, Permission::DocumentWrite)
            .is_ok());
        assert!(svc
            .check_permission(&claims, Permission::AdminAccess)
            .is_err());
    }

    #[test]
    fn test_check_role() {
        let svc = AuthorizationService::new();
        let claims = test_claims().with_roles(vec!["admin".into()]);

        assert!(svc.check_role(&claims, Role::User).is_ok());
        assert!(svc.check_role(&claims, Role::Engineer).is_ok());
        assert!(svc.check_role(&claims, Role::Admin).is_ok());
        assert!(svc.check_role(&claims, Role::SuperAdmin).is_err());
    }

    #[test]
    fn test_check_tenant() {
        let svc = AuthorizationService::new();
        let tenant_id = Uuid::new_v4();
        let claims = TokenClaims::new(Uuid::new_v4(), tenant_id);

        assert!(svc.check_tenant(&claims, tenant_id).is_ok());
        assert!(svc.check_tenant(&claims, Uuid::new_v4()).is_err());
    }

    #[test]
    fn test_super_admin_bypasses_checks() {
        let svc = AuthorizationService::new();
        let claims = test_claims().with_roles(vec!["super_admin".into()]);

        assert!(svc
            .check_permission(&claims, Permission::AdminAccess)
            .is_ok());
        assert!(svc.check_role(&claims, Role::SuperAdmin).is_ok());
        assert!(svc.check_tenant(&claims, Uuid::new_v4()).is_ok());
    }
}

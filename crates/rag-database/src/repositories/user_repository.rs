//! User and tenant repository for user management.

use sqlx::PgPool;
use uuid::Uuid;

use crate::{
    ApiKey, DatabaseError, Group, NewApiKey, NewGroup, NewRole, NewTenant, NewUser, NewUserGroup,
    NewUserRole, Result, Role, Tenant, User, UserGroup, UserRole,
};

/// Repository for user and tenant operations.
#[derive(Clone)]
pub struct UserRepository {
    pool: PgPool,
}

impl UserRepository {
    /// Create a new user repository.
    #[must_use]
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    // ==================== Tenant Operations ====================

    /// Create a new tenant.
    pub async fn create_tenant(&self, tenant: &NewTenant) -> Result<Tenant> {
        sqlx::query_as::<_, Tenant>(
            r#"
            INSERT INTO tenants (
                name, slug, description, tenant_type, settings, features,
                max_users, max_documents, max_storage_bytes, contact_email, isolation_mode
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING *
            "#,
        )
        .bind(&tenant.name)
        .bind(&tenant.slug)
        .bind(&tenant.description)
        .bind(tenant.tenant_type.as_deref().unwrap_or("standard"))
        .bind(tenant.settings.as_ref().unwrap_or(&serde_json::json!({})))
        .bind(tenant.features.as_ref().unwrap_or(&vec![]))
        .bind(tenant.max_users)
        .bind(tenant.max_documents)
        .bind(tenant.max_storage_bytes)
        .bind(&tenant.contact_email)
        .bind(tenant.isolation_mode.as_deref().unwrap_or("shared"))
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find a tenant by ID.
    pub async fn find_tenant_by_id(&self, id: Uuid) -> Result<Option<Tenant>> {
        sqlx::query_as::<_, Tenant>("SELECT * FROM tenants WHERE id = $1 AND deleted_at IS NULL")
            .bind(id)
            .fetch_optional(&self.pool)
            .await
            .map_err(DatabaseError::from)
    }

    /// Find a tenant by slug.
    pub async fn find_tenant_by_slug(&self, slug: &str) -> Result<Option<Tenant>> {
        sqlx::query_as::<_, Tenant>("SELECT * FROM tenants WHERE slug = $1 AND deleted_at IS NULL")
            .bind(slug)
            .fetch_optional(&self.pool)
            .await
            .map_err(DatabaseError::from)
    }

    /// List all active tenants.
    pub async fn list_tenants(&self, limit: i64, offset: i64) -> Result<Vec<Tenant>> {
        sqlx::query_as::<_, Tenant>(
            r#"
            SELECT * FROM tenants
            WHERE deleted_at IS NULL AND is_active = true
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            "#,
        )
        .bind(limit)
        .bind(offset)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    // ==================== User Operations ====================

    /// Create a new user.
    pub async fn create_user(&self, user: &NewUser) -> Result<User> {
        sqlx::query_as::<_, User>(
            r#"
            INSERT INTO users (
                tenant_id, email, username, external_id, name, avatar_url,
                password_hash, is_sso_user, user_metadata, permissions
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
            "#,
        )
        .bind(user.tenant_id)
        .bind(&user.email)
        .bind(&user.username)
        .bind(&user.external_id)
        .bind(&user.name)
        .bind(&user.avatar_url)
        .bind(&user.password_hash)
        .bind(user.is_sso_user.unwrap_or(false))
        .bind(
            user.user_metadata
                .as_ref()
                .unwrap_or(&serde_json::json!({})),
        )
        .bind(user.permissions.as_ref().unwrap_or(&vec![]))
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find a user by ID.
    pub async fn find_user_by_id(&self, id: Uuid) -> Result<Option<User>> {
        sqlx::query_as::<_, User>("SELECT * FROM users WHERE id = $1 AND deleted_at IS NULL")
            .bind(id)
            .fetch_optional(&self.pool)
            .await
            .map_err(DatabaseError::from)
    }

    /// Find a user by email within a tenant.
    pub async fn find_user_by_email(&self, tenant_id: Uuid, email: &str) -> Result<Option<User>> {
        sqlx::query_as::<_, User>(
            "SELECT * FROM users WHERE tenant_id = $1 AND email = $2 AND deleted_at IS NULL",
        )
        .bind(tenant_id)
        .bind(email)
        .fetch_optional(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find a user by external ID.
    pub async fn find_user_by_external_id(&self, external_id: &str) -> Result<Option<User>> {
        sqlx::query_as::<_, User>(
            "SELECT * FROM users WHERE external_id = $1 AND deleted_at IS NULL",
        )
        .bind(external_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// List users for a tenant.
    pub async fn list_users(&self, tenant_id: Uuid, limit: i64, offset: i64) -> Result<Vec<User>> {
        sqlx::query_as::<_, User>(
            r#"
            SELECT * FROM users
            WHERE tenant_id = $1 AND deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            "#,
        )
        .bind(tenant_id)
        .bind(limit)
        .bind(offset)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Update user's last login timestamp.
    pub async fn update_last_login(&self, user_id: Uuid) -> Result<()> {
        sqlx::query("UPDATE users SET last_login_at = NOW(), updated_at = NOW() WHERE id = $1")
            .bind(user_id)
            .execute(&self.pool)
            .await
            .map_err(DatabaseError::from)?;
        Ok(())
    }

    // ==================== Role Operations ====================

    /// Create a new role.
    pub async fn create_role(&self, role: &NewRole) -> Result<Role> {
        sqlx::query_as::<_, Role>(
            r#"
            INSERT INTO roles (
                tenant_id, name, description, is_system_role, is_default,
                permissions, parent_role_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
            "#,
        )
        .bind(role.tenant_id)
        .bind(&role.name)
        .bind(&role.description)
        .bind(role.is_system_role.unwrap_or(false))
        .bind(role.is_default.unwrap_or(false))
        .bind(&role.permissions)
        .bind(role.parent_role_id)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find a role by ID.
    pub async fn find_role_by_id(&self, id: Uuid) -> Result<Option<Role>> {
        sqlx::query_as::<_, Role>("SELECT * FROM roles WHERE id = $1 AND deleted_at IS NULL")
            .bind(id)
            .fetch_optional(&self.pool)
            .await
            .map_err(DatabaseError::from)
    }

    /// Find roles for a tenant (including system roles).
    pub async fn find_roles_for_tenant(&self, tenant_id: Uuid) -> Result<Vec<Role>> {
        sqlx::query_as::<_, Role>(
            r#"
            SELECT * FROM roles
            WHERE (tenant_id = $1 OR tenant_id IS NULL) AND deleted_at IS NULL
            ORDER BY is_system_role DESC, name ASC
            "#,
        )
        .bind(tenant_id)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Get user's roles.
    pub async fn get_user_roles(&self, user_id: Uuid) -> Result<Vec<Role>> {
        sqlx::query_as::<_, Role>(
            r#"
            SELECT r.* FROM roles r
            JOIN user_roles ur ON r.id = ur.role_id
            WHERE ur.user_id = $1 AND r.deleted_at IS NULL
            AND (ur.expires_at IS NULL OR ur.expires_at > NOW())
            "#,
        )
        .bind(user_id)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Assign a role to a user.
    pub async fn assign_role(&self, assignment: &NewUserRole) -> Result<UserRole> {
        sqlx::query_as::<_, UserRole>(
            r#"
            INSERT INTO user_roles (user_id, role_id, assigned_by, expires_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, role_id) DO UPDATE
            SET expires_at = $4, updated_at = NOW()
            RETURNING *
            "#,
        )
        .bind(assignment.user_id)
        .bind(assignment.role_id)
        .bind(assignment.assigned_by)
        .bind(assignment.expires_at)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Remove a role from a user.
    pub async fn remove_role(&self, user_id: Uuid, role_id: Uuid) -> Result<bool> {
        let result = sqlx::query("DELETE FROM user_roles WHERE user_id = $1 AND role_id = $2")
            .bind(user_id)
            .bind(role_id)
            .execute(&self.pool)
            .await
            .map_err(DatabaseError::from)?;
        Ok(result.rows_affected() > 0)
    }

    // ==================== Group Operations ====================

    /// Create a new group.
    pub async fn create_group(&self, group: &NewGroup) -> Result<Group> {
        sqlx::query_as::<_, Group>(
            r#"
            INSERT INTO groups (tenant_id, name, description, group_type, group_metadata)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            "#,
        )
        .bind(group.tenant_id)
        .bind(&group.name)
        .bind(&group.description)
        .bind(group.group_type.as_deref().unwrap_or("custom"))
        .bind(
            group
                .group_metadata
                .as_ref()
                .unwrap_or(&serde_json::json!({})),
        )
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find a group by ID.
    pub async fn find_group_by_id(&self, id: Uuid) -> Result<Option<Group>> {
        sqlx::query_as::<_, Group>("SELECT * FROM groups WHERE id = $1 AND deleted_at IS NULL")
            .bind(id)
            .fetch_optional(&self.pool)
            .await
            .map_err(DatabaseError::from)
    }

    /// Find groups for a tenant.
    pub async fn find_groups_for_tenant(&self, tenant_id: Uuid) -> Result<Vec<Group>> {
        sqlx::query_as::<_, Group>(
            "SELECT * FROM groups WHERE tenant_id = $1 AND deleted_at IS NULL ORDER BY name",
        )
        .bind(tenant_id)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Get user's groups.
    pub async fn get_user_groups(&self, user_id: Uuid) -> Result<Vec<Group>> {
        sqlx::query_as::<_, Group>(
            r#"
            SELECT g.* FROM groups g
            JOIN user_groups ug ON g.id = ug.group_id
            WHERE ug.user_id = $1 AND g.deleted_at IS NULL
            AND (ug.expires_at IS NULL OR ug.expires_at > NOW())
            "#,
        )
        .bind(user_id)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Add a user to a group.
    pub async fn add_user_to_group(&self, membership: &NewUserGroup) -> Result<UserGroup> {
        sqlx::query_as::<_, UserGroup>(
            r#"
            INSERT INTO user_groups (user_id, group_id, added_by, expires_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, group_id) DO UPDATE
            SET expires_at = $4, updated_at = NOW()
            RETURNING *
            "#,
        )
        .bind(membership.user_id)
        .bind(membership.group_id)
        .bind(membership.added_by)
        .bind(membership.expires_at)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Remove a user from a group.
    pub async fn remove_user_from_group(&self, user_id: Uuid, group_id: Uuid) -> Result<bool> {
        let result = sqlx::query("DELETE FROM user_groups WHERE user_id = $1 AND group_id = $2")
            .bind(user_id)
            .bind(group_id)
            .execute(&self.pool)
            .await
            .map_err(DatabaseError::from)?;
        Ok(result.rows_affected() > 0)
    }

    // ==================== API Key Operations ====================

    /// Create a new API key.
    pub async fn create_api_key(&self, api_key: &NewApiKey) -> Result<ApiKey> {
        sqlx::query_as::<_, ApiKey>(
            r#"
            INSERT INTO api_keys (user_id, name, key_prefix, key_hash, scopes, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            "#,
        )
        .bind(api_key.user_id)
        .bind(&api_key.name)
        .bind(&api_key.key_prefix)
        .bind(&api_key.key_hash)
        .bind(api_key.scopes.as_ref().unwrap_or(&vec![]))
        .bind(api_key.expires_at)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find an API key by prefix.
    pub async fn find_api_key_by_prefix(&self, prefix: &str) -> Result<Option<ApiKey>> {
        sqlx::query_as::<_, ApiKey>(
            "SELECT * FROM api_keys WHERE key_prefix = $1 AND deleted_at IS NULL",
        )
        .bind(prefix)
        .fetch_optional(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// List API keys for a user.
    pub async fn list_user_api_keys(&self, user_id: Uuid) -> Result<Vec<ApiKey>> {
        sqlx::query_as::<_, ApiKey>(
            "SELECT * FROM api_keys WHERE user_id = $1 AND deleted_at IS NULL ORDER BY created_at DESC",
        )
        .bind(user_id)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Update API key usage.
    pub async fn update_api_key_usage(&self, id: Uuid) -> Result<()> {
        sqlx::query(
            "UPDATE api_keys SET last_used_at = NOW(), usage_count = usage_count + 1 WHERE id = $1",
        )
        .bind(id)
        .execute(&self.pool)
        .await
        .map_err(DatabaseError::from)?;
        Ok(())
    }

    /// Soft delete an API key.
    pub async fn delete_api_key(&self, id: Uuid) -> Result<bool> {
        let result = sqlx::query("UPDATE api_keys SET deleted_at = NOW() WHERE id = $1")
            .bind(id)
            .execute(&self.pool)
            .await
            .map_err(DatabaseError::from)?;
        Ok(result.rows_affected() > 0)
    }
}

impl std::fmt::Debug for UserRepository {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("UserRepository").finish_non_exhaustive()
    }
}

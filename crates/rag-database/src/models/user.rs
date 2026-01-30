//! User, Tenant, Role, Group, and API Key models for RBAC.
//!
//! This module defines database models for user management, role-based access control,
//! and group membership in a multi-tenant system.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

/// Represents a tenant in the multi-tenant system.
///
/// Tenants provide isolation for users, documents, and all resources.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct Tenant {
    pub id: Uuid,
    pub name: String,
    pub slug: String,
    pub description: Option<String>,
    pub tenant_type: String,
    pub is_active: bool,
    pub settings: serde_json::Value,
    pub features: Vec<String>,
    pub max_users: Option<i32>,
    pub max_documents: Option<i32>,
    pub max_storage_bytes: Option<i64>,
    pub contact_email: Option<String>,
    pub isolation_mode: String,
    pub qdrant_collection_name: Option<String>,
    pub qdrant_settings: Option<serde_json::Value>,
    pub opensearch_index_name: Option<String>,
    pub opensearch_settings: Option<serde_json::Value>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub deleted_at: Option<DateTime<Utc>>,
}

impl Tenant {
    /// Get Qdrant collection name for this tenant.
    pub fn get_qdrant_collection(&self) -> String {
        if self.isolation_mode == "dedicated" {
            self.qdrant_collection_name
                .clone()
                .unwrap_or_else(|| format!("documents_{}", self.id))
        } else {
            "documents".to_string()
        }
    }

    /// Get OpenSearch index name for this tenant.
    pub fn get_opensearch_index(&self) -> String {
        if self.isolation_mode == "dedicated" {
            self.opensearch_index_name
                .clone()
                .unwrap_or_else(|| format!("documents-{}", self.id))
        } else {
            "documents".to_string()
        }
    }

    /// Check if tenant uses dedicated indices.
    pub fn is_isolated(&self) -> bool {
        self.isolation_mode == "dedicated"
    }
}

/// Data for creating a new tenant.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewTenant {
    pub name: String,
    pub slug: String,
    pub description: Option<String>,
    pub tenant_type: Option<String>,
    pub settings: Option<serde_json::Value>,
    pub features: Option<Vec<String>>,
    pub max_users: Option<i32>,
    pub max_documents: Option<i32>,
    pub max_storage_bytes: Option<i64>,
    pub contact_email: Option<String>,
    pub isolation_mode: Option<String>,
}

impl Default for NewTenant {
    fn default() -> Self {
        Self {
            name: String::new(),
            slug: String::new(),
            description: None,
            tenant_type: Some("standard".to_string()),
            settings: Some(serde_json::json!({})),
            features: Some(vec![]),
            max_users: None,
            max_documents: None,
            max_storage_bytes: None,
            contact_email: None,
            isolation_mode: Some("shared".to_string()),
        }
    }
}

/// Represents a user in the system.
///
/// Users belong to a tenant and can have roles and group memberships.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct User {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub email: String,
    pub username: Option<String>,
    pub external_id: Option<String>,
    pub name: Option<String>,
    pub avatar_url: Option<String>,
    pub password_hash: Option<String>,
    pub is_sso_user: bool,
    pub is_active: bool,
    pub is_verified: bool,
    pub last_login_at: Option<DateTime<Utc>>,
    pub user_metadata: serde_json::Value,
    pub permissions: Vec<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub deleted_at: Option<DateTime<Utc>>,
}

/// Data for creating a new user.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewUser {
    pub tenant_id: Uuid,
    pub email: String,
    pub username: Option<String>,
    pub external_id: Option<String>,
    pub name: Option<String>,
    pub avatar_url: Option<String>,
    pub password_hash: Option<String>,
    pub is_sso_user: Option<bool>,
    pub user_metadata: Option<serde_json::Value>,
    pub permissions: Option<Vec<String>>,
}

/// Represents a role in the RBAC system.
///
/// Roles define a set of permissions that can be assigned to users.
/// Can be system-defined or tenant-specific custom roles.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct Role {
    pub id: Uuid,
    pub tenant_id: Option<Uuid>,
    pub name: String,
    pub description: Option<String>,
    pub is_system_role: bool,
    pub is_default: bool,
    pub permissions: Vec<String>,
    pub parent_role_id: Option<Uuid>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub deleted_at: Option<DateTime<Utc>>,
}

/// Data for creating a new role.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewRole {
    pub tenant_id: Option<Uuid>,
    pub name: String,
    pub description: Option<String>,
    pub is_system_role: Option<bool>,
    pub is_default: Option<bool>,
    pub permissions: Vec<String>,
    pub parent_role_id: Option<Uuid>,
}

/// Represents a group for document access control.
///
/// Groups are used for document-level ACL, allowing access to be granted
/// to sets of users.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct Group {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub name: String,
    pub description: Option<String>,
    pub group_type: String,
    pub group_metadata: serde_json::Value,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub deleted_at: Option<DateTime<Utc>>,
}

/// Data for creating a new group.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewGroup {
    pub tenant_id: Uuid,
    pub name: String,
    pub description: Option<String>,
    pub group_type: Option<String>,
    pub group_metadata: Option<serde_json::Value>,
}

/// Association for user-role relationships.
///
/// Supports role assignment with optional expiration.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct UserRole {
    pub id: Uuid,
    pub user_id: Uuid,
    pub role_id: Uuid,
    pub assigned_by: Option<Uuid>,
    pub expires_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

/// Data for creating a new user-role assignment.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewUserRole {
    pub user_id: Uuid,
    pub role_id: Uuid,
    pub assigned_by: Option<Uuid>,
    pub expires_at: Option<DateTime<Utc>>,
}

/// Association for user-group relationships.
///
/// Supports group membership with optional expiration.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct UserGroup {
    pub id: Uuid,
    pub user_id: Uuid,
    pub group_id: Uuid,
    pub added_by: Option<Uuid>,
    pub expires_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

/// Data for creating a new user-group membership.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewUserGroup {
    pub user_id: Uuid,
    pub group_id: Uuid,
    pub added_by: Option<Uuid>,
    pub expires_at: Option<DateTime<Utc>>,
}

/// API key for programmatic access.
///
/// API keys are associated with a user and inherit their permissions.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct ApiKey {
    pub id: Uuid,
    pub user_id: Uuid,
    pub name: String,
    pub key_prefix: String,
    pub key_hash: String,
    pub scopes: Vec<String>,
    pub last_used_at: Option<DateTime<Utc>>,
    pub usage_count: i32,
    pub expires_at: Option<DateTime<Utc>>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub deleted_at: Option<DateTime<Utc>>,
}

/// Data for creating a new API key.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewApiKey {
    pub user_id: Uuid,
    pub name: String,
    pub key_prefix: String,
    pub key_hash: String,
    pub scopes: Option<Vec<String>>,
    pub expires_at: Option<DateTime<Utc>>,
}

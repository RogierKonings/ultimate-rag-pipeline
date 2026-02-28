//! Audit log model for tracking system events and user actions.
//!
//! Used for compliance, debugging, and security monitoring.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

/// Audit action types.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum AuditAction {
    Create,
    Read,
    Update,
    Delete,
    Search,
    Login,
    Logout,
    Export,
    Import,
}

impl AuditAction {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Create => "CREATE",
            Self::Read => "READ",
            Self::Update => "UPDATE",
            Self::Delete => "DELETE",
            Self::Search => "SEARCH",
            Self::Login => "LOGIN",
            Self::Logout => "LOGOUT",
            Self::Export => "EXPORT",
            Self::Import => "IMPORT",
        }
    }
}

impl std::fmt::Display for AuditAction {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// Stores audit trail for system events and user actions.
///
/// Used for compliance, debugging, and security monitoring.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct AuditLog {
    pub id: Uuid,
    pub event_type: String,
    pub event_source: String,
    pub tenant_id: Uuid,
    pub user_id: Option<Uuid>,
    pub resource_type: Option<String>,
    pub resource_id: Option<String>,
    pub action: String,
    pub description: Option<String>,
    pub request_id: Option<String>,
    pub ip_address: Option<String>,
    pub user_agent: Option<String>,
    pub audit_metadata: serde_json::Value,
    pub audit_changes: Option<serde_json::Value>,
    pub created_at: DateTime<Utc>,
}

/// Data for creating a new audit log entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewAuditLog {
    pub event_type: String,
    pub event_source: String,
    pub tenant_id: Uuid,
    pub user_id: Option<Uuid>,
    pub resource_type: Option<String>,
    pub resource_id: Option<String>,
    pub action: String,
    pub description: Option<String>,
    pub request_id: Option<String>,
    pub ip_address: Option<String>,
    pub user_agent: Option<String>,
    pub audit_metadata: Option<serde_json::Value>,
    pub audit_changes: Option<serde_json::Value>,
}

impl NewAuditLog {
    /// Create a new audit log entry builder.
    pub fn builder() -> AuditLogBuilder {
        AuditLogBuilder::default()
    }
}

/// Builder for creating audit log entries.
#[derive(Debug, Default)]
pub struct AuditLogBuilder {
    event_type: Option<String>,
    event_source: Option<String>,
    tenant_id: Option<Uuid>,
    user_id: Option<Uuid>,
    resource_type: Option<String>,
    resource_id: Option<String>,
    action: Option<String>,
    description: Option<String>,
    request_id: Option<String>,
    ip_address: Option<String>,
    user_agent: Option<String>,
    audit_metadata: Option<serde_json::Value>,
    audit_changes: Option<serde_json::Value>,
}

impl AuditLogBuilder {
    pub fn event_type(mut self, event_type: impl Into<String>) -> Self {
        self.event_type = Some(event_type.into());
        self
    }

    pub fn event_source(mut self, event_source: impl Into<String>) -> Self {
        self.event_source = Some(event_source.into());
        self
    }

    pub fn tenant_id(mut self, tenant_id: Uuid) -> Self {
        self.tenant_id = Some(tenant_id);
        self
    }

    pub fn user_id(mut self, user_id: Uuid) -> Self {
        self.user_id = Some(user_id);
        self
    }

    pub fn resource(
        mut self,
        resource_type: impl Into<String>,
        resource_id: impl Into<String>,
    ) -> Self {
        self.resource_type = Some(resource_type.into());
        self.resource_id = Some(resource_id.into());
        self
    }

    pub fn action(mut self, action: AuditAction) -> Self {
        self.action = Some(action.to_string());
        self
    }

    pub fn action_str(mut self, action: impl Into<String>) -> Self {
        self.action = Some(action.into());
        self
    }

    pub fn description(mut self, description: impl Into<String>) -> Self {
        self.description = Some(description.into());
        self
    }

    pub fn request_id(mut self, request_id: impl Into<String>) -> Self {
        self.request_id = Some(request_id.into());
        self
    }

    pub fn ip_address(mut self, ip_address: impl Into<String>) -> Self {
        self.ip_address = Some(ip_address.into());
        self
    }

    pub fn user_agent(mut self, user_agent: impl Into<String>) -> Self {
        self.user_agent = Some(user_agent.into());
        self
    }

    pub fn metadata(mut self, metadata: serde_json::Value) -> Self {
        self.audit_metadata = Some(metadata);
        self
    }

    pub fn changes(mut self, changes: serde_json::Value) -> Self {
        self.audit_changes = Some(changes);
        self
    }

    /// Build the NewAuditLog, returning an error if required fields are missing.
    pub fn build(self) -> Result<NewAuditLog, &'static str> {
        Ok(NewAuditLog {
            event_type: self.event_type.ok_or("event_type is required")?,
            event_source: self.event_source.ok_or("event_source is required")?,
            tenant_id: self.tenant_id.ok_or("tenant_id is required")?,
            user_id: self.user_id,
            resource_type: self.resource_type,
            resource_id: self.resource_id,
            action: self.action.ok_or("action is required")?,
            description: self.description,
            request_id: self.request_id,
            ip_address: self.ip_address,
            user_agent: self.user_agent,
            audit_metadata: self.audit_metadata,
            audit_changes: self.audit_changes,
        })
    }
}

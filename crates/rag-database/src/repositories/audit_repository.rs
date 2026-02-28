//! Audit log repository for tracking system events.

use chrono::{DateTime, Utc};
use sqlx::PgPool;
use uuid::Uuid;

use crate::{AuditLog, DatabaseError, NewAuditLog, Result};

/// Repository for audit log operations.
#[derive(Clone)]
pub struct AuditRepository {
    pool: PgPool,
}

impl AuditRepository {
    /// Create a new audit repository.
    #[must_use]
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Insert a new audit log entry.
    pub async fn create(&self, log: &NewAuditLog) -> Result<AuditLog> {
        sqlx::query_as::<_, AuditLog>(
            r#"
            INSERT INTO audit_logs (
                event_type, event_source, tenant_id, user_id, resource_type,
                resource_id, action, description, request_id, ip_address,
                user_agent, audit_metadata, audit_changes
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING *
            "#,
        )
        .bind(&log.event_type)
        .bind(&log.event_source)
        .bind(log.tenant_id)
        .bind(log.user_id)
        .bind(&log.resource_type)
        .bind(&log.resource_id)
        .bind(&log.action)
        .bind(&log.description)
        .bind(&log.request_id)
        .bind(&log.ip_address)
        .bind(&log.user_agent)
        .bind(
            log.audit_metadata
                .as_ref()
                .unwrap_or(&serde_json::json!({})),
        )
        .bind(&log.audit_changes)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find audit logs by tenant with pagination.
    pub async fn find_by_tenant(
        &self,
        tenant_id: Uuid,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<AuditLog>> {
        sqlx::query_as::<_, AuditLog>(
            r#"
            SELECT * FROM audit_logs
            WHERE tenant_id = $1
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

    /// Find audit logs by user.
    pub async fn find_by_user(
        &self,
        user_id: Uuid,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<AuditLog>> {
        sqlx::query_as::<_, AuditLog>(
            r#"
            SELECT * FROM audit_logs
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            "#,
        )
        .bind(user_id)
        .bind(limit)
        .bind(offset)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find audit logs by resource.
    pub async fn find_by_resource(
        &self,
        resource_type: &str,
        resource_id: &str,
        limit: i64,
    ) -> Result<Vec<AuditLog>> {
        sqlx::query_as::<_, AuditLog>(
            r#"
            SELECT * FROM audit_logs
            WHERE resource_type = $1 AND resource_id = $2
            ORDER BY created_at DESC
            LIMIT $3
            "#,
        )
        .bind(resource_type)
        .bind(resource_id)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find audit logs by event type.
    pub async fn find_by_event_type(
        &self,
        tenant_id: Uuid,
        event_type: &str,
        limit: i64,
    ) -> Result<Vec<AuditLog>> {
        sqlx::query_as::<_, AuditLog>(
            r#"
            SELECT * FROM audit_logs
            WHERE tenant_id = $1 AND event_type = $2
            ORDER BY created_at DESC
            LIMIT $3
            "#,
        )
        .bind(tenant_id)
        .bind(event_type)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find audit logs in a time range.
    pub async fn find_in_range(
        &self,
        tenant_id: Uuid,
        start: DateTime<Utc>,
        end: DateTime<Utc>,
        limit: i64,
    ) -> Result<Vec<AuditLog>> {
        sqlx::query_as::<_, AuditLog>(
            r#"
            SELECT * FROM audit_logs
            WHERE tenant_id = $1 AND created_at >= $2 AND created_at <= $3
            ORDER BY created_at DESC
            LIMIT $4
            "#,
        )
        .bind(tenant_id)
        .bind(start)
        .bind(end)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Count audit logs for a tenant.
    pub async fn count(&self, tenant_id: Uuid) -> Result<i64> {
        let row: (i64,) = sqlx::query_as("SELECT COUNT(*) FROM audit_logs WHERE tenant_id = $1")
            .bind(tenant_id)
            .fetch_one(&self.pool)
            .await
            .map_err(DatabaseError::from)?;
        Ok(row.0)
    }
}

impl std::fmt::Debug for AuditRepository {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AuditRepository").finish_non_exhaustive()
    }
}

//! Usage repository for token tracking and quota management.

use chrono::NaiveDate;
use sqlx::PgPool;

use crate::{DatabaseError, NewTenantQuota, NewTokenUsage, Result, TenantQuota, TokenUsage};

/// Repository for token usage and quota operations.
#[derive(Clone)]
pub struct UsageRepository {
    pool: PgPool,
}

impl UsageRepository {
    /// Create a new usage repository.
    #[must_use]
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    // ==================== Token Usage ====================

    /// Upsert token usage (insert or update on conflict).
    pub async fn upsert_usage(&self, usage: &NewTokenUsage) -> Result<TokenUsage> {
        sqlx::query_as::<_, TokenUsage>(
            r#"
            INSERT INTO token_usage (tenant_id, date, model, prompt_tokens, completion_tokens, embedding_tokens)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (tenant_id, date, model) DO UPDATE
            SET prompt_tokens = token_usage.prompt_tokens + EXCLUDED.prompt_tokens,
                completion_tokens = token_usage.completion_tokens + EXCLUDED.completion_tokens,
                embedding_tokens = token_usage.embedding_tokens + EXCLUDED.embedding_tokens,
                updated_at = NOW()
            RETURNING *
            "#,
        )
        .bind(&usage.tenant_id)
        .bind(usage.date)
        .bind(&usage.model)
        .bind(usage.prompt_tokens)
        .bind(usage.completion_tokens)
        .bind(usage.embedding_tokens)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Get usage for a tenant and date.
    pub async fn get_usage(&self, tenant_id: &str, date: NaiveDate) -> Result<Vec<TokenUsage>> {
        sqlx::query_as::<_, TokenUsage>(
            "SELECT * FROM token_usage WHERE tenant_id = $1 AND date = $2",
        )
        .bind(tenant_id)
        .bind(date)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Get total usage for a tenant in a date range.
    pub async fn get_total_usage(
        &self,
        tenant_id: &str,
        start_date: NaiveDate,
        end_date: NaiveDate,
    ) -> Result<i64> {
        let row: (Option<i64>,) = sqlx::query_as(
            r#"
            SELECT SUM(prompt_tokens + completion_tokens + embedding_tokens)
            FROM token_usage
            WHERE tenant_id = $1 AND date >= $2 AND date <= $3
            "#,
        )
        .bind(tenant_id)
        .bind(start_date)
        .bind(end_date)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)?;
        Ok(row.0.unwrap_or(0))
    }

    /// Get monthly usage for a tenant.
    pub async fn get_monthly_usage(&self, tenant_id: &str, year: i32, month: u32) -> Result<i64> {
        let start_date = NaiveDate::from_ymd_opt(year, month, 1).unwrap_or_default();
        let end_date = if month == 12 {
            NaiveDate::from_ymd_opt(year + 1, 1, 1)
        } else {
            NaiveDate::from_ymd_opt(year, month + 1, 1)
        }
        .unwrap_or_default()
        .pred_opt()
        .unwrap_or(start_date);

        self.get_total_usage(tenant_id, start_date, end_date).await
    }

    // ==================== Tenant Quota ====================

    /// Get or create tenant quota.
    pub async fn get_or_create_quota(&self, tenant_id: &str) -> Result<TenantQuota> {
        // Try to get existing quota
        if let Some(quota) = self.get_quota(tenant_id).await? {
            return Ok(quota);
        }

        // Create default quota
        let new_quota = NewTenantQuota::unlimited(tenant_id);
        self.create_quota(&new_quota).await
    }

    /// Get tenant quota.
    pub async fn get_quota(&self, tenant_id: &str) -> Result<Option<TenantQuota>> {
        sqlx::query_as::<_, TenantQuota>("SELECT * FROM tenant_quotas WHERE tenant_id = $1")
            .bind(tenant_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(DatabaseError::from)
    }

    /// Create tenant quota.
    pub async fn create_quota(&self, quota: &NewTenantQuota) -> Result<TenantQuota> {
        sqlx::query_as::<_, TenantQuota>(
            r#"
            INSERT INTO tenant_quotas (tenant_id, monthly_token_limit, quota_enabled, alert_threshold_percent)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            "#,
        )
        .bind(&quota.tenant_id)
        .bind(quota.monthly_token_limit)
        .bind(quota.quota_enabled)
        .bind(quota.alert_threshold_percent.unwrap_or(80))
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Update tenant quota.
    pub async fn update_quota(&self, quota: &NewTenantQuota) -> Result<TenantQuota> {
        sqlx::query_as::<_, TenantQuota>(
            r#"
            UPDATE tenant_quotas
            SET monthly_token_limit = $2, quota_enabled = $3, alert_threshold_percent = $4, updated_at = NOW()
            WHERE tenant_id = $1
            RETURNING *
            "#,
        )
        .bind(&quota.tenant_id)
        .bind(quota.monthly_token_limit)
        .bind(quota.quota_enabled)
        .bind(quota.alert_threshold_percent.unwrap_or(80))
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Check if tenant is over quota.
    pub async fn is_over_quota(&self, tenant_id: &str, year: i32, month: u32) -> Result<bool> {
        let quota = self.get_or_create_quota(tenant_id).await?;
        if quota.is_unlimited() {
            return Ok(false);
        }

        let usage = self.get_monthly_usage(tenant_id, year, month).await?;
        Ok(quota.is_over_quota(usage))
    }
}

impl std::fmt::Debug for UsageRepository {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("UsageRepository").finish_non_exhaustive()
    }
}

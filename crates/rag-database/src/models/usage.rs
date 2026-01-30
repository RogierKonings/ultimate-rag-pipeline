//! Token usage tracking models for quota management and billing.
//!
//! Provides daily token usage aggregation and quota configuration per tenant.

use chrono::{DateTime, NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

/// Daily token usage aggregation per tenant and model.
///
/// Usage data is buffered in Redis and periodically flushed to this table.
/// Each row represents one day's usage for a specific tenant/model combination.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct TokenUsage {
    pub id: Uuid,
    pub tenant_id: String,
    pub date: NaiveDate,
    pub model: String,
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
    pub embedding_tokens: i64,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

impl TokenUsage {
    /// Calculate total tokens (prompt + completion + embedding).
    pub fn total_tokens(&self) -> i64 {
        self.prompt_tokens + self.completion_tokens + self.embedding_tokens
    }
}

/// Data for creating or updating token usage.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewTokenUsage {
    pub tenant_id: String,
    pub date: NaiveDate,
    pub model: String,
    pub prompt_tokens: i64,
    pub completion_tokens: i64,
    pub embedding_tokens: i64,
}

impl NewTokenUsage {
    /// Create a new token usage entry.
    pub fn new(tenant_id: impl Into<String>, date: NaiveDate, model: impl Into<String>) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            date,
            model: model.into(),
            prompt_tokens: 0,
            completion_tokens: 0,
            embedding_tokens: 0,
        }
    }

    /// Add prompt tokens.
    pub fn with_prompt_tokens(mut self, tokens: i64) -> Self {
        self.prompt_tokens = tokens;
        self
    }

    /// Add completion tokens.
    pub fn with_completion_tokens(mut self, tokens: i64) -> Self {
        self.completion_tokens = tokens;
        self
    }

    /// Add embedding tokens.
    pub fn with_embedding_tokens(mut self, tokens: i64) -> Self {
        self.embedding_tokens = tokens;
        self
    }
}

/// Quota configuration per tenant.
///
/// When quota_enabled is True and monthly_token_limit is set,
/// requests exceeding the limit will receive a 429 response.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct TenantQuota {
    pub tenant_id: String,
    pub monthly_token_limit: Option<i64>,
    pub quota_enabled: bool,
    pub alert_threshold_percent: i64,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

impl TenantQuota {
    /// Check if tenant has unlimited quota.
    pub fn is_unlimited(&self) -> bool {
        !self.quota_enabled || self.monthly_token_limit.is_none()
    }

    /// Check if the given usage exceeds the quota.
    pub fn is_over_quota(&self, current_usage: i64) -> bool {
        if self.is_unlimited() {
            return false;
        }
        current_usage >= self.monthly_token_limit.unwrap_or(i64::MAX)
    }

    /// Check if the given usage exceeds the alert threshold.
    pub fn is_over_alert_threshold(&self, current_usage: i64) -> bool {
        if self.is_unlimited() {
            return false;
        }
        let limit = self.monthly_token_limit.unwrap_or(i64::MAX);
        let threshold = (limit as f64 * self.alert_threshold_percent as f64 / 100.0) as i64;
        current_usage >= threshold
    }

    /// Calculate the percentage of quota used.
    pub fn usage_percentage(&self, current_usage: i64) -> Option<f64> {
        self.monthly_token_limit
            .map(|limit| (current_usage as f64 / limit as f64) * 100.0)
    }
}

/// Data for creating or updating tenant quota.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewTenantQuota {
    pub tenant_id: String,
    pub monthly_token_limit: Option<i64>,
    pub quota_enabled: bool,
    pub alert_threshold_percent: Option<i64>,
}

impl NewTenantQuota {
    /// Create a new unlimited quota configuration.
    pub fn unlimited(tenant_id: impl Into<String>) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            monthly_token_limit: None,
            quota_enabled: false,
            alert_threshold_percent: Some(80),
        }
    }

    /// Create a new limited quota configuration.
    pub fn limited(tenant_id: impl Into<String>, monthly_limit: i64) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            monthly_token_limit: Some(monthly_limit),
            quota_enabled: true,
            alert_threshold_percent: Some(80),
        }
    }

    /// Set the alert threshold percentage.
    pub fn with_alert_threshold(mut self, percent: i64) -> Self {
        self.alert_threshold_percent = Some(percent);
        self
    }
}

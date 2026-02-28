//! Feedback repository for query feedback tracking.

use sqlx::PgPool;

use crate::{DatabaseError, NewQueryFeedback, QueryFeedback, Result};

/// Repository for query feedback operations.
#[derive(Clone)]
pub struct FeedbackRepository {
    pool: PgPool,
}

impl FeedbackRepository {
    /// Create a new feedback repository.
    #[must_use]
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Insert new feedback.
    pub async fn create(&self, feedback: &NewQueryFeedback) -> Result<QueryFeedback> {
        sqlx::query_as::<_, QueryFeedback>(
            r#"
            INSERT INTO query_feedback (request_id, tenant_id, rating, feedback_type, comment, session_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING *
            "#,
        )
        .bind(&feedback.request_id)
        .bind(&feedback.tenant_id)
        .bind(feedback.rating)
        .bind(feedback.feedback_type.as_deref().unwrap_or("general"))
        .bind(&feedback.comment)
        .bind(&feedback.session_id)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find feedback by request ID.
    pub async fn find_by_request_id(&self, request_id: &str) -> Result<Option<QueryFeedback>> {
        sqlx::query_as::<_, QueryFeedback>("SELECT * FROM query_feedback WHERE request_id = $1")
            .bind(request_id)
            .fetch_optional(&self.pool)
            .await
            .map_err(DatabaseError::from)
    }

    /// Find feedback by tenant with pagination.
    pub async fn find_by_tenant(
        &self,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<QueryFeedback>> {
        sqlx::query_as::<_, QueryFeedback>(
            r#"
            SELECT * FROM query_feedback
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

    /// Get average rating for a tenant.
    pub async fn get_average_rating(&self, tenant_id: &str) -> Result<Option<f64>> {
        let row: (Option<f64>,) =
            sqlx::query_as("SELECT AVG(rating::float) FROM query_feedback WHERE tenant_id = $1")
                .bind(tenant_id)
                .fetch_one(&self.pool)
                .await
                .map_err(DatabaseError::from)?;
        Ok(row.0)
    }

    /// Count feedback by rating for a tenant.
    pub async fn count_by_rating(&self, tenant_id: &str, rating: i32) -> Result<i64> {
        let row: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM query_feedback WHERE tenant_id = $1 AND rating = $2",
        )
        .bind(tenant_id)
        .bind(rating)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)?;
        Ok(row.0)
    }

    /// Count positive feedback (rating >= 4).
    pub async fn count_positive(&self, tenant_id: &str) -> Result<i64> {
        let row: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM query_feedback WHERE tenant_id = $1 AND rating >= 4",
        )
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)?;
        Ok(row.0)
    }

    /// Count negative feedback (rating <= 2).
    pub async fn count_negative(&self, tenant_id: &str) -> Result<i64> {
        let row: (i64,) = sqlx::query_as(
            "SELECT COUNT(*) FROM query_feedback WHERE tenant_id = $1 AND rating <= 2",
        )
        .bind(tenant_id)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)?;
        Ok(row.0)
    }
}

impl std::fmt::Debug for FeedbackRepository {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FeedbackRepository").finish_non_exhaustive()
    }
}

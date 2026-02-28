//! Document repository for source_documents table.

use sqlx::PgPool;
use uuid::Uuid;

use crate::{DatabaseError, NewSourceDocument, Result, SourceDocument};

/// Repository for source document operations.
#[derive(Clone)]
pub struct DocumentRepository {
    pool: PgPool,
}

impl DocumentRepository {
    /// Create a new document repository.
    #[must_use]
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Insert a new document.
    ///
    /// # Errors
    ///
    /// Returns an error if the insert fails.
    pub async fn create(&self, doc: &NewSourceDocument) -> Result<SourceDocument> {
        let visibility_str = doc.visibility.to_string();

        sqlx::query_as::<_, SourceDocument>(
            r#"
            INSERT INTO source_documents (
                id, tenant_id, title, source_uri, source_type, mime_type,
                content_hash, file_size, visibility, allowed_groups, metadata,
                status, chunk_count
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, 'pending', 0)
            RETURNING *
            "#,
        )
        .bind(doc.id)
        .bind(&doc.tenant_id)
        .bind(&doc.title)
        .bind(&doc.source_uri)
        .bind(&doc.source_type)
        .bind(&doc.mime_type)
        .bind(&doc.content_hash)
        .bind(doc.file_size)
        .bind(visibility_str)
        .bind(&doc.allowed_groups)
        .bind(&doc.metadata)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find a document by ID.
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn find_by_id(&self, id: Uuid) -> Result<Option<SourceDocument>> {
        sqlx::query_as::<_, SourceDocument>("SELECT * FROM source_documents WHERE id = $1")
            .bind(id)
            .fetch_optional(&self.pool)
            .await
            .map_err(DatabaseError::from)
    }

    /// Find a document by ID within a tenant.
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn find_by_id_and_tenant(
        &self,
        id: Uuid,
        tenant_id: &str,
    ) -> Result<Option<SourceDocument>> {
        sqlx::query_as::<_, SourceDocument>(
            "SELECT * FROM source_documents WHERE id = $1 AND tenant_id = $2",
        )
        .bind(id)
        .bind(tenant_id)
        .fetch_optional(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find a document by content hash (for deduplication).
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn find_by_content_hash(
        &self,
        tenant_id: &str,
        content_hash: &str,
    ) -> Result<Option<SourceDocument>> {
        sqlx::query_as::<_, SourceDocument>(
            "SELECT * FROM source_documents WHERE tenant_id = $1 AND content_hash = $2",
        )
        .bind(tenant_id)
        .bind(content_hash)
        .fetch_optional(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find documents by source URI.
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn find_by_source_uri(
        &self,
        tenant_id: &str,
        source_uri: &str,
    ) -> Result<Vec<SourceDocument>> {
        sqlx::query_as::<_, SourceDocument>(
            "SELECT * FROM source_documents WHERE tenant_id = $1 AND source_uri = $2",
        )
        .bind(tenant_id)
        .bind(source_uri)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// List documents for a tenant with pagination.
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn list(
        &self,
        tenant_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<SourceDocument>> {
        sqlx::query_as::<_, SourceDocument>(
            r#"
            SELECT * FROM source_documents
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

    /// Count documents for a tenant.
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn count(&self, tenant_id: &str) -> Result<i64> {
        let row: (i64,) =
            sqlx::query_as("SELECT COUNT(*) FROM source_documents WHERE tenant_id = $1")
                .bind(tenant_id)
                .fetch_one(&self.pool)
                .await
                .map_err(DatabaseError::from)?;
        Ok(row.0)
    }

    /// Update document status.
    ///
    /// # Errors
    ///
    /// Returns an error if the update fails.
    pub async fn update_status(
        &self,
        id: Uuid,
        status: &str,
        error_message: Option<&str>,
    ) -> Result<()> {
        sqlx::query(
            r#"
            UPDATE source_documents
            SET status = $2, error_message = $3, updated_at = NOW()
            WHERE id = $1
            "#,
        )
        .bind(id)
        .bind(status)
        .bind(error_message)
        .execute(&self.pool)
        .await
        .map_err(DatabaseError::from)?;
        Ok(())
    }

    /// Update chunk count.
    ///
    /// # Errors
    ///
    /// Returns an error if the update fails.
    pub async fn update_chunk_count(&self, id: Uuid, count: i32) -> Result<()> {
        sqlx::query(
            r#"
            UPDATE source_documents
            SET chunk_count = $2, updated_at = NOW()
            WHERE id = $1
            "#,
        )
        .bind(id)
        .bind(count)
        .execute(&self.pool)
        .await
        .map_err(DatabaseError::from)?;
        Ok(())
    }

    /// Delete a document by ID.
    ///
    /// # Errors
    ///
    /// Returns an error if the delete fails.
    pub async fn delete(&self, id: Uuid) -> Result<bool> {
        let result = sqlx::query("DELETE FROM source_documents WHERE id = $1")
            .bind(id)
            .execute(&self.pool)
            .await
            .map_err(DatabaseError::from)?;
        Ok(result.rows_affected() > 0)
    }

    /// Delete a document by ID within a tenant.
    ///
    /// # Errors
    ///
    /// Returns an error if the delete fails.
    pub async fn delete_by_tenant(&self, id: Uuid, tenant_id: &str) -> Result<bool> {
        let result = sqlx::query("DELETE FROM source_documents WHERE id = $1 AND tenant_id = $2")
            .bind(id)
            .bind(tenant_id)
            .execute(&self.pool)
            .await
            .map_err(DatabaseError::from)?;
        Ok(result.rows_affected() > 0)
    }

    /// Find documents with status.
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn find_by_status(
        &self,
        tenant_id: &str,
        status: &str,
        limit: i64,
    ) -> Result<Vec<SourceDocument>> {
        sqlx::query_as::<_, SourceDocument>(
            r#"
            SELECT * FROM source_documents
            WHERE tenant_id = $1 AND status = $2
            ORDER BY created_at ASC
            LIMIT $3
            "#,
        )
        .bind(tenant_id)
        .bind(status)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }
}

impl std::fmt::Debug for DocumentRepository {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("DocumentRepository").finish_non_exhaustive()
    }
}

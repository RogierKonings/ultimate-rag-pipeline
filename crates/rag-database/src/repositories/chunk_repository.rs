//! Chunk repository for chunks table.

use sqlx::PgPool;
use uuid::Uuid;

use crate::{Chunk, DatabaseError, NewChunk, Result};

/// Repository for chunk operations.
#[derive(Clone)]
pub struct ChunkRepository {
    pool: PgPool,
}

impl ChunkRepository {
    /// Create a new chunk repository.
    #[must_use]
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }

    /// Insert a new chunk.
    ///
    /// # Errors
    ///
    /// Returns an error if the insert fails.
    pub async fn create(&self, chunk: &NewChunk) -> Result<Chunk> {
        sqlx::query_as::<_, Chunk>(
            r#"
            INSERT INTO chunks (
                id, document_id, tenant_id, chunk_index, content,
                token_count, char_count, embedding_model, embedding_generated,
                content_hash, start_offset, end_offset, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, false, $9, $10, $11, $12)
            RETURNING *
            "#,
        )
        .bind(chunk.id)
        .bind(chunk.document_id)
        .bind(&chunk.tenant_id)
        .bind(chunk.chunk_index)
        .bind(&chunk.content)
        .bind(chunk.token_count)
        .bind(chunk.char_count)
        .bind(&chunk.embedding_model)
        .bind(&chunk.content_hash)
        .bind(chunk.start_offset)
        .bind(chunk.end_offset)
        .bind(&chunk.metadata)
        .fetch_one(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Bulk insert chunks.
    ///
    /// # Errors
    ///
    /// Returns an error if the insert fails.
    pub async fn create_many(&self, chunks: &[NewChunk]) -> Result<Vec<Chunk>> {
        if chunks.is_empty() {
            return Ok(Vec::new());
        }

        // Use a transaction for bulk insert
        let mut tx = self
            .pool
            .begin()
            .await
            .map_err(|e| DatabaseError::Transaction(e.to_string()))?;

        let mut results = Vec::with_capacity(chunks.len());

        for chunk in chunks {
            let result = sqlx::query_as::<_, Chunk>(
                r#"
                INSERT INTO chunks (
                    id, document_id, tenant_id, chunk_index, content,
                    token_count, char_count, embedding_model, embedding_generated,
                    content_hash, start_offset, end_offset, metadata
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, false, $9, $10, $11, $12)
                RETURNING *
                "#,
            )
            .bind(chunk.id)
            .bind(chunk.document_id)
            .bind(&chunk.tenant_id)
            .bind(chunk.chunk_index)
            .bind(&chunk.content)
            .bind(chunk.token_count)
            .bind(chunk.char_count)
            .bind(&chunk.embedding_model)
            .bind(&chunk.content_hash)
            .bind(chunk.start_offset)
            .bind(chunk.end_offset)
            .bind(&chunk.metadata)
            .fetch_one(&mut *tx)
            .await
            .map_err(DatabaseError::from)?;

            results.push(result);
        }

        tx.commit()
            .await
            .map_err(|e| DatabaseError::Transaction(e.to_string()))?;

        Ok(results)
    }

    /// Find a chunk by ID.
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn find_by_id(&self, id: Uuid) -> Result<Option<Chunk>> {
        sqlx::query_as::<_, Chunk>("SELECT * FROM chunks WHERE id = $1")
            .bind(id)
            .fetch_optional(&self.pool)
            .await
            .map_err(DatabaseError::from)
    }

    /// Find chunks by document ID.
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn find_by_document_id(&self, document_id: Uuid) -> Result<Vec<Chunk>> {
        sqlx::query_as::<_, Chunk>(
            "SELECT * FROM chunks WHERE document_id = $1 ORDER BY chunk_index ASC",
        )
        .bind(document_id)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Find chunks by multiple IDs.
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn find_by_ids(&self, ids: &[Uuid]) -> Result<Vec<Chunk>> {
        if ids.is_empty() {
            return Ok(Vec::new());
        }

        sqlx::query_as::<_, Chunk>("SELECT * FROM chunks WHERE id = ANY($1)")
            .bind(ids)
            .fetch_all(&self.pool)
            .await
            .map_err(DatabaseError::from)
    }

    /// Find chunks by content hash (for deduplication).
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn find_by_content_hash(
        &self,
        tenant_id: &str,
        content_hash: &str,
    ) -> Result<Option<Chunk>> {
        sqlx::query_as::<_, Chunk>(
            "SELECT * FROM chunks WHERE tenant_id = $1 AND content_hash = $2 LIMIT 1",
        )
        .bind(tenant_id)
        .bind(content_hash)
        .fetch_optional(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Count chunks for a document.
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn count_by_document(&self, document_id: Uuid) -> Result<i64> {
        let row: (i64,) = sqlx::query_as("SELECT COUNT(*) FROM chunks WHERE document_id = $1")
            .bind(document_id)
            .fetch_one(&self.pool)
            .await
            .map_err(DatabaseError::from)?;
        Ok(row.0)
    }

    /// Mark chunk as having embedding generated.
    ///
    /// # Errors
    ///
    /// Returns an error if the update fails.
    pub async fn mark_embedding_generated(&self, id: Uuid, model: &str) -> Result<()> {
        sqlx::query(
            r#"
            UPDATE chunks
            SET embedding_generated = true, embedding_model = $2, updated_at = NOW()
            WHERE id = $1
            "#,
        )
        .bind(id)
        .bind(model)
        .execute(&self.pool)
        .await
        .map_err(DatabaseError::from)?;
        Ok(())
    }

    /// Mark multiple chunks as having embedding generated.
    ///
    /// # Errors
    ///
    /// Returns an error if the update fails.
    pub async fn mark_embeddings_generated(&self, ids: &[Uuid], model: &str) -> Result<()> {
        if ids.is_empty() {
            return Ok(());
        }

        sqlx::query(
            r#"
            UPDATE chunks
            SET embedding_generated = true, embedding_model = $2, updated_at = NOW()
            WHERE id = ANY($1)
            "#,
        )
        .bind(ids)
        .bind(model)
        .execute(&self.pool)
        .await
        .map_err(DatabaseError::from)?;
        Ok(())
    }

    /// Find chunks without embeddings.
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn find_without_embeddings(&self, tenant_id: &str, limit: i64) -> Result<Vec<Chunk>> {
        sqlx::query_as::<_, Chunk>(
            r#"
            SELECT * FROM chunks
            WHERE tenant_id = $1 AND embedding_generated = false
            ORDER BY created_at ASC
            LIMIT $2
            "#,
        )
        .bind(tenant_id)
        .bind(limit)
        .fetch_all(&self.pool)
        .await
        .map_err(DatabaseError::from)
    }

    /// Delete chunks by document ID.
    ///
    /// # Errors
    ///
    /// Returns an error if the delete fails.
    pub async fn delete_by_document(&self, document_id: Uuid) -> Result<u64> {
        let result = sqlx::query("DELETE FROM chunks WHERE document_id = $1")
            .bind(document_id)
            .execute(&self.pool)
            .await
            .map_err(DatabaseError::from)?;
        Ok(result.rows_affected())
    }

    /// Delete a chunk by ID.
    ///
    /// # Errors
    ///
    /// Returns an error if the delete fails.
    pub async fn delete(&self, id: Uuid) -> Result<bool> {
        let result = sqlx::query("DELETE FROM chunks WHERE id = $1")
            .bind(id)
            .execute(&self.pool)
            .await
            .map_err(DatabaseError::from)?;
        Ok(result.rows_affected() > 0)
    }
}

impl std::fmt::Debug for ChunkRepository {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ChunkRepository").finish_non_exhaustive()
    }
}

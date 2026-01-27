//! Index coordinator for parallel writes to multiple stores.

use crate::error::Result;
use super::models::{DocumentRecord, IndexedChunk, WriteResult};
use rag_database::DatabasePool;
use rag_search::SearchClient;
use rag_types::{DocumentId, TenantId};
use rag_vectorstore::{FilterBuilder, VectorStoreClient};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::time::Instant;
use tracing::{debug, instrument, warn};

/// Configuration for the index coordinator.
#[derive(Debug, Clone)]
pub struct IndexCoordinatorConfig {
    /// Qdrant collection name.
    pub qdrant_collection: String,
    /// `OpenSearch` index name.
    pub opensearch_index: String,
}

impl Default for IndexCoordinatorConfig {
    fn default() -> Self {
        Self {
            qdrant_collection: "documents".to_string(),
            opensearch_index: "documents".to_string(),
        }
    }
}

/// Coordinates parallel writes to vector, keyword, and metadata stores.
pub struct IndexCoordinator {
    qdrant: VectorStoreClient,
    opensearch: SearchClient,
    /// Database pool for `PostgreSQL` operations.
    ///
    /// TODO: Implement actual `PostgreSQL` writes in `write_to_database` and `delete_from_database`.
    #[allow(dead_code)]
    database: DatabasePool,
    config: IndexCoordinatorConfig,
}

impl IndexCoordinator {
    /// Create a new index coordinator.
    #[must_use]
    pub fn new(
        qdrant: VectorStoreClient,
        opensearch: SearchClient,
        database: DatabasePool,
        config: IndexCoordinatorConfig,
    ) -> Self {
        Self {
            qdrant,
            opensearch,
            database,
            config,
        }
    }

    /// Index document and chunks to all stores in parallel.
    ///
    /// # Errors
    ///
    /// This function currently always returns `Ok`. Individual store write failures
    /// are captured in the `WriteResult` values of the returned `HashMap`.
    #[instrument(skip(self, document, chunks), fields(document_id = %document.document_id))]
    pub async fn index_document(
        &self,
        document: DocumentRecord,
        chunks: Vec<IndexedChunk>,
    ) -> Result<HashMap<String, WriteResult>> {
        let mut results = HashMap::new();

        // Run all writes in parallel using tokio::join!
        let (qdrant_result, opensearch_result, db_result) = tokio::join!(
            self.write_to_qdrant(&chunks),
            self.write_to_opensearch(&document, &chunks),
            self.write_to_database(&document, &chunks),
        );

        results.insert("qdrant".to_string(), qdrant_result);
        results.insert("opensearch".to_string(), opensearch_result);
        results.insert("database".to_string(), db_result);

        // Check if any writes failed
        let all_success = results.values().all(|r| r.success);
        if !all_success {
            let errors: Vec<_> = results
                .iter()
                .filter(|(_, r)| !r.success)
                .map(|(store, r)| format!("{}: {:?}", store, r.errors))
                .collect();
            warn!(?errors, "Some stores failed during indexing");
        }

        Ok(results)
    }

    /// Delete document from all stores.
    ///
    /// # Errors
    ///
    /// This function currently always returns `Ok`. Individual store delete failures
    /// are captured in the `WriteResult` values of the returned `HashMap`.
    #[instrument(skip(self), fields(document_id = %document_id))]
    pub async fn delete_document(
        &self,
        document_id: DocumentId,
        tenant_id: TenantId,
    ) -> Result<HashMap<String, WriteResult>> {
        let mut results = HashMap::new();

        let (qdrant_result, opensearch_result, db_result) = tokio::join!(
            self.delete_from_qdrant(document_id, tenant_id),
            self.delete_from_opensearch(document_id, tenant_id),
            self.delete_from_database(document_id),
        );

        results.insert("qdrant".to_string(), qdrant_result);
        results.insert("opensearch".to_string(), opensearch_result);
        results.insert("database".to_string(), db_result);

        Ok(results)
    }

    /// Re-index document (delete then write).
    ///
    /// # Errors
    ///
    /// This function currently always returns `Ok`. Individual store operation failures
    /// are captured in the `WriteResult` values of the returned `HashMap`.
    pub async fn reindex_document(
        &self,
        document: DocumentRecord,
        chunks: Vec<IndexedChunk>,
    ) -> Result<HashMap<String, WriteResult>> {
        // First delete existing data
        let _ = self
            .delete_document(document.document_id, document.tenant_id)
            .await?;

        // Then write new data
        self.index_document(document, chunks).await
    }

    async fn write_to_qdrant(&self, chunks: &[IndexedChunk]) -> WriteResult {
        let start = Instant::now();

        if chunks.is_empty() {
            return WriteResult::success(0, start.elapsed());
        }

        // Convert chunks to Qdrant format
        let ids: Vec<String> = chunks.iter().map(|c| c.chunk_id.to_string()).collect();
        let vectors: Vec<Vec<f32>> = chunks.iter().map(|c| c.embedding.clone()).collect();
        let payloads: Vec<Value> = chunks
            .iter()
            .map(|c| {
                let mut payload = json!({
                    "chunk_id": c.chunk_id.to_string(),
                    "document_id": c.document_id.to_string(),
                    "tenant_id": c.tenant_id.to_string(),
                    "chunk_index": c.chunk_index,
                    "content": c.content,
                });

                // Merge additional metadata
                if let Some(payload_obj) = payload.as_object_mut() {
                    for (key, value) in &c.metadata {
                        payload_obj.insert(key.clone(), value.clone());
                    }
                }

                payload
            })
            .collect();

        let count = chunks.len();

        match self
            .qdrant
            .upsert(Some(&self.config.qdrant_collection), ids, vectors, payloads)
            .await
        {
            Ok(()) => {
                debug!(chunks = count, collection = %self.config.qdrant_collection, "Wrote to Qdrant");
                WriteResult::success(count, start.elapsed())
            }
            Err(e) => {
                warn!(error = %e, "Failed to write to Qdrant");
                WriteResult::failure(e.to_string(), start.elapsed())
            }
        }
    }

    async fn write_to_opensearch(
        &self,
        document: &DocumentRecord,
        chunks: &[IndexedChunk],
    ) -> WriteResult {
        let start = Instant::now();

        if chunks.is_empty() {
            return WriteResult::success(0, start.elapsed());
        }

        // Convert chunks to OpenSearch documents
        let documents: Vec<(String, Value)> = chunks
            .iter()
            .map(|c| {
                let doc = json!({
                    "chunk_id": c.chunk_id.to_string(),
                    "document_id": c.document_id.to_string(),
                    "tenant_id": c.tenant_id.to_string(),
                    "content": c.content,
                    "title": document.title,
                    "source_uri": document.source_id,
                    "chunk_index": c.chunk_index,
                    // Include additional metadata
                    "metadata": c.metadata,
                });

                (c.chunk_id.to_string(), doc)
            })
            .collect();

        match self
            .opensearch
            .bulk_index(&self.config.opensearch_index, documents)
            .await
        {
            Ok(indexed) => {
                debug!(
                    document_id = %document.document_id,
                    chunks = indexed,
                    index = %self.config.opensearch_index,
                    "Wrote to OpenSearch"
                );
                WriteResult::success(indexed, start.elapsed())
            }
            Err(e) => {
                warn!(error = %e, "Failed to write to OpenSearch");
                WriteResult::failure(e.to_string(), start.elapsed())
            }
        }
    }

    #[allow(clippy::unused_async)]
    async fn write_to_database(
        &self,
        document: &DocumentRecord,
        chunks: &[IndexedChunk],
    ) -> WriteResult {
        let start = Instant::now();

        // TODO: Implement actual PostgreSQL writes using sqlx
        // The actual implementation would:
        // 1. Upsert document metadata to source_documents table
        // 2. Upsert chunk records to chunks table
        //
        // Example query for documents:
        // INSERT INTO source_documents (id, tenant_id, source_uri, title, metadata)
        // VALUES ($1, $2, $3, $4, $5)
        // ON CONFLICT (id) DO UPDATE SET ...
        //
        // For now, return success as a placeholder.
        // This requires defining the exact table schema and sqlx queries.

        let chunk_count = chunks.len();
        debug!(
            document_id = %document.document_id,
            chunks = chunk_count,
            "Writing to PostgreSQL (placeholder)"
        );

        WriteResult::success(chunk_count + 1, start.elapsed()) // +1 for document record
    }

    async fn delete_from_qdrant(&self, document_id: DocumentId, _tenant_id: TenantId) -> WriteResult {
        let start = Instant::now();

        // Create filter to match all chunks for this document
        let filter = FilterBuilder::new()
            .document(document_id.to_string())
            .build();

        match self
            .qdrant
            .delete_by_filter(Some(&self.config.qdrant_collection), filter)
            .await
        {
            Ok(()) => {
                debug!(document_id = %document_id, "Deleted from Qdrant");
                WriteResult::success(0, start.elapsed())
            }
            Err(e) => {
                warn!(error = %e, "Failed to delete from Qdrant");
                WriteResult::failure(e.to_string(), start.elapsed())
            }
        }
    }

    async fn delete_from_opensearch(
        &self,
        document_id: DocumentId,
        _tenant_id: TenantId,
    ) -> WriteResult {
        let start = Instant::now();

        // Create query to match all chunks for this document
        let query = json!({
            "term": {
                "document_id": document_id.to_string()
            }
        });

        match self
            .opensearch
            .delete_by_query(&self.config.opensearch_index, query)
            .await
        {
            Ok(deleted) => {
                debug!(document_id = %document_id, deleted = deleted, "Deleted from OpenSearch");
                #[allow(clippy::cast_possible_truncation)]
                WriteResult::success(deleted as usize, start.elapsed())
            }
            Err(e) => {
                warn!(error = %e, "Failed to delete from OpenSearch");
                WriteResult::failure(e.to_string(), start.elapsed())
            }
        }
    }

    #[allow(clippy::unused_async)]
    async fn delete_from_database(&self, document_id: DocumentId) -> WriteResult {
        let start = Instant::now();

        // TODO: Implement actual PostgreSQL deletes using sqlx
        // The actual implementation would:
        // 1. Delete chunks associated with this document
        // 2. Delete the document record
        //
        // Example:
        // DELETE FROM chunks WHERE document_id = $1;
        // DELETE FROM source_documents WHERE id = $1;
        //
        // For now, return success as a placeholder.

        debug!(document_id = %document_id, "Deleting from PostgreSQL (placeholder)");
        WriteResult::success(0, start.elapsed())
    }
}

impl std::fmt::Debug for IndexCoordinator {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("IndexCoordinator")
            .field("qdrant_collection", &self.config.qdrant_collection)
            .field("opensearch_index", &self.config.opensearch_index)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_config_default() {
        let config = IndexCoordinatorConfig::default();
        assert_eq!(config.qdrant_collection, "documents");
        assert_eq!(config.opensearch_index, "documents");
    }
}

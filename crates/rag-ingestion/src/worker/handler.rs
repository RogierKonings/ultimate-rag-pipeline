//! Ingestion job handler for processing documents.

use async_trait::async_trait;
use rag_database::{ChunkRepository, DatabasePool, DocumentRepository};
use rag_types::{ChunkId, DocumentId, TenantId};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;
use tracing::{error, info, instrument, warn};
use uuid::Uuid;

use crate::api::jobs::JobTracker;
use crate::api::types::JobStatus;
use crate::chunking::{ChunkingConfig, ChunkingStrategy, RecursiveCharacterSplitter};
use crate::connectors::{Connector, S3Config, S3Connector};
use crate::embedding::EmbeddingClient;
use crate::indexing::{DocumentRecord, IndexCoordinator, IndexedChunk};
use crate::parsers::{HtmlParser, MarkdownParser, Parser, PdfParser};

use super::job::Job;
use super::pool::JobHandler;

/// Handler for ingestion jobs.
pub struct IngestionJobHandler {
    /// In-memory job tracker for status updates.
    job_tracker: Arc<JobTracker>,
    /// Embedding client for generating vectors.
    embedding_client: Option<Arc<EmbeddingClient>>,
    /// Index coordinator for writing to stores.
    index_coordinator: Option<Arc<IndexCoordinator>>,
    /// Database pool for re-embedding workflows.
    database: Option<DatabasePool>,
}

impl IngestionJobHandler {
    /// Create a new ingestion job handler.
    #[must_use]
    pub fn new(
        job_tracker: Arc<JobTracker>,
        embedding_client: Option<Arc<EmbeddingClient>>,
        index_coordinator: Option<Arc<IndexCoordinator>>,
        database: Option<DatabasePool>,
    ) -> Self {
        Self {
            job_tracker,
            embedding_client,
            index_coordinator,
            database,
        }
    }

    fn extract_tracker_job_id(&self, payload: &Value) -> Result<Uuid, String> {
        payload
            .get("tracker_job_id")
            .and_then(|v| v.as_str())
            .and_then(|s| Uuid::parse_str(s).ok())
            .ok_or_else(|| "Missing or invalid tracker_job_id".to_string())
    }

    fn infer_storage_type(&self, source_id: &str) -> Option<&'static str> {
        if source_id.starts_with("uploads/")
            || source_id.starts_with("videos/")
            || source_id.starts_with("s3://")
        {
            Some("s3")
        } else {
            None
        }
    }

    fn json_object_to_map(value: Option<&Value>) -> HashMap<String, Value> {
        value
            .and_then(Value::as_object)
            .map(|obj| {
                obj.iter()
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect::<HashMap<String, Value>>()
            })
            .unwrap_or_default()
    }

    /// Process a single document ingestion job.
    #[instrument(skip(self, job), fields(job_id = %job.id, job_type = %job.job_type))]
    async fn process_ingest_single(&self, job: &Job) -> Result<Value, String> {
        let payload = &job.payload;

        // Extract tracker job ID for status updates
        let tracker_job_id = self.extract_tracker_job_id(payload)?;

        // Mark job as started
        self.job_tracker
            .update_status(&tracker_job_id, JobStatus::Started);

        // Extract source information - try source_id first, then fall back to source_config.path or keys[0]
        let source_id = payload
            .get("source_id")
            .and_then(|v| v.as_str())
            .or_else(|| payload.get("source_uri").and_then(|v| v.as_str()))
            .or_else(|| {
                payload
                    .get("source_config")
                    .and_then(|c| c.get("path"))
                    .and_then(|v| v.as_str())
            })
            .or_else(|| {
                // For batch jobs, try to get the first key from the keys array
                payload
                    .get("source_config")
                    .and_then(|c| c.get("keys"))
                    .and_then(|v| v.as_array())
                    .and_then(|arr| arr.first())
                    .and_then(|v| v.as_str())
            })
            .ok_or("Missing source_id, source_uri, source_config.path, or source_config.keys")?;

        let source_type = payload
            .get("source_type")
            .and_then(|v| v.as_str())
            .unwrap_or("file");

        // Check if this is an S3 source
        let storage_type = payload
            .get("source_config")
            .and_then(|c| c.get("storage_type"))
            .and_then(|v| v.as_str())
            .or_else(|| self.infer_storage_type(source_id));

        let tenant_id = &job.tenant_id;

        info!(
            source_id = source_id,
            source_type = source_type,
            storage_type = storage_type,
            tenant_id = tenant_id,
            "Processing document"
        );

        // Update progress: parsing
        self.job_tracker
            .update_progress(&tracker_job_id, 0, 4, "parsing");

        // Read and parse document content
        let content = if storage_type == Some("s3") {
            self.read_s3_document(source_id, payload).await?
        } else {
            self.read_local_document(source_id).await?
        };

        // Update progress: chunking
        self.job_tracker
            .update_progress(&tracker_job_id, 1, 4, "chunking");

        // Chunk the content. Reindex payloads may provide settings at the top level.
        let chunk_size = payload
            .get("chunk_size")
            .and_then(|v| v.as_u64())
            .or_else(|| {
                payload
                    .get("processing")
                    .and_then(|p| p.get("chunk_size"))
                    .and_then(|v| v.as_u64())
            })
            .unwrap_or(512) as u32;

        let chunk_overlap = payload
            .get("chunk_overlap")
            .and_then(|v| v.as_u64())
            .or_else(|| {
                payload
                    .get("processing")
                    .and_then(|p| p.get("chunk_overlap"))
                    .and_then(|v| v.as_u64())
            })
            .unwrap_or(50) as u32;

        let chunks = self.chunk_content(&content, chunk_size, chunk_overlap)?;
        let chunk_count = chunks.len();

        info!(chunks = chunk_count, "Document chunked");

        // Update progress: embedding
        self.job_tracker
            .update_progress(&tracker_job_id, 2, 4, "embedding");

        // Generate embeddings if client is available
        let embeddings = if let Some(ref client) = self.embedding_client {
            let texts: Vec<String> = chunks.iter().map(|c| c.clone()).collect();
            match client.embed_batch(&texts).await {
                Ok((embeddings, _tokens)) => {
                    info!(embeddings = embeddings.len(), "Embeddings generated");
                    Some(embeddings)
                }
                Err(e) => {
                    error!(error = %e, "Failed to generate embeddings");
                    return Err(format!("Embedding failed: {e}"));
                }
            }
        } else {
            warn!("No embedding client configured - skipping embeddings");
            None
        };

        // Update progress: indexing
        self.job_tracker
            .update_progress(&tracker_job_id, 3, 4, "indexing");

        // Index to stores if coordinator is available
        if let Some(ref coordinator) = self.index_coordinator {
            let document_uuid = payload
                .get("document_id")
                .and_then(|v| v.as_str())
                .and_then(|s| Uuid::parse_str(s).ok())
                .unwrap_or_else(Uuid::new_v4);
            let document_id = DocumentId::from_uuid(document_uuid);

            // Parse tenant_id as UUID, or generate a new one
            let tenant_uuid = Uuid::parse_str(tenant_id).unwrap_or_else(|_| Uuid::new_v4());
            let tenant_id_typed = TenantId::from_uuid(tenant_uuid);

            let document_title = payload
                .get("title")
                .and_then(|v| v.as_str())
                .map(ToOwned::to_owned)
                .or_else(|| Some(source_id.to_string()));

            let document = DocumentRecord {
                document_id,
                tenant_id: tenant_id_typed,
                source_id: source_id.to_string(),
                title: document_title,
                metadata: Self::json_object_to_map(payload.get("metadata")),
            };

            let indexed_chunks: Vec<IndexedChunk> = chunks
                .iter()
                .enumerate()
                .map(|(i, content)| {
                    let embedding = embeddings
                        .as_ref()
                        .and_then(|e| e.get(i).cloned())
                        .unwrap_or_default();

                    IndexedChunk {
                        chunk_id: ChunkId::new(),
                        document_id,
                        tenant_id: tenant_id_typed,
                        content: content.clone(),
                        chunk_index: i as u32,
                        embedding,
                        metadata: Self::json_object_to_map(payload.get("metadata")),
                    }
                })
                .collect();

            let indexing_result = if job.job_type == "reindex_document" {
                coordinator.reindex_document(document, indexed_chunks).await
            } else {
                coordinator.index_document(document, indexed_chunks).await
            };

            match indexing_result {
                Ok(results) => {
                    let all_success = results.values().all(|r| r.success);
                    if !all_success {
                        let errors: Vec<_> = results
                            .iter()
                            .filter(|(_, r)| !r.success)
                            .map(|(store, r)| format!("{}: {:?}", store, r.errors))
                            .collect();
                        self.job_tracker
                            .add_error(&tracker_job_id, errors.join(", "));
                    }
                    info!(?results, "Document indexed");
                }
                Err(e) => {
                    error!(error = %e, "Failed to index document");
                    return Err(format!("Indexing failed: {e}"));
                }
            }
        } else {
            warn!("No index coordinator configured - skipping indexing");
        }

        // Mark job as complete
        self.job_tracker
            .update_counts(&tracker_job_id, 1, chunk_count as u32);
        self.job_tracker.complete_job(&tracker_job_id);

        info!(
            tracker_job_id = %tracker_job_id,
            documents = 1,
            chunks = chunk_count,
            "Ingestion completed"
        );

        Ok(json!({
            "status": "completed",
            "documents_processed": 1,
            "chunks_created": chunk_count
        }))
    }

    /// Process a re-embedding job for existing indexed documents.
    #[instrument(skip(self, job), fields(job_id = %job.id, job_type = %job.job_type))]
    async fn process_reembed(&self, job: &Job) -> Result<Value, String> {
        let payload = &job.payload;
        let tracker_job_id = self.extract_tracker_job_id(payload)?;

        self.job_tracker
            .update_status(&tracker_job_id, JobStatus::Started);

        let database = self
            .database
            .as_ref()
            .ok_or("Database not configured for reembed jobs")?;
        let embedding_client = self
            .embedding_client
            .as_ref()
            .ok_or("Embedding client not configured for reembed jobs")?;
        let coordinator = self
            .index_coordinator
            .as_ref()
            .ok_or("Index coordinator not configured for reembed jobs")?;

        let tenant_id = payload
            .get("target_scope")
            .and_then(|scope| scope.get("tenant_id"))
            .and_then(|v| v.as_str())
            .unwrap_or(&job.tenant_id)
            .to_string();

        let source_type_filters: Vec<String> = payload
            .get("target_scope")
            .and_then(|scope| scope.get("source_types"))
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|value| value.as_str().map(ToOwned::to_owned))
                    .collect()
            })
            .unwrap_or_default();

        let mut requested_document_ids: Vec<Uuid> = payload
            .get("target_scope")
            .and_then(|scope| scope.get("document_ids"))
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|value| value.as_str())
                    .filter_map(|value| Uuid::parse_str(value).ok())
                    .collect()
            })
            .unwrap_or_default();

        let batch_size = payload
            .get("batch_size")
            .and_then(|v| v.as_u64())
            .map(|v| v as usize)
            .unwrap_or(100)
            .max(1);

        let embedding_model = payload
            .get("embedding_model")
            .and_then(|v| v.as_str())
            .unwrap_or("unknown");

        let document_repo = DocumentRepository::new(database.inner().clone());
        let chunk_repo = ChunkRepository::new(database.inner().clone());

        if requested_document_ids.is_empty() {
            // Fallback scope: reembed tenant documents, optionally filtered by source type.
            let docs = document_repo
                .list(&tenant_id, 10_000, 0)
                .await
                .map_err(|e| format!("Failed to list documents for reembed: {e}"))?;

            requested_document_ids = docs
                .into_iter()
                .filter(|doc| {
                    source_type_filters.is_empty() || source_type_filters.contains(&doc.source_type)
                })
                .map(|doc| doc.id)
                .collect();
        }

        if requested_document_ids.is_empty() {
            self.job_tracker.complete_job(&tracker_job_id);
            return Ok(json!({
                "status": "completed",
                "documents_processed": 0,
                "chunks_created": 0,
                "message": "No documents matched reembed scope"
            }));
        }

        let total_docs = requested_document_ids.len() as u32;
        self.job_tracker
            .update_progress(&tracker_job_id, 0, total_docs, "reembedding");

        let tenant_uuid = Uuid::parse_str(&tenant_id).unwrap_or_else(|_| Uuid::new_v4());
        let tenant_typed = TenantId::from_uuid(tenant_uuid);

        let mut processed_docs = 0u32;
        let mut total_chunks = 0u32;

        for (index, document_uuid) in requested_document_ids.iter().enumerate() {
            let document = match document_repo
                .find_by_id_and_tenant(*document_uuid, &tenant_id)
                .await
            {
                Ok(Some(doc)) => doc,
                Ok(None) => {
                    self.job_tracker.add_error(
                        &tracker_job_id,
                        format!(
                            "Document {} not found for tenant {}",
                            document_uuid, tenant_id
                        ),
                    );
                    self.job_tracker.update_progress(
                        &tracker_job_id,
                        (index + 1) as u32,
                        total_docs,
                        "reembedding",
                    );
                    continue;
                }
                Err(e) => {
                    self.job_tracker.add_error(
                        &tracker_job_id,
                        format!("Failed to fetch document {document_uuid}: {e}"),
                    );
                    self.job_tracker.update_progress(
                        &tracker_job_id,
                        (index + 1) as u32,
                        total_docs,
                        "reembedding",
                    );
                    continue;
                }
            };

            let chunks = match chunk_repo.find_by_document_id(*document_uuid).await {
                Ok(chunks) => chunks,
                Err(e) => {
                    self.job_tracker.add_error(
                        &tracker_job_id,
                        format!("Failed to load chunks for {document_uuid}: {e}"),
                    );
                    self.job_tracker.update_progress(
                        &tracker_job_id,
                        (index + 1) as u32,
                        total_docs,
                        "reembedding",
                    );
                    continue;
                }
            };

            if chunks.is_empty() {
                self.job_tracker.add_error(
                    &tracker_job_id,
                    format!("Document {} has no chunks to reembed", document_uuid),
                );
                self.job_tracker.update_progress(
                    &tracker_job_id,
                    (index + 1) as u32,
                    total_docs,
                    "reembedding",
                );
                continue;
            }

            let texts: Vec<String> = chunks.iter().map(|chunk| chunk.content.clone()).collect();
            let mut embeddings: Vec<Vec<f32>> = Vec::with_capacity(texts.len());

            for text_batch in texts.chunks(batch_size) {
                let batch_texts: Vec<String> = text_batch.to_vec();
                match embedding_client.embed_batch(&batch_texts).await {
                    Ok((batch_embeddings, _tokens)) => {
                        if batch_embeddings.len() != batch_texts.len() {
                            self.job_tracker.add_error(
                                &tracker_job_id,
                                format!(
                                    "Embedding size mismatch for {}: expected {}, got {}",
                                    document_uuid,
                                    batch_texts.len(),
                                    batch_embeddings.len()
                                ),
                            );
                            embeddings.clear();
                            break;
                        }
                        embeddings.extend(batch_embeddings);
                    }
                    Err(e) => {
                        self.job_tracker.add_error(
                            &tracker_job_id,
                            format!("Embedding failed for {}: {}", document_uuid, e),
                        );
                        embeddings.clear();
                        break;
                    }
                }
            }

            if embeddings.len() != chunks.len() {
                self.job_tracker.update_progress(
                    &tracker_job_id,
                    (index + 1) as u32,
                    total_docs,
                    "reembedding",
                );
                continue;
            }

            let document_id_typed = DocumentId::from_uuid(*document_uuid);

            let indexed_chunks: Vec<IndexedChunk> = chunks
                .iter()
                .zip(embeddings.into_iter())
                .map(|(chunk, embedding)| IndexedChunk {
                    chunk_id: ChunkId::from_uuid(chunk.id),
                    document_id: document_id_typed,
                    tenant_id: tenant_typed,
                    content: chunk.content.clone(),
                    embedding,
                    chunk_index: u32::try_from(chunk.chunk_index).unwrap_or(0),
                    metadata: Self::json_object_to_map(Some(&chunk.metadata)),
                })
                .collect();

            let reindex_results = coordinator
                .reindex_document(
                    DocumentRecord {
                        document_id: document_id_typed,
                        tenant_id: tenant_typed,
                        source_id: document.source_uri.clone(),
                        title: document.title.clone(),
                        metadata: Self::json_object_to_map(Some(&document.metadata)),
                    },
                    indexed_chunks,
                )
                .await;

            match reindex_results {
                Ok(store_results) => {
                    if !store_results.values().all(|r| r.success) {
                        let store_errors: Vec<String> = store_results
                            .iter()
                            .filter(|(_, r)| !r.success)
                            .map(|(store, result)| format!("{}: {:?}", store, result.errors))
                            .collect();
                        self.job_tracker
                            .add_error(&tracker_job_id, store_errors.join(", "));
                    }
                }
                Err(e) => {
                    self.job_tracker.add_error(
                        &tracker_job_id,
                        format!("Reindex failed for {}: {}", document_uuid, e),
                    );
                    self.job_tracker.update_progress(
                        &tracker_job_id,
                        (index + 1) as u32,
                        total_docs,
                        "reembedding",
                    );
                    continue;
                }
            }

            let chunk_ids: Vec<Uuid> = chunks.iter().map(|chunk| chunk.id).collect();
            if let Err(e) = chunk_repo
                .mark_embeddings_generated(&chunk_ids, embedding_model)
                .await
            {
                self.job_tracker.add_error(
                    &tracker_job_id,
                    format!(
                        "Failed to mark embeddings generated for {}: {}",
                        document_uuid, e
                    ),
                );
            }

            if let Err(e) = document_repo
                .update_status(*document_uuid, "completed", None)
                .await
            {
                self.job_tracker.add_error(
                    &tracker_job_id,
                    format!("Failed to mark document {} completed: {}", document_uuid, e),
                );
            }

            processed_docs += 1;
            total_chunks += chunks.len() as u32;
            self.job_tracker.update_progress(
                &tracker_job_id,
                (index + 1) as u32,
                total_docs,
                "reembedding",
            );
        }

        if processed_docs == 0 {
            return Err("Reembed job failed: no documents were successfully processed".to_string());
        }

        self.job_tracker
            .update_counts(&tracker_job_id, processed_docs, total_chunks);
        self.job_tracker.complete_job(&tracker_job_id);

        Ok(json!({
            "status": "completed",
            "documents_processed": processed_docs,
            "chunks_created": total_chunks
        }))
    }

    /// Read document from S3/MinIO storage.
    async fn read_s3_document(&self, source_id: &str, payload: &Value) -> Result<String, String> {
        let source_config = payload.get("source_config");

        // Extract S3 connection details (support both naming conventions)
        // First try source_config, then fall back to environment variable, then default
        let s3_endpoint = source_config
            .and_then(|cfg| cfg.get("s3_endpoint"))
            .and_then(|v| v.as_str())
            .map(ToOwned::to_owned)
            .or_else(|| std::env::var("S3_ENDPOINT").ok())
            .unwrap_or_else(|| "http://minio:9000".to_string());

        let s3_bucket = source_config
            .and_then(|cfg| cfg.get("s3_bucket"))
            .and_then(|v| v.as_str())
            .map(ToOwned::to_owned)
            .or_else(|| {
                source_config
                    .and_then(|cfg| cfg.get("bucket"))
                    .and_then(|v| v.as_str())
                    .map(ToOwned::to_owned)
            })
            .or_else(|| std::env::var("S3_BUCKET").ok())
            .unwrap_or_else(|| "rag-documents".to_string());

        info!(
            endpoint = s3_endpoint,
            bucket = s3_bucket,
            key = source_id,
            "Connecting to S3"
        );

        // Create S3 connector
        let config = S3Config::new(&s3_bucket).with_endpoint(s3_endpoint);

        let mut connector = S3Connector::new(config);

        // Connect to S3
        connector
            .connect()
            .await
            .map_err(|e| format!("Failed to connect to S3: {e}"))?;

        // Fetch the document
        let raw_doc = connector
            .fetch_document(source_id)
            .await
            .map_err(|e| format!("Failed to fetch document from S3: {e}"))?;

        let bytes = raw_doc.content;

        // Determine parser based on file extension
        let extension = source_id.rsplit('.').next().unwrap_or("").to_lowercase();

        self.parse_bytes(&bytes, &extension)
    }

    /// Read document from local filesystem.
    async fn read_local_document(&self, source_id: &str) -> Result<String, String> {
        let path = std::path::Path::new(source_id);

        if !path.exists() {
            return Err(format!("File not found: {source_id}"));
        }

        // Read file as bytes
        let bytes = std::fs::read(path).map_err(|e| format!("Failed to read file: {e}"))?;

        // Determine parser based on extension
        let extension = path
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_lowercase();

        self.parse_bytes(&bytes, &extension)
    }

    /// Parse bytes into text based on file extension.
    fn parse_bytes(&self, bytes: &[u8], extension: &str) -> Result<String, String> {
        match extension {
            "pdf" => {
                let parser = PdfParser::default();
                match parser.parse(bytes, None) {
                    Ok(doc) => Ok(doc.text),
                    Err(e) => Err(format!("Failed to parse PDF: {e}")),
                }
            }
            "html" | "htm" => {
                let parser = HtmlParser::default();
                match parser.parse(bytes, None) {
                    Ok(doc) => Ok(doc.text),
                    Err(e) => Err(format!("Failed to parse HTML: {e}")),
                }
            }
            "md" | "markdown" => {
                let parser = MarkdownParser::default();
                match parser.parse(bytes, None) {
                    Ok(doc) => Ok(doc.text),
                    Err(e) => Err(format!("Failed to parse Markdown: {e}")),
                }
            }
            "txt" | "" | "docx" => {
                // For plain text and DOCX (treated as plain text for now), convert bytes to string
                String::from_utf8(bytes.to_vec())
                    .map_err(|e| format!("Failed to decode file as UTF-8: {e}"))
            }
            _ => {
                // Try to read as plain text
                String::from_utf8(bytes.to_vec())
                    .map_err(|e| format!("Failed to decode file as UTF-8: {e}"))
            }
        }
    }

    /// Chunk content using the configured strategy.
    fn chunk_content(
        &self,
        content: &str,
        chunk_size: u32,
        chunk_overlap: u32,
    ) -> Result<Vec<String>, String> {
        let config = ChunkingConfig {
            target_tokens: chunk_size.saturating_sub(100),
            max_tokens: chunk_size,
            chunk_overlap,
            min_chunk_size: 50,
            tokenizer: "cl100k_base".to_string(),
        };

        let splitter = RecursiveCharacterSplitter::new(config)
            .map_err(|e| format!("Failed to create splitter: {e}"))?;
        let document_id = rag_types::DocumentId::new();

        match splitter.chunk(content, document_id, None) {
            Ok(chunks) => Ok(chunks.into_iter().map(|c| c.content).collect()),
            Err(e) => Err(format!("Chunking failed: {e}")),
        }
    }
}

#[async_trait]
impl JobHandler for IngestionJobHandler {
    #[instrument(skip(self, job), fields(job_id = %job.id, job_type = %job.job_type))]
    async fn handle(&self, job: &Job) -> Result<Value, String> {
        match job.job_type.as_str() {
            "ingest_single" | "ingest_batch" | "sync" | "reindex_document" => {
                self.process_ingest_single(job).await
            }
            "reembed" => self.process_reembed(job).await,
            _ => Err(format!("Unknown job type: {}", job.job_type)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn test_handler_creation() {
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(tracker, None, None, None);
        assert!(handler.embedding_client.is_none());
        assert!(handler.index_coordinator.is_none());
        assert!(handler.database.is_none());
    }

    #[test]
    fn test_infer_storage_type() {
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(tracker, None, None, None);

        assert_eq!(
            handler.infer_storage_type("uploads/tenant/doc.pdf"),
            Some("s3")
        );
        assert_eq!(
            handler.infer_storage_type("videos/tenant/file.mp4"),
            Some("s3")
        );
        assert_eq!(handler.infer_storage_type("/tmp/doc.txt"), None);
    }

    #[test]
    fn test_json_object_to_map() {
        let payload = json!({
            "a": 1,
            "b": "two"
        });

        let map = IngestionJobHandler::json_object_to_map(Some(&payload));
        assert_eq!(map.get("a").and_then(Value::as_i64), Some(1));
        assert_eq!(map.get("b").and_then(Value::as_str), Some("two"));
    }

    #[tokio::test]
    async fn test_handle_sync_job_supported() {
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(Arc::clone(&tracker), None, None, None);
        let tracker_job_id = tracker.create_job("tenant-1".to_string());

        let file_path = std::env::temp_dir().join(format!("ingestion-sync-{}.txt", Uuid::new_v4()));
        fs::write(&file_path, "hello sync job").unwrap();

        let job = Job::new(
            "sync",
            "tenant-1",
            json!({
                "tracker_job_id": tracker_job_id.to_string(),
                "source_config": {
                    "path": file_path.to_string_lossy(),
                }
            }),
        );

        let result = handler.handle(&job).await;
        fs::remove_file(&file_path).ok();
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_handle_reindex_job_supported() {
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(Arc::clone(&tracker), None, None, None);
        let tracker_job_id = tracker.create_job("tenant-1".to_string());

        let file_path =
            std::env::temp_dir().join(format!("ingestion-reindex-{}.txt", Uuid::new_v4()));
        fs::write(&file_path, "hello reindex job").unwrap();

        let job = Job::new(
            "reindex_document",
            "tenant-1",
            json!({
                "tracker_job_id": tracker_job_id.to_string(),
                "document_id": Uuid::new_v4().to_string(),
                "source_uri": file_path.to_string_lossy(),
            }),
        );

        let result = handler.handle(&job).await;
        fs::remove_file(&file_path).ok();
        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_handle_reembed_job_requires_dependencies() {
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(Arc::clone(&tracker), None, None, None);
        let tracker_job_id = tracker.create_job("tenant-1".to_string());

        let job = Job::new(
            "reembed",
            "tenant-1",
            json!({
                "tracker_job_id": tracker_job_id.to_string(),
                "embedding_model": "all-MiniLM-L6-v2",
                "target_scope": {
                    "tenant_id": "tenant-1",
                    "document_ids": [Uuid::new_v4().to_string()]
                }
            }),
        );

        let result = handler.handle(&job).await;
        assert!(result.is_err());
    }
}

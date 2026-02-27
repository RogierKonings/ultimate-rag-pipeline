//! Ingestion job handler for processing documents.

use async_trait::async_trait;
use rag_database::{ChunkRepository, DatabasePool, DocumentRepository};
use rag_types::{ChunkId, ChunkingStrategy as ChunkingStrategyType, DocumentId, TenantId};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;
use tracing::{error, info, instrument, warn};
use uuid::Uuid;

use crate::api::jobs::JobTracker;
use crate::api::types::JobStatus;
use crate::chunking::{
    Chunk as TextChunk, ChunkingConfig, ChunkingStrategy, HierarchicalChunker,
    RecursiveCharacterSplitter, SemanticChunker, SemanticChunkerConfig,
};
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

    #[allow(clippy::unused_self)] // kept as method for handler API consistency
    fn extract_tracker_job_id(&self, payload: &Value) -> Result<Uuid, String> {
        payload
            .get("tracker_job_id")
            .and_then(|v| v.as_str())
            .and_then(|s| Uuid::parse_str(s).ok())
            .ok_or_else(|| "Missing or invalid tracker_job_id".to_string())
    }

    /// Extract `document_id` from a job payload, if present and valid.
    #[allow(clippy::unused_self)] // kept as method for handler API consistency
    fn extract_document_id(&self, payload: &Value) -> Option<Uuid> {
        payload
            .get("document_id")
            .and_then(|v| v.as_str())
            .and_then(|s| Uuid::parse_str(s).ok())
    }

    #[allow(clippy::unused_self)] // kept as method for handler API consistency
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
    #[allow(clippy::too_many_lines)]
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
        #[allow(clippy::cast_possible_truncation)] // chunk size fits in u32
        let chunk_size = payload
            .get("chunk_size")
            .and_then(serde_json::Value::as_u64)
            .or_else(|| {
                payload
                    .get("processing")
                    .and_then(|p| p.get("chunk_size"))
                    .and_then(serde_json::Value::as_u64)
            })
            .unwrap_or(512) as u32;

        #[allow(clippy::cast_possible_truncation)] // chunk overlap fits in u32
        let chunk_overlap = payload
            .get("chunk_overlap")
            .and_then(serde_json::Value::as_u64)
            .or_else(|| {
                payload
                    .get("processing")
                    .and_then(|p| p.get("chunk_overlap"))
                    .and_then(serde_json::Value::as_u64)
            })
            .unwrap_or(50) as u32;

        let chunking_strategy = self.extract_chunking_strategy(payload);
        let chunks = self.chunk_content(&content, chunking_strategy, chunk_size, chunk_overlap)?;
        let chunk_count = chunks.len();

        info!(chunks = chunk_count, strategy = ?chunking_strategy, "Document chunked");

        // Update progress: embedding
        self.job_tracker
            .update_progress(&tracker_job_id, 2, 4, "embedding");

        // Generate embeddings if client is available
        let embeddings = if let Some(ref client) = self.embedding_client {
            let texts: Vec<String> = chunks.iter().map(|c| c.content.clone()).collect();
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

            let base_chunk_metadata = Self::json_object_to_map(payload.get("metadata"));
            let indexed_chunks: Vec<IndexedChunk> = chunks
                .iter()
                .enumerate()
                .map(|(i, chunk)| {
                    let embedding = embeddings
                        .as_ref()
                        .and_then(|e| e.get(i).cloned())
                        .unwrap_or_default();

                    let mut metadata = base_chunk_metadata.clone();
                    metadata.insert(
                        "chunking_strategy".to_string(),
                        Value::String(
                            match chunking_strategy {
                                ChunkingStrategyType::Recursive => "recursive",
                                ChunkingStrategyType::Semantic => "semantic",
                                ChunkingStrategyType::Hierarchical => "hierarchical",
                            }
                            .to_string(),
                        ),
                    );
                    metadata.insert(
                        "token_count".to_string(),
                        Value::Number(serde_json::Number::from(chunk.token_count)),
                    );
                    #[allow(clippy::cast_possible_truncation)] // start offsets fit in u64
                    metadata.insert(
                        "start_char".to_string(),
                        Value::Number(serde_json::Number::from(chunk.start_char as u64)),
                    );
                    #[allow(clippy::cast_possible_truncation)] // end offsets fit in u64
                    metadata.insert(
                        "end_char".to_string(),
                        Value::Number(serde_json::Number::from(chunk.end_char as u64)),
                    );

                    IndexedChunk {
                        chunk_id: ChunkId::new(),
                        document_id,
                        tenant_id: tenant_id_typed,
                        content: chunk.content.clone(),
                        chunk_index: chunk.chunk_index,
                        embedding,
                        metadata,
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
        #[allow(clippy::cast_possible_truncation)] // chunk count fits in u32
        let chunk_count_u32 = chunk_count as u32;
        self.job_tracker
            .update_counts(&tracker_job_id, 1, chunk_count_u32);
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
    #[allow(clippy::too_many_lines)]
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

        #[allow(clippy::cast_possible_truncation)] // batch size fits in usize
        let batch_size = payload
            .get("batch_size")
            .and_then(serde_json::Value::as_u64)
            .map_or(100, |v| v as usize)
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

        #[allow(clippy::cast_possible_truncation)] // document count fits in u32
        let total_docs = requested_document_ids.len() as u32;
        self.job_tracker
            .update_progress(&tracker_job_id, 0, total_docs, "reembedding");

        let tenant_uuid = Uuid::parse_str(&tenant_id).unwrap_or_else(|_| Uuid::new_v4());
        let tenant_typed = TenantId::from_uuid(tenant_uuid);

        let mut processed_docs = 0u32;
        let mut total_chunks = 0u32;

        for (index, document_uuid) in requested_document_ids.iter().enumerate() {
            #[allow(clippy::cast_possible_truncation)] // index fits in u32
            let progress = (index + 1) as u32;
            let document = match document_repo
                .find_by_id_and_tenant(*document_uuid, &tenant_id)
                .await
            {
                Ok(Some(doc)) => doc,
                Ok(None) => {
                    self.job_tracker.add_error(
                        &tracker_job_id,
                        format!("Document {document_uuid} not found for tenant {tenant_id}"),
                    );
                    self.job_tracker.update_progress(
                        &tracker_job_id,
                        progress,
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
                        progress,
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
                        progress,
                        total_docs,
                        "reembedding",
                    );
                    continue;
                }
            };

            if chunks.is_empty() {
                self.job_tracker.add_error(
                    &tracker_job_id,
                    format!("Document {document_uuid} has no chunks to reembed"),
                );
                self.job_tracker.update_progress(
                    &tracker_job_id,
                    progress,
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
                            format!("Embedding failed for {document_uuid}: {e}"),
                        );
                        embeddings.clear();
                        break;
                    }
                }
            }

            if embeddings.len() != chunks.len() {
                self.job_tracker.update_progress(
                    &tracker_job_id,
                    progress,
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
                        format!("Reindex failed for {document_uuid}: {e}"),
                    );
                    self.job_tracker.update_progress(
                        &tracker_job_id,
                        progress,
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
                    format!("Failed to mark embeddings generated for {document_uuid}: {e}"),
                );
            }

            if let Err(e) = document_repo
                .update_status(*document_uuid, "completed", None)
                .await
            {
                self.job_tracker.add_error(
                    &tracker_job_id,
                    format!("Failed to mark document {document_uuid} completed: {e}"),
                );
            }

            processed_docs += 1;
            #[allow(clippy::cast_possible_truncation)] // chunk count fits in u32
            let chunk_len = chunks.len() as u32;
            total_chunks += chunk_len;
            self.job_tracker
                .update_progress(&tracker_job_id, progress, total_docs, "reembedding");
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
    #[allow(clippy::unused_async)] // async for consistency with other read methods
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
    #[allow(clippy::unused_self)] // kept as method for handler API consistency
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
                let parser = MarkdownParser;
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

    #[allow(clippy::unused_self)] // kept as method for handler API consistency
    fn extract_chunking_strategy(&self, payload: &Value) -> ChunkingStrategyType {
        let strategy_value = payload.get("chunking_strategy").or_else(|| {
            payload
                .get("processing")
                .and_then(|processing| processing.get("chunking_strategy"))
        });

        let Some(value) = strategy_value else {
            return ChunkingStrategyType::Recursive;
        };

        let Some(raw) = value.as_str() else {
            return serde_json::from_value::<ChunkingStrategyType>(value.clone())
                .unwrap_or(ChunkingStrategyType::Recursive);
        };

        match raw.to_ascii_lowercase().as_str() {
            "recursive" => ChunkingStrategyType::Recursive,
            "semantic" => ChunkingStrategyType::Semantic,
            "hierarchical" | "document_structure" => ChunkingStrategyType::Hierarchical,
            other => {
                warn!(
                    strategy = other,
                    "Unknown chunking strategy in payload; defaulting to recursive"
                );
                ChunkingStrategyType::Recursive
            }
        }
    }

    /// Chunk content using the configured strategy.
    #[allow(clippy::unused_self)] // kept as method for handler API consistency
    fn chunk_content(
        &self,
        content: &str,
        strategy: ChunkingStrategyType,
        chunk_size: u32,
        chunk_overlap: u32,
    ) -> Result<Vec<TextChunk>, String> {
        let max_tokens = chunk_size.max(1);
        let target_tokens = max_tokens.saturating_sub(100).max(1);
        let config = ChunkingConfig {
            target_tokens,
            max_tokens,
            chunk_overlap,
            min_chunk_size: 50,
            tokenizer: "cl100k_base".to_string(),
        };

        let document_id = rag_types::DocumentId::new();

        let result = match strategy {
            ChunkingStrategyType::Recursive => {
                let splitter = RecursiveCharacterSplitter::new(config)
                    .map_err(|e| format!("Failed to create recursive splitter: {e}"))?;
                splitter.chunk(content, document_id, None)
            }
            ChunkingStrategyType::Semantic => {
                let semantic_config = SemanticChunkerConfig::from(config);
                let chunker = SemanticChunker::with_config(semantic_config)
                    .map_err(|e| format!("Failed to create semantic chunker: {e}"))?;
                chunker.chunk(content, document_id, None)
            }
            ChunkingStrategyType::Hierarchical => {
                let chunker = HierarchicalChunker::with_config(config)
                    .map_err(|e| format!("Failed to create hierarchical chunker: {e}"))?;
                chunker.chunk(content, document_id, None)
            }
        };

        match result {
            Ok(chunks) => Ok(chunks),
            Err(e) => Err(format!("Chunking failed: {e}")),
        }
    }
}

#[async_trait]
impl JobHandler for IngestionJobHandler {
    #[instrument(skip(self, job), fields(job_id = %job.id, job_type = %job.job_type))]
    async fn handle(&self, job: &Job) -> Result<Value, String> {
        let result = match job.job_type.as_str() {
            "ingest_single" | "ingest_batch" | "sync" | "reindex_document" => {
                self.process_ingest_single(job).await
            }
            "reembed" => self.process_reembed(job).await,
            _ => Err(format!("Unknown job type: {}", job.job_type)),
        };

        // Propagate failure to the in-memory job tracker so the status API
        // reflects the error instead of staying stuck at "progress".
        if let Err(ref error) = result {
            if let Ok(tracker_job_id) = self.extract_tracker_job_id(&job.payload) {
                self.job_tracker.fail_job(&tracker_job_id, error.clone());
            }

            // Also update the PostgreSQL document status to "failed" so the
            // document doesn't stay stuck in "pending" forever.
            if let Some(ref database) = self.database {
                if let Some(doc_id) = self.extract_document_id(&job.payload) {
                    let repo = DocumentRepository::new(database.inner().clone());
                    if let Err(db_err) = repo
                        .update_status(doc_id, "failed", Some(error.as_str()))
                        .await
                    {
                        warn!(
                            error = %db_err,
                            document_id = %doc_id,
                            "Failed to update document status to 'failed' in PostgreSQL"
                        );
                    }
                }
            }
        }

        result
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

    #[test]
    fn test_extract_chunking_strategy_from_processing_payload() {
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(tracker, None, None, None);
        let payload = json!({
            "processing": {
                "chunking_strategy": "semantic"
            }
        });

        let strategy = handler.extract_chunking_strategy(&payload);
        assert_eq!(strategy, ChunkingStrategyType::Semantic);
    }

    #[test]
    fn test_extract_chunking_strategy_from_top_level_payload() {
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(tracker, None, None, None);
        let payload = json!({
            "chunking_strategy": "hierarchical"
        });

        let strategy = handler.extract_chunking_strategy(&payload);
        assert_eq!(strategy, ChunkingStrategyType::Hierarchical);
    }

    #[test]
    fn test_extract_chunking_strategy_unknown_defaults_to_recursive() {
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(tracker, None, None, None);
        let payload = json!({
            "processing": {
                "chunking_strategy": "unknown_strategy"
            }
        });

        let strategy = handler.extract_chunking_strategy(&payload);
        assert_eq!(strategy, ChunkingStrategyType::Recursive);
    }

    #[test]
    fn test_chunk_content_supports_semantic_strategy() {
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(tracker, None, None, None);
        let content = "Sentence one. Sentence two. Sentence three.";

        let chunks = handler
            .chunk_content(content, ChunkingStrategyType::Semantic, 128, 10)
            .unwrap();
        assert!(!chunks.is_empty());
    }

    #[test]
    fn test_chunk_content_supports_hierarchical_strategy() {
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(tracker, None, None, None);
        let content = "# Overview\nFirst section.\n\n## Details\nSecond section.";

        let chunks = handler
            .chunk_content(content, ChunkingStrategyType::Hierarchical, 128, 10)
            .unwrap();
        assert!(!chunks.is_empty());
        assert!(chunks.iter().any(|c| c.source_section.is_some()));
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

    #[tokio::test]
    async fn test_failed_ingest_job_updates_tracker_to_failure() {
        // When an ingest job fails (e.g., source file doesn't exist),
        // the in-memory tracker should reflect Failure status.
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(Arc::clone(&tracker), None, None, None);
        let tracker_job_id = tracker.create_job("tenant-1".to_string());

        let job = Job::new(
            "ingest_single",
            "tenant-1",
            json!({
                "tracker_job_id": tracker_job_id.to_string(),
                "source_id": "/nonexistent/path/to/document.pdf",
                "document_id": Uuid::new_v4().to_string(),
            }),
        );

        let result = handler.handle(&job).await;
        assert!(result.is_err());

        // The in-memory tracker must show Failure, not stuck at Pending/Started
        let job_state = tracker.get_job(&tracker_job_id).unwrap();
        assert_eq!(job_state.status, JobStatus::Failure);
        assert!(job_state.error_message.is_some());
    }

    #[test]
    fn test_extract_document_id_from_payload() {
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(tracker, None, None, None);

        let doc_id = Uuid::new_v4();
        let payload = json!({ "document_id": doc_id.to_string() });
        assert_eq!(handler.extract_document_id(&payload), Some(doc_id));

        // Missing document_id returns None
        let payload = json!({ "source_id": "test.pdf" });
        assert_eq!(handler.extract_document_id(&payload), None);

        // Invalid UUID returns None
        let payload = json!({ "document_id": "not-a-uuid" });
        assert_eq!(handler.extract_document_id(&payload), None);
    }
}

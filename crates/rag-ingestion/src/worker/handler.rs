//! Ingestion job handler for processing documents.

use async_trait::async_trait;
use rag_types::{ChunkId, DocumentId, TenantId};
use serde_json::{json, Value};
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
}

impl IngestionJobHandler {
    /// Create a new ingestion job handler.
    #[must_use]
    pub fn new(
        job_tracker: Arc<JobTracker>,
        embedding_client: Option<Arc<EmbeddingClient>>,
        index_coordinator: Option<Arc<IndexCoordinator>>,
    ) -> Self {
        Self {
            job_tracker,
            embedding_client,
            index_coordinator,
        }
    }

    /// Process a single document ingestion job.
    #[instrument(skip(self, job), fields(job_id = %job.id, job_type = %job.job_type))]
    async fn process_ingest_single(&self, job: &Job) -> Result<Value, String> {
        let payload = &job.payload;

        // Extract tracker job ID for status updates
        let tracker_job_id = payload
            .get("tracker_job_id")
            .and_then(|v| v.as_str())
            .and_then(|s| Uuid::parse_str(s).ok())
            .ok_or("Missing or invalid tracker_job_id")?;

        // Mark job as started
        self.job_tracker.update_status(&tracker_job_id, JobStatus::Started);

        // Extract source information - try source_id first, then fall back to source_config.path or keys[0]
        let source_id = payload
            .get("source_id")
            .and_then(|v| v.as_str())
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
            .ok_or("Missing source_id, source_config.path, or source_config.keys")?;

        let source_type = payload
            .get("source_type")
            .and_then(|v| v.as_str())
            .unwrap_or("file");

        // Check if this is an S3 source
        let storage_type = payload
            .get("source_config")
            .and_then(|c| c.get("storage_type"))
            .and_then(|v| v.as_str());

        let tenant_id = &job.tenant_id;

        info!(
            source_id = source_id,
            source_type = source_type,
            storage_type = storage_type,
            tenant_id = tenant_id,
            "Processing document"
        );

        // Update progress: parsing
        self.job_tracker.update_progress(&tracker_job_id, 0, 4, "parsing");

        // Read and parse document content
        let content = if storage_type == Some("s3") {
            self.read_s3_document(source_id, payload).await?
        } else {
            self.read_local_document(source_id).await?
        };

        // Update progress: chunking
        self.job_tracker.update_progress(&tracker_job_id, 1, 4, "chunking");

        // Chunk the content
        let chunk_size = payload
            .get("processing")
            .and_then(|p| p.get("chunk_size"))
            .and_then(|v| v.as_u64())
            .unwrap_or(512) as u32;

        let chunk_overlap = payload
            .get("processing")
            .and_then(|p| p.get("chunk_overlap"))
            .and_then(|v| v.as_u64())
            .unwrap_or(50) as u32;

        let chunks = self.chunk_content(&content, chunk_size, chunk_overlap)?;
        let chunk_count = chunks.len();

        info!(chunks = chunk_count, "Document chunked");

        // Update progress: embedding
        self.job_tracker.update_progress(&tracker_job_id, 2, 4, "embedding");

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
        self.job_tracker.update_progress(&tracker_job_id, 3, 4, "indexing");

        // Index to stores if coordinator is available
        if let Some(ref coordinator) = self.index_coordinator {
            let document_id = DocumentId::new();

            // Parse tenant_id as UUID, or generate a new one
            let tenant_uuid = Uuid::parse_str(tenant_id)
                .unwrap_or_else(|_| Uuid::new_v4());
            let tenant_id_typed = TenantId::from_uuid(tenant_uuid);

            let document = DocumentRecord {
                document_id,
                tenant_id: tenant_id_typed,
                source_id: source_id.to_string(),
                title: Some(source_id.to_string()),
                metadata: Default::default(),
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
                        metadata: Default::default(),
                    }
                })
                .collect();

            match coordinator.index_document(document, indexed_chunks).await {
                Ok(results) => {
                    let all_success = results.values().all(|r| r.success);
                    if !all_success {
                        let errors: Vec<_> = results
                            .iter()
                            .filter(|(_, r)| !r.success)
                            .map(|(store, r)| format!("{}: {:?}", store, r.errors))
                            .collect();
                        self.job_tracker.add_error(&tracker_job_id, errors.join(", "));
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
        self.job_tracker.update_counts(&tracker_job_id, 1, chunk_count as u32);
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

    /// Read document from S3/MinIO storage.
    async fn read_s3_document(&self, source_id: &str, payload: &Value) -> Result<String, String> {
        let source_config = payload
            .get("source_config")
            .ok_or("Missing source_config for S3 document")?;

        // Extract S3 connection details (support both naming conventions)
        // First try source_config, then fall back to environment variable, then default
        let s3_endpoint = source_config
            .get("s3_endpoint")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string())
            .or_else(|| std::env::var("S3_ENDPOINT").ok())
            .unwrap_or_else(|| "http://minio:9000".to_string());

        let s3_bucket = source_config
            .get("s3_bucket")
            .and_then(|v| v.as_str())
            .or_else(|| source_config.get("bucket").and_then(|v| v.as_str()))
            .unwrap_or("rag-documents");

        info!(
            endpoint = s3_endpoint,
            bucket = s3_bucket,
            key = source_id,
            "Connecting to S3"
        );

        // Create S3 connector
        let config = S3Config::new(s3_bucket)
            .with_endpoint(s3_endpoint);

        let mut connector = S3Connector::new(config);

        // Connect to S3
        connector.connect().await
            .map_err(|e| format!("Failed to connect to S3: {e}"))?;

        // Fetch the document
        let raw_doc = connector.fetch_document(source_id).await
            .map_err(|e| format!("Failed to fetch document from S3: {e}"))?;

        let bytes = raw_doc.content;

        // Determine parser based on file extension
        let extension = source_id
            .rsplit('.')
            .next()
            .unwrap_or("")
            .to_lowercase();

        self.parse_bytes(&bytes, &extension)
    }

    /// Read document from local filesystem.
    async fn read_local_document(&self, source_id: &str) -> Result<String, String> {
        let path = std::path::Path::new(source_id);

        if !path.exists() {
            return Err(format!("File not found: {source_id}"));
        }

        // Read file as bytes
        let bytes = std::fs::read(path)
            .map_err(|e| format!("Failed to read file: {e}"))?;

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
            "ingest_single" | "ingest_batch" => self.process_ingest_single(job).await,
            _ => Err(format!("Unknown job type: {}", job.job_type)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_handler_creation() {
        let tracker = Arc::new(JobTracker::new());
        let handler = IngestionJobHandler::new(tracker, None, None);
        assert!(handler.embedding_client.is_none());
        assert!(handler.index_coordinator.is_none());
    }
}

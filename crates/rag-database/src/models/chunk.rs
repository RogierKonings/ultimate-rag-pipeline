//! Chunk model.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

/// Document chunk stored in PostgreSQL.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct Chunk {
    /// Unique identifier.
    pub id: Uuid,
    /// Reference to parent document.
    pub document_id: Uuid,
    /// Tenant ID for multi-tenancy.
    pub tenant_id: String,
    /// Position within the document.
    pub chunk_index: i32,
    /// Chunk text content.
    pub content: String,
    /// Token count.
    pub token_count: i32,
    /// Character count.
    pub char_count: i32,
    /// Embedding model used.
    pub embedding_model: Option<String>,
    /// Whether embedding has been generated.
    pub embedding_generated: bool,
    /// Content hash for deduplication.
    pub content_hash: String,
    /// Start position in source document.
    pub start_offset: Option<i32>,
    /// End position in source document.
    pub end_offset: Option<i32>,
    /// Additional metadata as JSON.
    #[sqlx(default)]
    pub metadata: serde_json::Value,
    /// Created timestamp.
    pub created_at: DateTime<Utc>,
    /// Updated timestamp.
    pub updated_at: DateTime<Utc>,
}

impl Chunk {
    /// Create a new chunk builder.
    #[must_use]
    pub fn builder(
        document_id: Uuid,
        tenant_id: impl Into<String>,
        content: impl Into<String>,
    ) -> ChunkBuilder {
        ChunkBuilder::new(document_id, tenant_id, content)
    }

    /// Get a truncated preview of the content.
    #[must_use]
    pub fn preview(&self, max_len: usize) -> &str {
        if self.content.len() <= max_len {
            &self.content
        } else {
            &self.content[..max_len]
        }
    }
}

/// Builder for creating chunks.
#[derive(Debug, Clone)]
pub struct ChunkBuilder {
    document_id: Uuid,
    tenant_id: String,
    chunk_index: i32,
    content: String,
    token_count: i32,
    char_count: i32,
    embedding_model: Option<String>,
    content_hash: String,
    start_offset: Option<i32>,
    end_offset: Option<i32>,
    metadata: serde_json::Value,
}

impl ChunkBuilder {
    /// Create a new builder.
    fn new(document_id: Uuid, tenant_id: impl Into<String>, content: impl Into<String>) -> Self {
        let content = content.into();
        let char_count = content.len() as i32;

        Self {
            document_id,
            tenant_id: tenant_id.into(),
            chunk_index: 0,
            content,
            token_count: 0,
            char_count,
            embedding_model: None,
            content_hash: String::new(),
            start_offset: None,
            end_offset: None,
            metadata: serde_json::Value::Null,
        }
    }

    /// Set the chunk index.
    #[must_use]
    pub const fn index(mut self, index: i32) -> Self {
        self.chunk_index = index;
        self
    }

    /// Set the token count.
    #[must_use]
    pub const fn token_count(mut self, count: i32) -> Self {
        self.token_count = count;
        self
    }

    /// Set the embedding model.
    #[must_use]
    pub fn embedding_model(mut self, model: impl Into<String>) -> Self {
        self.embedding_model = Some(model.into());
        self
    }

    /// Set the content hash.
    #[must_use]
    pub fn content_hash(mut self, hash: impl Into<String>) -> Self {
        self.content_hash = hash.into();
        self
    }

    /// Set the offsets.
    #[must_use]
    pub const fn offsets(mut self, start: i32, end: i32) -> Self {
        self.start_offset = Some(start);
        self.end_offset = Some(end);
        self
    }

    /// Set additional metadata.
    #[must_use]
    pub fn metadata(mut self, metadata: serde_json::Value) -> Self {
        self.metadata = metadata;
        self
    }

    /// Build the chunk (for insertion).
    #[must_use]
    pub fn build(self) -> NewChunk {
        NewChunk {
            id: Uuid::new_v4(),
            document_id: self.document_id,
            tenant_id: self.tenant_id,
            chunk_index: self.chunk_index,
            content: self.content,
            token_count: self.token_count,
            char_count: self.char_count,
            embedding_model: self.embedding_model,
            content_hash: self.content_hash,
            start_offset: self.start_offset,
            end_offset: self.end_offset,
            metadata: self.metadata,
        }
    }
}

/// New chunk for insertion.
#[derive(Debug, Clone, Serialize)]
pub struct NewChunk {
    /// Unique identifier.
    pub id: Uuid,
    /// Reference to parent document.
    pub document_id: Uuid,
    /// Tenant ID.
    pub tenant_id: String,
    /// Position within the document.
    pub chunk_index: i32,
    /// Chunk text content.
    pub content: String,
    /// Token count.
    pub token_count: i32,
    /// Character count.
    pub char_count: i32,
    /// Embedding model.
    pub embedding_model: Option<String>,
    /// Content hash.
    pub content_hash: String,
    /// Start offset.
    pub start_offset: Option<i32>,
    /// End offset.
    pub end_offset: Option<i32>,
    /// Metadata.
    pub metadata: serde_json::Value,
}

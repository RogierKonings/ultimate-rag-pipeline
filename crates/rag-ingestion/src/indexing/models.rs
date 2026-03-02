//! Data models for indexing operations.

use rag_types::{AclMetadata, ChunkId, DocumentId, TenantId};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::time::Duration;

/// Metadata record for a document being indexed.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentRecord {
    /// Unique identifier for the document.
    pub document_id: DocumentId,
    /// Tenant that owns this document.
    pub tenant_id: TenantId,
    /// External source identifier (e.g., file path, S3 key).
    pub source_id: String,
    /// Optional document title.
    pub title: Option<String>,
    /// Access control metadata.
    #[serde(default)]
    pub acl: AclMetadata,
    /// Additional metadata.
    #[serde(default)]
    pub metadata: HashMap<String, Value>,
}

impl DocumentRecord {
    /// Create a new document record.
    pub fn new(document_id: DocumentId, tenant_id: TenantId, source_id: impl Into<String>) -> Self {
        Self {
            document_id,
            tenant_id,
            source_id: source_id.into(),
            title: None,
            acl: AclMetadata::default(),
            metadata: HashMap::new(),
        }
    }

    /// Set the document title.
    #[must_use]
    pub fn with_title(mut self, title: impl Into<String>) -> Self {
        self.title = Some(title.into());
        self
    }

    /// Set access control metadata.
    #[must_use]
    pub fn with_acl(mut self, acl: AclMetadata) -> Self {
        self.acl = acl;
        self
    }

    /// Add metadata.
    #[must_use]
    pub fn with_metadata(mut self, key: impl Into<String>, value: Value) -> Self {
        self.metadata.insert(key.into(), value);
        self
    }
}

/// A chunk ready to be indexed with its embedding.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IndexedChunk {
    /// Unique identifier for this chunk.
    pub chunk_id: ChunkId,
    /// Parent document ID.
    pub document_id: DocumentId,
    /// Tenant that owns this chunk.
    pub tenant_id: TenantId,
    /// Text content of the chunk.
    pub content: String,
    /// Vector embedding.
    pub embedding: Vec<f32>,
    /// Position within the document (0-indexed).
    pub chunk_index: u32,
    /// Access control metadata (inherited from parent document).
    #[serde(default)]
    pub acl: AclMetadata,
    /// Additional metadata.
    #[serde(default)]
    pub metadata: HashMap<String, Value>,
}

impl IndexedChunk {
    /// Create a new indexed chunk.
    pub fn new(
        chunk_id: ChunkId,
        document_id: DocumentId,
        tenant_id: TenantId,
        content: impl Into<String>,
        embedding: Vec<f32>,
        chunk_index: u32,
    ) -> Self {
        Self {
            chunk_id,
            document_id,
            tenant_id,
            content: content.into(),
            embedding,
            chunk_index,
            acl: AclMetadata::default(),
            metadata: HashMap::new(),
        }
    }

    /// Set access control metadata.
    #[must_use]
    pub fn with_acl(mut self, acl: AclMetadata) -> Self {
        self.acl = acl;
        self
    }

    /// Add metadata.
    #[must_use]
    pub fn with_metadata(mut self, key: impl Into<String>, value: Value) -> Self {
        self.metadata.insert(key.into(), value);
        self
    }
}

/// Result of a write operation to a single store.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WriteResult {
    /// Whether the write succeeded.
    pub success: bool,
    /// Number of items successfully written.
    pub items_written: usize,
    /// Number of items that failed to write.
    pub items_failed: usize,
    /// Error messages if any.
    #[serde(default)]
    pub errors: Vec<String>,
    /// Time taken for the write operation.
    #[serde(with = "duration_millis")]
    pub duration: Duration,
}

impl WriteResult {
    /// Create a successful write result.
    pub fn success(items_written: usize, duration: Duration) -> Self {
        Self {
            success: true,
            items_written,
            items_failed: 0,
            errors: vec![],
            duration,
        }
    }

    /// Create a failed write result.
    pub fn failure(error: impl Into<String>, duration: Duration) -> Self {
        Self {
            success: false,
            items_written: 0,
            items_failed: 0,
            errors: vec![error.into()],
            duration,
        }
    }

    /// Create a partial success result.
    pub fn partial(
        items_written: usize,
        items_failed: usize,
        errors: Vec<String>,
        duration: Duration,
    ) -> Self {
        Self {
            success: items_failed == 0,
            items_written,
            items_failed,
            errors,
            duration,
        }
    }
}

mod duration_millis {
    use serde::{Deserialize, Deserializer, Serializer};
    use std::time::Duration;

    #[allow(clippy::cast_possible_truncation)] // duration millis fits in u64
    pub fn serialize<S>(duration: &Duration, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_u64(duration.as_millis() as u64)
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Duration, D::Error>
    where
        D: Deserializer<'de>,
    {
        let millis = u64::deserialize(deserializer)?;
        Ok(Duration::from_millis(millis))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_document_record_builder() {
        let doc = DocumentRecord::new(DocumentId::new(), TenantId::new(), "path/to/file.pdf")
            .with_title("My Document")
            .with_metadata("author", Value::String("John".to_string()));

        assert_eq!(doc.source_id, "path/to/file.pdf");
        assert_eq!(doc.title, Some("My Document".to_string()));
        assert!(doc.metadata.contains_key("author"));
    }

    #[test]
    fn test_indexed_chunk_builder() {
        let chunk = IndexedChunk::new(
            ChunkId::new(),
            DocumentId::new(),
            TenantId::new(),
            "Hello world",
            vec![0.1, 0.2, 0.3],
            0,
        )
        .with_metadata("section", Value::String("intro".to_string()));

        assert_eq!(chunk.content, "Hello world");
        assert_eq!(chunk.embedding, vec![0.1, 0.2, 0.3]);
        assert_eq!(chunk.chunk_index, 0);
    }

    #[test]
    fn test_write_result_success() {
        let result = WriteResult::success(10, Duration::from_millis(50));
        assert!(result.success);
        assert_eq!(result.items_written, 10);
        assert_eq!(result.items_failed, 0);
        assert!(result.errors.is_empty());
    }

    #[test]
    fn test_write_result_failure() {
        let result = WriteResult::failure("Connection refused", Duration::from_millis(100));
        assert!(!result.success);
        assert_eq!(result.items_written, 0);
        assert_eq!(result.errors.len(), 1);
    }

    #[test]
    fn test_write_result_serde() {
        let result = WriteResult::success(5, Duration::from_millis(123));
        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("\"duration\":123"));

        let parsed: WriteResult = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.duration, Duration::from_millis(123));
    }

    #[test]
    fn test_document_record_with_acl() {
        use rag_types::{AclMetadata, Visibility};
        let acl = AclMetadata {
            visibility: Visibility::Group,
            owner_id: Some("owner-1".to_string()),
            allowed_groups: vec!["eng".to_string()],
            ..AclMetadata::default()
        };
        let doc = DocumentRecord::new(
            DocumentId::new(),
            TenantId::new(),
            "test.pdf".to_string(),
        )
        .with_acl(acl.clone());
        assert_eq!(doc.acl, acl);
    }

    #[test]
    fn test_indexed_chunk_inherits_acl() {
        use rag_types::{AclMetadata, Visibility};
        let acl = AclMetadata {
            visibility: Visibility::Private,
            owner_id: Some("user-1".to_string()),
            ..AclMetadata::default()
        };
        let chunk = IndexedChunk::new(
            ChunkId::new(),
            DocumentId::new(),
            TenantId::new(),
            "content".to_string(),
            vec![0.1, 0.2],
            0,
        )
        .with_acl(acl.clone());
        assert_eq!(chunk.acl, acl);
    }
}

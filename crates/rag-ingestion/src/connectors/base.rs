//! Base types and traits for document connectors.

use async_trait::async_trait;
use bytes::Bytes;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

use crate::error::Result;

/// Type of document source.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StorageBackend {
    /// Local filesystem.
    Local,
    /// S3-compatible object storage.
    S3,
}

impl std::fmt::Display for StorageBackend {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Local => write!(f, "local"),
            Self::S3 => write!(f, "s3"),
        }
    }
}

/// Metadata about a document in a source.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentMetadata {
    /// Identifier within the source (relative path or S3 key).
    pub source_id: String,
    /// Type of source.
    pub source_type: StorageBackend,
    /// Original filename.
    pub filename: String,
    /// MIME type if detected.
    pub mime_type: Option<String>,
    /// File size in bytes.
    pub size_bytes: Option<u64>,
    /// Creation timestamp.
    pub created_at: Option<DateTime<Utc>>,
    /// Last modification timestamp.
    pub modified_at: Option<DateTime<Utc>>,
    /// Additional metadata.
    #[serde(default)]
    pub extra: HashMap<String, Value>,
}

impl DocumentMetadata {
    /// Create new document metadata.
    pub fn new(
        source_id: impl Into<String>,
        source_type: StorageBackend,
        filename: impl Into<String>,
    ) -> Self {
        Self {
            source_id: source_id.into(),
            source_type,
            filename: filename.into(),
            mime_type: None,
            size_bytes: None,
            created_at: None,
            modified_at: None,
            extra: HashMap::new(),
        }
    }

    /// Set MIME type.
    #[must_use]
    pub fn with_mime_type(mut self, mime_type: impl Into<String>) -> Self {
        self.mime_type = Some(mime_type.into());
        self
    }

    /// Set file size.
    #[must_use]
    pub fn with_size(mut self, size_bytes: u64) -> Self {
        self.size_bytes = Some(size_bytes);
        self
    }

    /// Set timestamps.
    #[must_use]
    pub fn with_timestamps(
        mut self,
        created_at: Option<DateTime<Utc>>,
        modified_at: Option<DateTime<Utc>>,
    ) -> Self {
        self.created_at = created_at;
        self.modified_at = modified_at;
        self
    }

    /// Add extra metadata.
    #[must_use]
    pub fn with_extra(mut self, key: impl Into<String>, value: Value) -> Self {
        self.extra.insert(key.into(), value);
        self
    }
}

/// Raw document content with metadata.
#[derive(Debug, Clone)]
pub struct RawDocument {
    /// Binary content of the document.
    pub content: Bytes,
    /// Document metadata.
    pub metadata: DocumentMetadata,
}

impl RawDocument {
    /// Create a new raw document.
    pub fn new(content: impl Into<Bytes>, metadata: DocumentMetadata) -> Self {
        Self {
            content: content.into(),
            metadata,
        }
    }

    /// Get content as UTF-8 string if valid.
    pub fn content_as_str(&self) -> Result<&str> {
        std::str::from_utf8(&self.content)
            .map_err(|e| crate::error::Error::Parse(format!("Invalid UTF-8: {e}")))
    }
}

/// Trait for document connectors.
#[async_trait]
pub trait Connector: Send + Sync {
    /// Connect to the source.
    async fn connect(&mut self) -> Result<()>;

    /// Disconnect from the source.
    async fn disconnect(&mut self) -> Result<()>;

    /// List documents in the source.
    ///
    /// # Arguments
    /// * `path` - Optional path/prefix to filter documents
    async fn list_documents(&self, path: Option<&str>) -> Result<Vec<DocumentMetadata>>;

    /// Fetch a document by its source ID.
    async fn fetch_document(&self, source_id: &str) -> Result<RawDocument>;

    /// Check if the connector is connected.
    fn is_connected(&self) -> bool;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_source_type_display() {
        assert_eq!(StorageBackend::Local.to_string(), "local");
        assert_eq!(StorageBackend::S3.to_string(), "s3");
    }

    #[test]
    fn test_source_type_serde() {
        let st = StorageBackend::S3;
        let json = serde_json::to_string(&st).unwrap();
        assert_eq!(json, "\"s3\"");

        let parsed: StorageBackend = serde_json::from_str("\"local\"").unwrap();
        assert_eq!(parsed, StorageBackend::Local);
    }

    #[test]
    fn test_document_metadata_builder() {
        let meta = DocumentMetadata::new("path/to/file.pdf", StorageBackend::Local, "file.pdf")
            .with_mime_type("application/pdf")
            .with_size(1024)
            .with_extra("author", Value::String("Test".to_string()));

        assert_eq!(meta.source_id, "path/to/file.pdf");
        assert_eq!(meta.filename, "file.pdf");
        assert_eq!(meta.mime_type, Some("application/pdf".to_string()));
        assert_eq!(meta.size_bytes, Some(1024));
        assert!(meta.extra.contains_key("author"));
    }

    #[test]
    fn test_raw_document_content_as_str() {
        let meta = DocumentMetadata::new("test.txt", StorageBackend::Local, "test.txt");
        let doc = RawDocument::new("Hello, World!", meta);

        assert_eq!(doc.content_as_str().unwrap(), "Hello, World!");
    }

    #[test]
    fn test_raw_document_invalid_utf8() {
        let meta = DocumentMetadata::new("test.bin", StorageBackend::Local, "test.bin");
        let doc = RawDocument::new(vec![0xFF, 0xFE], meta);

        assert!(doc.content_as_str().is_err());
    }
}

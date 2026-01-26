//! Source document model.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

/// Visibility level for documents.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, sqlx::Type)]
#[sqlx(type_name = "VARCHAR")]
#[sqlx(rename_all = "lowercase")]
#[serde(rename_all = "lowercase")]
pub enum Visibility {
    /// Public to all users.
    Public,
    /// Visible only to specific groups.
    Private,
    /// Visible only within the tenant.
    Internal,
}

impl Default for Visibility {
    fn default() -> Self {
        Self::Private
    }
}

/// Source document metadata stored in PostgreSQL.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct SourceDocument {
    /// Unique identifier.
    pub id: Uuid,
    /// Tenant ID for multi-tenancy.
    pub tenant_id: String,
    /// Document title.
    pub title: Option<String>,
    /// Source URI (file path, URL, etc.).
    pub source_uri: String,
    /// Source type (file, web, api, etc.).
    pub source_type: String,
    /// MIME type of the document.
    pub mime_type: Option<String>,
    /// Content hash for deduplication.
    pub content_hash: String,
    /// File size in bytes.
    pub file_size: Option<i64>,
    /// Total number of chunks.
    pub chunk_count: i32,
    /// Processing status.
    pub status: String,
    /// Error message if processing failed.
    pub error_message: Option<String>,
    /// Visibility level.
    #[sqlx(try_from = "String")]
    pub visibility: Visibility,
    /// Groups allowed to access this document.
    #[sqlx(default)]
    pub allowed_groups: Vec<String>,
    /// Additional metadata as JSON.
    #[sqlx(default)]
    pub metadata: serde_json::Value,
    /// Created timestamp.
    pub created_at: DateTime<Utc>,
    /// Updated timestamp.
    pub updated_at: DateTime<Utc>,
}

impl SourceDocument {
    /// Create a new source document builder.
    #[must_use]
    pub fn builder(tenant_id: impl Into<String>, source_uri: impl Into<String>) -> SourceDocumentBuilder {
        SourceDocumentBuilder::new(tenant_id, source_uri)
    }

    /// Check if the document is in a terminal state.
    #[must_use]
    pub fn is_terminal(&self) -> bool {
        matches!(self.status.as_str(), "completed" | "failed")
    }

    /// Check if the document is accessible by the given groups.
    #[must_use]
    pub fn is_accessible_by(&self, groups: &[String]) -> bool {
        match self.visibility {
            Visibility::Public => true,
            Visibility::Private | Visibility::Internal => {
                self.allowed_groups.iter().any(|g| groups.contains(g))
            }
        }
    }
}

/// Builder for creating source documents.
#[derive(Debug, Clone)]
pub struct SourceDocumentBuilder {
    tenant_id: String,
    source_uri: String,
    title: Option<String>,
    source_type: String,
    mime_type: Option<String>,
    content_hash: String,
    file_size: Option<i64>,
    visibility: Visibility,
    allowed_groups: Vec<String>,
    metadata: serde_json::Value,
}

impl SourceDocumentBuilder {
    /// Create a new builder.
    fn new(tenant_id: impl Into<String>, source_uri: impl Into<String>) -> Self {
        Self {
            tenant_id: tenant_id.into(),
            source_uri: source_uri.into(),
            title: None,
            source_type: "file".to_string(),
            mime_type: None,
            content_hash: String::new(),
            file_size: None,
            visibility: Visibility::default(),
            allowed_groups: Vec::new(),
            metadata: serde_json::Value::Null,
        }
    }

    /// Set the document title.
    #[must_use]
    pub fn title(mut self, title: impl Into<String>) -> Self {
        self.title = Some(title.into());
        self
    }

    /// Set the source type.
    #[must_use]
    pub fn source_type(mut self, source_type: impl Into<String>) -> Self {
        self.source_type = source_type.into();
        self
    }

    /// Set the MIME type.
    #[must_use]
    pub fn mime_type(mut self, mime_type: impl Into<String>) -> Self {
        self.mime_type = Some(mime_type.into());
        self
    }

    /// Set the content hash.
    #[must_use]
    pub fn content_hash(mut self, hash: impl Into<String>) -> Self {
        self.content_hash = hash.into();
        self
    }

    /// Set the file size.
    #[must_use]
    pub const fn file_size(mut self, size: i64) -> Self {
        self.file_size = Some(size);
        self
    }

    /// Set the visibility.
    #[must_use]
    pub const fn visibility(mut self, visibility: Visibility) -> Self {
        self.visibility = visibility;
        self
    }

    /// Set allowed groups.
    #[must_use]
    pub fn allowed_groups(mut self, groups: Vec<String>) -> Self {
        self.allowed_groups = groups;
        self
    }

    /// Set additional metadata.
    #[must_use]
    pub fn metadata(mut self, metadata: serde_json::Value) -> Self {
        self.metadata = metadata;
        self
    }

    /// Build the source document (for insertion).
    #[must_use]
    pub fn build(self) -> NewSourceDocument {
        NewSourceDocument {
            id: Uuid::new_v4(),
            tenant_id: self.tenant_id,
            title: self.title,
            source_uri: self.source_uri,
            source_type: self.source_type,
            mime_type: self.mime_type,
            content_hash: self.content_hash,
            file_size: self.file_size,
            visibility: self.visibility,
            allowed_groups: self.allowed_groups,
            metadata: self.metadata,
        }
    }
}

/// New source document for insertion.
#[derive(Debug, Clone, Serialize)]
pub struct NewSourceDocument {
    /// Unique identifier.
    pub id: Uuid,
    /// Tenant ID.
    pub tenant_id: String,
    /// Document title.
    pub title: Option<String>,
    /// Source URI.
    pub source_uri: String,
    /// Source type.
    pub source_type: String,
    /// MIME type.
    pub mime_type: Option<String>,
    /// Content hash.
    pub content_hash: String,
    /// File size.
    pub file_size: Option<i64>,
    /// Visibility.
    pub visibility: Visibility,
    /// Allowed groups.
    pub allowed_groups: Vec<String>,
    /// Metadata.
    pub metadata: serde_json::Value,
}

// Custom TryFrom for Visibility from String (needed for sqlx)
impl TryFrom<String> for Visibility {
    type Error = String;

    fn try_from(s: String) -> std::result::Result<Self, Self::Error> {
        match s.to_lowercase().as_str() {
            "public" => Ok(Self::Public),
            "private" => Ok(Self::Private),
            "internal" => Ok(Self::Internal),
            _ => Err(format!("Unknown visibility: {s}")),
        }
    }
}

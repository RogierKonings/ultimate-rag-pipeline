//! Document and chunk types.
//!
//! These types represent the core data structures for document management
//! in the RAG pipeline.

use crate::ids::{ChunkId, DocumentId, GroupId, TenantId};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use validator::Validate;

/// Source type for ingested documents.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SourceType {
    /// Local or S3 filesystem
    Filesystem,
    /// Database connector
    Database,
    /// Web crawler
    Web,
    /// API integration
    Api,
}

impl std::fmt::Display for SourceType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Filesystem => write!(f, "filesystem"),
            Self::Database => write!(f, "database"),
            Self::Web => write!(f, "web"),
            Self::Api => write!(f, "api"),
        }
    }
}

/// Visibility level for documents and chunks.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[cfg_attr(feature = "sqlx", derive(sqlx::Type))]
#[cfg_attr(
    feature = "sqlx",
    sqlx(type_name = "VARCHAR", rename_all = "lowercase")
)]
#[serde(rename_all = "lowercase")]
pub enum Visibility {
    /// Accessible to all users in the tenant
    Public,
    /// Accessible only to the owner
    #[default]
    Private,
    /// Accessible to specific groups
    Group,
    /// Accessible to all users in the tenant
    Tenant,
}

impl Visibility {
    /// Check if this visibility level requires ACL filtering.
    #[must_use]
    pub const fn requires_acl_check(&self) -> bool {
        !matches!(self, Self::Public)
    }
}

impl std::fmt::Display for Visibility {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Public => write!(f, "public"),
            Self::Private => write!(f, "private"),
            Self::Group => write!(f, "group"),
            Self::Tenant => write!(f, "tenant"),
        }
    }
}

impl TryFrom<String> for Visibility {
    type Error = String;

    fn try_from(s: String) -> std::result::Result<Self, Self::Error> {
        match s.to_lowercase().as_str() {
            "public" => Ok(Self::Public),
            "private" => Ok(Self::Private),
            "group" => Ok(Self::Group),
            "tenant" | "internal" => Ok(Self::Tenant),
            _ => Err(format!("Unknown visibility: {s}")),
        }
    }
}

/// First-class ACL metadata carried on every document and chunk.
///
/// This struct is the canonical representation of access control across all stores
/// (`PostgreSQL`, Qdrant, `OpenSearch`). All stores must write these fields identically.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AclMetadata {
    /// Visibility level (default: Private — safe by default).
    #[serde(default)]
    pub visibility: Visibility,
    /// User ID of the document owner (set from X-User-Id at ingest time).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub owner_id: Option<String>,
    /// Groups explicitly granted access.
    #[serde(default)]
    pub allowed_groups: Vec<String>,
    /// Individual users explicitly granted access.
    #[serde(default)]
    pub allowed_users: Vec<String>,
    /// Groups explicitly denied access (overrides allowed).
    #[serde(default)]
    pub denied_groups: Vec<String>,
    /// Individual users explicitly denied access (overrides allowed).
    #[serde(default)]
    pub denied_users: Vec<String>,
}

impl Default for AclMetadata {
    fn default() -> Self {
        Self {
            visibility: Visibility::Private,
            owner_id: None,
            allowed_groups: vec![],
            allowed_users: vec![],
            denied_groups: vec![],
            denied_users: vec![],
        }
    }
}

impl AclMetadata {
    /// Convert to a flat JSON value suitable for Qdrant/OpenSearch payloads.
    #[must_use]
    pub fn to_json_value(&self) -> serde_json::Value {
        serde_json::json!({
            "visibility": self.visibility,
            "owner_id": self.owner_id,
            "allowed_groups": self.allowed_groups,
            "allowed_users": self.allowed_users,
            "denied_groups": self.denied_groups,
            "denied_users": self.denied_users,
        })
    }
}

/// Index synchronization status.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum IndexStatus {
    /// Not yet indexed
    #[default]
    Pending,
    /// Successfully indexed
    Ok,
    /// Indexing failed
    Error,
    /// Index is out of date
    Stale,
}

impl std::fmt::Display for IndexStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Pending => write!(f, "pending"),
            Self::Ok => write!(f, "ok"),
            Self::Error => write!(f, "error"),
            Self::Stale => write!(f, "stale"),
        }
    }
}

/// Soft delete status.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum EntityStatus {
    /// Entity is active
    #[default]
    Active,
    /// Entity has been soft-deleted
    Deleted,
}

/// A source document in the RAG pipeline.
///
/// Documents represent the original ingested content before chunking.
/// Each document belongs to a tenant and can have visibility restrictions.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
pub struct Document {
    /// Unique identifier
    pub id: DocumentId,

    /// External source identifier (e.g., file path, URL)
    #[validate(length(min = 1, max = 2048))]
    pub source_id: String,

    /// Type of source
    pub source_type: SourceType,

    /// Document title
    #[validate(length(max = 512))]
    pub title: Option<String>,

    /// SHA-256 hash of the document content for deduplication
    #[validate(length(equal = 64))]
    pub content_hash: String,

    /// Additional metadata
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,

    /// Owning tenant
    pub tenant_id: TenantId,

    /// Visibility level
    #[serde(default)]
    pub visibility: Visibility,

    /// Groups with access (when visibility is Group)
    #[serde(default)]
    pub allowed_groups: Vec<GroupId>,

    /// Qdrant index status
    #[serde(default)]
    pub qdrant_status: IndexStatus,

    /// `OpenSearch` index status
    #[serde(default)]
    pub opensearch_status: IndexStatus,

    /// Last successful indexing time
    pub last_indexed_at: Option<DateTime<Utc>>,

    /// Last indexing error message
    pub last_index_error: Option<String>,

    /// Number of indexing attempts
    #[serde(default)]
    pub index_attempts: u32,

    /// Creation timestamp
    pub created_at: DateTime<Utc>,

    /// Last update timestamp
    pub updated_at: DateTime<Utc>,

    /// Soft delete status
    #[serde(default)]
    pub status: EntityStatus,

    /// Soft delete timestamp
    pub deleted_at: Option<DateTime<Utc>>,
}

impl Document {
    /// Create a new document with required fields.
    #[must_use]
    pub fn new(
        source_id: String,
        source_type: SourceType,
        content_hash: String,
        tenant_id: TenantId,
    ) -> Self {
        let now = Utc::now();
        Self {
            id: DocumentId::new(),
            source_id,
            source_type,
            title: None,
            content_hash,
            metadata: HashMap::new(),
            tenant_id,
            visibility: Visibility::default(),
            allowed_groups: Vec::new(),
            qdrant_status: IndexStatus::default(),
            opensearch_status: IndexStatus::default(),
            last_indexed_at: None,
            last_index_error: None,
            index_attempts: 0,
            created_at: now,
            updated_at: now,
            status: EntityStatus::default(),
            deleted_at: None,
        }
    }

    /// Check if the document is active (not deleted).
    #[must_use]
    pub const fn is_active(&self) -> bool {
        matches!(self.status, EntityStatus::Active)
    }

    /// Check if the document is fully indexed.
    #[must_use]
    pub const fn is_indexed(&self) -> bool {
        matches!(self.qdrant_status, IndexStatus::Ok)
            && matches!(self.opensearch_status, IndexStatus::Ok)
    }
}

/// A chunk of a document.
///
/// Chunks are created during ingestion by splitting documents according
/// to the configured chunking strategy.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
pub struct Chunk {
    /// Unique identifier
    pub id: ChunkId,

    /// Parent document
    pub document_id: DocumentId,

    /// Position within the document (0-indexed)
    pub chunk_index: u32,

    /// Chunk text content
    #[validate(length(min = 1))]
    pub content: String,

    /// Token count (optional, depends on tokenizer)
    pub token_count: Option<u32>,

    /// Embedding model used
    pub embedding_model: Option<String>,

    /// Embedding version/hash
    pub embedding_version: Option<String>,

    /// Additional chunk metadata
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,

    /// Owning tenant (denormalized for query efficiency)
    pub tenant_id: TenantId,

    /// Creation timestamp
    pub created_at: DateTime<Utc>,

    /// Soft delete status
    #[serde(default)]
    pub status: EntityStatus,
}

impl Chunk {
    /// Create a new chunk.
    #[must_use]
    pub fn new(
        document_id: DocumentId,
        chunk_index: u32,
        content: String,
        tenant_id: TenantId,
    ) -> Self {
        Self {
            id: ChunkId::new(),
            document_id,
            chunk_index,
            content,
            token_count: None,
            embedding_model: None,
            embedding_version: None,
            metadata: HashMap::new(),
            tenant_id,
            created_at: Utc::now(),
            status: EntityStatus::default(),
        }
    }

    /// Set the token count.
    #[must_use]
    pub const fn with_token_count(mut self, count: u32) -> Self {
        self.token_count = Some(count);
        self
    }

    /// Set the embedding model information.
    #[must_use]
    pub fn with_embedding_info(mut self, model: String, version: String) -> Self {
        self.embedding_model = Some(model);
        self.embedding_version = Some(version);
        self
    }
}

/// Chunking strategy for document processing.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum ChunkingStrategy {
    /// Automatically select the best strategy based on document characteristics.
    #[default]
    Auto,
    /// Recursive character-based splitting.
    Recursive,
    /// Semantic sentence-based splitting.
    Semantic,
    /// Document structure-aware splitting.
    Hierarchical,
    /// Row-per-chunk splitting for CSV, Markdown tables, and HTML tables.
    Tabular,
    /// Question-and-answer pair splitting for FAQ documents.
    #[serde(rename = "qa")]
    QA,
    /// Zone-based splitting that applies different sub-strategies per content
    /// type (prose, table, code) within a single mixed-content document.
    #[serde(rename = "mixed_content")]
    MixedContent,
}

/// Configuration for document chunking.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
pub struct ChunkingConfig {
    /// Chunking strategy
    #[serde(default)]
    pub strategy: ChunkingStrategy,

    /// Target chunk size in tokens
    #[validate(range(min = 100, max = 4096))]
    #[serde(default = "default_chunk_size")]
    pub chunk_size: u32,

    /// Overlap between chunks in tokens
    #[validate(range(max = 500))]
    #[serde(default = "default_chunk_overlap")]
    pub chunk_overlap: u32,

    /// Enable PII detection
    #[serde(default = "default_true")]
    pub enable_pii_detection: bool,

    /// Custom metadata to add to all chunks
    #[serde(default)]
    pub custom_metadata: HashMap<String, serde_json::Value>,
}

const fn default_chunk_size() -> u32 {
    512
}

const fn default_chunk_overlap() -> u32 {
    50
}

const fn default_true() -> bool {
    true
}

impl Default for ChunkingConfig {
    fn default() -> Self {
        Self {
            strategy: ChunkingStrategy::default(),
            chunk_size: default_chunk_size(),
            chunk_overlap: default_chunk_overlap(),
            enable_pii_detection: true,
            custom_metadata: HashMap::new(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_document_creation() {
        let tenant_id = TenantId::new();
        let doc = Document::new(
            "/path/to/file.pdf".to_string(),
            SourceType::Filesystem,
            "a".repeat(64),
            tenant_id,
        );

        assert!(doc.is_active());
        assert!(!doc.is_indexed());
        assert_eq!(doc.source_type, SourceType::Filesystem);
        assert_eq!(doc.tenant_id, tenant_id);
    }

    #[test]
    fn test_chunk_creation() {
        let tenant_id = TenantId::new();
        let doc_id = DocumentId::new();

        let chunk = Chunk::new(doc_id, 0, "Hello, world!".to_string(), tenant_id)
            .with_token_count(3)
            .with_embedding_info("all-MiniLM-L6-v2".to_string(), "v1".to_string());

        assert_eq!(chunk.chunk_index, 0);
        assert_eq!(chunk.token_count, Some(3));
        assert_eq!(chunk.embedding_model, Some("all-MiniLM-L6-v2".to_string()));
    }

    #[test]
    fn test_source_type_serialization() {
        let source = SourceType::Filesystem;
        let json = serde_json::to_string(&source).unwrap();
        assert_eq!(json, "\"filesystem\"");

        let deserialized: SourceType = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized, source);
    }

    #[test]
    fn test_visibility_default() {
        let vis = Visibility::default();
        assert_eq!(vis, Visibility::Private);
    }

    #[test]
    fn test_chunking_config_default() {
        let config = ChunkingConfig::default();
        assert_eq!(config.strategy, ChunkingStrategy::Auto);
        assert_eq!(config.chunk_size, 512);
        assert_eq!(config.chunk_overlap, 50);
        assert!(config.enable_pii_detection);
    }

    #[test]
    fn test_acl_metadata_default() {
        let acl = AclMetadata::default();
        assert_eq!(acl.visibility, Visibility::Private);
        assert!(acl.owner_id.is_none());
        assert!(acl.allowed_groups.is_empty());
        assert!(acl.allowed_users.is_empty());
        assert!(acl.denied_groups.is_empty());
        assert!(acl.denied_users.is_empty());
    }

    #[test]
    fn test_acl_metadata_serde_roundtrip() {
        let acl = AclMetadata {
            visibility: Visibility::Group,
            owner_id: Some("user-123".to_string()),
            allowed_groups: vec!["eng".to_string(), "qa".to_string()],
            allowed_users: vec!["user-456".to_string()],
            denied_groups: vec!["contractors".to_string()],
            denied_users: vec!["user-789".to_string()],
        };
        let json = serde_json::to_string(&acl).unwrap();
        let deserialized: AclMetadata = serde_json::from_str(&json).unwrap();
        assert_eq!(acl, deserialized);
    }

    #[test]
    fn test_acl_metadata_to_json_value() {
        let acl = AclMetadata::default();
        let value = acl.to_json_value();
        assert_eq!(value["visibility"], "private");
        assert_eq!(value["allowed_groups"], serde_json::json!([]));
    }
}

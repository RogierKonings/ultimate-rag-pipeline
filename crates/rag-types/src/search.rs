//! Search and retrieval types.
//!
//! Types for hybrid search operations combining semantic and keyword search.

use crate::ids::{ChunkId, DocumentId, TenantId};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use validator::Validate;

/// Search mode for retrieval.
///
/// This is the canonical definition used by both rag-types and rag-retrieval.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum SearchMode {
    /// Combine semantic and keyword search with RRF fusion.
    #[default]
    Hybrid,
    /// Semantic (vector) search only.
    Semantic,
    /// Keyword (BM25) search only.
    Keyword,
}

impl SearchMode {
    /// Check if this mode includes semantic search.
    #[must_use]
    pub const fn uses_semantic(&self) -> bool {
        matches!(self, Self::Semantic | Self::Hybrid)
    }

    /// Check if this mode includes keyword search.
    #[must_use]
    pub const fn uses_keyword(&self) -> bool {
        matches!(self, Self::Keyword | Self::Hybrid)
    }
}

impl std::fmt::Display for SearchMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Hybrid => write!(f, "hybrid"),
            Self::Semantic => write!(f, "semantic"),
            Self::Keyword => write!(f, "keyword"),
        }
    }
}

/// Search request parameters.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
pub struct SearchRequest {
    /// The search query
    #[validate(length(min = 1, max = 2000))]
    pub query: String,

    /// Search mode
    #[serde(default)]
    pub mode: SearchMode,

    /// Number of results to return
    #[validate(range(min = 1, max = 100))]
    #[serde(default = "default_top_k")]
    pub top_k: u32,

    /// Weight for semantic search (0.0-1.0)
    #[validate(range(min = 0.0, max = 1.0))]
    #[serde(default = "default_semantic_weight")]
    pub semantic_weight: f32,

    /// Weight for keyword search (0.0-1.0)
    #[validate(range(min = 0.0, max = 1.0))]
    #[serde(default = "default_keyword_weight")]
    pub keyword_weight: f32,

    /// Whether to rerank results
    #[serde(default)]
    pub rerank: bool,

    /// Number of candidates to rerank
    #[validate(range(min = 1, max = 100))]
    #[serde(default = "default_rerank_top_k")]
    pub rerank_top_k: u32,

    /// Metadata filters
    #[serde(default)]
    pub filters: Option<HashMap<String, serde_json::Value>>,

    /// Minimum score threshold (0.0-1.0)
    #[validate(range(min = 0.0, max = 1.0))]
    #[serde(default)]
    pub min_score: f32,

    /// Include metadata in results
    #[serde(default = "default_true")]
    pub include_metadata: bool,

    /// Include highlights in results
    #[serde(default = "default_true")]
    pub include_highlights: bool,
}

const fn default_top_k() -> u32 {
    10
}

const fn default_semantic_weight() -> f32 {
    0.7
}

const fn default_keyword_weight() -> f32 {
    0.3
}

const fn default_rerank_top_k() -> u32 {
    20
}

const fn default_true() -> bool {
    true
}

impl Default for SearchRequest {
    fn default() -> Self {
        Self {
            query: String::new(),
            mode: SearchMode::default(),
            top_k: default_top_k(),
            semantic_weight: default_semantic_weight(),
            keyword_weight: default_keyword_weight(),
            rerank: false,
            rerank_top_k: default_rerank_top_k(),
            filters: None,
            min_score: 0.0,
            include_metadata: true,
            include_highlights: true,
        }
    }
}

/// A retrieved chunk from search.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RetrievedChunk {
    /// Chunk identifier
    pub chunk_id: ChunkId,

    /// Parent document identifier
    pub document_id: DocumentId,

    /// Chunk content
    pub content: String,

    /// Combined score (0.0-1.0)
    pub score: f32,

    /// Document title
    pub title: Option<String>,

    /// Source URI
    pub source: Option<String>,

    /// Source type
    pub source_type: Option<String>,

    /// Position within document
    pub chunk_index: u32,

    /// Total chunks in document
    pub total_chunks: Option<u32>,

    /// Creation timestamp
    pub created_at: Option<DateTime<Utc>>,

    /// Update timestamp
    pub updated_at: Option<DateTime<Utc>>,

    /// Semantic search score
    pub semantic_score: Option<f32>,

    /// Keyword search score
    pub keyword_score: Option<f32>,

    /// Reranker score
    pub rerank_score: Option<f32>,

    /// Additional metadata
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,

    /// Highlighted snippets
    #[serde(default)]
    pub highlights: Vec<String>,
}

impl RetrievedChunk {
    /// Create a new retrieved chunk with minimal required fields.
    #[must_use]
    pub fn new(chunk_id: ChunkId, document_id: DocumentId, content: String, score: f32) -> Self {
        Self {
            chunk_id,
            document_id,
            content,
            score,
            title: None,
            source: None,
            source_type: None,
            chunk_index: 0,
            total_chunks: None,
            created_at: None,
            updated_at: None,
            semantic_score: None,
            keyword_score: None,
            rerank_score: None,
            metadata: HashMap::new(),
            highlights: Vec::new(),
        }
    }
}

/// Search performance metrics.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SearchMetrics {
    /// Query preprocessing time in ms
    pub query_preprocessing_ms: f64,

    /// Embedding generation time in ms
    pub embedding_ms: Option<f64>,

    /// Semantic search time in ms
    pub semantic_search_ms: Option<f64>,

    /// Keyword search time in ms
    pub keyword_search_ms: Option<f64>,

    /// Fusion time in ms
    pub fusion_ms: Option<f64>,

    /// Reranking time in ms
    pub rerank_ms: Option<f64>,

    /// Total search time in ms
    pub total_ms: f64,

    /// Number of semantic search results
    pub semantic_results_count: u32,

    /// Number of keyword search results
    pub keyword_results_count: u32,

    /// Number of results after fusion
    pub fused_results_count: u32,

    /// Final number of results returned
    pub final_results_count: u32,
}

/// Debug information for search operations.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SearchDebugInfo {
    /// Semantic search candidates
    pub semantic_candidates: u32,

    /// Keyword search candidates
    pub keyword_candidates: u32,

    /// Results after fusion
    pub after_fusion: u32,

    /// Results after reranking
    pub after_rerank: u32,

    /// Results after ACL filtering
    pub after_acl: u32,

    /// Preprocessing latency
    pub preprocessing_latency_ms: f64,

    /// Embedding latency
    pub embedding_latency_ms: f64,

    /// Semantic search latency
    pub semantic_search_latency_ms: f64,

    /// Keyword search latency
    pub keyword_search_latency_ms: f64,

    /// Fusion latency
    pub fusion_latency_ms: f64,

    /// Rerank latency
    pub rerank_latency_ms: f64,

    /// ACL filter latency
    pub acl_filter_latency_ms: f64,

    /// Total latency
    pub total_latency_ms: f64,

    /// Embedding model used
    pub embedding_model: Option<String>,

    /// Rerank model used
    pub rerank_model: Option<String>,

    /// Fusion method
    #[serde(default = "default_fusion_method")]
    pub fusion_method: String,

    /// Semantic weight used
    #[serde(default = "default_semantic_weight")]
    pub semantic_weight: f32,

    /// Keyword weight used
    #[serde(default = "default_keyword_weight")]
    pub keyword_weight: f32,

    /// RRF constant k
    #[serde(default = "default_rrf_k")]
    pub rrf_k: u32,
}

fn default_fusion_method() -> String {
    "rrf".to_string()
}

const fn default_rrf_k() -> u32 {
    60
}

/// Complete search result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchResult {
    /// Retrieved chunks
    pub results: Vec<RetrievedChunk>,

    /// Total matching results (before `top_k` limit)
    pub total_results: u32,

    /// Original query
    pub query: String,

    /// Search mode used
    pub mode: SearchMode,

    /// Performance metrics
    pub metrics: SearchMetrics,

    /// Unique query identifier
    pub query_id: uuid::Uuid,

    /// Processing timestamp
    pub processed_at: DateTime<Utc>,

    /// Debug information (if requested)
    pub debug: Option<SearchDebugInfo>,

    /// Degradation mode active (if any components failed)
    pub degradation_mode: Option<String>,

    /// Components used in search
    #[serde(default)]
    pub components_used: Vec<String>,
}

impl SearchResult {
    /// Create a new search result.
    #[must_use]
    pub fn new(
        results: Vec<RetrievedChunk>,
        query: String,
        mode: SearchMode,
        metrics: SearchMetrics,
    ) -> Self {
        #[allow(clippy::cast_possible_truncation)]
        let total_results = results.len() as u32;
        Self {
            results,
            total_results,
            query,
            mode,
            metrics,
            query_id: uuid::Uuid::new_v4(),
            processed_at: Utc::now(),
            debug: None,
            degradation_mode: None,
            components_used: Vec::new(),
        }
    }
}

/// ACL context for filtering search results.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AclContext {
    /// Tenant ID
    pub tenant_id: TenantId,

    /// User ID (optional for anonymous queries)
    pub user_id: Option<crate::ids::UserId>,

    /// Groups the user belongs to
    #[serde(default)]
    pub user_groups: Vec<crate::ids::GroupId>,

    /// Whether the user is an admin (bypasses ACL)
    #[serde(default)]
    pub is_admin: bool,
}

impl AclContext {
    /// Create a new ACL context.
    #[must_use]
    pub const fn new(tenant_id: TenantId) -> Self {
        Self {
            tenant_id,
            user_id: None,
            user_groups: Vec::new(),
            is_admin: false,
        }
    }

    /// Create an admin ACL context.
    #[must_use]
    pub const fn admin(tenant_id: TenantId) -> Self {
        Self {
            tenant_id,
            user_id: None,
            user_groups: Vec::new(),
            is_admin: true,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_search_mode_default() {
        assert_eq!(SearchMode::default(), SearchMode::Hybrid);
    }

    #[test]
    fn test_search_request_defaults() {
        let request = SearchRequest::default();
        assert_eq!(request.top_k, 10);
        assert!((request.semantic_weight - 0.7).abs() < f32::EPSILON);
        assert!((request.keyword_weight - 0.3).abs() < f32::EPSILON);
        assert!(!request.rerank);
    }

    #[test]
    fn test_retrieved_chunk_creation() {
        let chunk = RetrievedChunk::new(
            ChunkId::new(),
            DocumentId::new(),
            "Test content".to_string(),
            0.85,
        );

        assert_eq!(chunk.content, "Test content");
        assert!((chunk.score - 0.85).abs() < f32::EPSILON);
    }

    #[test]
    fn test_acl_context_admin() {
        let tenant_id = TenantId::new();
        let ctx = AclContext::admin(tenant_id);
        assert!(ctx.is_admin);
        assert_eq!(ctx.tenant_id, tenant_id);
    }

    #[test]
    fn test_search_mode_serialization() {
        let mode = SearchMode::Hybrid;
        let json = serde_json::to_string(&mode).unwrap();
        assert_eq!(json, "\"hybrid\"");

        let deserialized: SearchMode = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized, mode);
    }
}

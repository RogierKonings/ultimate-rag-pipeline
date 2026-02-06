//! Core types for the retrieval service.
//!
//! This module defines the fundamental types used throughout the retrieval
//! pipeline, including search modes, query types, visibility controls,
//! user context, and result structures.

pub use rag_types::Visibility;
use rag_types::SearchMode;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

/// Query type for intent classification and query preprocessing.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum QueryType {
    /// Simple factual query (who, what, when, where).
    Simple,
    /// Complex question requiring reasoning.
    #[default]
    Question,
    /// Semantic similarity search.
    Semantic,
    /// Hybrid search with both semantic and keyword components.
    Hybrid,
}

impl QueryType {
    /// Get the recommended search mode for this query type.
    #[must_use]
    pub const fn recommended_search_mode(&self) -> SearchMode {
        match self {
            Self::Simple => SearchMode::Keyword,
            Self::Question | Self::Hybrid => SearchMode::Hybrid,
            Self::Semantic => SearchMode::Semantic,
        }
    }
}

/// User context for ACL enforcement during retrieval.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserContext {
    /// Unique user identifier.
    pub user_id: Uuid,
    /// Tenant the user belongs to.
    pub tenant_id: Uuid,
    /// Groups the user is a member of.
    #[serde(default)]
    pub groups: Vec<String>,
    /// Roles assigned to the user.
    #[serde(default)]
    pub roles: Vec<String>,
    /// Whether the user has admin privileges.
    #[serde(default)]
    pub is_admin: bool,
}

impl UserContext {
    /// Create a new user context.
    #[must_use]
    pub fn new(user_id: Uuid, tenant_id: Uuid) -> Self {
        Self {
            user_id,
            tenant_id,
            groups: Vec::new(),
            roles: Vec::new(),
            is_admin: false,
        }
    }

    /// Add groups to the user context.
    #[must_use]
    pub fn with_groups(mut self, groups: Vec<String>) -> Self {
        self.groups = groups;
        self
    }

    /// Add roles to the user context.
    #[must_use]
    pub fn with_roles(mut self, roles: Vec<String>) -> Self {
        self.roles = roles;
        self
    }

    /// Set admin flag.
    #[must_use]
    pub const fn with_admin(mut self, is_admin: bool) -> Self {
        self.is_admin = is_admin;
        self
    }

    /// Check if user can access a document with the given visibility and allowed groups.
    ///
    /// # Important Limitation
    ///
    /// **This method does NOT handle private document ownership verification.**
    /// For documents with [`Visibility::Private`], this method always returns `false`
    /// (unless the user is an admin), because it does not have access to the document's
    /// `owner_id` to verify ownership.
    ///
    /// Callers must handle private document ownership checks separately by comparing
    /// `self.user_id` against the document's owner ID before or after calling this method.
    ///
    /// # Returns
    ///
    /// - `true` if the user has admin privileges
    /// - `true` for [`Visibility::Public`] documents
    /// - `true` for [`Visibility::Tenant`] documents (tenant filtering is done at query level)
    /// - `false` for [`Visibility::Private`] documents (ownership must be checked separately)
    /// - For [`Visibility::Group`], returns `true` if the user belongs to any allowed group
    #[must_use]
    pub fn can_access(&self, visibility: Visibility, allowed_groups: &[String]) -> bool {
        if self.is_admin {
            return true;
        }

        match visibility {
            Visibility::Public => true,
            Visibility::Tenant => true, // Tenant filtering is done at query level
            Visibility::Private => false, // Private docs require owner check (not done here)
            Visibility::Group => {
                // Check if user is in any of the allowed groups
                self.groups.iter().any(|g| allowed_groups.contains(g))
            }
        }
    }
}

/// A single retrieval result with all associated metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RetrievalResult {
    /// Unique chunk identifier.
    pub chunk_id: String,
    /// Parent document identifier.
    pub document_id: String,
    /// The actual content of the chunk.
    pub content: String,
    /// Combined/final score after all processing.
    pub score: f32,

    // Document metadata
    /// Document title.
    #[serde(default)]
    pub title: Option<String>,
    /// Source URI of the document.
    #[serde(default)]
    pub source_uri: Option<String>,
    /// Index of this chunk within the document.
    pub chunk_index: u32,
    /// Total number of chunks in the document.
    #[serde(default)]
    pub total_chunks: Option<u32>,

    // Score breakdown
    /// Score from semantic (vector) search.
    #[serde(default)]
    pub semantic_score: Option<f32>,
    /// Score from keyword (BM25) search.
    #[serde(default)]
    pub keyword_score: Option<f32>,
    /// Score from cross-encoder reranking.
    #[serde(default)]
    pub rerank_score: Option<f32>,

    // Additional fields
    /// Arbitrary metadata from the document.
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
    /// Highlighted snippets from keyword search.
    #[serde(default)]
    pub highlights: Vec<String>,

    // ACL fields
    /// Visibility level of the document.
    #[serde(default)]
    pub visibility: Visibility,
    /// Groups that can access this document.
    #[serde(default)]
    pub allowed_groups: Vec<String>,
}

impl RetrievalResult {
    /// Create a new retrieval result with minimal fields.
    #[must_use]
    pub fn new(chunk_id: String, document_id: String, content: String, score: f32) -> Self {
        Self {
            chunk_id,
            document_id,
            content,
            score,
            title: None,
            source_uri: None,
            chunk_index: 0,
            total_chunks: None,
            semantic_score: None,
            keyword_score: None,
            rerank_score: None,
            metadata: HashMap::new(),
            highlights: Vec::new(),
            visibility: Visibility::default(),
            allowed_groups: Vec::new(),
        }
    }

    /// Set the document title.
    #[must_use]
    pub fn with_title(mut self, title: impl Into<String>) -> Self {
        self.title = Some(title.into());
        self
    }

    /// Set the source URI.
    #[must_use]
    pub fn with_source_uri(mut self, uri: impl Into<String>) -> Self {
        self.source_uri = Some(uri.into());
        self
    }

    /// Set semantic score.
    #[must_use]
    pub const fn with_semantic_score(mut self, score: f32) -> Self {
        self.semantic_score = Some(score);
        self
    }

    /// Set keyword score.
    #[must_use]
    pub const fn with_keyword_score(mut self, score: f32) -> Self {
        self.keyword_score = Some(score);
        self
    }

    /// Set rerank score.
    #[must_use]
    pub const fn with_rerank_score(mut self, score: f32) -> Self {
        self.rerank_score = Some(score);
        self
    }
}

/// Timing and count metrics for retrieval operations.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RetrievalMetrics {
    // Timing fields (in milliseconds)
    /// Time spent preprocessing the query.
    pub preprocessing_ms: u64,
    /// Time spent on semantic (vector) search.
    pub semantic_search_ms: u64,
    /// Time spent on keyword (BM25) search.
    pub keyword_search_ms: u64,
    /// Time spent on RRF fusion.
    pub fusion_ms: u64,
    /// Time spent on cross-encoder reranking.
    pub rerank_ms: u64,
    /// Time spent on ACL filtering.
    pub acl_filter_ms: u64,
    /// Total retrieval time.
    pub total_ms: u64,

    // Count fields
    /// Number of results from semantic search before fusion.
    pub semantic_count: usize,
    /// Number of results from keyword search before fusion.
    pub keyword_count: usize,
    /// Number of results after fusion.
    pub fused_count: usize,
    /// Number of results after reranking.
    pub reranked_count: usize,
    /// Number of results after ACL filtering.
    pub final_count: usize,
}

impl RetrievalMetrics {
    /// Create new empty metrics.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Calculate and set the total time from component times.
    ///
    /// This method sums all component timing fields to compute `total_ms`.
    ///
    /// # Important Note on Parallel Operations
    ///
    /// This calculation assumes **sequential execution** of all retrieval stages.
    /// In practice, some operations may run in parallel (e.g., semantic search and
    /// keyword search often execute concurrently). When operations run in parallel,
    /// the actual wall-clock time will be **less than** the sum computed here.
    ///
    /// For accurate wall-clock timing when parallel operations are used, measure
    /// the total elapsed time externally rather than relying on this method.
    pub fn calculate_total(&mut self) {
        self.total_ms = self.preprocessing_ms
            + self.semantic_search_ms
            + self.keyword_search_ms
            + self.fusion_ms
            + self.rerank_ms
            + self.acl_filter_ms;
    }
}

/// Debug information for retrieval operations.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RetrievalDebug {
    /// Detected query type.
    #[serde(default)]
    pub query_type: Option<QueryType>,
    /// Terms added during query expansion.
    #[serde(default)]
    pub expanded_terms: Vec<String>,
    /// Whether HyDE (Hypothetical Document Embedding) was used.
    #[serde(default)]
    pub hyde_used: bool,
    /// Whether results were served from cache.
    #[serde(default)]
    pub cache_hit: bool,
    /// The processed/expanded query sent to search.
    #[serde(default)]
    pub processed_query: Option<String>,
}

impl RetrievalDebug {
    /// Create new debug info.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the query type.
    #[must_use]
    pub const fn with_query_type(mut self, query_type: QueryType) -> Self {
        self.query_type = Some(query_type);
        self
    }

    /// Set expanded terms.
    #[must_use]
    pub fn with_expanded_terms(mut self, terms: Vec<String>) -> Self {
        self.expanded_terms = terms;
        self
    }

    /// Set HyDE flag.
    #[must_use]
    pub const fn with_hyde(mut self, hyde_used: bool) -> Self {
        self.hyde_used = hyde_used;
        self
    }

    /// Set cache hit flag.
    #[must_use]
    pub const fn with_cache_hit(mut self, cache_hit: bool) -> Self {
        self.cache_hit = cache_hit;
        self
    }

    /// Set processed query.
    #[must_use]
    pub fn with_processed_query(mut self, query: impl Into<String>) -> Self {
        self.processed_query = Some(query.into());
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_search_mode_default() {
        let mode = SearchMode::default();
        assert_eq!(mode, SearchMode::Hybrid);
    }

    #[test]
    fn test_search_mode_uses() {
        assert!(SearchMode::Semantic.uses_semantic());
        assert!(!SearchMode::Semantic.uses_keyword());

        assert!(!SearchMode::Keyword.uses_semantic());
        assert!(SearchMode::Keyword.uses_keyword());

        assert!(SearchMode::Hybrid.uses_semantic());
        assert!(SearchMode::Hybrid.uses_keyword());
    }

    #[test]
    fn test_query_type_default() {
        let qt = QueryType::default();
        assert_eq!(qt, QueryType::Question);
    }

    #[test]
    fn test_query_type_recommended_mode() {
        assert_eq!(
            QueryType::Simple.recommended_search_mode(),
            SearchMode::Keyword
        );
        assert_eq!(
            QueryType::Question.recommended_search_mode(),
            SearchMode::Hybrid
        );
        assert_eq!(
            QueryType::Semantic.recommended_search_mode(),
            SearchMode::Semantic
        );
        assert_eq!(
            QueryType::Hybrid.recommended_search_mode(),
            SearchMode::Hybrid
        );
    }

    #[test]
    fn test_visibility_default() {
        let vis = Visibility::default();
        assert_eq!(vis, Visibility::Private);
    }

    #[test]
    fn test_visibility_requires_acl() {
        assert!(!Visibility::Public.requires_acl_check());
        assert!(Visibility::Private.requires_acl_check());
        assert!(Visibility::Group.requires_acl_check());
        assert!(Visibility::Tenant.requires_acl_check());
    }

    #[test]
    fn test_user_context_creation() {
        let user_id = Uuid::new_v4();
        let tenant_id = Uuid::new_v4();

        let ctx = UserContext::new(user_id, tenant_id)
            .with_groups(vec!["engineering".into(), "frontend".into()])
            .with_roles(vec!["developer".into()])
            .with_admin(false);

        assert_eq!(ctx.user_id, user_id);
        assert_eq!(ctx.tenant_id, tenant_id);
        assert_eq!(ctx.groups.len(), 2);
        assert_eq!(ctx.roles.len(), 1);
        assert!(!ctx.is_admin);
    }

    #[test]
    fn test_user_context_can_access() {
        let ctx = UserContext::new(Uuid::new_v4(), Uuid::new_v4())
            .with_groups(vec!["engineering".into()]);

        // Public is always accessible
        assert!(ctx.can_access(Visibility::Public, &[]));

        // Tenant is accessible (tenant filtering done at query level)
        assert!(ctx.can_access(Visibility::Tenant, &[]));

        // Private is not accessible through this method
        assert!(!ctx.can_access(Visibility::Private, &[]));

        // Group access with matching group
        assert!(ctx.can_access(Visibility::Group, &["engineering".into()]));

        // Group access without matching group
        assert!(!ctx.can_access(Visibility::Group, &["sales".into()]));
    }

    #[test]
    fn test_user_context_admin_access() {
        let ctx = UserContext::new(Uuid::new_v4(), Uuid::new_v4()).with_admin(true);

        // Admin can access everything
        assert!(ctx.can_access(Visibility::Public, &[]));
        assert!(ctx.can_access(Visibility::Private, &[]));
        assert!(ctx.can_access(Visibility::Group, &["any_group".into()]));
        assert!(ctx.can_access(Visibility::Tenant, &[]));
    }

    #[test]
    fn test_retrieval_result_creation() {
        let result = RetrievalResult::new(
            "chunk_001".into(),
            "doc_001".into(),
            "Test content".into(),
            0.95,
        )
        .with_title("Test Document")
        .with_source_uri("https://example.com/doc.pdf")
        .with_semantic_score(0.92)
        .with_keyword_score(0.88)
        .with_rerank_score(0.95);

        assert_eq!(result.chunk_id, "chunk_001");
        assert_eq!(result.document_id, "doc_001");
        assert_eq!(result.content, "Test content");
        assert!((result.score - 0.95).abs() < f32::EPSILON);
        assert_eq!(result.title.as_deref(), Some("Test Document"));
        assert_eq!(
            result.source_uri.as_deref(),
            Some("https://example.com/doc.pdf")
        );
        assert!((result.semantic_score.unwrap() - 0.92).abs() < f32::EPSILON);
        assert!((result.keyword_score.unwrap() - 0.88).abs() < f32::EPSILON);
        assert!((result.rerank_score.unwrap() - 0.95).abs() < f32::EPSILON);
    }

    #[test]
    fn test_retrieval_metrics() {
        let mut metrics = RetrievalMetrics::new();
        metrics.preprocessing_ms = 10;
        metrics.semantic_search_ms = 50;
        metrics.keyword_search_ms = 30;
        metrics.fusion_ms = 5;
        metrics.rerank_ms = 150;
        metrics.acl_filter_ms = 5;
        metrics.calculate_total();

        assert_eq!(metrics.total_ms, 250);
    }

    #[test]
    fn test_retrieval_debug() {
        let debug = RetrievalDebug::new()
            .with_query_type(QueryType::Question)
            .with_expanded_terms(vec!["term1".into(), "term2".into()])
            .with_hyde(true)
            .with_cache_hit(false)
            .with_processed_query("expanded query");

        assert_eq!(debug.query_type, Some(QueryType::Question));
        assert_eq!(debug.expanded_terms.len(), 2);
        assert!(debug.hyde_used);
        assert!(!debug.cache_hit);
        assert_eq!(debug.processed_query.as_deref(), Some("expanded query"));
    }

    #[test]
    fn test_search_mode_serialization() {
        let mode = SearchMode::Hybrid;
        let json = serde_json::to_string(&mode).unwrap();
        assert_eq!(json, r#""hybrid""#);

        let deserialized: SearchMode = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized, SearchMode::Hybrid);
    }

    #[test]
    fn test_query_type_serialization() {
        let qt = QueryType::Question;
        let json = serde_json::to_string(&qt).unwrap();
        assert_eq!(json, r#""question""#);

        let deserialized: QueryType = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized, QueryType::Question);
    }

    #[test]
    fn test_visibility_serialization() {
        let vis = Visibility::Group;
        let json = serde_json::to_string(&vis).unwrap();
        assert_eq!(json, r#""group""#);

        let deserialized: Visibility = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized, Visibility::Group);
    }
}

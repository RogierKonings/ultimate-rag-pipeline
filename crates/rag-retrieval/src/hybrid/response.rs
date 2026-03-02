//! Response types for hybrid search operations.
//!
//! This module provides the `HybridSearchResponse` type that encapsulates the
//! results of a hybrid search along with metadata about the search operation.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

use crate::fusion::{FusedResult, FusionMethod};
use crate::types::{FullAcl, Visibility};

/// A hybrid search result with enriched content data.
///
/// This struct extends `FusedResult` with additional content and metadata fields
/// that are useful for presenting search results to users.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HybridSearchResult {
    /// Unique chunk identifier.
    pub chunk_id: Uuid,

    /// Parent document identifier.
    pub document_id: Uuid,

    /// The actual content of the chunk.
    pub content: String,

    /// Final fused score.
    pub fused_score: f32,

    /// Original score from semantic search (if present).
    #[serde(default)]
    pub semantic_score: Option<f32>,

    /// Original score from keyword search (if present).
    #[serde(default)]
    pub keyword_score: Option<f32>,

    /// Rank in semantic results (1-based, None if not in semantic results).
    #[serde(default)]
    pub semantic_rank: Option<usize>,

    /// Rank in keyword results (1-based, None if not in keyword results).
    #[serde(default)]
    pub keyword_rank: Option<usize>,

    /// Document title (if available).
    #[serde(default)]
    pub title: Option<String>,

    /// Source URI of the document (if available).
    #[serde(default)]
    pub source_uri: Option<String>,

    /// Index of this chunk within the document.
    #[serde(default)]
    pub chunk_index: u32,

    /// Visibility level of the document.
    #[serde(default)]
    pub visibility: Visibility,

    /// Groups that can access this document.
    #[serde(default)]
    pub allowed_groups: Vec<String>,

    /// Document owner ID.
    #[serde(default)]
    pub owner_id: Option<String>,

    /// Individual users with access.
    #[serde(default)]
    pub allowed_users: Vec<String>,

    /// Groups explicitly denied.
    #[serde(default)]
    pub denied_groups: Vec<String>,

    /// Users explicitly denied.
    #[serde(default)]
    pub denied_users: Vec<String>,

    /// Highlighted text fragments from keyword search.
    #[serde(default)]
    pub highlights: Vec<String>,

    /// Additional metadata from the document.
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

impl HybridSearchResult {
    /// Create a new hybrid search result with minimal fields.
    #[must_use]
    pub fn new(chunk_id: Uuid, document_id: Uuid, content: String, fused_score: f32) -> Self {
        Self {
            chunk_id,
            document_id,
            content,
            fused_score,
            semantic_score: None,
            keyword_score: None,
            semantic_rank: None,
            keyword_rank: None,
            title: None,
            source_uri: None,
            chunk_index: 0,
            visibility: Visibility::default(),
            allowed_groups: Vec::new(),
            owner_id: None,
            allowed_users: Vec::new(),
            denied_groups: Vec::new(),
            denied_users: Vec::new(),
            highlights: Vec::new(),
            metadata: HashMap::new(),
        }
    }

    /// Set the semantic score and rank.
    #[must_use]
    pub const fn with_semantic(mut self, score: f32, rank: usize) -> Self {
        self.semantic_score = Some(score);
        self.semantic_rank = Some(rank);
        self
    }

    /// Set the keyword score and rank.
    #[must_use]
    pub const fn with_keyword(mut self, score: f32, rank: usize) -> Self {
        self.keyword_score = Some(score);
        self.keyword_rank = Some(rank);
        self
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

    /// Set the chunk index.
    #[must_use]
    pub const fn with_chunk_index(mut self, index: u32) -> Self {
        self.chunk_index = index;
        self
    }

    /// Set the visibility level.
    #[must_use]
    pub const fn with_visibility(mut self, visibility: Visibility) -> Self {
        self.visibility = visibility;
        self
    }

    /// Set the allowed groups.
    #[must_use]
    pub fn with_allowed_groups(mut self, groups: Vec<String>) -> Self {
        self.allowed_groups = groups;
        self
    }

    /// Set the owner ID.
    #[must_use]
    pub fn with_owner_id(mut self, owner_id: Option<String>) -> Self {
        self.owner_id = owner_id;
        self
    }

    /// Set the allowed users.
    #[must_use]
    pub fn with_allowed_users(mut self, users: Vec<String>) -> Self {
        self.allowed_users = users;
        self
    }

    /// Set the denied groups.
    #[must_use]
    pub fn with_denied_groups(mut self, groups: Vec<String>) -> Self {
        self.denied_groups = groups;
        self
    }

    /// Set the denied users.
    #[must_use]
    pub fn with_denied_users(mut self, users: Vec<String>) -> Self {
        self.denied_users = users;
        self
    }

    /// Set the highlights.
    #[must_use]
    pub fn with_highlights(mut self, highlights: Vec<String>) -> Self {
        self.highlights = highlights;
        self
    }

    /// Set additional metadata.
    #[must_use]
    pub fn with_metadata(mut self, metadata: HashMap<String, serde_json::Value>) -> Self {
        self.metadata = metadata;
        self
    }

    /// Check if this result appears in both search methods.
    #[must_use]
    pub const fn is_in_both(&self) -> bool {
        self.semantic_rank.is_some() && self.keyword_rank.is_some()
    }

    /// Get the best rank across both search methods.
    #[must_use]
    pub fn best_rank(&self) -> Option<usize> {
        match (self.semantic_rank, self.keyword_rank) {
            (Some(s), Some(k)) => Some(s.min(k)),
            (Some(s), None) => Some(s),
            (None, Some(k)) => Some(k),
            (None, None) => None,
        }
    }

    /// Extract the full ACL fields for post-search filtering.
    #[must_use]
    pub fn to_full_acl(&self) -> FullAcl {
        FullAcl {
            visibility: self.visibility,
            owner_id: self.owner_id.clone(),
            allowed_groups: self.allowed_groups.clone(),
            allowed_users: self.allowed_users.clone(),
            denied_groups: self.denied_groups.clone(),
            denied_users: self.denied_users.clone(),
        }
    }
}

impl From<FusedResult<Uuid>> for HybridSearchResult {
    fn from(result: FusedResult<Uuid>) -> Self {
        Self {
            chunk_id: result.id,
            document_id: Uuid::nil(),
            content: String::new(),
            fused_score: result.fused_score,
            semantic_score: result.semantic_score,
            keyword_score: result.keyword_score,
            semantic_rank: result.semantic_rank,
            keyword_rank: result.keyword_rank,
            title: None,
            source_uri: None,
            chunk_index: 0,
            visibility: Visibility::default(),
            allowed_groups: Vec::new(),
            owner_id: None,
            allowed_users: Vec::new(),
            denied_groups: Vec::new(),
            denied_users: Vec::new(),
            highlights: Vec::new(),
            metadata: HashMap::new(),
        }
    }
}

/// Response from a hybrid search operation.
///
/// This struct contains the search results along with metadata about the
/// search operation, including timing and result counts from each search method.
///
/// # Example
///
/// ```
/// use rag_retrieval::hybrid::HybridSearchResponse;
/// use rag_retrieval::fusion::FusionMethod;
///
/// let response = HybridSearchResponse::new(FusionMethod::Rrf);
///
/// // Check search metadata
/// println!("Found {} semantic, {} keyword results",
///     response.total_semantic,
///     response.total_keyword
/// );
/// println!("Search took {}ms", response.search_time_ms);
/// ```
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HybridSearchResponse {
    /// The fused search results.
    pub results: Vec<HybridSearchResult>,

    /// Total number of results from semantic search before fusion.
    pub total_semantic: usize,

    /// Total number of results from keyword search before fusion.
    pub total_keyword: usize,

    /// Total search time in milliseconds.
    pub search_time_ms: u64,

    /// The fusion method used to combine results.
    pub fusion_method: FusionMethod,

    /// Time spent on semantic search in milliseconds.
    #[serde(default)]
    pub semantic_time_ms: u64,

    /// Time spent on keyword search in milliseconds.
    #[serde(default)]
    pub keyword_time_ms: u64,

    /// Time spent on fusion in milliseconds.
    #[serde(default)]
    pub fusion_time_ms: u64,
}

impl HybridSearchResponse {
    /// Create a new empty response with the specified fusion method.
    #[must_use]
    pub fn new(fusion_method: FusionMethod) -> Self {
        Self {
            results: Vec::new(),
            total_semantic: 0,
            total_keyword: 0,
            search_time_ms: 0,
            fusion_method,
            semantic_time_ms: 0,
            keyword_time_ms: 0,
            fusion_time_ms: 0,
        }
    }

    /// Set the results.
    #[must_use]
    pub fn with_results(mut self, results: Vec<HybridSearchResult>) -> Self {
        self.results = results;
        self
    }

    /// Set the total semantic result count.
    #[must_use]
    pub const fn with_total_semantic(mut self, count: usize) -> Self {
        self.total_semantic = count;
        self
    }

    /// Set the total keyword result count.
    #[must_use]
    pub const fn with_total_keyword(mut self, count: usize) -> Self {
        self.total_keyword = count;
        self
    }

    /// Set the total search time in milliseconds.
    #[must_use]
    pub const fn with_search_time_ms(mut self, time_ms: u64) -> Self {
        self.search_time_ms = time_ms;
        self
    }

    /// Set the semantic search time in milliseconds.
    #[must_use]
    pub const fn with_semantic_time_ms(mut self, time_ms: u64) -> Self {
        self.semantic_time_ms = time_ms;
        self
    }

    /// Set the keyword search time in milliseconds.
    #[must_use]
    pub const fn with_keyword_time_ms(mut self, time_ms: u64) -> Self {
        self.keyword_time_ms = time_ms;
        self
    }

    /// Set the fusion time in milliseconds.
    #[must_use]
    pub const fn with_fusion_time_ms(mut self, time_ms: u64) -> Self {
        self.fusion_time_ms = time_ms;
        self
    }

    /// Get the number of results.
    #[must_use]
    pub fn len(&self) -> usize {
        self.results.len()
    }

    /// Check if there are no results.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.results.is_empty()
    }

    /// Get the results as a slice.
    #[must_use]
    pub fn results(&self) -> &[HybridSearchResult] {
        &self.results
    }

    /// Get the number of results that appear in both search methods.
    #[must_use]
    pub fn count_in_both(&self) -> usize {
        self.results.iter().filter(|r| r.is_in_both()).count()
    }

    /// Take the results, consuming the response.
    #[must_use]
    pub fn into_results(self) -> Vec<HybridSearchResult> {
        self.results
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hybrid_search_result_creation() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let result = HybridSearchResult::new(chunk_id, document_id, "Test content".into(), 0.95)
            .with_semantic(0.92, 1)
            .with_keyword(0.88, 3)
            .with_title("Test Document")
            .with_source_uri("https://example.com/doc.pdf")
            .with_chunk_index(2)
            .with_visibility(Visibility::Group)
            .with_allowed_groups(vec!["engineering".into()])
            .with_highlights(vec!["<em>test</em> content".into()]);

        assert_eq!(result.chunk_id, chunk_id);
        assert_eq!(result.document_id, document_id);
        assert_eq!(result.content, "Test content");
        assert!((result.fused_score - 0.95).abs() < f32::EPSILON);
        assert_eq!(result.semantic_score, Some(0.92));
        assert_eq!(result.semantic_rank, Some(1));
        assert_eq!(result.keyword_score, Some(0.88));
        assert_eq!(result.keyword_rank, Some(3));
        assert_eq!(result.title.as_deref(), Some("Test Document"));
        assert!(result.is_in_both());
        assert_eq!(result.best_rank(), Some(1));
    }

    #[test]
    fn test_hybrid_search_result_single_source() {
        let result = HybridSearchResult::new(Uuid::new_v4(), Uuid::new_v4(), "Content".into(), 0.9)
            .with_semantic(0.9, 2);

        assert!(!result.is_in_both());
        assert_eq!(result.best_rank(), Some(2));
    }

    #[test]
    fn test_hybrid_search_result_from_fused() {
        let chunk_id = Uuid::new_v4();
        let fused: FusedResult<Uuid> = FusedResult::new(chunk_id, 0.85)
            .with_semantic(0.9, 1)
            .with_keyword(0.8, 2);

        let result: HybridSearchResult = fused.into();

        assert_eq!(result.chunk_id, chunk_id);
        assert!((result.fused_score - 0.85).abs() < f32::EPSILON);
        assert_eq!(result.semantic_score, Some(0.9));
        assert_eq!(result.semantic_rank, Some(1));
        assert_eq!(result.keyword_score, Some(0.8));
        assert_eq!(result.keyword_rank, Some(2));
    }

    #[test]
    fn test_hybrid_search_response_creation() {
        let response = HybridSearchResponse::new(FusionMethod::Rrf)
            .with_total_semantic(50)
            .with_total_keyword(45)
            .with_search_time_ms(150)
            .with_semantic_time_ms(30)
            .with_keyword_time_ms(25)
            .with_fusion_time_ms(5);

        assert_eq!(response.total_semantic, 50);
        assert_eq!(response.total_keyword, 45);
        assert_eq!(response.search_time_ms, 150);
        assert_eq!(response.semantic_time_ms, 30);
        assert_eq!(response.keyword_time_ms, 25);
        assert_eq!(response.fusion_time_ms, 5);
        assert_eq!(response.fusion_method, FusionMethod::Rrf);
        assert!(response.is_empty());
    }

    #[test]
    fn test_hybrid_search_response_with_results() {
        let results = vec![
            HybridSearchResult::new(Uuid::new_v4(), Uuid::new_v4(), "Result 1".into(), 0.95)
                .with_semantic(0.92, 1)
                .with_keyword(0.88, 2),
            HybridSearchResult::new(Uuid::new_v4(), Uuid::new_v4(), "Result 2".into(), 0.85)
                .with_semantic(0.85, 3),
        ];

        let response = HybridSearchResponse::new(FusionMethod::Linear).with_results(results);

        assert_eq!(response.len(), 2);
        assert!(!response.is_empty());
        assert_eq!(response.count_in_both(), 1);
    }

    #[test]
    fn test_hybrid_search_response_serialization() {
        let response = HybridSearchResponse::new(FusionMethod::Dbsf)
            .with_total_semantic(25)
            .with_total_keyword(30)
            .with_search_time_ms(100);

        let json = serde_json::to_string(&response).unwrap();
        assert!(json.contains("\"total_semantic\":25"));
        assert!(json.contains("\"total_keyword\":30"));
        assert!(json.contains("\"dbsf\""));

        let deserialized: HybridSearchResponse = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.total_semantic, 25);
        assert_eq!(deserialized.total_keyword, 30);
        assert_eq!(deserialized.fusion_method, FusionMethod::Dbsf);
    }

    #[test]
    fn test_hybrid_search_result_serialization() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let result = HybridSearchResult::new(chunk_id, document_id, "Test content".into(), 0.9)
            .with_title("Test Title")
            .with_visibility(Visibility::Group);

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains(&chunk_id.to_string()));
        assert!(json.contains("Test Title"));
        assert!(json.contains("\"group\""));

        let deserialized: HybridSearchResult = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.chunk_id, chunk_id);
        assert_eq!(deserialized.title, Some("Test Title".into()));
        assert_eq!(deserialized.visibility, Visibility::Group);
    }
}

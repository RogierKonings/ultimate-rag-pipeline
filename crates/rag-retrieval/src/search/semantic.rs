//! Semantic search using Qdrant vector store.
//!
//! This module provides semantic (vector similarity) search functionality
//! by wrapping the Qdrant vector store client with additional features like
//! tenant isolation, ACL filtering, and multi-query search.

use std::collections::HashMap;
use std::sync::Arc;

use futures::future::try_join_all;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::{debug, instrument};
use uuid::Uuid;

use rag_vectorstore::{
    Condition, Filter, FilterBuilder, SearchParams, SearchRequest, ScoredPoint, VectorStoreClient,
    VectorStoreConfig,
};

use crate::error::{RetrievalError, Result};
use crate::fusion::ScoredItem;
use crate::types::{UserContext, Visibility};

use super::SemanticSearchConfig;

/// A semantic search result with all metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SemanticResult {
    /// Unique chunk identifier.
    pub chunk_id: Uuid,

    /// Parent document identifier.
    pub document_id: Uuid,

    /// Similarity score (normalized 0-1, higher is better).
    pub score: f32,

    /// The actual content of the chunk.
    pub content: String,

    /// Document title (if available).
    #[serde(default)]
    pub title: Option<String>,

    /// Source URI of the document (if available).
    #[serde(default)]
    pub source_uri: Option<String>,

    /// Index of this chunk within the document.
    pub chunk_index: u32,

    /// Visibility level of the document.
    #[serde(default)]
    pub visibility: Visibility,

    /// Groups that can access this document.
    #[serde(default)]
    pub allowed_groups: Vec<String>,

    /// Additional metadata from the document.
    #[serde(default)]
    pub metadata: HashMap<String, Value>,
}

impl SemanticResult {
    /// Create a new semantic result with minimal fields.
    #[must_use]
    pub fn new(chunk_id: Uuid, document_id: Uuid, score: f32, content: String) -> Self {
        Self {
            chunk_id,
            document_id,
            score,
            content,
            title: None,
            source_uri: None,
            chunk_index: 0,
            visibility: Visibility::default(),
            allowed_groups: Vec::new(),
            metadata: HashMap::new(),
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

    /// Set the chunk index.
    #[must_use]
    pub const fn with_chunk_index(mut self, index: u32) -> Self {
        self.chunk_index = index;
        self
    }

    /// Set the visibility.
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

    /// Set additional metadata.
    #[must_use]
    pub fn with_metadata(mut self, metadata: HashMap<String, Value>) -> Self {
        self.metadata = metadata;
        self
    }
}

/// Implement conversion to `ScoredItem` for fusion compatibility.
impl From<SemanticResult> for ScoredItem<Uuid> {
    fn from(result: SemanticResult) -> Self {
        Self::new(result.chunk_id, result.score)
    }
}

impl From<&SemanticResult> for ScoredItem<Uuid> {
    fn from(result: &SemanticResult) -> Self {
        Self::new(result.chunk_id, result.score)
    }
}

/// Additional filters for search operations.
#[derive(Debug, Clone, Default)]
pub struct SearchFilters {
    /// Filter by source type (e.g., "pdf", "web", "api").
    pub source_type: Option<String>,

    /// Filter by document ID.
    pub document_id: Option<Uuid>,

    /// Filter by specific groups.
    pub groups: Option<Vec<String>>,

    /// Additional key-value filters.
    pub custom: HashMap<String, String>,
}

impl SearchFilters {
    /// Create empty filters.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Filter by source type.
    #[must_use]
    pub fn with_source_type(mut self, source_type: impl Into<String>) -> Self {
        self.source_type = Some(source_type.into());
        self
    }

    /// Filter by document ID.
    #[must_use]
    pub const fn with_document_id(mut self, document_id: Uuid) -> Self {
        self.document_id = Some(document_id);
        self
    }

    /// Filter by groups.
    #[must_use]
    pub fn with_groups(mut self, groups: Vec<String>) -> Self {
        self.groups = Some(groups);
        self
    }

    /// Add a custom filter.
    #[must_use]
    pub fn with_custom(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.custom.insert(key.into(), value.into());
        self
    }
}

/// Semantic searcher using Qdrant vector store.
#[derive(Clone)]
pub struct SemanticSearcher {
    client: Arc<VectorStoreClient>,
    config: SemanticSearchConfig,
}

impl SemanticSearcher {
    /// Create a new semantic searcher by connecting to Qdrant.
    ///
    /// # Errors
    ///
    /// Returns an error if connection to Qdrant fails.
    pub async fn new(config: &SemanticSearchConfig) -> Result<Self> {
        let store_config = VectorStoreConfig::new(&config.url)
            .with_default_collection(&config.collection)
            .with_timeout(config.timeout());

        let client = VectorStoreClient::connect(&store_config)
            .await
            .map_err(RetrievalError::from)?;

        Ok(Self {
            client: Arc::new(client),
            config: config.clone(),
        })
    }

    /// Create a semantic searcher from an existing Qdrant client.
    #[must_use]
    pub fn from_client(client: VectorStoreClient, config: SemanticSearchConfig) -> Self {
        Self {
            client: Arc::new(client),
            config,
        }
    }

    /// Perform semantic search with a single embedding.
    ///
    /// # Arguments
    ///
    /// * `embedding` - Query embedding vector
    /// * `user_context` - User context for tenant isolation and ACL
    /// * `filters` - Optional additional filters
    /// * `top_k` - Override for number of results (uses config default if None)
    ///
    /// # Errors
    ///
    /// Returns an error if the search operation fails.
    #[instrument(skip(self, embedding, user_context, filters))]
    pub async fn search(
        &self,
        embedding: &[f32],
        user_context: &UserContext,
        filters: Option<SearchFilters>,
        top_k: Option<usize>,
    ) -> Result<Vec<SemanticResult>> {
        let top_k = top_k.unwrap_or(self.config.top_k);

        // Build the filter
        let filter = self.build_filter(user_context, filters.as_ref());

        // Build search request
        let mut request = SearchRequest::new(embedding.to_vec())
            .with_limit(top_k as u64)
            .with_filter(filter)
            .with_params(SearchParams {
                ef: Some(self.config.ef_search),
                exact: false,
            });

        if let Some(threshold) = self.config.score_threshold {
            request = request.with_score_threshold(threshold);
        }

        if !self.config.with_payload {
            request = request.without_payload();
        }

        // Execute search
        let result = self
            .client
            .search(Some(&self.config.collection), request)
            .await
            .map_err(RetrievalError::from)?;

        debug!(
            collection = %self.config.collection,
            results = result.points.len(),
            duration_ms = ?result.duration_ms,
            "Semantic search completed"
        );

        // Convert results
        let semantic_results: Vec<SemanticResult> = result
            .points
            .into_iter()
            .filter_map(|point| self.convert_result(point).ok())
            .collect();

        Ok(semantic_results)
    }

    /// Perform multi-vector search with parallel execution.
    ///
    /// This is useful for query expansion (e.g., multiple reformulations)
    /// where we want to search with multiple embeddings and aggregate results.
    ///
    /// # Arguments
    ///
    /// * `embeddings` - Multiple query embedding vectors
    /// * `user_context` - User context for tenant isolation and ACL
    /// * `filters` - Optional additional filters
    /// * `top_k` - Override for number of results (uses config default if None)
    ///
    /// # Errors
    ///
    /// Returns an error if any search operation fails.
    #[instrument(skip(self, embeddings, user_context, filters), fields(query_count = embeddings.len()))]
    pub async fn search_multi_vector(
        &self,
        embeddings: &[Vec<f32>],
        user_context: &UserContext,
        filters: Option<SearchFilters>,
        top_k: Option<usize>,
    ) -> Result<Vec<SemanticResult>> {
        if embeddings.is_empty() {
            return Ok(Vec::new());
        }

        // Execute searches in parallel
        let futures: Vec<_> = embeddings
            .iter()
            .map(|emb| self.search(emb, user_context, filters.clone(), top_k))
            .collect();

        let results = try_join_all(futures).await?;

        // Aggregate and deduplicate results
        let final_top_k = top_k.unwrap_or(self.config.top_k);
        let aggregated = self.aggregate_results(results, final_top_k);

        debug!(
            query_count = embeddings.len(),
            final_count = aggregated.len(),
            "Multi-vector search completed"
        );

        Ok(aggregated)
    }

    /// Build a Qdrant filter with tenant isolation and optional additional filters.
    #[allow(clippy::unused_self)]
    fn build_filter(
        &self,
        user_context: &UserContext,
        filters: Option<&SearchFilters>,
    ) -> Filter {
        let mut builder = FilterBuilder::new();

        // Always filter by tenant
        builder = builder.tenant(user_context.tenant_id.to_string());

        // Add visibility/ACL filter if not admin
        if !user_context.is_admin {
            // For non-admin users, we need to filter by visibility and groups
            // This creates a filter: (visibility = public) OR (user in allowed_groups)
            builder = builder.should(create_visibility_condition("public"));

            if !user_context.groups.is_empty() {
                // Allow documents where user is in allowed_groups
                builder = builder.should(create_groups_condition(&user_context.groups));
            }
        }

        // Apply additional filters
        if let Some(filters) = filters {
            if let Some(ref source_type) = filters.source_type {
                builder = builder.match_string("source_type", source_type.clone());
            }

            if let Some(ref doc_id) = filters.document_id {
                builder = builder.document(doc_id.to_string());
            }

            if let Some(ref groups) = filters.groups {
                if !groups.is_empty() {
                    builder = builder.any_of_strings("allowed_groups", groups.clone());
                }
            }

            for (key, value) in &filters.custom {
                builder = builder.match_string(key.clone(), value.clone());
            }
        }

        builder.build()
    }

    /// Convert a Qdrant `ScoredPoint` to a `SemanticResult`.
    #[allow(clippy::unused_self)]
    fn convert_result(&self, point: ScoredPoint) -> Result<SemanticResult> {
        // Parse chunk_id from point ID
        let chunk_id = Uuid::parse_str(&point.id)
            .map_err(|e| RetrievalError::internal(format!("Invalid chunk_id format: {e}")))?;

        // Extract document_id from payload
        let document_id = point
            .get_string("document_id")
            .and_then(|s| Uuid::parse_str(s).ok())
            .unwrap_or_else(Uuid::nil);

        // Extract content from payload
        let content = point
            .get_string("content")
            .unwrap_or_default()
            .to_string();

        // Extract optional fields
        let title = point.get_string("title").map(String::from);
        let source_uri = point.get_string("source_uri").map(String::from);

        // Extract chunk_index
        #[allow(clippy::cast_possible_truncation)]
        let chunk_index = point
            .get_payload("chunk_index")
            .and_then(Value::as_u64)
            .unwrap_or(0) as u32;

        // Extract visibility
        let visibility = point
            .get_string("visibility")
            .and_then(|v| serde_json::from_str(&format!("\"{v}\"")).ok())
            .unwrap_or_default();

        // Extract allowed_groups
        let allowed_groups = point
            .get_payload("allowed_groups")
            .and_then(Value::as_array)
            .map(|arr| {
                arr.iter()
                    .filter_map(Value::as_str)
                    .map(String::from)
                    .collect()
            })
            .unwrap_or_default();

        // Build metadata from remaining payload fields
        let excluded_keys = [
            "document_id",
            "content",
            "title",
            "source_uri",
            "chunk_index",
            "visibility",
            "allowed_groups",
            "tenant_id",
        ];
        let metadata: HashMap<String, Value> = point
            .payload
            .into_iter()
            .filter(|(k, _)| !excluded_keys.contains(&k.as_str()))
            .collect();

        Ok(SemanticResult {
            chunk_id,
            document_id,
            score: point.score,
            content,
            title,
            source_uri,
            chunk_index,
            visibility,
            allowed_groups,
            metadata,
        })
    }

    /// Aggregate results from multiple queries, deduplicating and re-ranking.
    ///
    /// Uses max score for duplicates and re-sorts by score.
    #[allow(clippy::unused_self)]
    fn aggregate_results(
        &self,
        results_lists: Vec<Vec<SemanticResult>>,
        top_k: usize,
    ) -> Vec<SemanticResult> {
        let mut best_results: HashMap<Uuid, SemanticResult> = HashMap::new();

        for results in results_lists {
            for result in results {
                best_results
                    .entry(result.chunk_id)
                    .and_modify(|existing| {
                        if result.score > existing.score {
                            *existing = result.clone();
                        }
                    })
                    .or_insert(result);
            }
        }

        // Convert to sorted vector
        let mut aggregated: Vec<SemanticResult> = best_results.into_values().collect();
        aggregated.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        // Apply top_k limit
        aggregated.truncate(top_k);

        aggregated
    }

    /// Check if the Qdrant service is healthy.
    ///
    /// # Errors
    ///
    /// Returns an error if the health check fails.
    pub async fn health_check(&self) -> Result<()> {
        self.client
            .health_check()
            .await
            .map_err(RetrievalError::from)
    }

    /// Get information about the collection.
    ///
    /// # Errors
    ///
    /// Returns an error if the collection doesn't exist or info retrieval fails.
    pub async fn get_collection_info(&self) -> Result<CollectionInfo> {
        let info = self
            .client
            .collection_info(&self.config.collection)
            .await
            .map_err(RetrievalError::from)?;

        Ok(CollectionInfo {
            name: info.name,
            points_count: info.points_count,
            vectors_count: info.vectors_count,
        })
    }

    /// Get the collection name.
    #[must_use]
    pub fn collection(&self) -> &str {
        &self.config.collection
    }
}

/// Collection information.
#[derive(Debug, Clone)]
pub struct CollectionInfo {
    /// Collection name.
    pub name: String,
    /// Number of points in the collection.
    pub points_count: u64,
    /// Number of vectors in the collection.
    pub vectors_count: u64,
}

impl std::fmt::Debug for SemanticSearcher {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SemanticSearcher")
            .field("url", &self.config.url)
            .field("collection", &self.config.collection)
            .field("top_k", &self.config.top_k)
            .finish_non_exhaustive()
    }
}

/// Helper function to create a visibility match condition.
fn create_visibility_condition(visibility: &str) -> Condition {
    use rag_vectorstore::qdrant_client::qdrant::{
        condition::ConditionOneOf, r#match::MatchValue, FieldCondition, Match,
    };

    Condition {
        condition_one_of: Some(ConditionOneOf::Field(FieldCondition {
            key: "visibility".into(),
            r#match: Some(Match {
                match_value: Some(MatchValue::Keyword(visibility.into())),
            }),
            ..Default::default()
        })),
    }
}

/// Helper function to create a groups match condition.
fn create_groups_condition(groups: &[String]) -> Condition {
    use rag_vectorstore::qdrant_client::qdrant::{
        condition::ConditionOneOf, r#match::MatchValue, FieldCondition, Match, RepeatedStrings,
    };

    Condition {
        condition_one_of: Some(ConditionOneOf::Field(FieldCondition {
            key: "allowed_groups".into(),
            r#match: Some(Match {
                match_value: Some(MatchValue::Keywords(RepeatedStrings {
                    strings: groups.to_vec(),
                })),
            }),
            ..Default::default()
        })),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_semantic_result_creation() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let result = SemanticResult::new(chunk_id, document_id, 0.95, "Test content".into())
            .with_title("Test Doc")
            .with_source_uri("https://example.com/doc.pdf")
            .with_chunk_index(2)
            .with_visibility(Visibility::Group)
            .with_allowed_groups(vec!["engineering".into()]);

        assert_eq!(result.chunk_id, chunk_id);
        assert_eq!(result.document_id, document_id);
        assert!((result.score - 0.95).abs() < f32::EPSILON);
        assert_eq!(result.content, "Test content");
        assert_eq!(result.title.as_deref(), Some("Test Doc"));
        assert_eq!(
            result.source_uri.as_deref(),
            Some("https://example.com/doc.pdf")
        );
        assert_eq!(result.chunk_index, 2);
        assert_eq!(result.visibility, Visibility::Group);
        assert_eq!(result.allowed_groups, vec!["engineering"]);
    }

    #[test]
    fn test_semantic_result_to_scored_item() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let result = SemanticResult::new(chunk_id, document_id, 0.85, "Content".into());

        let scored: ScoredItem<Uuid> = result.into();
        assert_eq!(scored.id, chunk_id);
        assert!((scored.score - 0.85).abs() < f32::EPSILON);
    }

    #[test]
    fn test_semantic_result_ref_to_scored_item() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let result = SemanticResult::new(chunk_id, document_id, 0.85, "Content".into());

        let scored: ScoredItem<Uuid> = (&result).into();
        assert_eq!(scored.id, chunk_id);
        assert!((scored.score - 0.85).abs() < f32::EPSILON);
    }

    #[test]
    fn test_search_filters() {
        let filters = SearchFilters::new()
            .with_source_type("pdf")
            .with_document_id(Uuid::new_v4())
            .with_groups(vec!["eng".into()])
            .with_custom("category", "docs");

        assert_eq!(filters.source_type, Some("pdf".into()));
        assert!(filters.document_id.is_some());
        assert_eq!(filters.groups, Some(vec!["eng".into()]));
        assert_eq!(filters.custom.get("category"), Some(&"docs".into()));
    }

    #[test]
    fn test_semantic_result_serialization() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let result = SemanticResult::new(chunk_id, document_id, 0.9, "Test".into())
            .with_title("Title");

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains(&chunk_id.to_string()));
        assert!(json.contains("Title"));

        let deserialized: SemanticResult = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.chunk_id, chunk_id);
        assert_eq!(deserialized.title, Some("Title".into()));
    }

    #[test]
    fn test_collection_info() {
        let info = CollectionInfo {
            name: "documents".into(),
            points_count: 1000,
            vectors_count: 1000,
        };

        assert_eq!(info.name, "documents");
        assert_eq!(info.points_count, 1000);
    }
}

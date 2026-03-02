//! Keyword search using `OpenSearch` BM25.
//!
//! This module provides keyword (BM25) search functionality by wrapping
//! the `OpenSearch` client with additional features like tenant isolation,
//! ACL filtering, score normalization, and multi-query search.

use std::collections::HashMap;
use std::sync::Arc;

use futures::future::try_join_all;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::{debug, instrument};
use uuid::Uuid;

use rag_search::{BM25Request, SearchClient, SearchConfig, SearchHit};

use crate::error::{Result, RetrievalError};
use crate::fusion::ScoredItem;
use crate::types::{UserContext, Visibility};

use super::KeywordSearchConfig;

/// A keyword search result with all metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeywordResult {
    /// Unique chunk identifier.
    pub chunk_id: Uuid,

    /// Parent document identifier.
    pub document_id: Uuid,

    /// Normalized score (0-1, higher is better).
    pub score: f32,

    /// Original BM25 score before normalization.
    pub raw_score: f32,

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

    /// Highlighted text fragments from the search.
    #[serde(default)]
    pub highlights: Vec<String>,

    /// Additional metadata from the document.
    #[serde(default)]
    pub metadata: HashMap<String, Value>,
}

impl KeywordResult {
    /// Create a new keyword result with minimal fields.
    #[must_use]
    pub fn new(
        chunk_id: Uuid,
        document_id: Uuid,
        score: f32,
        raw_score: f32,
        content: String,
    ) -> Self {
        Self {
            chunk_id,
            document_id,
            score,
            raw_score,
            content,
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

    /// Set the highlights.
    #[must_use]
    pub fn with_highlights(mut self, highlights: Vec<String>) -> Self {
        self.highlights = highlights;
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
impl From<KeywordResult> for ScoredItem<Uuid> {
    fn from(result: KeywordResult) -> Self {
        Self::new(result.chunk_id, result.score)
    }
}

impl From<&KeywordResult> for ScoredItem<Uuid> {
    fn from(result: &KeywordResult) -> Self {
        Self::new(result.chunk_id, result.score)
    }
}

/// Additional filters for keyword search operations.
#[derive(Debug, Clone, Default)]
pub struct KeywordSearchFilters {
    /// Filter by source type (e.g., "pdf", "web", "api").
    pub source_type: Option<String>,

    /// Filter by document ID.
    pub document_id: Option<Uuid>,

    /// Filter by specific groups.
    pub groups: Option<Vec<String>>,

    /// Additional key-value filters.
    pub custom: HashMap<String, String>,
}

impl KeywordSearchFilters {
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

/// Keyword searcher using `OpenSearch` BM25.
#[derive(Clone)]
pub struct KeywordSearcher {
    client: Arc<SearchClient>,
    config: KeywordSearchConfig,
}

impl KeywordSearcher {
    /// Create a new keyword searcher by connecting to `OpenSearch`.
    ///
    /// # Errors
    ///
    /// Returns an error if connection to `OpenSearch` fails.
    pub fn new(config: &KeywordSearchConfig) -> Result<Self> {
        let search_config = SearchConfig::new(&config.url)
            .with_default_index(&config.index)
            .with_timeout(config.timeout());

        let client = SearchClient::new(search_config).map_err(RetrievalError::from)?;

        Ok(Self {
            client: Arc::new(client),
            config: config.clone(),
        })
    }

    /// Create a keyword searcher from an existing `OpenSearch` client.
    #[must_use]
    pub const fn from_client(client: Arc<SearchClient>, config: KeywordSearchConfig) -> Self {
        Self { client, config }
    }

    /// Perform keyword search with a single query.
    ///
    /// # Arguments
    ///
    /// * `query` - Query text
    /// * `user_context` - User context for tenant isolation and ACL
    /// * `filters` - Optional additional filters
    /// * `top_k` - Override for number of results (uses config default if None)
    ///
    /// # Errors
    ///
    /// Returns an error if the search operation fails.
    #[instrument(skip(self, user_context, filters))]
    pub async fn search(
        &self,
        query: &str,
        user_context: &UserContext,
        filters: Option<KeywordSearchFilters>,
        top_k: Option<usize>,
    ) -> Result<Vec<KeywordResult>> {
        let top_k = top_k.unwrap_or(self.config.top_k);

        // Build the BM25 request
        let mut request = BM25Request::new(query)
            .with_fields(self.config.fields.clone())
            .with_limit(top_k)
            .with_tenant(user_context.tenant_id.to_string());

        // Enable highlighting if configured
        if self.config.highlight {
            request = request.with_highlight();
        }

        // Apply additional filters
        if let Some(ref filters) = filters {
            if let Some(ref source_type) = filters.source_type {
                request = request.with_filter("source_type", source_type.clone());
            }

            if let Some(ref doc_id) = filters.document_id {
                request = request.with_filter("document_id", doc_id.to_string());
            }

            // Apply groups filter for ACL consistency with semantic search
            if let Some(ref groups) = filters.groups {
                if !groups.is_empty() {
                    // Filter by allowed_groups - documents must have at least one matching group
                    for group in groups {
                        request = request.with_filter("allowed_groups", group.clone());
                    }
                }
            }

            for (key, value) in &filters.custom {
                request = request.with_filter(key.clone(), value.clone());
            }
        }

        // Execute search
        let response = self
            .client
            .search(&self.config.index, &request)
            .await
            .map_err(RetrievalError::from)?;

        debug!(
            index = %self.config.index,
            results = response.hits.len(),
            total = response.total,
            took_ms = response.took_ms,
            "Keyword search completed"
        );

        // Normalize results and convert to KeywordResult
        let results = self.normalize_results(response.hits);

        Ok(results)
    }

    /// Perform multi-query search with parallel execution.
    ///
    /// This is useful for query expansion where multiple query variations
    /// are searched and results aggregated.
    ///
    /// # Arguments
    ///
    /// * `queries` - Multiple query texts
    /// * `user_context` - User context for tenant isolation and ACL
    /// * `filters` - Optional additional filters
    /// * `top_k` - Override for number of results (uses config default if None)
    ///
    /// # Errors
    ///
    /// Returns an error if any search operation fails.
    #[instrument(skip(self, queries, user_context, filters), fields(query_count = queries.len()))]
    pub async fn search_with_expansion(
        &self,
        queries: &[String],
        user_context: &UserContext,
        filters: Option<KeywordSearchFilters>,
        top_k: Option<usize>,
    ) -> Result<Vec<KeywordResult>> {
        if queries.is_empty() {
            return Ok(Vec::new());
        }

        // Execute searches in parallel
        let futures: Vec<_> = queries
            .iter()
            .map(|q| self.search(q, user_context, filters.clone(), top_k))
            .collect();

        let results = try_join_all(futures).await?;

        // Aggregate and deduplicate results
        let final_top_k = top_k.unwrap_or(self.config.top_k);
        let aggregated = self.aggregate_results(results, final_top_k);

        debug!(
            query_count = queries.len(),
            final_count = aggregated.len(),
            "Multi-query keyword search completed"
        );

        Ok(aggregated)
    }

    /// Normalize BM25 scores to the 0-1 range using min-max normalization.
    #[allow(clippy::unused_self)]
    fn normalize_results(&self, hits: Vec<SearchHit>) -> Vec<KeywordResult> {
        if hits.is_empty() {
            return Vec::new();
        }

        // Find min and max scores
        #[allow(clippy::cast_possible_truncation)]
        let min_score = hits
            .iter()
            .map(|h| h.score as f32)
            .fold(f32::INFINITY, f32::min);
        #[allow(clippy::cast_possible_truncation)]
        let max_score = hits
            .iter()
            .map(|h| h.score as f32)
            .fold(f32::NEG_INFINITY, f32::max);
        let range = max_score - min_score;

        // Convert hits to KeywordResult with normalized scores
        hits.into_iter()
            .filter_map(|hit| Self::convert_hit(&hit, min_score, range).ok())
            .collect()
    }

    /// Convert an `OpenSearch` hit to a `KeywordResult`.
    #[allow(clippy::cast_possible_truncation, clippy::too_many_lines)]
    fn convert_hit(hit: &SearchHit, min_score: f32, range: f32) -> Result<KeywordResult> {
        let raw_score = hit.score as f32;

        // Normalize score to 0-1 range
        let score = if range > f32::EPSILON {
            (raw_score - min_score) / range
        } else {
            // All scores are the same, set to 1.0
            1.0
        };

        // Parse chunk_id
        let chunk_id = Self::parse_uuid(&hit.source, "chunk_id", &hit.id)?;

        // Parse document_id
        let document_id = Self::parse_uuid(&hit.source, "document_id", &Uuid::nil().to_string())?;

        // Extract content from source
        let content = hit.get_string("content").unwrap_or_default().to_string();

        // Extract optional fields
        let title = hit.get_string("title").map(String::from);
        let source_uri = hit.get_string("source_uri").map(String::from);

        // Extract chunk_index
        let chunk_index = hit
            .get_field("chunk_index")
            .and_then(Value::as_u64)
            .unwrap_or(0) as u32;

        // Extract visibility
        let visibility = hit
            .get_string("visibility")
            .and_then(|v| serde_json::from_str(&format!("\"{v}\"")).ok())
            .unwrap_or_default();

        // Extract allowed_groups
        let allowed_groups = hit
            .get_field("allowed_groups")
            .and_then(Value::as_array)
            .map(|arr| {
                arr.iter()
                    .filter_map(Value::as_str)
                    .map(String::from)
                    .collect()
            })
            .unwrap_or_default();

        // Extract owner_id
        let owner_id = hit.get_string("owner_id").map(String::from);

        // Extract allowed_users
        let allowed_users = hit
            .get_field("allowed_users")
            .and_then(Value::as_array)
            .map(|arr| {
                arr.iter()
                    .filter_map(Value::as_str)
                    .map(String::from)
                    .collect()
            })
            .unwrap_or_default();

        // Extract denied_groups
        let denied_groups = hit
            .get_field("denied_groups")
            .and_then(Value::as_array)
            .map(|arr| {
                arr.iter()
                    .filter_map(Value::as_str)
                    .map(String::from)
                    .collect()
            })
            .unwrap_or_default();

        // Extract denied_users
        let denied_users = hit
            .get_field("denied_users")
            .and_then(Value::as_array)
            .map(|arr| {
                arr.iter()
                    .filter_map(Value::as_str)
                    .map(String::from)
                    .collect()
            })
            .unwrap_or_default();

        // Extract highlights (flatten all field highlights into a single list)
        let highlights: Vec<String> = hit.highlights.values().flatten().cloned().collect();

        // Build metadata from remaining source fields
        let excluded_keys = [
            "chunk_id",
            "document_id",
            "content",
            "title",
            "source_uri",
            "chunk_index",
            "visibility",
            "allowed_groups",
            "owner_id",
            "allowed_users",
            "denied_groups",
            "denied_users",
            "tenant_id",
        ];
        let metadata: HashMap<String, Value> = hit
            .source
            .as_object()
            .map(|obj| {
                obj.iter()
                    .filter(|(k, _)| !excluded_keys.contains(&k.as_str()))
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect()
            })
            .unwrap_or_default();

        Ok(KeywordResult {
            chunk_id,
            document_id,
            score,
            raw_score,
            content,
            title,
            source_uri,
            chunk_index,
            visibility,
            allowed_groups,
            owner_id,
            allowed_users,
            denied_groups,
            denied_users,
            highlights,
            metadata,
        })
    }

    /// Parse a UUID from a JSON value, with a fallback.
    fn parse_uuid(source: &Value, field: &str, fallback: &str) -> Result<Uuid> {
        let uuid_str = source
            .get(field)
            .and_then(Value::as_str)
            .unwrap_or(fallback);

        Uuid::parse_str(uuid_str)
            .map_err(|e| RetrievalError::internal(format!("Invalid UUID in {field}: {e}")))
    }

    /// Aggregate results from multiple queries, deduplicating and re-ranking.
    ///
    /// Uses max score for duplicates and re-sorts by score.
    #[allow(clippy::unused_self)]
    fn aggregate_results(
        &self,
        results_lists: Vec<Vec<KeywordResult>>,
        top_k: usize,
    ) -> Vec<KeywordResult> {
        let mut best_results: HashMap<Uuid, KeywordResult> = HashMap::new();

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
        let mut aggregated: Vec<KeywordResult> = best_results.into_values().collect();
        aggregated.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        // Apply top_k limit
        aggregated.truncate(top_k);

        aggregated
    }

    /// Get information about the index (stub for now).
    #[must_use]
    pub fn get_index_info(&self) -> IndexInfo {
        IndexInfo {
            name: self.config.index.clone(),
        }
    }

    /// Get the index name.
    #[must_use]
    pub fn index(&self) -> &str {
        &self.config.index
    }

    /// Check if the `OpenSearch` service is healthy.
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
}

/// Index information.
#[derive(Debug, Clone)]
pub struct IndexInfo {
    /// Index name.
    pub name: String,
}

impl std::fmt::Debug for KeywordSearcher {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("KeywordSearcher")
            .field("url", &self.config.url)
            .field("index", &self.config.index)
            .field("top_k", &self.config.top_k)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_keyword_result_creation() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let result = KeywordResult::new(chunk_id, document_id, 0.95, 12.5, "Test content".into())
            .with_title("Test Doc")
            .with_source_uri("https://example.com/doc.pdf")
            .with_chunk_index(2)
            .with_visibility(Visibility::Group)
            .with_allowed_groups(vec!["engineering".into()])
            .with_highlights(vec!["<em>test</em> content".into()]);

        assert_eq!(result.chunk_id, chunk_id);
        assert_eq!(result.document_id, document_id);
        assert!((result.score - 0.95).abs() < f32::EPSILON);
        assert!((result.raw_score - 12.5).abs() < f32::EPSILON);
        assert_eq!(result.content, "Test content");
        assert_eq!(result.title.as_deref(), Some("Test Doc"));
        assert_eq!(
            result.source_uri.as_deref(),
            Some("https://example.com/doc.pdf")
        );
        assert_eq!(result.chunk_index, 2);
        assert_eq!(result.visibility, Visibility::Group);
        assert_eq!(result.allowed_groups, vec!["engineering"]);
        assert_eq!(result.highlights, vec!["<em>test</em> content"]);
    }

    #[test]
    fn test_keyword_result_to_scored_item() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let result = KeywordResult::new(chunk_id, document_id, 0.85, 10.0, "Content".into());

        let scored: ScoredItem<Uuid> = result.into();
        assert_eq!(scored.id, chunk_id);
        assert!((scored.score - 0.85).abs() < f32::EPSILON);
    }

    #[test]
    fn test_keyword_result_ref_to_scored_item() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let result = KeywordResult::new(chunk_id, document_id, 0.85, 10.0, "Content".into());

        let scored: ScoredItem<Uuid> = (&result).into();
        assert_eq!(scored.id, chunk_id);
        assert!((scored.score - 0.85).abs() < f32::EPSILON);
    }

    #[test]
    fn test_keyword_search_filters() {
        let filters = KeywordSearchFilters::new()
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
    fn test_keyword_result_serialization() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let result = KeywordResult::new(chunk_id, document_id, 0.9, 11.2, "Test".into())
            .with_title("Title")
            .with_highlights(vec!["highlight".into()]);

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains(&chunk_id.to_string()));
        assert!(json.contains("Title"));
        assert!(json.contains("highlight"));
        assert!(json.contains("11.2")); // raw_score

        let deserialized: KeywordResult = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.chunk_id, chunk_id);
        assert_eq!(deserialized.title, Some("Title".into()));
        assert!((deserialized.raw_score - 11.2).abs() < f32::EPSILON);
    }

    #[test]
    fn test_index_info() {
        let info = IndexInfo {
            name: "documents".into(),
        };

        assert_eq!(info.name, "documents");
    }
}

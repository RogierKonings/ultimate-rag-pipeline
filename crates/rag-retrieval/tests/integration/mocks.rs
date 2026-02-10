//! Mock implementations for integration testing.
//!
//! This module provides mock implementations of external service clients
//! that can be used to test the retrieval pipeline without requiring
//! actual external services like Qdrant or `OpenSearch`.

use std::collections::HashMap;
use std::sync::Mutex;
use uuid::Uuid;

use rag_retrieval::fusion::ScoredItem;
use rag_retrieval::types::Visibility;

/// Mock result for testing.
#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct MockSearchResult {
    pub chunk_id: Uuid,
    pub document_id: Uuid,
    pub content: String,
    pub score: f32,
    pub title: Option<String>,
    pub source_uri: Option<String>,
    pub chunk_index: u32,
    pub visibility: Visibility,
    pub allowed_groups: Vec<String>,
    pub highlights: Vec<String>,
    pub metadata: HashMap<String, serde_json::Value>,
}

impl MockSearchResult {
    /// Create a new mock search result with minimal fields.
    #[must_use]
    pub fn new(chunk_id: Uuid, document_id: Uuid, content: impl Into<String>, score: f32) -> Self {
        Self {
            chunk_id,
            document_id,
            content: content.into(),
            score,
            title: None,
            source_uri: None,
            chunk_index: 0,
            visibility: Visibility::Public,
            allowed_groups: Vec::new(),
            highlights: Vec::new(),
            metadata: HashMap::new(),
        }
    }

    /// Set the title.
    #[must_use]
    pub fn with_title(mut self, title: impl Into<String>) -> Self {
        self.title = Some(title.into());
        self
    }

    /// Set the visibility.
    #[must_use]
    pub fn with_visibility(mut self, visibility: Visibility) -> Self {
        self.visibility = visibility;
        self
    }

    /// Set allowed groups.
    #[must_use]
    pub fn with_allowed_groups(mut self, groups: Vec<String>) -> Self {
        self.allowed_groups = groups;
        self
    }

    /// Set highlights.
    #[must_use]
    pub fn with_highlights(mut self, highlights: Vec<String>) -> Self {
        self.highlights = highlights;
        self
    }
}

/// Mock vector store for testing semantic search.
///
/// This mock simulates a vector database like Qdrant by storing
/// pre-defined results and returning them when queried.
pub struct MockVectorStore {
    /// Pre-configured results to return.
    results: Mutex<Vec<MockSearchResult>>,
    /// Call count for verification.
    call_count: Mutex<usize>,
    /// Whether to fail on next call.
    should_fail: Mutex<bool>,
    /// Error message if `should_fail` is true.
    error_message: Mutex<String>,
}

#[allow(dead_code)]
impl MockVectorStore {
    /// Create a new mock vector store with the given results.
    #[must_use]
    pub fn new(results: Vec<MockSearchResult>) -> Self {
        Self {
            results: Mutex::new(results),
            call_count: Mutex::new(0),
            should_fail: Mutex::new(false),
            error_message: Mutex::new("Mock vector store error".to_string()),
        }
    }

    /// Create an empty mock vector store.
    #[must_use]
    pub fn empty() -> Self {
        Self::new(Vec::new())
    }

    /// Set results to return.
    pub fn set_results(&self, results: Vec<MockSearchResult>) {
        *self.results.lock().unwrap() = results;
    }

    /// Configure the mock to fail on next call.
    pub fn set_should_fail(&self, should_fail: bool, message: impl Into<String>) {
        *self.should_fail.lock().unwrap() = should_fail;
        *self.error_message.lock().unwrap() = message.into();
    }

    /// Get the number of times search was called.
    #[must_use]
    pub fn call_count(&self) -> usize {
        *self.call_count.lock().unwrap()
    }

    /// Simulate a search query.
    pub fn search(
        &self,
        _embedding: &[f32],
        top_k: usize,
    ) -> Result<Vec<MockSearchResult>, String> {
        let mut count = self.call_count.lock().unwrap();
        *count += 1;

        if *self.should_fail.lock().unwrap() {
            return Err(self.error_message.lock().unwrap().clone());
        }

        let results = self.results.lock().unwrap();
        Ok(results.iter().take(top_k).cloned().collect())
    }

    /// Convert results to `ScoredItems` for fusion testing.
    #[must_use]
    pub fn as_scored_items(&self) -> Vec<ScoredItem<Uuid>> {
        self.results
            .lock()
            .unwrap()
            .iter()
            .map(|r| ScoredItem::new(r.chunk_id, r.score))
            .collect()
    }
}

impl Default for MockVectorStore {
    fn default() -> Self {
        Self::empty()
    }
}

/// Mock keyword search client for testing.
///
/// This mock simulates a keyword search engine like `OpenSearch` by storing
/// pre-defined results and returning them when queried.
pub struct MockKeywordSearcher {
    /// Pre-configured results to return.
    results: Mutex<Vec<MockSearchResult>>,
    /// Call count for verification.
    call_count: Mutex<usize>,
    /// Whether to fail on next call.
    should_fail: Mutex<bool>,
    /// Error message if `should_fail` is true.
    error_message: Mutex<String>,
}

#[allow(dead_code)]
impl MockKeywordSearcher {
    /// Create a new mock keyword searcher with the given results.
    #[must_use]
    pub fn new(results: Vec<MockSearchResult>) -> Self {
        Self {
            results: Mutex::new(results),
            call_count: Mutex::new(0),
            should_fail: Mutex::new(false),
            error_message: Mutex::new("Mock keyword search error".to_string()),
        }
    }

    /// Create an empty mock keyword searcher.
    #[must_use]
    pub fn empty() -> Self {
        Self::new(Vec::new())
    }

    /// Set results to return.
    pub fn set_results(&self, results: Vec<MockSearchResult>) {
        *self.results.lock().unwrap() = results;
    }

    /// Configure the mock to fail on next call.
    pub fn set_should_fail(&self, should_fail: bool, message: impl Into<String>) {
        *self.should_fail.lock().unwrap() = should_fail;
        *self.error_message.lock().unwrap() = message.into();
    }

    /// Get the number of times search was called.
    #[must_use]
    pub fn call_count(&self) -> usize {
        *self.call_count.lock().unwrap()
    }

    /// Simulate a search query.
    pub fn search(&self, _query: &str, top_k: usize) -> Result<Vec<MockSearchResult>, String> {
        let mut count = self.call_count.lock().unwrap();
        *count += 1;

        if *self.should_fail.lock().unwrap() {
            return Err(self.error_message.lock().unwrap().clone());
        }

        let results = self.results.lock().unwrap();
        Ok(results.iter().take(top_k).cloned().collect())
    }

    /// Convert results to `ScoredItems` for fusion testing.
    #[must_use]
    pub fn as_scored_items(&self) -> Vec<ScoredItem<Uuid>> {
        self.results
            .lock()
            .unwrap()
            .iter()
            .map(|r| ScoredItem::new(r.chunk_id, r.score))
            .collect()
    }
}

impl Default for MockKeywordSearcher {
    fn default() -> Self {
        Self::empty()
    }
}

/// Mock embedding client for testing.
///
/// This mock simulates an embedding service by returning pre-configured
/// embeddings or generating deterministic fake embeddings.
pub struct MockEmbeddingClient {
    /// Pre-configured embeddings to return (query -> embedding).
    embeddings: Mutex<HashMap<String, Vec<f32>>>,
    /// Default embedding dimension.
    dimension: usize,
    /// Call count for verification.
    call_count: Mutex<usize>,
    /// Whether to fail on next call.
    should_fail: Mutex<bool>,
}

#[allow(dead_code)]
impl MockEmbeddingClient {
    /// Create a new mock embedding client with the given dimension.
    #[must_use]
    pub fn new(dimension: usize) -> Self {
        Self {
            embeddings: Mutex::new(HashMap::new()),
            dimension,
            call_count: Mutex::new(0),
            should_fail: Mutex::new(false),
        }
    }

    /// Create a mock with 384 dimensions (all-MiniLM-L6-v2 dimension).
    #[must_use]
    pub fn default_dimension() -> Self {
        Self::new(384)
    }

    /// Add a pre-configured embedding for a specific query.
    pub fn add_embedding(&self, query: impl Into<String>, embedding: Vec<f32>) {
        self.embeddings
            .lock()
            .unwrap()
            .insert(query.into(), embedding);
    }

    /// Configure the mock to fail on next call.
    pub fn set_should_fail(&self, should_fail: bool) {
        *self.should_fail.lock().unwrap() = should_fail;
    }

    /// Get the number of times embed was called.
    #[must_use]
    pub fn call_count(&self) -> usize {
        *self.call_count.lock().unwrap()
    }

    /// Generate an embedding for the given query.
    pub fn embed(&self, query: &str) -> Result<Vec<f32>, String> {
        let mut count = self.call_count.lock().unwrap();
        *count += 1;

        if *self.should_fail.lock().unwrap() {
            return Err("Mock embedding service error".to_string());
        }

        // Return pre-configured embedding if available
        if let Some(embedding) = self.embeddings.lock().unwrap().get(query) {
            return Ok(embedding.clone());
        }

        // Generate deterministic fake embedding based on query hash
        Ok(self.generate_fake_embedding(query))
    }

    /// Generate a deterministic fake embedding based on the query.
    fn generate_fake_embedding(&self, query: &str) -> Vec<f32> {
        use std::hash::{Hash, Hasher};
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        query.hash(&mut hasher);
        let seed = hasher.finish();

        // Generate deterministic values based on seed
        (0..self.dimension)
            .map(|i| {
                
                ((seed.wrapping_add(i as u64) % 1000) as f32 / 1000.0).mul_add(2.0, -1.0)
            })
            .collect()
    }
}

impl Default for MockEmbeddingClient {
    fn default() -> Self {
        Self::default_dimension()
    }
}

/// Mock reranker client for testing.
///
/// This mock simulates a cross-encoder reranker by returning
/// adjusted scores for input documents.
pub struct MockReranker {
    /// Score adjustment factor (multiplied by original score).
    score_factor: f32,
    /// Call count for verification.
    call_count: Mutex<usize>,
    /// Whether to fail on next call.
    should_fail: Mutex<bool>,
}

#[allow(dead_code)]
impl MockReranker {
    /// Create a new mock reranker with the given score factor.
    #[must_use]
    pub fn new(score_factor: f32) -> Self {
        Self {
            score_factor,
            call_count: Mutex::new(0),
            should_fail: Mutex::new(false),
        }
    }

    /// Configure the mock to fail on next call.
    pub fn set_should_fail(&self, should_fail: bool) {
        *self.should_fail.lock().unwrap() = should_fail;
    }

    /// Get the number of times rerank was called.
    #[must_use]
    pub fn call_count(&self) -> usize {
        *self.call_count.lock().unwrap()
    }

    /// Rerank the given results.
    pub fn rerank<T: Clone>(
        &self,
        _query: &str,
        results: Vec<(T, f32)>,
    ) -> Result<Vec<(T, f32)>, String> {
        let mut count = self.call_count.lock().unwrap();
        *count += 1;

        if *self.should_fail.lock().unwrap() {
            return Err("Mock reranker error".to_string());
        }

        // Apply score factor and re-sort
        let mut adjusted: Vec<(T, f32)> = results
            .into_iter()
            .map(|(item, score)| (item, score * self.score_factor))
            .collect();

        adjusted.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

        Ok(adjusted)
    }
}

impl Default for MockReranker {
    fn default() -> Self {
        Self::new(1.0)
    }
}

/// Helper function to generate test results with overlapping IDs.
///
/// Creates two lists of results where some chunk IDs appear in both lists.
/// Useful for testing fusion algorithms.
#[must_use]
pub fn generate_overlapping_results(
    semantic_count: usize,
    keyword_count: usize,
    overlap_count: usize,
) -> (Vec<MockSearchResult>, Vec<MockSearchResult>) {
    let doc_id = Uuid::new_v4();

    // Create shared chunk IDs for overlap
    let shared_ids: Vec<Uuid> = (0..overlap_count).map(|_| Uuid::new_v4()).collect();

    // Create semantic results
    let mut semantic_results: Vec<MockSearchResult> = shared_ids
        .iter()
        .enumerate()
        .map(|(i, &chunk_id)| {
            MockSearchResult::new(
                chunk_id,
                doc_id,
                format!("Shared content {i}"),
                (i as f32).mul_add(-0.05, 0.95),
            )
            .with_title(format!("Shared Document {i}"))
        })
        .collect();

    // Add unique semantic results
    for i in 0..(semantic_count - overlap_count) {
        semantic_results.push(
            MockSearchResult::new(
                Uuid::new_v4(),
                doc_id,
                format!("Semantic unique content {i}"),
                (i as f32).mul_add(-0.03, 0.8),
            )
            .with_title(format!("Semantic Document {i}")),
        );
    }

    // Create keyword results
    let mut keyword_results: Vec<MockSearchResult> = shared_ids
        .iter()
        .enumerate()
        .map(|(i, &chunk_id)| {
            MockSearchResult::new(
                chunk_id,
                doc_id,
                format!("Shared content {i}"),
                (i as f32).mul_add(-0.5, 12.0),
            )
            .with_title(format!("Shared Document {i}"))
            .with_highlights(vec![format!("<em>Shared</em> content {}", i)])
        })
        .collect();

    // Add unique keyword results
    for i in 0..(keyword_count - overlap_count) {
        keyword_results.push(
            MockSearchResult::new(
                Uuid::new_v4(),
                doc_id,
                format!("Keyword unique content {i}"),
                (i as f32).mul_add(-0.3, 10.0),
            )
            .with_title(format!("Keyword Document {i}"))
            .with_highlights(vec![format!("<em>Keyword</em> unique {}", i)]),
        );
    }

    (semantic_results, keyword_results)
}

/// Helper function to convert mock results to scored items.
#[must_use]
pub fn to_scored_items(results: &[MockSearchResult]) -> Vec<ScoredItem<Uuid>> {
    results
        .iter()
        .map(|r| ScoredItem::new(r.chunk_id, r.score))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_mock_search_result_creation() {
        let chunk_id = Uuid::new_v4();
        let document_id = Uuid::new_v4();

        let result = MockSearchResult::new(chunk_id, document_id, "Test content", 0.95)
            .with_title("Test Document")
            .with_visibility(Visibility::Group)
            .with_allowed_groups(vec!["engineering".into()])
            .with_highlights(vec!["<em>Test</em> content".into()]);

        assert_eq!(result.chunk_id, chunk_id);
        assert_eq!(result.document_id, document_id);
        assert_eq!(result.content, "Test content");
        assert!((result.score - 0.95).abs() < f32::EPSILON);
        assert_eq!(result.title, Some("Test Document".into()));
        assert_eq!(result.visibility, Visibility::Group);
        assert_eq!(result.allowed_groups, vec!["engineering".to_string()]);
        assert_eq!(result.highlights, vec!["<em>Test</em> content".to_string()]);
    }

    #[test]
    fn test_mock_vector_store() {
        let chunk_id = Uuid::new_v4();
        let results = vec![MockSearchResult::new(
            chunk_id,
            Uuid::new_v4(),
            "Content",
            0.9,
        )];

        let store = MockVectorStore::new(results);

        let search_results = store.search(&[0.1; 384], 10).unwrap();
        assert_eq!(search_results.len(), 1);
        assert_eq!(search_results[0].chunk_id, chunk_id);
        assert_eq!(store.call_count(), 1);
    }

    #[test]
    fn test_mock_vector_store_failure() {
        let store = MockVectorStore::empty();
        store.set_should_fail(true, "Connection refused");

        let result = store.search(&[0.1; 384], 10);
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Connection refused"));
    }

    #[test]
    fn test_mock_keyword_searcher() {
        let chunk_id = Uuid::new_v4();
        let results = vec![
            MockSearchResult::new(chunk_id, Uuid::new_v4(), "Content", 12.0)
                .with_highlights(vec!["<em>Content</em>".into()]),
        ];

        let searcher = MockKeywordSearcher::new(results);

        let search_results = searcher.search("test query", 10).unwrap();
        assert_eq!(search_results.len(), 1);
        assert_eq!(search_results[0].chunk_id, chunk_id);
        assert_eq!(searcher.call_count(), 1);
    }

    #[test]
    fn test_mock_embedding_client() {
        let client = MockEmbeddingClient::default_dimension();

        let embedding = client.embed("test query").unwrap();
        assert_eq!(embedding.len(), 384);
        assert_eq!(client.call_count(), 1);

        // Same query should produce same embedding
        let embedding2 = client.embed("test query").unwrap();
        assert_eq!(embedding, embedding2);

        // Different query should produce different embedding
        let embedding3 = client.embed("different query").unwrap();
        assert_ne!(embedding, embedding3);
    }

    #[test]
    fn test_mock_embedding_client_preconfigured() {
        let client = MockEmbeddingClient::new(4);
        client.add_embedding("known query", vec![0.1, 0.2, 0.3, 0.4]);

        let embedding = client.embed("known query").unwrap();
        assert_eq!(embedding, vec![0.1, 0.2, 0.3, 0.4]);

        // Unknown query uses generated embedding
        let unknown = client.embed("unknown").unwrap();
        assert_eq!(unknown.len(), 4);
    }

    #[test]
    #[allow(clippy::similar_names)]
    fn test_mock_reranker() {
        let reranker = MockReranker::new(0.9);

        let results = vec![("doc1", 0.8), ("doc2", 0.9), ("doc3", 0.7)];

        let reranked = reranker.rerank("query", results).unwrap();

        // Should be sorted by adjusted score (descending)
        assert_eq!(reranked.len(), 3);
        assert_eq!(reranked[0].0, "doc2");
        assert!((reranked[0].1 - 0.81).abs() < f32::EPSILON); // 0.9 * 0.9
    }

    #[test]
    fn test_generate_overlapping_results() {
        let (semantic, keyword) = generate_overlapping_results(10, 8, 3);

        assert_eq!(semantic.len(), 10);
        assert_eq!(keyword.len(), 8);

        // Find overlapping IDs
        let semantic_ids: std::collections::HashSet<_> =
            semantic.iter().map(|r| r.chunk_id).collect();
        let keyword_ids: std::collections::HashSet<_> =
            keyword.iter().map(|r| r.chunk_id).collect();

        assert_eq!(semantic_ids.intersection(&keyword_ids).count(), 3);
    }

    #[test]
    fn test_to_scored_items() {
        let results = vec![
            MockSearchResult::new(Uuid::new_v4(), Uuid::new_v4(), "A", 0.9),
            MockSearchResult::new(Uuid::new_v4(), Uuid::new_v4(), "B", 0.8),
        ];

        let scored = to_scored_items(&results);

        assert_eq!(scored.len(), 2);
        assert_eq!(scored[0].id, results[0].chunk_id);
        assert!((scored[0].score - 0.9).abs() < f32::EPSILON);
    }
}

//! Linear weighted fusion algorithm.
//!
//! Linear fusion combines scores from multiple search methods using weighted
//! summation:
//!
//! ```text
//! fused_score = w_s * semantic_score + w_k * keyword_score
//! ```
//!
//! When normalization is enabled (recommended), scores are first normalized
//! to the 0-1 range using min-max normalization before being combined.
//!
//! # When to Use
//!
//! Linear fusion works best when:
//! - Score distributions from different search methods are similar
//! - Scores are well-calibrated (higher scores reliably indicate better matches)
//! - You want a simple, interpretable fusion method
//!
//! # Example
//!
//! ```
//! use rag_retrieval::fusion::linear::{linear_fusion, LinearConfig};
//! use rag_retrieval::ScoredItem;
//!
//! let semantic = vec![
//!     ScoredItem::new("doc1", 0.9),
//!     ScoredItem::new("doc2", 0.8),
//! ];
//!
//! let keyword = vec![
//!     ScoredItem::new("doc2", 0.95),
//!     ScoredItem::new("doc3", 0.85),
//! ];
//!
//! let config = LinearConfig::default();
//! let fused = linear_fusion(&semantic, &keyword, &config);
//!
//! // doc2 appears in both lists and will have a high fused score
//! ```

use super::rrf::ScoredItem;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::hash::Hash;
use tracing::debug;

/// Configuration for linear fusion.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinearConfig {
    /// Weight for semantic (vector) search results.
    pub semantic_weight: f32,

    /// Weight for keyword (BM25) search results.
    pub keyword_weight: f32,

    /// Maximum number of results to return.
    pub top_k: Option<usize>,

    /// Whether to normalize scores to 0-1 range before fusion.
    ///
    /// Normalization is highly recommended when score distributions
    /// differ between search methods (e.g., cosine similarity vs BM25).
    pub normalize: bool,
}

impl Default for LinearConfig {
    fn default() -> Self {
        Self {
            semantic_weight: 0.7,
            keyword_weight: 0.3,
            top_k: None,
            normalize: true,
        }
    }
}

impl LinearConfig {
    /// Create a new linear config with default values.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set weights for semantic and keyword results.
    #[must_use]
    pub const fn with_weights(mut self, semantic: f32, keyword: f32) -> Self {
        self.semantic_weight = semantic;
        self.keyword_weight = keyword;
        self
    }

    /// Set the maximum number of results.
    #[must_use]
    pub const fn with_top_k(mut self, top_k: usize) -> Self {
        self.top_k = Some(top_k);
        self
    }

    /// Set whether to normalize scores.
    #[must_use]
    pub const fn with_normalize(mut self, normalize: bool) -> Self {
        self.normalize = normalize;
        self
    }
}

/// Perform linear weighted fusion of two result lists.
///
/// Items appearing in only one list use 0.0 for the missing score
/// (after normalization if enabled).
///
/// # Arguments
///
/// * `semantic_results` - Results from semantic (vector) search
/// * `keyword_results` - Results from keyword (BM25) search
/// * `config` - Linear fusion configuration
///
/// # Returns
///
/// A vector of fused results, sorted by fused score in descending order.
#[must_use]
pub fn linear_fusion<T>(
    semantic_results: &[ScoredItem<T>],
    keyword_results: &[ScoredItem<T>],
    config: &LinearConfig,
) -> Vec<ScoredItem<T>>
where
    T: Clone + Eq + Hash,
{
    if semantic_results.is_empty() && keyword_results.is_empty() {
        return Vec::new();
    }

    // Normalize scores to 0-1 range if configured
    let semantic_map = if config.normalize {
        normalize_to_map(semantic_results)
    } else {
        items_to_map(semantic_results)
    };

    let keyword_map = if config.normalize {
        normalize_to_map(keyword_results)
    } else {
        items_to_map(keyword_results)
    };

    // Collect all unique IDs
    let mut all_ids: HashMap<T, ()> = HashMap::new();
    for item in semantic_results {
        all_ids.insert(item.id.clone(), ());
    }
    for item in keyword_results {
        all_ids.insert(item.id.clone(), ());
    }

    // Compute fused scores
    let mut results: Vec<ScoredItem<T>> = all_ids
        .into_iter()
        .map(|(id, _)| {
            let semantic_score = semantic_map.get(&id).copied().unwrap_or(0.0);
            let keyword_score = keyword_map.get(&id).copied().unwrap_or(0.0);

            let fused_score =
                config.semantic_weight * semantic_score + config.keyword_weight * keyword_score;

            ScoredItem::new(id, fused_score)
        })
        .collect();

    debug!(
        semantic_count = semantic_results.len(),
        keyword_count = keyword_results.len(),
        unique_items = results.len(),
        normalize = config.normalize,
        "Linear fusion computed"
    );

    // Sort by score descending
    results.sort_by(|a, b| {
        b.score
            .partial_cmp(&a.score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    // Apply top_k limit
    if let Some(top_k) = config.top_k {
        results.truncate(top_k);
    }

    results
}

/// Convert scored items to a map of ID -> score.
fn items_to_map<T: Clone + Eq + Hash>(items: &[ScoredItem<T>]) -> HashMap<T, f32> {
    items
        .iter()
        .map(|item| (item.id.clone(), item.score))
        .collect()
}

/// Normalize scores to 0-1 range and return as a map.
///
/// Uses min-max normalization:
/// ```text
/// normalized = (score - min) / (max - min)
/// ```
///
/// If all scores are the same, returns 1.0 for all items.
#[must_use]
pub fn normalize_to_map<T: Clone + Eq + Hash>(items: &[ScoredItem<T>]) -> HashMap<T, f32> {
    if items.is_empty() {
        return HashMap::new();
    }

    let min_score = items.iter().map(|i| i.score).fold(f32::INFINITY, f32::min);
    let max_score = items
        .iter()
        .map(|i| i.score)
        .fold(f32::NEG_INFINITY, f32::max);

    let range = max_score - min_score;

    items
        .iter()
        .map(|item| {
            let normalized = if range > f32::EPSILON {
                (item.score - min_score) / range
            } else {
                1.0 // All scores are the same
            };
            (item.id.clone(), normalized)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_linear_config_default() {
        let config = LinearConfig::default();
        assert!((config.semantic_weight - 0.7).abs() < f32::EPSILON);
        assert!((config.keyword_weight - 0.3).abs() < f32::EPSILON);
        assert!(config.top_k.is_none());
        assert!(config.normalize);
    }

    #[test]
    fn test_linear_config_builder() {
        let config = LinearConfig::new()
            .with_weights(0.5, 0.5)
            .with_top_k(10)
            .with_normalize(false);

        assert!((config.semantic_weight - 0.5).abs() < f32::EPSILON);
        assert!((config.keyword_weight - 0.5).abs() < f32::EPSILON);
        assert_eq!(config.top_k, Some(10));
        assert!(!config.normalize);
    }

    #[test]
    fn test_normalize_to_map() {
        let items = vec![
            ScoredItem::new("a", 10.0),
            ScoredItem::new("b", 5.0),
            ScoredItem::new("c", 0.0),
        ];

        let normalized = normalize_to_map(&items);

        assert!((normalized["a"] - 1.0).abs() < f32::EPSILON);
        assert!((normalized["b"] - 0.5).abs() < f32::EPSILON);
        assert!(normalized["c"].abs() < f32::EPSILON);
    }

    #[test]
    fn test_normalize_same_scores() {
        let items = vec![ScoredItem::new("a", 5.0), ScoredItem::new("b", 5.0)];

        let normalized = normalize_to_map(&items);

        // All same scores should become 1.0
        assert!((normalized["a"] - 1.0).abs() < f32::EPSILON);
        assert!((normalized["b"] - 1.0).abs() < f32::EPSILON);
    }

    #[test]
    fn test_normalize_empty() {
        let items: Vec<ScoredItem<String>> = vec![];
        let normalized = normalize_to_map(&items);
        assert!(normalized.is_empty());
    }

    #[test]
    fn test_linear_fusion_basic() {
        let semantic = vec![
            ScoredItem::new("doc1", 0.9),
            ScoredItem::new("doc2", 0.8),
        ];

        let keyword = vec![
            ScoredItem::new("doc2", 0.95),
            ScoredItem::new("doc3", 0.85),
        ];

        let config = LinearConfig::default();
        let fused = linear_fusion(&semantic, &keyword, &config);

        assert_eq!(fused.len(), 3); // doc1, doc2, doc3

        // With normalization and default weights (0.7 semantic, 0.3 keyword):
        // semantic: doc1=1.0 (max), doc2=0.0 (min) - only 2 items
        // keyword: doc2=1.0 (max), doc3=0.0 (min) - only 2 items
        // doc1: 0.7 * 1.0 + 0.3 * 0.0 = 0.7
        // doc2: 0.7 * 0.0 + 0.3 * 1.0 = 0.3
        // doc3: 0.7 * 0.0 + 0.3 * 0.0 = 0.0
        // So doc1 ranks first with semantic weight dominance
        assert_eq!(fused[0].id, "doc1");

        // All three docs should be present
        assert!(fused.iter().any(|r| r.id == "doc1"));
        assert!(fused.iter().any(|r| r.id == "doc2"));
        assert!(fused.iter().any(|r| r.id == "doc3"));
    }

    #[test]
    fn test_linear_fusion_without_normalization() {
        let semantic = vec![
            ScoredItem::new("doc1", 0.9),
            ScoredItem::new("doc2", 0.8),
        ];

        let keyword = vec![
            ScoredItem::new("doc2", 10.0), // Different scale
            ScoredItem::new("doc3", 8.0),
        ];

        let config = LinearConfig::default().with_normalize(false);
        let fused = linear_fusion(&semantic, &keyword, &config);

        // Without normalization, keyword scores dominate due to scale difference
        // doc2: 0.7 * 0.8 + 0.3 * 10.0 = 0.56 + 3.0 = 3.56
        // doc3: 0.7 * 0.0 + 0.3 * 8.0 = 0.0 + 2.4 = 2.4
        // doc1: 0.7 * 0.9 + 0.3 * 0.0 = 0.63 + 0.0 = 0.63

        assert_eq!(fused[0].id, "doc2");
        assert!(fused[0].score > 3.0);
    }

    #[test]
    fn test_linear_fusion_with_normalization() {
        let semantic = vec![
            ScoredItem::new("doc1", 0.9),
            ScoredItem::new("doc2", 0.7),
        ];

        let keyword = vec![
            ScoredItem::new("doc2", 10.0), // Different scale
            ScoredItem::new("doc3", 8.0),
        ];

        let config = LinearConfig::default().with_normalize(true);
        let fused = linear_fusion(&semantic, &keyword, &config);

        // With normalization, all scores are 0-1
        for item in &fused {
            assert!(item.score >= 0.0 && item.score <= 1.0);
        }
    }

    #[test]
    fn test_linear_fusion_top_k() {
        let semantic = vec![
            ScoredItem::new("doc1", 0.9),
            ScoredItem::new("doc2", 0.8),
            ScoredItem::new("doc3", 0.7),
        ];

        let keyword = vec![
            ScoredItem::new("doc4", 0.95),
            ScoredItem::new("doc5", 0.85),
        ];

        let config = LinearConfig::default().with_top_k(3);
        let fused = linear_fusion(&semantic, &keyword, &config);

        assert_eq!(fused.len(), 3);
    }

    #[test]
    fn test_linear_fusion_empty_inputs() {
        let semantic: Vec<ScoredItem<String>> = vec![];
        let keyword: Vec<ScoredItem<String>> = vec![];

        let config = LinearConfig::default();
        let fused = linear_fusion(&semantic, &keyword, &config);

        assert!(fused.is_empty());
    }

    #[test]
    fn test_linear_fusion_single_source() {
        let semantic = vec![
            ScoredItem::new("doc1", 0.9),
            ScoredItem::new("doc2", 0.8),
        ];
        let keyword: Vec<ScoredItem<&str>> = vec![];

        let config = LinearConfig::default().with_weights(0.7, 0.3);
        let fused = linear_fusion(&semantic, &keyword, &config);

        assert_eq!(fused.len(), 2);

        // With normalization and no keyword results:
        // doc1: 0.7 * 1.0 + 0.3 * 0.0 = 0.7
        // doc2: 0.7 * 0.0 + 0.3 * 0.0 = 0.0
        assert_eq!(fused[0].id, "doc1");
        assert!((fused[0].score - 0.7).abs() < f32::EPSILON);
    }

    #[test]
    fn test_linear_fusion_equal_weights() {
        let semantic = vec![ScoredItem::new("doc1", 1.0)];
        let keyword = vec![ScoredItem::new("doc2", 1.0)];

        let config = LinearConfig::default().with_weights(0.5, 0.5);
        let fused = linear_fusion(&semantic, &keyword, &config);

        // Both should have same score (0.5 * 1.0 + 0.5 * 0.0 = 0.5)
        assert!((fused[0].score - fused[1].score).abs() < f32::EPSILON);
    }

    #[test]
    fn test_linear_fusion_sorted_descending() {
        let semantic = vec![
            ScoredItem::new("doc1", 0.5),
            ScoredItem::new("doc2", 0.9),
            ScoredItem::new("doc3", 0.1),
        ];
        let keyword: Vec<ScoredItem<&str>> = vec![];

        let config = LinearConfig::default();
        let fused = linear_fusion(&semantic, &keyword, &config);

        // Should be sorted by score descending
        for i in 1..fused.len() {
            assert!(fused[i - 1].score >= fused[i].score);
        }
    }
}

//! Reciprocal Rank Fusion (RRF) algorithm.
//!
//! RRF combines multiple ranked lists into a single list by giving each item
//! a score based on its rank in each list:
//!
//! ```text
//! RRF_score(d) = Σ 1 / (k + rank_i(d))
//! ```
//!
//! where `k` is a constant (default 60) that controls the importance of
//! highly-ranked items.
//!
//! Reference: Cormack, G. V., Clarke, C. L. A., & Buettcher, S. (2009).
//! Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::hash::Hash;
use thiserror::Error;
use tracing::debug;

/// Error type for RRF operations.
#[derive(Debug, Error)]
pub enum RrfError {
    /// Weights length does not match the number of lists.
    #[error("Weights length ({weights_len}) must match lists length ({lists_len})")]
    WeightsMismatch { weights_len: usize, lists_len: usize },
}

/// Result type for RRF operations.
pub type Result<T> = std::result::Result<T, RrfError>;

/// Configuration for RRF fusion.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RrfConfig {
    /// The k constant in the RRF formula.
    ///
    /// Higher values give more weight to lower-ranked items.
    /// Default: 60 (standard value from literature).
    pub k: f32,

    /// Optional weights for each result list.
    ///
    /// If provided, must have the same length as the number of lists.
    /// Weights are multiplied with the RRF score for each list.
    pub weights: Option<Vec<f32>>,

    /// Maximum number of results to return.
    ///
    /// If None, returns all fused results.
    pub top_k: Option<usize>,
}

impl Default for RrfConfig {
    fn default() -> Self {
        Self {
            k: 60.0,
            weights: None,
            top_k: None,
        }
    }
}

impl RrfConfig {
    /// Create a new RRF config with the given k value.
    #[must_use]
    pub const fn new(k: f32) -> Self {
        Self {
            k,
            weights: None,
            top_k: None,
        }
    }

    /// Set weights for each result list.
    #[must_use]
    pub fn with_weights(mut self, weights: Vec<f32>) -> Self {
        self.weights = Some(weights);
        self
    }

    /// Set the maximum number of results.
    #[must_use]
    pub const fn with_top_k(mut self, top_k: usize) -> Self {
        self.top_k = Some(top_k);
        self
    }
}

/// A scored item from a search result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ScoredItem<T> {
    /// The item identifier
    pub id: T,
    /// The score (higher is better)
    pub score: f32,
}

impl<T> ScoredItem<T> {
    /// Create a new scored item.
    #[must_use]
    pub fn new(id: T, score: f32) -> Self {
        Self { id, score }
    }
}

impl<T: PartialEq> PartialEq for ScoredItem<T> {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}

impl<T: Eq> Eq for ScoredItem<T> {}

impl<T: Hash> Hash for ScoredItem<T> {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.id.hash(state);
    }
}

/// Compute the RRF score for a single rank.
///
/// ```
/// use rag_retrieval::rrf::rrf_score;
///
/// // First rank (index 0) with k=60
/// assert!((rrf_score(0, 60.0) - 1.0/60.0).abs() < 1e-6);
///
/// // Second rank (index 1) with k=60
/// assert!((rrf_score(1, 60.0) - 1.0/61.0).abs() < 1e-6);
/// ```
#[inline]
#[must_use]
pub fn rrf_score(rank: usize, k: f32) -> f32 {
    1.0 / (k + rank as f32)
}

/// Perform Reciprocal Rank Fusion on multiple result lists.
///
/// Each list should be sorted by score in descending order (best first).
/// The function returns a new list of scored items, sorted by fused score.
///
/// # Arguments
///
/// * `lists` - Slice of references to scored item lists
/// * `config` - RRF configuration
///
/// # Returns
///
/// A vector of scored items with fused scores, sorted descending.
///
/// # Errors
///
/// Returns [`RrfError::WeightsMismatch`] if weights are provided but don't match
/// the number of lists.
pub fn reciprocal_rank_fusion<T>(
    lists: &[&[ScoredItem<T>]],
    config: &RrfConfig,
) -> Result<Vec<ScoredItem<T>>>
where
    T: Clone + Eq + Hash,
{
    if lists.is_empty() {
        return Ok(Vec::new());
    }

    // Validate weights
    if let Some(ref weights) = config.weights {
        if weights.len() != lists.len() {
            return Err(RrfError::WeightsMismatch {
                weights_len: weights.len(),
                lists_len: lists.len(),
            });
        }
    }

    // Accumulate RRF scores for each item
    let mut scores: HashMap<T, f32> = HashMap::new();

    for (list_idx, list) in lists.iter().enumerate() {
        let weight = config.weights.as_ref().map_or(1.0, |w| w[list_idx]);

        for (rank, item) in list.iter().enumerate() {
            let score = rrf_score(rank, config.k) * weight;
            *scores.entry(item.id.clone()).or_insert(0.0) += score;
        }
    }

    debug!(
        lists = lists.len(),
        unique_items = scores.len(),
        "RRF fusion computed"
    );

    // Convert to sorted vector
    let mut results: Vec<ScoredItem<T>> = scores
        .into_iter()
        .map(|(id, score)| ScoredItem::new(id, score))
        .collect();

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

    Ok(results)
}

/// Perform weighted RRF fusion with explicit weights.
///
/// This is a convenience function that sets up weights in the config.
/// Since this function always provides exactly 2 weights for 2 lists,
/// it cannot fail due to weight mismatch.
///
/// # Arguments
///
/// * `semantic_results` - Results from semantic (vector) search
/// * `keyword_results` - Results from keyword (BM25) search
/// * `semantic_weight` - Weight for semantic results (typically 0.7)
/// * `keyword_weight` - Weight for keyword results (typically 0.3)
/// * `k` - The k constant (default 60)
/// * `top_k` - Maximum results to return
#[must_use]
pub fn hybrid_fusion<T>(
    semantic_results: &[ScoredItem<T>],
    keyword_results: &[ScoredItem<T>],
    semantic_weight: f32,
    keyword_weight: f32,
    k: f32,
    top_k: Option<usize>,
) -> Vec<ScoredItem<T>>
where
    T: Clone + Eq + Hash,
{
    let config = RrfConfig {
        k,
        weights: Some(vec![semantic_weight, keyword_weight]),
        top_k,
    };

    // SAFETY: This function always provides exactly 2 weights for 2 lists,
    // so the weight mismatch error can never occur.
    reciprocal_rank_fusion(&[semantic_results, keyword_results], &config)
        .expect("hybrid_fusion: weight mismatch should be impossible with 2 weights and 2 lists")
}

/// Normalize scores to the 0-1 range using min-max normalization.
///
/// # Arguments
///
/// * `items` - Mutable slice of scored items to normalize
pub fn normalize_scores<T>(items: &mut [ScoredItem<T>]) {
    if items.is_empty() {
        return;
    }

    let min_score = items.iter().map(|i| i.score).fold(f32::INFINITY, f32::min);
    let max_score = items
        .iter()
        .map(|i| i.score)
        .fold(f32::NEG_INFINITY, f32::max);

    let range = max_score - min_score;
    if range > f32::EPSILON {
        for item in items {
            item.score = (item.score - min_score) / range;
        }
    } else {
        // All scores are the same, set to 1.0
        for item in items {
            item.score = 1.0;
        }
    }
}

/// Deduplicate results by ID, keeping the highest-scored item.
///
/// # Arguments
///
/// * `items` - Slice of scored items
///
/// # Returns
///
/// A new vector with duplicates removed.
#[must_use]
pub fn deduplicate<T>(items: &[ScoredItem<T>]) -> Vec<ScoredItem<T>>
where
    T: Clone + Eq + Hash,
{
    let mut seen: HashMap<T, f32> = HashMap::new();

    for item in items {
        seen.entry(item.id.clone())
            .and_modify(|score| {
                if item.score > *score {
                    *score = item.score;
                }
            })
            .or_insert(item.score);
    }

    seen.into_iter()
        .map(|(id, score)| ScoredItem::new(id, score))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rrf_score() {
        // First position (rank 0)
        let score = rrf_score(0, 60.0);
        assert!((score - 1.0 / 60.0).abs() < 1e-6);

        // Second position (rank 1)
        let score = rrf_score(1, 60.0);
        assert!((score - 1.0 / 61.0).abs() < 1e-6);

        // Higher k gives more weight to lower ranks
        let score_k1 = rrf_score(10, 1.0);
        let score_k60 = rrf_score(10, 60.0);
        assert!(score_k1 > score_k60);
    }

    #[test]
    fn test_basic_fusion() {
        let list1 = vec![
            ScoredItem::new("a", 0.9),
            ScoredItem::new("b", 0.8),
            ScoredItem::new("c", 0.7),
        ];

        let list2 = vec![
            ScoredItem::new("b", 0.95),
            ScoredItem::new("d", 0.85),
            ScoredItem::new("a", 0.75),
        ];

        let config = RrfConfig::default();
        let fused = reciprocal_rank_fusion(&[&list1, &list2], &config).unwrap();

        // Item "b" appears at rank 1 in list1 and rank 0 in list2
        // It should have the highest combined score
        assert_eq!(fused[0].id, "b");

        // "a" appears at rank 0 in list1 and rank 2 in list2
        assert!(fused.iter().any(|i| i.id == "a"));

        // "d" only appears in list2
        assert!(fused.iter().any(|i| i.id == "d"));

        // "c" only appears in list1
        assert!(fused.iter().any(|i| i.id == "c"));
    }

    #[test]
    fn test_weighted_fusion() {
        let list1 = vec![ScoredItem::new("a", 0.9)];
        let list2 = vec![ScoredItem::new("b", 0.9)];

        // Equal weights
        let config = RrfConfig::default().with_weights(vec![1.0, 1.0]);
        let fused = reciprocal_rank_fusion(&[&list1, &list2], &config).unwrap();
        assert!((fused[0].score - fused[1].score).abs() < 1e-6);

        // Higher weight for first list
        let config = RrfConfig::default().with_weights(vec![2.0, 1.0]);
        let fused = reciprocal_rank_fusion(&[&list1, &list2], &config).unwrap();
        assert_eq!(fused[0].id, "a");
        assert!(fused[0].score > fused[1].score);
    }

    #[test]
    fn test_top_k() {
        let list = vec![
            ScoredItem::new("a", 0.9),
            ScoredItem::new("b", 0.8),
            ScoredItem::new("c", 0.7),
            ScoredItem::new("d", 0.6),
            ScoredItem::new("e", 0.5),
        ];

        let config = RrfConfig::default().with_top_k(3);
        let fused = reciprocal_rank_fusion(&[&list], &config).unwrap();

        assert_eq!(fused.len(), 3);
    }

    #[test]
    fn test_empty_lists() {
        let config = RrfConfig::default();
        let fused: Vec<ScoredItem<String>> = reciprocal_rank_fusion(&[], &config).unwrap();
        assert!(fused.is_empty());
    }

    #[test]
    fn test_hybrid_fusion() {
        let semantic = vec![ScoredItem::new("doc1", 0.9), ScoredItem::new("doc2", 0.8)];

        let keyword = vec![ScoredItem::new("doc2", 0.95), ScoredItem::new("doc3", 0.85)];

        let fused = hybrid_fusion(&semantic, &keyword, 0.7, 0.3, 60.0, Some(10));

        // doc2 appears in both, should be ranked highly
        assert!(!fused.is_empty());
        let doc2_score = fused.iter().find(|i| i.id == "doc2").unwrap().score;
        let doc1_score = fused.iter().find(|i| i.id == "doc1").unwrap().score;

        // doc2 should score higher because it appears in both lists
        assert!(doc2_score > doc1_score);
    }

    #[test]
    fn test_normalize_scores() {
        let mut items = vec![
            ScoredItem::new("a", 10.0),
            ScoredItem::new("b", 5.0),
            ScoredItem::new("c", 0.0),
        ];

        normalize_scores(&mut items);

        assert!((items[0].score - 1.0).abs() < 1e-6); // max -> 1.0
        assert!((items[1].score - 0.5).abs() < 1e-6); // middle -> 0.5
        assert!(items[2].score.abs() < 1e-6); // min -> 0.0
    }

    #[test]
    fn test_normalize_same_scores() {
        let mut items = vec![ScoredItem::new("a", 5.0), ScoredItem::new("b", 5.0)];

        normalize_scores(&mut items);

        // All scores are the same, should become 1.0
        assert!((items[0].score - 1.0).abs() < 1e-6);
        assert!((items[1].score - 1.0).abs() < 1e-6);
    }

    #[test]
    fn test_deduplicate() {
        let items = vec![
            ScoredItem::new("a", 0.9),
            ScoredItem::new("b", 0.8),
            ScoredItem::new("a", 0.7), // duplicate with lower score
        ];

        let deduped = deduplicate(&items);

        assert_eq!(deduped.len(), 2);

        // "a" should keep the higher score
        let a_item = deduped.iter().find(|i| i.id == "a").unwrap();
        assert!((a_item.score - 0.9).abs() < 1e-6);
    }

    #[test]
    fn test_invalid_weights() {
        let list = vec![ScoredItem::new("a", 0.9)];
        let config = RrfConfig::default().with_weights(vec![1.0, 2.0]); // 2 weights for 1 list

        let result = reciprocal_rank_fusion(&[&list], &config);
        assert!(result.is_err());

        let err = result.unwrap_err();
        assert!(matches!(
            err,
            RrfError::WeightsMismatch {
                weights_len: 2,
                lists_len: 1
            }
        ));
        assert!(err.to_string().contains("Weights length"));
    }
}

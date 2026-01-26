//! Distribution-Based Score Fusion (DBSF) algorithm.
//!
//! DBSF uses z-score normalization to account for different score distributions
//! across search methods. This is particularly useful when:
//!
//! - Score distributions have different means and standard deviations
//! - Scores are not naturally bounded (e.g., BM25 scores can vary widely)
//! - You want statistically-grounded normalization
//!
//! # Z-Score Normalization
//!
//! For each score, the z-score is computed as:
//!
//! ```text
//! z = (score - mean) / std_dev
//! ```
//!
//! This transforms scores to have mean 0 and standard deviation 1, making
//! them comparable across different distributions.
//!
//! # Fusion Formula
//!
//! After normalization, scores are combined using weighted summation:
//!
//! ```text
//! fused_score = w_s * z_semantic + w_k * z_keyword
//! ```
//!
//! # Example
//!
//! ```
//! use rag_retrieval::fusion::dbsf::{distribution_based_fusion, DbsfConfig};
//! use rag_retrieval::ScoredItem;
//!
//! let semantic = vec![
//!     ScoredItem::new("doc1", 0.95),
//!     ScoredItem::new("doc2", 0.85),
//! ];
//!
//! let keyword = vec![
//!     ScoredItem::new("doc2", 12.5),  // BM25 score (different scale)
//!     ScoredItem::new("doc3", 10.2),
//! ];
//!
//! let config = DbsfConfig::default();
//! let fused = distribution_based_fusion(&semantic, &keyword, &config);
//! ```

use super::rrf::ScoredItem;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::hash::Hash;
use tracing::debug;

/// Configuration for Distribution-Based Score Fusion.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DbsfConfig {
    /// Weight for semantic (vector) search results.
    pub semantic_weight: f32,

    /// Weight for keyword (BM25) search results.
    pub keyword_weight: f32,

    /// Maximum number of results to return.
    pub top_k: Option<usize>,
}

impl Default for DbsfConfig {
    fn default() -> Self {
        Self {
            semantic_weight: 0.7,
            keyword_weight: 0.3,
            top_k: None,
        }
    }
}

impl DbsfConfig {
    /// Create a new DBSF config with default values.
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
}

/// Statistics for a score distribution.
#[derive(Debug, Clone, Copy)]
pub struct DistributionStats {
    /// Mean of the scores.
    pub mean: f32,
    /// Standard deviation of the scores.
    pub std_dev: f32,
    /// Number of samples.
    pub count: usize,
}

impl DistributionStats {
    /// Calculate statistics from a slice of scores.
    #[must_use]
    pub fn from_scores(scores: &[f32]) -> Self {
        if scores.is_empty() {
            return Self {
                mean: 0.0,
                std_dev: 1.0, // Use 1.0 to avoid division by zero
                count: 0,
            };
        }

        let count = scores.len();
        let mean = scores.iter().sum::<f32>() / count as f32;

        let variance = if count > 1 {
            scores.iter().map(|&s| (s - mean).powi(2)).sum::<f32>() / (count - 1) as f32
        } else {
            0.0
        };

        let std_dev = variance.sqrt();

        Self {
            mean,
            std_dev: if std_dev > f32::EPSILON { std_dev } else { 1.0 },
            count,
        }
    }
}

/// Calculate statistics from a list of scored items.
#[must_use]
pub fn calculate_stats<T>(items: &[ScoredItem<T>]) -> DistributionStats {
    let scores: Vec<f32> = items.iter().map(|item| item.score).collect();
    DistributionStats::from_scores(&scores)
}

/// Normalize scores using z-score normalization.
///
/// # Formula
///
/// ```text
/// z = (score - mean) / std_dev
/// ```
///
/// # Returns
///
/// A map of ID -> z-score for each item.
#[must_use]
pub fn z_score_normalize<T: Clone + Eq + Hash>(items: &[ScoredItem<T>]) -> HashMap<T, f32> {
    if items.is_empty() {
        return HashMap::new();
    }

    let stats = calculate_stats(items);

    items
        .iter()
        .map(|item| {
            let z_score = (item.score - stats.mean) / stats.std_dev;
            (item.id.clone(), z_score)
        })
        .collect()
}

/// Perform Distribution-Based Score Fusion on two result lists.
///
/// This function normalizes scores using z-score normalization and then
/// combines them using weighted summation.
///
/// Items appearing in only one list use 0.0 (the mean z-score) for the
/// missing score, which is a neutral value in z-score space.
///
/// # Arguments
///
/// * `semantic_results` - Results from semantic (vector) search
/// * `keyword_results` - Results from keyword (BM25) search
/// * `config` - DBSF configuration
///
/// # Returns
///
/// A vector of fused results, sorted by fused score in descending order.
#[must_use]
pub fn distribution_based_fusion<T>(
    semantic_results: &[ScoredItem<T>],
    keyword_results: &[ScoredItem<T>],
    config: &DbsfConfig,
) -> Vec<ScoredItem<T>>
where
    T: Clone + Eq + Hash,
{
    if semantic_results.is_empty() && keyword_results.is_empty() {
        return Vec::new();
    }

    // Calculate z-scores for each list
    let semantic_zscores = z_score_normalize(semantic_results);
    let keyword_zscores = z_score_normalize(keyword_results);

    // Log statistics for debugging
    let semantic_stats = calculate_stats(semantic_results);
    let keyword_stats = calculate_stats(keyword_results);

    debug!(
        semantic_mean = semantic_stats.mean,
        semantic_std = semantic_stats.std_dev,
        semantic_count = semantic_stats.count,
        keyword_mean = keyword_stats.mean,
        keyword_std = keyword_stats.std_dev,
        keyword_count = keyword_stats.count,
        "DBSF distribution statistics"
    );

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
            // Use 0.0 (mean z-score) for missing values
            let semantic_z = semantic_zscores.get(&id).copied().unwrap_or(0.0);
            let keyword_z = keyword_zscores.get(&id).copied().unwrap_or(0.0);

            let fused_score =
                config.semantic_weight * semantic_z + config.keyword_weight * keyword_z;

            ScoredItem::new(id, fused_score)
        })
        .collect();

    debug!(
        unique_items = results.len(),
        semantic_weight = config.semantic_weight,
        keyword_weight = config.keyword_weight,
        "DBSF fusion computed"
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dbsf_config_default() {
        let config = DbsfConfig::default();
        assert!((config.semantic_weight - 0.7).abs() < f32::EPSILON);
        assert!((config.keyword_weight - 0.3).abs() < f32::EPSILON);
        assert!(config.top_k.is_none());
    }

    #[test]
    fn test_dbsf_config_builder() {
        let config = DbsfConfig::new().with_weights(0.5, 0.5).with_top_k(10);

        assert!((config.semantic_weight - 0.5).abs() < f32::EPSILON);
        assert!((config.keyword_weight - 0.5).abs() < f32::EPSILON);
        assert_eq!(config.top_k, Some(10));
    }

    #[test]
    fn test_distribution_stats_basic() {
        let scores = vec![1.0, 2.0, 3.0, 4.0, 5.0];
        let stats = DistributionStats::from_scores(&scores);

        assert!((stats.mean - 3.0).abs() < f32::EPSILON);
        assert!(stats.std_dev > 0.0);
        assert_eq!(stats.count, 5);
    }

    #[test]
    fn test_distribution_stats_empty() {
        let scores: Vec<f32> = vec![];
        let stats = DistributionStats::from_scores(&scores);

        assert!(stats.mean.abs() < f32::EPSILON);
        assert!((stats.std_dev - 1.0).abs() < f32::EPSILON); // Default to 1.0
        assert_eq!(stats.count, 0);
    }

    #[test]
    fn test_distribution_stats_single() {
        let scores = vec![5.0];
        let stats = DistributionStats::from_scores(&scores);

        assert!((stats.mean - 5.0).abs() < f32::EPSILON);
        assert!((stats.std_dev - 1.0).abs() < f32::EPSILON); // Default when no variance
        assert_eq!(stats.count, 1);
    }

    #[test]
    fn test_z_score_normalize() {
        let items = vec![
            ScoredItem::new("a", 1.0),
            ScoredItem::new("b", 2.0),
            ScoredItem::new("c", 3.0),
        ];

        let zscores = z_score_normalize(&items);

        // Mean = 2.0, so "b" should have z-score close to 0
        assert!(zscores["b"].abs() < f32::EPSILON);

        // "a" should be negative (below mean)
        assert!(zscores["a"] < 0.0);

        // "c" should be positive (above mean)
        assert!(zscores["c"] > 0.0);

        // Z-scores should be symmetric around the mean
        assert!((zscores["a"].abs() - zscores["c"].abs()).abs() < f32::EPSILON);
    }

    #[test]
    fn test_z_score_normalize_empty() {
        let items: Vec<ScoredItem<String>> = vec![];
        let zscores = z_score_normalize(&items);
        assert!(zscores.is_empty());
    }

    #[test]
    fn test_dbsf_basic() {
        let semantic = vec![
            ScoredItem::new("doc1", 0.9),
            ScoredItem::new("doc2", 0.8),
            ScoredItem::new("doc3", 0.7),
        ];

        let keyword = vec![
            ScoredItem::new("doc2", 12.0),
            ScoredItem::new("doc4", 10.0),
            ScoredItem::new("doc1", 8.0),
        ];

        let config = DbsfConfig::default();
        let fused = distribution_based_fusion(&semantic, &keyword, &config);

        assert_eq!(fused.len(), 4); // doc1, doc2, doc3, doc4

        // doc2 appears in both lists at good positions
        let doc2 = fused.iter().find(|r| r.id == "doc2").unwrap();
        assert!(doc2.score > 0.0); // Should be positive (above average in both)
    }

    #[test]
    fn test_dbsf_different_scales() {
        // Semantic scores: 0-1 range
        let semantic = vec![
            ScoredItem::new("doc1", 0.95),
            ScoredItem::new("doc2", 0.5),
        ];

        // Keyword scores: 0-100 range
        let keyword = vec![
            ScoredItem::new("doc2", 80.0),
            ScoredItem::new("doc3", 20.0),
        ];

        let config = DbsfConfig::new().with_weights(0.5, 0.5);
        let fused = distribution_based_fusion(&semantic, &keyword, &config);

        // Despite very different scales, z-score normalization should handle it
        assert_eq!(fused.len(), 3);

        // Results should be sorted descending
        for i in 1..fused.len() {
            assert!(fused[i - 1].score >= fused[i].score);
        }
    }

    #[test]
    fn test_dbsf_top_k() {
        let semantic = vec![
            ScoredItem::new("doc1", 0.9),
            ScoredItem::new("doc2", 0.8),
            ScoredItem::new("doc3", 0.7),
        ];

        let keyword = vec![
            ScoredItem::new("doc4", 0.95),
            ScoredItem::new("doc5", 0.85),
        ];

        let config = DbsfConfig::default().with_top_k(3);
        let fused = distribution_based_fusion(&semantic, &keyword, &config);

        assert_eq!(fused.len(), 3);
    }

    #[test]
    fn test_dbsf_empty_inputs() {
        let semantic: Vec<ScoredItem<String>> = vec![];
        let keyword: Vec<ScoredItem<String>> = vec![];

        let config = DbsfConfig::default();
        let fused = distribution_based_fusion(&semantic, &keyword, &config);

        assert!(fused.is_empty());
    }

    #[test]
    fn test_dbsf_single_source() {
        let semantic = vec![
            ScoredItem::new("doc1", 0.9),
            ScoredItem::new("doc2", 0.8),
        ];
        let keyword: Vec<ScoredItem<&str>> = vec![];

        let config = DbsfConfig::default();
        let fused = distribution_based_fusion(&semantic, &keyword, &config);

        assert_eq!(fused.len(), 2);

        // Results should be sorted by fused score
        assert!(fused[0].score >= fused[1].score);
    }

    #[test]
    fn test_dbsf_overlap_handling() {
        // Both lists have doc1 and doc2, but with different scores
        let semantic = vec![
            ScoredItem::new("doc1", 0.9), // High semantic score
            ScoredItem::new("doc2", 0.3), // Low semantic score
        ];

        let keyword = vec![
            ScoredItem::new("doc2", 0.95), // High keyword score
            ScoredItem::new("doc1", 0.1),  // Low keyword score
        ];

        let config = DbsfConfig::new().with_weights(0.5, 0.5);
        let fused = distribution_based_fusion(&semantic, &keyword, &config);

        // With equal weights, both docs should be close in score
        // because each excels in one dimension
        assert_eq!(fused.len(), 2);
    }

    #[test]
    fn test_dbsf_preserves_ranking_within_list() {
        // Items only in semantic list
        let semantic = vec![
            ScoredItem::new("doc1", 0.9),
            ScoredItem::new("doc2", 0.8),
            ScoredItem::new("doc3", 0.7),
        ];
        let keyword: Vec<ScoredItem<&str>> = vec![];

        let config = DbsfConfig::default();
        let fused = distribution_based_fusion(&semantic, &keyword, &config);

        // Relative ordering should be preserved
        let positions: HashMap<&str, usize> = fused
            .iter()
            .enumerate()
            .map(|(i, item)| (item.id, i))
            .collect();

        assert!(positions["doc1"] < positions["doc2"]);
        assert!(positions["doc2"] < positions["doc3"]);
    }
}

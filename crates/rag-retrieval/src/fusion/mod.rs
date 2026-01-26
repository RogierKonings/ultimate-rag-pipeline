//! Fusion algorithms for combining search results.
//!
//! This module provides multiple fusion algorithms for combining results from
//! different search methods (semantic and keyword search):
//!
//! - **RRF (Reciprocal Rank Fusion)**: Rank-based fusion that combines results
//!   based on their position in each list. Best for cases where score distributions
//!   differ significantly between search methods.
//!
//! - **Linear Fusion**: Simple weighted combination of normalized scores.
//!   Best when score distributions are similar and well-calibrated.
//!
//! - **DBSF (Distribution-Based Score Fusion)**: Uses z-score normalization to
//!   account for different score distributions. Best when score distributions
//!   have different means and standard deviations.
//!
//! # Example
//!
//! ```
//! use rag_retrieval::fusion::{fuse, FusionConfig, FusionMethod};
//! use rag_retrieval::ScoredItem;
//!
//! let semantic_results = vec![
//!     ScoredItem::new("doc1", 0.95),
//!     ScoredItem::new("doc2", 0.85),
//!     ScoredItem::new("doc3", 0.75),
//! ];
//!
//! let keyword_results = vec![
//!     ScoredItem::new("doc2", 12.5),  // BM25 score
//!     ScoredItem::new("doc4", 10.2),
//!     ScoredItem::new("doc1", 8.1),
//! ];
//!
//! // Use RRF (default)
//! let config = FusionConfig::default();
//! let fused = fuse(&semantic_results, &keyword_results, &config).unwrap();
//!
//! // Use Linear fusion with normalization
//! let config = FusionConfig::new(FusionMethod::Linear);
//! let fused = fuse(&semantic_results, &keyword_results, &config).unwrap();
//!
//! // Use DBSF for distribution-aware fusion
//! let config = FusionConfig::new(FusionMethod::Dbsf);
//! let fused = fuse(&semantic_results, &keyword_results, &config).unwrap();
//! ```

pub mod dbsf;
pub mod linear;
pub mod rrf;

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::hash::Hash;

// Re-export all public items from submodules
pub use dbsf::{distribution_based_fusion, DbsfConfig};
pub use linear::{linear_fusion, LinearConfig};
pub use rrf::{
    deduplicate, hybrid_fusion, normalize_scores, reciprocal_rank_fusion, rrf_score, RrfConfig,
    RrfError, ScoredItem,
};

/// Fusion method to use for combining search results.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "snake_case")]
pub enum FusionMethod {
    /// Reciprocal Rank Fusion - rank-based fusion.
    #[default]
    Rrf,
    /// Linear weighted fusion with optional score normalization.
    Linear,
    /// Distribution-Based Score Fusion using z-score normalization.
    Dbsf,
}

impl FusionMethod {
    /// Check if this method uses score normalization.
    #[must_use]
    pub const fn uses_normalization(&self) -> bool {
        matches!(self, Self::Linear | Self::Dbsf)
    }

    /// Check if this method is rank-based (ignores actual scores).
    #[must_use]
    pub const fn is_rank_based(&self) -> bool {
        matches!(self, Self::Rrf)
    }
}

/// Configuration for fusion operations.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FusionConfig {
    /// The fusion method to use.
    pub method: FusionMethod,

    /// Weight for semantic (vector) search results.
    /// Default: 0.7
    pub semantic_weight: f32,

    /// Weight for keyword (BM25) search results.
    /// Default: 0.3
    pub keyword_weight: f32,

    /// The k constant for RRF (only used when method is Rrf).
    /// Higher values give more weight to lower-ranked items.
    /// Default: 60.0
    pub rrf_k: f32,

    /// Maximum number of results to return.
    /// If None, returns all fused results.
    pub top_k: Option<usize>,

    /// Whether to deduplicate results by ID.
    /// Default: true
    pub deduplicate: bool,

    /// Whether to normalize scores before linear fusion.
    /// Only applies to Linear method.
    /// Default: true
    pub normalize_linear: bool,
}

impl Default for FusionConfig {
    fn default() -> Self {
        Self {
            method: FusionMethod::default(),
            semantic_weight: 0.7,
            keyword_weight: 0.3,
            rrf_k: 60.0,
            top_k: None,
            deduplicate: true,
            normalize_linear: true,
        }
    }
}

impl FusionConfig {
    /// Create a new fusion config with the specified method.
    #[must_use]
    pub fn new(method: FusionMethod) -> Self {
        Self {
            method,
            ..Default::default()
        }
    }

    /// Set the semantic weight.
    #[must_use]
    pub const fn with_semantic_weight(mut self, weight: f32) -> Self {
        self.semantic_weight = weight;
        self
    }

    /// Set the keyword weight.
    #[must_use]
    pub const fn with_keyword_weight(mut self, weight: f32) -> Self {
        self.keyword_weight = weight;
        self
    }

    /// Set both weights at once.
    #[must_use]
    pub const fn with_weights(mut self, semantic: f32, keyword: f32) -> Self {
        self.semantic_weight = semantic;
        self.keyword_weight = keyword;
        self
    }

    /// Set the RRF k constant.
    #[must_use]
    pub const fn with_rrf_k(mut self, k: f32) -> Self {
        self.rrf_k = k;
        self
    }

    /// Set the maximum number of results.
    #[must_use]
    pub const fn with_top_k(mut self, top_k: usize) -> Self {
        self.top_k = Some(top_k);
        self
    }

    /// Set whether to deduplicate results.
    #[must_use]
    pub const fn with_deduplicate(mut self, deduplicate: bool) -> Self {
        self.deduplicate = deduplicate;
        self
    }

    /// Set whether to normalize scores for linear fusion.
    #[must_use]
    pub const fn with_normalize_linear(mut self, normalize: bool) -> Self {
        self.normalize_linear = normalize;
        self
    }
}

/// A fused result with detailed score information.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FusedResult<T> {
    /// The item identifier.
    pub id: T,
    /// The final fused score.
    pub fused_score: f32,
    /// Original score from semantic search (if present).
    pub semantic_score: Option<f32>,
    /// Original score from keyword search (if present).
    pub keyword_score: Option<f32>,
    /// Rank in semantic results (1-based, None if not in semantic results).
    pub semantic_rank: Option<usize>,
    /// Rank in keyword results (1-based, None if not in keyword results).
    pub keyword_rank: Option<usize>,
}

impl<T> FusedResult<T> {
    /// Create a new fused result.
    #[must_use]
    pub fn new(id: T, fused_score: f32) -> Self {
        Self {
            id,
            fused_score,
            semantic_score: None,
            keyword_score: None,
            semantic_rank: None,
            keyword_rank: None,
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
}

impl<T: PartialEq> PartialEq for FusedResult<T> {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}

impl<T: Eq> Eq for FusedResult<T> {}

impl<T: Hash> Hash for FusedResult<T> {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.id.hash(state);
    }
}

/// Error type for fusion operations.
#[derive(Debug, thiserror::Error)]
pub enum FusionError {
    /// Error from RRF fusion.
    #[error("RRF fusion error: {0}")]
    Rrf(#[from] RrfError),

    /// Invalid configuration.
    #[error("Invalid configuration: {0}")]
    Config(String),
}

/// Result type for fusion operations.
pub type Result<T> = std::result::Result<T, FusionError>;

/// Perform fusion of semantic and keyword search results.
///
/// This is the main entry point for all fusion operations. It dispatches to
/// the appropriate fusion algorithm based on the configuration.
///
/// # Arguments
///
/// * `semantic_results` - Results from semantic (vector) search
/// * `keyword_results` - Results from keyword (BM25) search
/// * `config` - Fusion configuration
///
/// # Returns
///
/// A vector of fused results with detailed score information, sorted by
/// fused score in descending order.
///
/// # Errors
///
/// Returns a `FusionError` if the fusion operation fails.
pub fn fuse<T>(
    semantic_results: &[ScoredItem<T>],
    keyword_results: &[ScoredItem<T>],
    config: &FusionConfig,
) -> Result<Vec<FusedResult<T>>>
where
    T: Clone + Eq + Hash,
{
    // Build lookup maps for scores and ranks
    let semantic_map = build_score_rank_map(semantic_results);
    let keyword_map = build_score_rank_map(keyword_results);

    // Perform fusion based on method
    let fused_items = match config.method {
        FusionMethod::Rrf => {
            let rrf_config = RrfConfig {
                k: config.rrf_k,
                weights: Some(vec![config.semantic_weight, config.keyword_weight]),
                top_k: config.top_k,
            };
            reciprocal_rank_fusion(&[semantic_results, keyword_results], &rrf_config)?
        }
        FusionMethod::Linear => {
            let linear_config = LinearConfig {
                semantic_weight: config.semantic_weight,
                keyword_weight: config.keyword_weight,
                top_k: config.top_k,
                normalize: config.normalize_linear,
            };
            linear_fusion(semantic_results, keyword_results, &linear_config)
        }
        FusionMethod::Dbsf => {
            let dbsf_config = DbsfConfig {
                semantic_weight: config.semantic_weight,
                keyword_weight: config.keyword_weight,
                top_k: config.top_k,
            };
            distribution_based_fusion(semantic_results, keyword_results, &dbsf_config)
        }
    };

    // Convert to FusedResult with rank information
    let results = convert_to_fused_results(fused_items, &semantic_map, &keyword_map);

    Ok(results)
}

/// Build a map of ID -> (score, rank) from a list of scored items.
fn build_score_rank_map<T: Clone + Eq + Hash>(
    items: &[ScoredItem<T>],
) -> HashMap<T, (f32, usize)> {
    items
        .iter()
        .enumerate()
        .map(|(idx, item)| (item.id.clone(), (item.score, idx + 1))) // 1-based rank
        .collect()
}

/// Convert ScoredItems to FusedResults with rank information.
fn convert_to_fused_results<T: Clone + Eq + Hash>(
    fused_items: Vec<ScoredItem<T>>,
    semantic_map: &HashMap<T, (f32, usize)>,
    keyword_map: &HashMap<T, (f32, usize)>,
) -> Vec<FusedResult<T>> {
    fused_items
        .into_iter()
        .map(|item| {
            let mut result = FusedResult::new(item.id.clone(), item.score);

            if let Some(&(score, rank)) = semantic_map.get(&item.id) {
                result = result.with_semantic(score, rank);
            }

            if let Some(&(score, rank)) = keyword_map.get(&item.id) {
                result = result.with_keyword(score, rank);
            }

            result
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_data() -> (Vec<ScoredItem<String>>, Vec<ScoredItem<String>>) {
        let semantic = vec![
            ScoredItem::new("doc1".to_string(), 0.95),
            ScoredItem::new("doc2".to_string(), 0.85),
            ScoredItem::new("doc3".to_string(), 0.75),
        ];

        let keyword = vec![
            ScoredItem::new("doc2".to_string(), 12.5),
            ScoredItem::new("doc4".to_string(), 10.2),
            ScoredItem::new("doc1".to_string(), 8.1),
        ];

        (semantic, keyword)
    }

    #[test]
    fn test_fusion_method_default() {
        assert_eq!(FusionMethod::default(), FusionMethod::Rrf);
    }

    #[test]
    fn test_fusion_method_properties() {
        assert!(FusionMethod::Rrf.is_rank_based());
        assert!(!FusionMethod::Linear.is_rank_based());
        assert!(!FusionMethod::Dbsf.is_rank_based());

        assert!(!FusionMethod::Rrf.uses_normalization());
        assert!(FusionMethod::Linear.uses_normalization());
        assert!(FusionMethod::Dbsf.uses_normalization());
    }

    #[test]
    fn test_fusion_config_default() {
        let config = FusionConfig::default();
        assert_eq!(config.method, FusionMethod::Rrf);
        assert!((config.semantic_weight - 0.7).abs() < f32::EPSILON);
        assert!((config.keyword_weight - 0.3).abs() < f32::EPSILON);
        assert!((config.rrf_k - 60.0).abs() < f32::EPSILON);
        assert!(config.top_k.is_none());
        assert!(config.deduplicate);
        assert!(config.normalize_linear);
    }

    #[test]
    fn test_fusion_config_builder() {
        let config = FusionConfig::new(FusionMethod::Linear)
            .with_weights(0.6, 0.4)
            .with_top_k(10)
            .with_deduplicate(false)
            .with_normalize_linear(false);

        assert_eq!(config.method, FusionMethod::Linear);
        assert!((config.semantic_weight - 0.6).abs() < f32::EPSILON);
        assert!((config.keyword_weight - 0.4).abs() < f32::EPSILON);
        assert_eq!(config.top_k, Some(10));
        assert!(!config.deduplicate);
        assert!(!config.normalize_linear);
    }

    #[test]
    fn test_fused_result_creation() {
        let result: FusedResult<String> = FusedResult::new("doc1".to_string(), 0.9)
            .with_semantic(0.95, 1)
            .with_keyword(0.85, 3);

        assert_eq!(result.id, "doc1");
        assert!((result.fused_score - 0.9).abs() < f32::EPSILON);
        assert_eq!(result.semantic_score, Some(0.95));
        assert_eq!(result.semantic_rank, Some(1));
        assert_eq!(result.keyword_score, Some(0.85));
        assert_eq!(result.keyword_rank, Some(3));
        assert!(result.is_in_both());
        assert_eq!(result.best_rank(), Some(1));
    }

    #[test]
    fn test_fused_result_single_source() {
        let result: FusedResult<String> =
            FusedResult::new("doc1".to_string(), 0.9).with_semantic(0.95, 2);

        assert!(!result.is_in_both());
        assert_eq!(result.best_rank(), Some(2));
    }

    #[test]
    fn test_fuse_rrf() {
        let (semantic, keyword) = create_test_data();
        let config = FusionConfig::new(FusionMethod::Rrf);

        let results = fuse(&semantic, &keyword, &config).unwrap();

        // doc2 appears in both lists at good positions
        assert!(!results.is_empty());

        // Find doc2 in results
        let doc2 = results.iter().find(|r| r.id == "doc2").unwrap();
        assert!(doc2.is_in_both());
        assert_eq!(doc2.semantic_rank, Some(2));
        assert_eq!(doc2.keyword_rank, Some(1));
    }

    #[test]
    fn test_fuse_linear() {
        let (semantic, keyword) = create_test_data();
        let config = FusionConfig::new(FusionMethod::Linear);

        let results = fuse(&semantic, &keyword, &config).unwrap();

        assert!(!results.is_empty());

        // All results should have fused scores
        for result in &results {
            assert!(result.fused_score >= 0.0);
        }
    }

    #[test]
    fn test_fuse_dbsf() {
        let (semantic, keyword) = create_test_data();
        let config = FusionConfig::new(FusionMethod::Dbsf);

        let results = fuse(&semantic, &keyword, &config).unwrap();

        assert!(!results.is_empty());

        // Results should be sorted by fused score (descending)
        for i in 1..results.len() {
            assert!(results[i - 1].fused_score >= results[i].fused_score);
        }
    }

    #[test]
    fn test_fuse_with_top_k() {
        let (semantic, keyword) = create_test_data();
        let config = FusionConfig::new(FusionMethod::Rrf).with_top_k(2);

        let results = fuse(&semantic, &keyword, &config).unwrap();

        assert_eq!(results.len(), 2);
    }

    #[test]
    fn test_fuse_empty_inputs() {
        let semantic: Vec<ScoredItem<String>> = vec![];
        let keyword: Vec<ScoredItem<String>> = vec![];
        let config = FusionConfig::default();

        let results = fuse(&semantic, &keyword, &config).unwrap();

        assert!(results.is_empty());
    }

    #[test]
    fn test_fuse_single_source() {
        let semantic = vec![
            ScoredItem::new("doc1".to_string(), 0.95),
            ScoredItem::new("doc2".to_string(), 0.85),
        ];
        let keyword: Vec<ScoredItem<String>> = vec![];
        let config = FusionConfig::default();

        let results = fuse(&semantic, &keyword, &config).unwrap();

        assert_eq!(results.len(), 2);

        // Results should only have semantic info
        for result in &results {
            assert!(result.semantic_rank.is_some());
            assert!(result.keyword_rank.is_none());
            assert!(!result.is_in_both());
        }
    }

    #[test]
    fn test_fusion_method_serialization() {
        let method = FusionMethod::Dbsf;
        let json = serde_json::to_string(&method).unwrap();
        assert_eq!(json, r#""dbsf""#);

        let deserialized: FusionMethod = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized, FusionMethod::Dbsf);
    }
}

//! Configuration for hybrid search operations.
//!
//! This module provides the `HybridSearchConfig` struct that controls all aspects
//! of hybrid search including search limits, fusion settings, filtering, and timeouts.

use serde::{Deserialize, Serialize};

use crate::fusion::FusionMethod;

/// Configuration for hybrid search operations.
///
/// This struct controls all aspects of hybrid search including:
/// - Search limits (top-k values for each stage)
/// - Fusion method and weights
/// - Score filtering and deduplication
/// - Timeouts for individual operations
///
/// # Example
///
/// ```
/// use rag_retrieval::hybrid::HybridSearchConfig;
/// use rag_retrieval::fusion::FusionMethod;
///
/// // Default configuration
/// let config = HybridSearchConfig::default();
/// assert_eq!(config.top_k, 10);
/// assert_eq!(config.fusion_method, FusionMethod::Rrf);
///
/// // Custom configuration via builder
/// let config = HybridSearchConfig::default()
///     .with_top_k(20)
///     .with_fusion_method(FusionMethod::Linear)
///     .with_weights(0.6, 0.4);
///
/// // Load from environment
/// let config = HybridSearchConfig::from_env();
/// ```
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HybridSearchConfig {
    // Search limits
    /// Final number of results to return.
    /// Default: 10
    pub top_k: usize,

    /// Number of results to retrieve from semantic search before fusion.
    /// Default: 50
    pub semantic_top_k: usize,

    /// Number of results to retrieve from keyword search before fusion.
    /// Default: 50
    pub keyword_top_k: usize,

    // Fusion settings
    /// The fusion method to use for combining results.
    /// Default: RRF (Reciprocal Rank Fusion)
    pub fusion_method: FusionMethod,

    /// The k constant for RRF fusion.
    /// Higher values give more weight to lower-ranked items.
    /// Default: 60
    pub rrf_k: u32,

    /// Weight for semantic search results in fusion.
    /// Default: 0.7
    pub semantic_weight: f32,

    /// Weight for keyword search results in fusion.
    /// Default: 0.3
    pub keyword_weight: f32,

    // Filtering
    /// Minimum score threshold for results.
    /// Results with scores below this will be filtered out.
    /// Default: 0.0 (no filtering)
    pub min_score: f32,

    /// Whether to deduplicate results by document ID.
    /// When enabled, only the highest-scored chunk per document is kept.
    /// Default: true
    pub deduplicate: bool,

    // Timeouts (in milliseconds)
    /// Timeout for semantic search operations.
    /// Default: 3000ms
    pub semantic_timeout_ms: u64,

    /// Timeout for keyword search operations.
    /// Default: 3000ms
    pub keyword_timeout_ms: u64,

    /// Total timeout for the entire hybrid search operation.
    /// Default: 15000ms
    pub total_timeout_ms: u64,
}

impl Default for HybridSearchConfig {
    fn default() -> Self {
        Self {
            // Search limits
            top_k: 10,
            semantic_top_k: 50,
            keyword_top_k: 50,

            // Fusion settings
            fusion_method: FusionMethod::Rrf,
            rrf_k: 60,
            semantic_weight: 0.7,
            keyword_weight: 0.3,

            // Filtering
            min_score: 0.0,
            deduplicate: true,

            // Timeouts
            semantic_timeout_ms: 3000,
            keyword_timeout_ms: 3000,
            total_timeout_ms: 15000,
        }
    }
}

impl HybridSearchConfig {
    /// Create a new configuration with default values.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the final number of results to return.
    #[must_use]
    pub const fn with_top_k(mut self, top_k: usize) -> Self {
        self.top_k = top_k;
        self
    }

    /// Set the number of results to retrieve from semantic search.
    #[must_use]
    pub const fn with_semantic_top_k(mut self, top_k: usize) -> Self {
        self.semantic_top_k = top_k;
        self
    }

    /// Set the number of results to retrieve from keyword search.
    #[must_use]
    pub const fn with_keyword_top_k(mut self, top_k: usize) -> Self {
        self.keyword_top_k = top_k;
        self
    }

    /// Set the fusion method.
    #[must_use]
    pub const fn with_fusion_method(mut self, method: FusionMethod) -> Self {
        self.fusion_method = method;
        self
    }

    /// Set the RRF k constant.
    #[must_use]
    pub const fn with_rrf_k(mut self, k: u32) -> Self {
        self.rrf_k = k;
        self
    }

    /// Set the semantic search weight.
    #[must_use]
    pub const fn with_semantic_weight(mut self, weight: f32) -> Self {
        self.semantic_weight = weight;
        self
    }

    /// Set the keyword search weight.
    #[must_use]
    pub const fn with_keyword_weight(mut self, weight: f32) -> Self {
        self.keyword_weight = weight;
        self
    }

    /// Set both search weights at once.
    #[must_use]
    pub const fn with_weights(mut self, semantic: f32, keyword: f32) -> Self {
        self.semantic_weight = semantic;
        self.keyword_weight = keyword;
        self
    }

    /// Set the minimum score threshold.
    #[must_use]
    pub const fn with_min_score(mut self, min_score: f32) -> Self {
        self.min_score = min_score;
        self
    }

    /// Set whether to deduplicate by document ID.
    #[must_use]
    pub const fn with_deduplicate(mut self, deduplicate: bool) -> Self {
        self.deduplicate = deduplicate;
        self
    }

    /// Set the semantic search timeout in milliseconds.
    #[must_use]
    pub const fn with_semantic_timeout_ms(mut self, timeout_ms: u64) -> Self {
        self.semantic_timeout_ms = timeout_ms;
        self
    }

    /// Set the keyword search timeout in milliseconds.
    #[must_use]
    pub const fn with_keyword_timeout_ms(mut self, timeout_ms: u64) -> Self {
        self.keyword_timeout_ms = timeout_ms;
        self
    }

    /// Set the total search timeout in milliseconds.
    #[must_use]
    pub const fn with_total_timeout_ms(mut self, timeout_ms: u64) -> Self {
        self.total_timeout_ms = timeout_ms;
        self
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `HYBRID_TOP_K`: Final number of results (default: 10)
    /// - `HYBRID_SEMANTIC_TOP_K`: Semantic search limit (default: 50)
    /// - `HYBRID_KEYWORD_TOP_K`: Keyword search limit (default: 50)
    /// - `HYBRID_FUSION_METHOD`: Fusion method (rrf, linear, dbsf) (default: rrf)
    /// - `HYBRID_RRF_K`: RRF k constant (default: 60)
    /// - `HYBRID_SEMANTIC_WEIGHT`: Semantic weight (default: 0.7)
    /// - `HYBRID_KEYWORD_WEIGHT`: Keyword weight (default: 0.3)
    /// - `HYBRID_MIN_SCORE`: Minimum score threshold (default: 0.0)
    /// - `HYBRID_DEDUPLICATE`: Enable deduplication (default: true)
    /// - `HYBRID_SEMANTIC_TIMEOUT_MS`: Semantic timeout (default: 3000)
    /// - `HYBRID_KEYWORD_TIMEOUT_MS`: Keyword timeout (default: 3000)
    /// - `HYBRID_TOTAL_TIMEOUT_MS`: Total timeout (default: 15000)
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        // Search limits
        if let Ok(val) = std::env::var("HYBRID_TOP_K") {
            if let Ok(v) = val.parse() {
                config.top_k = v;
            }
        }

        if let Ok(val) = std::env::var("HYBRID_SEMANTIC_TOP_K") {
            if let Ok(v) = val.parse() {
                config.semantic_top_k = v;
            }
        }

        if let Ok(val) = std::env::var("HYBRID_KEYWORD_TOP_K") {
            if let Ok(v) = val.parse() {
                config.keyword_top_k = v;
            }
        }

        // Fusion settings
        if let Ok(val) = std::env::var("HYBRID_FUSION_METHOD") {
            config.fusion_method = match val.to_lowercase().as_str() {
                "linear" => FusionMethod::Linear,
                "dbsf" => FusionMethod::Dbsf,
                _ => FusionMethod::Rrf,
            };
        }

        if let Ok(val) = std::env::var("HYBRID_RRF_K") {
            if let Ok(v) = val.parse() {
                config.rrf_k = v;
            }
        }

        if let Ok(val) = std::env::var("HYBRID_SEMANTIC_WEIGHT") {
            if let Ok(v) = val.parse() {
                config.semantic_weight = v;
            }
        }

        if let Ok(val) = std::env::var("HYBRID_KEYWORD_WEIGHT") {
            if let Ok(v) = val.parse() {
                config.keyword_weight = v;
            }
        }

        // Filtering
        if let Ok(val) = std::env::var("HYBRID_MIN_SCORE") {
            if let Ok(v) = val.parse() {
                config.min_score = v;
            }
        }

        if let Ok(val) = std::env::var("HYBRID_DEDUPLICATE") {
            config.deduplicate = val.to_lowercase() == "true";
        }

        // Timeouts
        if let Ok(val) = std::env::var("HYBRID_SEMANTIC_TIMEOUT_MS") {
            if let Ok(v) = val.parse() {
                config.semantic_timeout_ms = v;
            }
        }

        if let Ok(val) = std::env::var("HYBRID_KEYWORD_TIMEOUT_MS") {
            if let Ok(v) = val.parse() {
                config.keyword_timeout_ms = v;
            }
        }

        if let Ok(val) = std::env::var("HYBRID_TOTAL_TIMEOUT_MS") {
            if let Ok(v) = val.parse() {
                config.total_timeout_ms = v;
            }
        }

        config
    }

    /// Get the semantic search timeout as a Duration.
    #[must_use]
    pub const fn semantic_timeout(&self) -> std::time::Duration {
        std::time::Duration::from_millis(self.semantic_timeout_ms)
    }

    /// Get the keyword search timeout as a Duration.
    #[must_use]
    pub const fn keyword_timeout(&self) -> std::time::Duration {
        std::time::Duration::from_millis(self.keyword_timeout_ms)
    }

    /// Get the total search timeout as a Duration.
    #[must_use]
    pub const fn total_timeout(&self) -> std::time::Duration {
        std::time::Duration::from_millis(self.total_timeout_ms)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hybrid_config_default() {
        let config = HybridSearchConfig::default();

        assert_eq!(config.top_k, 10);
        assert_eq!(config.semantic_top_k, 50);
        assert_eq!(config.keyword_top_k, 50);
        assert_eq!(config.fusion_method, FusionMethod::Rrf);
        assert_eq!(config.rrf_k, 60);
        assert!((config.semantic_weight - 0.7).abs() < f32::EPSILON);
        assert!((config.keyword_weight - 0.3).abs() < f32::EPSILON);
        assert!((config.min_score - 0.0).abs() < f32::EPSILON);
        assert!(config.deduplicate);
        assert_eq!(config.semantic_timeout_ms, 3000);
        assert_eq!(config.keyword_timeout_ms, 3000);
        assert_eq!(config.total_timeout_ms, 15000);
    }

    #[test]
    fn test_hybrid_config_builder() {
        let config = HybridSearchConfig::new()
            .with_top_k(20)
            .with_semantic_top_k(100)
            .with_keyword_top_k(100)
            .with_fusion_method(FusionMethod::Linear)
            .with_rrf_k(30)
            .with_weights(0.6, 0.4)
            .with_min_score(0.5)
            .with_deduplicate(false)
            .with_semantic_timeout_ms(5000)
            .with_keyword_timeout_ms(5000)
            .with_total_timeout_ms(20000);

        assert_eq!(config.top_k, 20);
        assert_eq!(config.semantic_top_k, 100);
        assert_eq!(config.keyword_top_k, 100);
        assert_eq!(config.fusion_method, FusionMethod::Linear);
        assert_eq!(config.rrf_k, 30);
        assert!((config.semantic_weight - 0.6).abs() < f32::EPSILON);
        assert!((config.keyword_weight - 0.4).abs() < f32::EPSILON);
        assert!((config.min_score - 0.5).abs() < f32::EPSILON);
        assert!(!config.deduplicate);
        assert_eq!(config.semantic_timeout_ms, 5000);
        assert_eq!(config.keyword_timeout_ms, 5000);
        assert_eq!(config.total_timeout_ms, 20000);
    }

    #[test]
    fn test_hybrid_config_from_env() {
        // Clear any existing env vars that might interfere
        std::env::remove_var("HYBRID_TOP_K");
        std::env::remove_var("HYBRID_FUSION_METHOD");

        // Set specific env vars for testing
        std::env::set_var("HYBRID_TOP_K", "25");
        std::env::set_var("HYBRID_FUSION_METHOD", "linear");
        std::env::set_var("HYBRID_SEMANTIC_WEIGHT", "0.8");
        std::env::set_var("HYBRID_DEDUPLICATE", "false");

        let config = HybridSearchConfig::from_env();

        assert_eq!(config.top_k, 25);
        assert_eq!(config.fusion_method, FusionMethod::Linear);
        assert!((config.semantic_weight - 0.8).abs() < f32::EPSILON);
        assert!(!config.deduplicate);

        // Clean up
        std::env::remove_var("HYBRID_TOP_K");
        std::env::remove_var("HYBRID_FUSION_METHOD");
        std::env::remove_var("HYBRID_SEMANTIC_WEIGHT");
        std::env::remove_var("HYBRID_DEDUPLICATE");
    }

    #[test]
    fn test_hybrid_config_timeout_durations() {
        let config = HybridSearchConfig::default()
            .with_semantic_timeout_ms(5000)
            .with_keyword_timeout_ms(4000)
            .with_total_timeout_ms(10000);

        assert_eq!(
            config.semantic_timeout(),
            std::time::Duration::from_millis(5000)
        );
        assert_eq!(
            config.keyword_timeout(),
            std::time::Duration::from_millis(4000)
        );
        assert_eq!(
            config.total_timeout(),
            std::time::Duration::from_millis(10000)
        );
    }

    #[test]
    fn test_hybrid_config_serialization() {
        let config = HybridSearchConfig::default()
            .with_top_k(15)
            .with_fusion_method(FusionMethod::Dbsf);

        let json = serde_json::to_string(&config).unwrap();
        assert!(json.contains("\"top_k\":15"));
        assert!(json.contains("\"dbsf\""));

        let deserialized: HybridSearchConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.top_k, 15);
        assert_eq!(deserialized.fusion_method, FusionMethod::Dbsf);
    }
}

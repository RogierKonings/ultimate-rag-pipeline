//! Property-based tests for fusion algorithms.
//!
//! These tests verify invariant properties of the fusion algorithms
//! using random inputs. Each property should hold for all valid inputs.

use proptest::prelude::*;
use rag_retrieval::fusion::{
    distribution_based_fusion, fuse, linear_fusion, reciprocal_rank_fusion, DbsfConfig,
    FusionConfig, FusionMethod, LinearConfig, RrfConfig, ScoredItem,
};

/// Generate an arbitrary scored item with a string ID.
fn arb_scored_item() -> impl Strategy<Value = ScoredItem<String>> {
    (
        "[a-z]{1,10}",     // Random ID
        0.0f32..=100.0f32, // Score can range widely
    )
        .prop_map(|(id, score)| ScoredItem::new(id, score))
}

/// Generate a vector of scored items with unique IDs.
fn arb_scored_items(min: usize, max: usize) -> impl Strategy<Value = Vec<ScoredItem<String>>> {
    proptest::collection::vec(arb_scored_item(), min..max).prop_map(|items| {
        // Deduplicate by ID, keeping first occurrence
        let mut seen = std::collections::HashSet::new();
        items
            .into_iter()
            .filter(|item| seen.insert(item.id.clone()))
            .collect()
    })
}

proptest! {
    /// RRF output should always be sorted by score in descending order.
    #[test]
    fn rrf_output_sorted_descending(
        semantic in arb_scored_items(0, 50),
        keyword in arb_scored_items(0, 50)
    ) {
        let config = RrfConfig::default();
        let results = reciprocal_rank_fusion(&[&semantic, &keyword], &config).unwrap();

        // Verify descending order
        for window in results.windows(2) {
            prop_assert!(
                window[0].score >= window[1].score,
                "Results not sorted descending: {} >= {} failed",
                window[0].score,
                window[1].score
            );
        }
    }

    /// RRF should not lose any items - all input items should appear in output.
    #[test]
    fn rrf_no_data_loss(
        semantic in arb_scored_items(1, 30),
        keyword in arb_scored_items(1, 30)
    ) {
        let config = RrfConfig::default(); // No top_k limit

        let results = reciprocal_rank_fusion(&[&semantic, &keyword], &config).unwrap();

        // Collect all unique input IDs
        let mut expected_ids: std::collections::HashSet<String> =
            semantic.iter().map(|i| i.id.clone()).collect();
        expected_ids.extend(keyword.iter().map(|i| i.id.clone()));

        // Collect all output IDs
        let output_ids: std::collections::HashSet<String> =
            results.iter().map(|i| i.id.clone()).collect();

        // All input IDs should be in output
        prop_assert_eq!(
            expected_ids, output_ids,
            "Some IDs were lost in fusion"
        );
    }

    /// RRF scores should always be positive.
    #[test]
    fn rrf_scores_positive(
        semantic in arb_scored_items(1, 30),
        keyword in arb_scored_items(1, 30),
        k in 1.0f32..=100.0f32
    ) {
        let config = RrfConfig::new(k);
        let results = reciprocal_rank_fusion(&[&semantic, &keyword], &config).unwrap();

        for result in &results {
            prop_assert!(
                result.score > 0.0,
                "RRF score should be positive, got {}",
                result.score
            );
        }
    }

    /// Linear fusion output should always be sorted descending.
    #[test]
    fn linear_output_sorted_descending(
        semantic in arb_scored_items(0, 30),
        keyword in arb_scored_items(0, 30)
    ) {
        let config = LinearConfig::default();
        let results = linear_fusion(&semantic, &keyword, &config);

        for window in results.windows(2) {
            prop_assert!(
                window[0].score >= window[1].score,
                "Results not sorted descending: {} >= {} failed",
                window[0].score,
                window[1].score
            );
        }
    }

    /// Linear fusion with normalization should produce scores in valid range.
    #[test]
    fn linear_scores_bounded(
        semantic in arb_scored_items(1, 20),
        keyword in arb_scored_items(1, 20),
        semantic_weight in 0.0f32..=1.0f32,
        keyword_weight in 0.0f32..=1.0f32
    ) {
        let config = LinearConfig {
            semantic_weight,
            keyword_weight,
            top_k: None,
            normalize: true, // With normalization, scores should be bounded
        };
        let results = linear_fusion(&semantic, &keyword, &config);

        for result in &results {
            prop_assert!(
                result.score >= 0.0,
                "Score should be >= 0, got {}",
                result.score
            );
            // With normalized inputs (0-1) and weights, max possible is sum of weights
            let max_possible = semantic_weight + keyword_weight;
            prop_assert!(
                result.score <= max_possible + f32::EPSILON,
                "Score {} exceeds max possible {} (weights: s={}, k={})",
                result.score,
                max_possible,
                semantic_weight,
                keyword_weight
            );
        }
    }

    /// DBSF output should always be sorted descending.
    #[test]
    fn dbsf_output_sorted_descending(
        semantic in arb_scored_items(0, 30),
        keyword in arb_scored_items(0, 30)
    ) {
        let config = DbsfConfig::default();
        let results = distribution_based_fusion(&semantic, &keyword, &config);

        for window in results.windows(2) {
            prop_assert!(
                window[0].score >= window[1].score,
                "Results not sorted descending: {} >= {} failed",
                window[0].score,
                window[1].score
            );
        }
    }

    /// DBSF should not lose any items when no top_k is set.
    #[test]
    fn dbsf_no_data_loss(
        semantic in arb_scored_items(1, 30),
        keyword in arb_scored_items(1, 30)
    ) {
        let config = DbsfConfig::default();
        let results = distribution_based_fusion(&semantic, &keyword, &config);

        // Collect all unique input IDs
        let mut expected_ids: std::collections::HashSet<String> =
            semantic.iter().map(|i| i.id.clone()).collect();
        expected_ids.extend(keyword.iter().map(|i| i.id.clone()));

        // Collect all output IDs
        let output_ids: std::collections::HashSet<String> =
            results.iter().map(|i| i.id.clone()).collect();

        prop_assert_eq!(
            expected_ids, output_ids,
            "Some IDs were lost in DBSF fusion"
        );
    }

    /// top_k parameter should limit results correctly.
    #[test]
    fn fusion_respects_top_k(
        semantic in arb_scored_items(5, 30),
        keyword in arb_scored_items(5, 30),
        top_k in 1usize..=10
    ) {
        // RRF
        let rrf_config = RrfConfig::default().with_top_k(top_k);
        let rrf_results = reciprocal_rank_fusion(&[&semantic, &keyword], &rrf_config).unwrap();
        let expected_rrf = top_k.min(semantic.len() + keyword.len()); // Can't exceed total unique
        prop_assert!(
            rrf_results.len() <= expected_rrf,
            "RRF returned {} results but expected <= {}",
            rrf_results.len(),
            expected_rrf
        );

        // Linear
        let linear_config = LinearConfig::default().with_top_k(top_k);
        let linear_results = linear_fusion(&semantic, &keyword, &linear_config);
        let expected_linear = top_k.min(semantic.len() + keyword.len());
        prop_assert!(
            linear_results.len() <= expected_linear,
            "Linear returned {} results but expected <= {}",
            linear_results.len(),
            expected_linear
        );

        // DBSF
        let dbsf_config = DbsfConfig::default().with_top_k(top_k);
        let dbsf_results = distribution_based_fusion(&semantic, &keyword, &dbsf_config);
        let expected_dbsf = top_k.min(semantic.len() + keyword.len());
        prop_assert!(
            dbsf_results.len() <= expected_dbsf,
            "DBSF returned {} results but expected <= {}",
            dbsf_results.len(),
            expected_dbsf
        );
    }

    /// Empty inputs should produce empty outputs.
    #[test]
    fn fusion_empty_inputs_produce_empty_outputs(
        _dummy in Just(())  // Just need to run this test
    ) {
        let empty: Vec<ScoredItem<String>> = vec![];

        // RRF
        let rrf_results = reciprocal_rank_fusion(&[&empty, &empty], &RrfConfig::default()).unwrap();
        prop_assert!(rrf_results.is_empty(), "RRF with empty inputs should be empty");

        // Linear
        let linear_results = linear_fusion(&empty, &empty, &LinearConfig::default());
        prop_assert!(linear_results.is_empty(), "Linear with empty inputs should be empty");

        // DBSF
        let dbsf_results = distribution_based_fusion(&empty, &empty, &DbsfConfig::default());
        prop_assert!(dbsf_results.is_empty(), "DBSF with empty inputs should be empty");
    }

    /// Unified fuse() API should produce consistent results.
    #[test]
    fn unified_fuse_api_consistent(
        semantic in arb_scored_items(1, 20),
        keyword in arb_scored_items(1, 20)
    ) {
        // Test RRF through unified API
        let config = FusionConfig::new(FusionMethod::Rrf);
        let results = fuse(&semantic, &keyword, &config).unwrap();

        // Results should be sorted
        for window in results.windows(2) {
            prop_assert!(
                window[0].fused_score >= window[1].fused_score,
                "Unified fuse results not sorted"
            );
        }

        // Results should include rank information
        for result in &results {
            // At least one of semantic_rank or keyword_rank should be set
            prop_assert!(
                result.semantic_rank.is_some() || result.keyword_rank.is_some(),
                "FusedResult should have at least one rank set"
            );
        }
    }

    /// Weights should affect fusion proportionally.
    #[test]
    fn weights_affect_fusion_proportionally(
        item_id in "[a-z]{5}",
        semantic_score in 0.5f32..=1.0f32,
        keyword_score in 0.5f32..=1.0f32
    ) {
        let semantic = vec![ScoredItem::new(item_id.clone(), semantic_score)];
        let keyword = vec![ScoredItem::new(item_id.clone(), keyword_score)];

        // High semantic weight
        let config_high_semantic = LinearConfig {
            semantic_weight: 0.9,
            keyword_weight: 0.1,
            top_k: None,
            normalize: false,
        };
        let results_high_semantic = linear_fusion(&semantic, &keyword, &config_high_semantic);

        // High keyword weight
        let config_high_keyword = LinearConfig {
            semantic_weight: 0.1,
            keyword_weight: 0.9,
            top_k: None,
            normalize: false,
        };
        let results_high_keyword = linear_fusion(&semantic, &keyword, &config_high_keyword);

        if !results_high_semantic.is_empty() && !results_high_keyword.is_empty() {
            let score_high_semantic = results_high_semantic[0].score;
            let score_high_keyword = results_high_keyword[0].score;

            // When semantic score > keyword score, high semantic weight should produce higher final
            if semantic_score > keyword_score {
                prop_assert!(
                    score_high_semantic > score_high_keyword,
                    "High semantic weight should boost score when semantic > keyword"
                );
            } else if keyword_score > semantic_score {
                prop_assert!(
                    score_high_keyword > score_high_semantic,
                    "High keyword weight should boost score when keyword > semantic"
                );
            }
        }
    }
}

#[cfg(test)]
mod determinism_tests {
    use super::*;

    /// Fusion algorithms should be deterministic - same inputs produce same outputs.
    #[test]
    fn fusion_is_deterministic() {
        let semantic = vec![
            ScoredItem::new("doc1".to_string(), 0.9),
            ScoredItem::new("doc2".to_string(), 0.8),
            ScoredItem::new("doc3".to_string(), 0.7),
        ];

        let keyword = vec![
            ScoredItem::new("doc2".to_string(), 12.5),
            ScoredItem::new("doc4".to_string(), 10.2),
            ScoredItem::new("doc1".to_string(), 8.1),
        ];

        // Run RRF multiple times
        let config = RrfConfig::default();
        let results1 = reciprocal_rank_fusion(&[&semantic, &keyword], &config).unwrap();
        let results2 = reciprocal_rank_fusion(&[&semantic, &keyword], &config).unwrap();

        assert_eq!(results1.len(), results2.len());
        for (r1, r2) in results1.iter().zip(results2.iter()) {
            assert_eq!(r1.id, r2.id);
            assert!((r1.score - r2.score).abs() < f32::EPSILON);
        }

        // Run Linear multiple times
        let config = LinearConfig::default();
        let results1 = linear_fusion(&semantic, &keyword, &config);
        let results2 = linear_fusion(&semantic, &keyword, &config);

        assert_eq!(results1.len(), results2.len());
        for (r1, r2) in results1.iter().zip(results2.iter()) {
            assert_eq!(r1.id, r2.id);
            assert!((r1.score - r2.score).abs() < f32::EPSILON);
        }

        // Run DBSF multiple times
        let config = DbsfConfig::default();
        let results1 = distribution_based_fusion(&semantic, &keyword, &config);
        let results2 = distribution_based_fusion(&semantic, &keyword, &config);

        assert_eq!(results1.len(), results2.len());
        for (r1, r2) in results1.iter().zip(results2.iter()) {
            assert_eq!(r1.id, r2.id);
            assert!((r1.score - r2.score).abs() < f32::EPSILON);
        }
    }
}

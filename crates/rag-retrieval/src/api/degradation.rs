//! Runtime degradation evaluation for the retrieval service.
//!
//! This module evaluates the actual execution outcomes of a retrieval request
//! and produces accurate degradation metadata (`degradation_mode`,
//! `components_used`, `components_skipped`) instead of hardcoded defaults.
//!
//! # Components
//!
//! The retrieval pipeline consists of four trackable components:
//!
//! - `embedding` – query vectorisation (always required for semantic modes)
//! - `semantic` – Qdrant vector search
//! - `keyword`  – OpenSearch BM25 search
//! - `reranker`  – cross-encoder reranking
//!
//! # Degradation Modes
//!
//! | Mode                | Meaning                                         |
//! |---------------------|-------------------------------------------------|
//! | `None`              | All requested components completed successfully |
//! | `"semantic_only"`   | Hybrid was requested but keyword search failed  |
//! | `"keyword_only"`    | Hybrid was requested but semantic search failed |
//! | `"rerank_skipped"`  | Reranking was requested but failed/unavailable  |

use rag_types::SearchMode;

/// Tracks the outcome of each retrieval component during a single request.
#[derive(Debug, Clone, Default)]
#[allow(clippy::struct_excessive_bools)]
pub struct ComponentOutcome {
    /// Whether query embedding succeeded.
    pub embedding_ok: bool,
    /// Whether semantic search was attempted.
    pub semantic_attempted: bool,
    /// Whether semantic search succeeded.
    pub semantic_ok: bool,
    /// Whether keyword search was attempted.
    pub keyword_attempted: bool,
    /// Whether keyword search succeeded.
    pub keyword_ok: bool,
    /// Whether reranking was requested for this request.
    pub rerank_requested: bool,
    /// Whether reranking was actually executed successfully.
    pub rerank_ok: bool,
}

impl ComponentOutcome {
    /// Create a new outcome tracker with all fields set to `false`.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Mark the embedding component as succeeded.
    #[must_use]
    pub fn with_embedding_ok(mut self) -> Self {
        self.embedding_ok = true;
        self
    }

    /// Mark semantic search as attempted and optionally succeeded.
    #[must_use]
    pub fn with_semantic(mut self, ok: bool) -> Self {
        self.semantic_attempted = true;
        self.semantic_ok = ok;
        self
    }

    /// Mark keyword search as attempted and optionally succeeded.
    #[must_use]
    pub fn with_keyword(mut self, ok: bool) -> Self {
        self.keyword_attempted = true;
        self.keyword_ok = ok;
        self
    }

    /// Mark reranking as requested and optionally succeeded.
    #[must_use]
    pub fn with_rerank(mut self, requested: bool, ok: bool) -> Self {
        self.rerank_requested = requested;
        self.rerank_ok = ok;
        self
    }
}

/// The result of degradation evaluation for a single retrieval request.
#[derive(Debug, Clone)]
pub struct DegradationResult {
    /// The degradation mode string, or `None` when fully healthy.
    pub mode: Option<String>,
    /// Components that contributed results to this request.
    pub components_used: Vec<String>,
    /// Components that were expected but skipped due to failure or
    /// unavailability.
    pub components_skipped: Vec<String>,
}

/// Evaluate degradation status from the component outcomes of a retrieval
/// request.
///
/// The `search_mode` is the mode that was *requested* by the caller (Hybrid,
/// Semantic, or Keyword). The `outcome` records which components actually
/// succeeded.
///
/// # Examples
///
/// ```
/// use rag_retrieval::api::degradation::{evaluate, ComponentOutcome};
/// use rag_types::SearchMode;
///
/// // Normal hybrid search – everything succeeded
/// let outcome = ComponentOutcome::new()
///     .with_embedding_ok()
///     .with_semantic(true)
///     .with_keyword(true)
///     .with_rerank(false, false);
/// let result = evaluate(SearchMode::Hybrid, &outcome);
/// assert!(result.mode.is_none());
/// assert_eq!(result.components_used, vec!["embedding", "semantic", "keyword"]);
/// assert!(result.components_skipped.is_empty());
/// ```
#[must_use]
pub fn evaluate(search_mode: SearchMode, outcome: &ComponentOutcome) -> DegradationResult {
    let mut used: Vec<String> = Vec::new();
    let mut skipped: Vec<String> = Vec::new();

    // Embedding is implicitly required for semantic/hybrid modes.
    // We track it as used when it succeeded.
    if outcome.embedding_ok {
        used.push("embedding".into());
    } else if search_mode.uses_semantic() && outcome.semantic_attempted {
        skipped.push("embedding".into());
    }

    // Determine which search components were expected based on requested mode.
    match search_mode {
        SearchMode::Hybrid => {
            if outcome.semantic_ok {
                used.push("semantic".into());
            } else if outcome.semantic_attempted {
                skipped.push("semantic".into());
            }

            if outcome.keyword_ok {
                used.push("keyword".into());
            } else if outcome.keyword_attempted {
                skipped.push("keyword".into());
            }
        }
        SearchMode::Semantic => {
            if outcome.semantic_ok {
                used.push("semantic".into());
            } else if outcome.semantic_attempted {
                skipped.push("semantic".into());
            }
        }
        SearchMode::Keyword => {
            if outcome.keyword_ok {
                used.push("keyword".into());
            } else if outcome.keyword_attempted {
                skipped.push("keyword".into());
            }
        }
    }

    // Reranker tracking
    if outcome.rerank_requested {
        if outcome.rerank_ok {
            used.push("reranker".into());
        } else {
            skipped.push("reranker".into());
        }
    }

    // Determine the degradation mode.
    let mode = determine_mode(search_mode, outcome);

    DegradationResult {
        mode,
        components_used: used,
        components_skipped: skipped,
    }
}

/// Determine the degradation mode string from the search mode and outcome.
fn determine_mode(search_mode: SearchMode, outcome: &ComponentOutcome) -> Option<String> {
    match search_mode {
        SearchMode::Hybrid => {
            let semantic_failed = outcome.semantic_attempted && !outcome.semantic_ok;
            let keyword_failed = outcome.keyword_attempted && !outcome.keyword_ok;

            if semantic_failed && keyword_failed {
                // Both failed – should normally be caught before we get here,
                // but represent it as "minimal" for safety.
                Some("minimal".into())
            } else if semantic_failed {
                Some("keyword_only".into())
            } else if keyword_failed {
                Some("semantic_only".into())
            } else if outcome.rerank_requested && !outcome.rerank_ok {
                Some("rerank_skipped".into())
            } else {
                None // fully healthy
            }
        }
        SearchMode::Semantic | SearchMode::Keyword => {
            // For single-mode searches the only possible degradation is a
            // reranker skip.
            if outcome.rerank_requested && !outcome.rerank_ok {
                Some("rerank_skipped".into())
            } else {
                None
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // ---------------------------------------------------------------
    // Hybrid mode tests
    // ---------------------------------------------------------------

    #[test]
    fn test_hybrid_all_ok() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_semantic(true)
            .with_keyword(true)
            .with_rerank(false, false);

        let result = evaluate(SearchMode::Hybrid, &outcome);

        assert!(result.mode.is_none());
        assert_eq!(
            result.components_used,
            vec!["embedding", "semantic", "keyword"]
        );
        assert!(result.components_skipped.is_empty());
    }

    #[test]
    fn test_hybrid_all_ok_with_rerank() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_semantic(true)
            .with_keyword(true)
            .with_rerank(true, true);

        let result = evaluate(SearchMode::Hybrid, &outcome);

        assert!(result.mode.is_none());
        assert_eq!(
            result.components_used,
            vec!["embedding", "semantic", "keyword", "reranker"]
        );
        assert!(result.components_skipped.is_empty());
    }

    #[test]
    fn test_hybrid_semantic_failed() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_semantic(false)
            .with_keyword(true);

        let result = evaluate(SearchMode::Hybrid, &outcome);

        assert_eq!(result.mode.as_deref(), Some("keyword_only"));
        assert_eq!(result.components_used, vec!["embedding", "keyword"]);
        assert_eq!(result.components_skipped, vec!["semantic"]);
    }

    #[test]
    fn test_hybrid_embedding_failed_keyword_fallback() {
        let outcome = ComponentOutcome::new()
            .with_semantic(false)
            .with_keyword(true);

        let result = evaluate(SearchMode::Hybrid, &outcome);

        assert_eq!(result.mode.as_deref(), Some("keyword_only"));
        assert_eq!(result.components_used, vec!["keyword"]);
        assert_eq!(result.components_skipped, vec!["embedding", "semantic"]);
    }

    #[test]
    fn test_hybrid_keyword_failed() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_semantic(true)
            .with_keyword(false);

        let result = evaluate(SearchMode::Hybrid, &outcome);

        assert_eq!(result.mode.as_deref(), Some("semantic_only"));
        assert_eq!(result.components_used, vec!["embedding", "semantic"]);
        assert_eq!(result.components_skipped, vec!["keyword"]);
    }

    #[test]
    fn test_hybrid_both_failed() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_semantic(false)
            .with_keyword(false);

        let result = evaluate(SearchMode::Hybrid, &outcome);

        assert_eq!(result.mode.as_deref(), Some("minimal"));
        assert_eq!(result.components_used, vec!["embedding"]);
        assert_eq!(result.components_skipped, vec!["semantic", "keyword"]);
    }

    #[test]
    fn test_hybrid_rerank_skipped() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_semantic(true)
            .with_keyword(true)
            .with_rerank(true, false);

        let result = evaluate(SearchMode::Hybrid, &outcome);

        assert_eq!(result.mode.as_deref(), Some("rerank_skipped"));
        assert_eq!(
            result.components_used,
            vec!["embedding", "semantic", "keyword"]
        );
        assert_eq!(result.components_skipped, vec!["reranker"]);
    }

    // ---------------------------------------------------------------
    // Semantic-only mode tests
    // ---------------------------------------------------------------

    #[test]
    fn test_semantic_only_ok() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_semantic(true);

        let result = evaluate(SearchMode::Semantic, &outcome);

        assert!(result.mode.is_none());
        assert_eq!(result.components_used, vec!["embedding", "semantic"]);
        assert!(result.components_skipped.is_empty());
    }

    #[test]
    fn test_semantic_rerank_skipped() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_semantic(true)
            .with_rerank(true, false);

        let result = evaluate(SearchMode::Semantic, &outcome);

        assert_eq!(result.mode.as_deref(), Some("rerank_skipped"));
        assert_eq!(result.components_used, vec!["embedding", "semantic"]);
        assert_eq!(result.components_skipped, vec!["reranker"]);
    }

    // ---------------------------------------------------------------
    // Keyword-only mode tests
    // ---------------------------------------------------------------

    #[test]
    fn test_keyword_only_ok() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_keyword(true);

        let result = evaluate(SearchMode::Keyword, &outcome);

        assert!(result.mode.is_none());
        assert_eq!(result.components_used, vec!["embedding", "keyword"]);
        assert!(result.components_skipped.is_empty());
    }

    #[test]
    fn test_keyword_rerank_skipped() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_keyword(true)
            .with_rerank(true, false);

        let result = evaluate(SearchMode::Keyword, &outcome);

        assert_eq!(result.mode.as_deref(), Some("rerank_skipped"));
        assert_eq!(result.components_used, vec!["embedding", "keyword"]);
        assert_eq!(result.components_skipped, vec!["reranker"]);
    }

    // ---------------------------------------------------------------
    // Edge cases
    // ---------------------------------------------------------------

    #[test]
    fn test_no_components_attempted() {
        let outcome = ComponentOutcome::new();

        let result = evaluate(SearchMode::Hybrid, &outcome);

        // No search components attempted means nothing to degrade
        assert!(result.mode.is_none());
        assert!(result.components_used.is_empty());
        assert!(result.components_skipped.is_empty());
    }

    #[test]
    fn test_rerank_not_requested_not_listed() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_semantic(true)
            .with_keyword(true)
            .with_rerank(false, false);

        let result = evaluate(SearchMode::Hybrid, &outcome);

        assert!(!result.components_used.contains(&"reranker".to_string()));
        assert!(!result.components_skipped.contains(&"reranker".to_string()));
    }

    // ---------------------------------------------------------------
    // Search mode + component matrix: only requested components appear
    // ---------------------------------------------------------------

    #[test]
    fn test_semantic_mode_keyword_not_listed() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_semantic(true);

        let result = evaluate(SearchMode::Semantic, &outcome);

        assert!(!result.components_used.contains(&"keyword".to_string()));
        assert!(!result.components_skipped.contains(&"keyword".to_string()));
    }

    #[test]
    fn test_keyword_mode_semantic_not_listed() {
        let outcome = ComponentOutcome::new()
            .with_embedding_ok()
            .with_keyword(true);

        let result = evaluate(SearchMode::Keyword, &outcome);

        assert!(!result.components_used.contains(&"semantic".to_string()));
        assert!(!result.components_skipped.contains(&"semantic".to_string()));
    }
}

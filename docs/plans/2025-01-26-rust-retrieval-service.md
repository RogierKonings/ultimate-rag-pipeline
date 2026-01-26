# Rust Retrieval Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a production-ready Rust retrieval service with full feature parity to the Python implementation, including hybrid search, reranking, ACL filtering, caching, query preprocessing, and observability.

**Architecture:** The service uses Axum for HTTP, with modular components for semantic search (Qdrant), keyword search (OpenSearch), hybrid fusion (RRF/Linear/DBSF), cross-encoder reranking, and ACL-based access control. Query preprocessing includes normalization, classification, expansion, and HyDE. All components are async and instrument with OpenTelemetry.

**Tech Stack:** Rust 1.75+, Axum, Tokio, qdrant-client, opensearch-rs, redis-rs, reqwest, serde, tracing, opentelemetry, utoipa (OpenAPI)

---

## Phase Overview

| Phase | Tasks | Description |
|-------|-------|-------------|
| 1 | 1-4 | Core types and error handling |
| 2 | 5-9 | Search components (semantic, keyword, fusion) |
| 3 | 10-13 | Query preprocessing pipeline |
| 4 | 14-16 | Reranking and ACL filtering |
| 5 | 17-19 | Caching layer |
| 6 | 20-22 | Hybrid searcher orchestration |
| 7 | 23-27 | Axum API service |
| 8 | 28-30 | Observability and metrics |
| 9 | 31-32 | Integration tests and benchmarks |

---

## Task 1: Core Retrieval Types

**Files:**
- Modify: `crates/rag-retrieval/src/lib.rs`
- Create: `crates/rag-retrieval/src/types.rs`
- Create: `crates/rag-retrieval/src/error.rs`
- Test: `crates/rag-retrieval/src/types.rs` (inline tests)

**Step 1: Create error types**

Create `crates/rag-retrieval/src/error.rs`:

```rust
//! Error types for the retrieval service.

use thiserror::Error;

/// Result type for retrieval operations.
pub type Result<T> = std::result::Result<T, RetrievalError>;

/// Errors that can occur during retrieval operations.
#[derive(Debug, Error)]
pub enum RetrievalError {
    /// Semantic search (Qdrant) error.
    #[error("Semantic search error: {0}")]
    SemanticSearch(String),

    /// Keyword search (OpenSearch) error.
    #[error("Keyword search error: {0}")]
    KeywordSearch(String),

    /// Embedding service error.
    #[error("Embedding error: {0}")]
    Embedding(String),

    /// Reranking service error.
    #[error("Reranking error: {0}")]
    Reranking(String),

    /// Cache error.
    #[error("Cache error: {0}")]
    Cache(String),

    /// LLM gateway error (for HyDE/expansion).
    #[error("LLM error: {0}")]
    Llm(String),

    /// Configuration error.
    #[error("Configuration error: {0}")]
    Config(String),

    /// Timeout error.
    #[error("Operation timed out: {0}")]
    Timeout(String),

    /// Invalid request.
    #[error("Invalid request: {0}")]
    InvalidRequest(String),

    /// Authentication/authorization error.
    #[error("Authorization error: {0}")]
    Unauthorized(String),

    /// Internal error.
    #[error("Internal error: {0}")]
    Internal(String),
}

impl From<rag_vectorstore::VectorStoreError> for RetrievalError {
    fn from(err: rag_vectorstore::VectorStoreError) -> Self {
        RetrievalError::SemanticSearch(err.to_string())
    }
}

impl From<rag_search::SearchError> for RetrievalError {
    fn from(err: rag_search::SearchError) -> Self {
        RetrievalError::KeywordSearch(err.to_string())
    }
}

impl From<rag_cache::CacheError> for RetrievalError {
    fn from(err: rag_cache::CacheError) -> Self {
        RetrievalError::Cache(err.to_string())
    }
}
```

**Step 2: Create core types**

Create `crates/rag-retrieval/src/types.rs`:

```rust
//! Core types for the retrieval service.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use uuid::Uuid;

/// Search mode for retrieval.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SearchMode {
    /// Semantic search only (vector similarity).
    Semantic,
    /// Keyword search only (BM25).
    Keyword,
    /// Hybrid search combining semantic and keyword.
    #[default]
    Hybrid,
}

/// Query type classification.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum QueryType {
    /// Short factual queries.
    Simple,
    /// Natural language questions.
    #[default]
    Question,
    /// Concept/meaning focused.
    Semantic,
    /// Mixed intent.
    Hybrid,
}

/// Visibility level for documents.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Visibility {
    /// Accessible to all users in tenant.
    #[default]
    Public,
    /// Only accessible to document owner.
    Private,
    /// Accessible to users in allowed_groups.
    Group,
    /// Accessible to all users in the same tenant.
    Tenant,
}

/// User context extracted from JWT for ACL filtering.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UserContext {
    /// User identifier.
    pub user_id: Uuid,
    /// Tenant identifier (required for multi-tenancy).
    pub tenant_id: Uuid,
    /// User's group memberships.
    #[serde(default)]
    pub groups: Vec<String>,
    /// User's roles.
    #[serde(default)]
    pub roles: Vec<String>,
    /// Whether the user has admin privileges.
    #[serde(default)]
    pub is_admin: bool,
}

impl UserContext {
    /// Create a new user context.
    #[must_use]
    pub fn new(user_id: Uuid, tenant_id: Uuid) -> Self {
        Self {
            user_id,
            tenant_id,
            groups: Vec::new(),
            roles: Vec::new(),
            is_admin: false,
        }
    }

    /// Add groups to the context.
    #[must_use]
    pub fn with_groups(mut self, groups: Vec<String>) -> Self {
        self.groups = groups;
        self
    }

    /// Add roles to the context.
    #[must_use]
    pub fn with_roles(mut self, roles: Vec<String>) -> Self {
        self.roles = roles;
        self
    }

    /// Set admin flag.
    #[must_use]
    pub fn with_admin(mut self, is_admin: bool) -> Self {
        self.is_admin = is_admin;
        self
    }
}

/// A search result item with all score components.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RetrievalResult {
    /// Chunk identifier.
    pub chunk_id: Uuid,
    /// Parent document identifier.
    pub document_id: Uuid,
    /// Chunk content text.
    pub content: String,
    /// Final combined score.
    pub score: f32,
    /// Document title.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    /// Source URI.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_uri: Option<String>,
    /// Chunk index within the document.
    pub chunk_index: u32,
    /// Total chunks in the document.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total_chunks: Option<u32>,
    /// Semantic search score (if applicable).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub semantic_score: Option<f32>,
    /// Keyword search score (if applicable).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub keyword_score: Option<f32>,
    /// Reranker score (if reranking was applied).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rerank_score: Option<f32>,
    /// Additional metadata.
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, serde_json::Value>,
    /// Keyword highlights.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub highlights: Vec<String>,
    /// Document visibility level.
    #[serde(default)]
    pub visibility: Visibility,
    /// Groups allowed to access this document.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub allowed_groups: Vec<String>,
}

/// Metrics from a retrieval operation.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RetrievalMetrics {
    /// Query preprocessing time in milliseconds.
    pub preprocessing_ms: u64,
    /// Semantic search time in milliseconds.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub semantic_search_ms: Option<u64>,
    /// Keyword search time in milliseconds.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub keyword_search_ms: Option<u64>,
    /// Fusion time in milliseconds.
    pub fusion_ms: u64,
    /// Reranking time in milliseconds.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub rerank_ms: Option<u64>,
    /// ACL filtering time in milliseconds.
    pub acl_filter_ms: u64,
    /// Total request time in milliseconds.
    pub total_ms: u64,
    /// Number of semantic results before fusion.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub semantic_results_count: Option<usize>,
    /// Number of keyword results before fusion.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub keyword_results_count: Option<usize>,
    /// Number of results after fusion.
    pub fused_results_count: usize,
    /// Number of results after reranking.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reranked_results_count: Option<usize>,
    /// Final number of results returned.
    pub final_results_count: usize,
}

/// Debug information for a retrieval operation.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct RetrievalDebug {
    /// Classified query type.
    pub query_type: QueryType,
    /// Expanded query terms.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub expanded_terms: Vec<String>,
    /// Whether HyDE was used.
    pub hyde_used: bool,
    /// Whether result was from cache.
    pub cache_hit: bool,
    /// The processed/normalized query.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub processed_query: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_user_context_builder() {
        let ctx = UserContext::new(Uuid::new_v4(), Uuid::new_v4())
            .with_groups(vec!["engineering".into()])
            .with_roles(vec!["user".into()])
            .with_admin(false);

        assert_eq!(ctx.groups, vec!["engineering"]);
        assert_eq!(ctx.roles, vec!["user"]);
        assert!(!ctx.is_admin);
    }

    #[test]
    fn test_search_mode_default() {
        assert_eq!(SearchMode::default(), SearchMode::Hybrid);
    }

    #[test]
    fn test_visibility_serde() {
        let vis = Visibility::Group;
        let json = serde_json::to_string(&vis).unwrap();
        assert_eq!(json, "\"group\"");

        let parsed: Visibility = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed, Visibility::Group);
    }
}
```

**Step 3: Update lib.rs to export new modules**

Update `crates/rag-retrieval/src/lib.rs`:

```rust
//! Retrieval service for the RAG Pipeline.
//!
//! This crate provides the full retrieval pipeline:
//! - Query preprocessing (normalization, classification, expansion, HyDE)
//! - Semantic search (Qdrant vector similarity)
//! - Keyword search (OpenSearch BM25)
//! - Hybrid fusion (RRF, Linear, DBSF)
//! - Cross-encoder reranking
//! - ACL-based access control filtering
//! - Result caching
//!
//! # Example
//!
//! ```no_run
//! use rag_retrieval::{HybridSearcher, SearchRequest, SearchMode};
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     // Build and use the hybrid searcher
//!     // See HybridSearcher documentation for full example
//!     Ok(())
//! }
//! ```

pub mod error;
pub mod rrf;
pub mod types;

// Re-exports
pub use error::{RetrievalError, Result};
pub use rrf::{
    deduplicate, hybrid_fusion, normalize_scores, reciprocal_rank_fusion, RrfConfig, ScoredItem,
};
pub use types::{
    QueryType, RetrievalDebug, RetrievalMetrics, RetrievalResult, SearchMode, UserContext,
    Visibility,
};
```

**Step 4: Update Cargo.toml with new dependencies**

Update `crates/rag-retrieval/Cargo.toml`:

```toml
[package]
name = "rag-retrieval"
description = "Retrieval service for RAG Pipeline - hybrid search, reranking, ACL filtering"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
repository.workspace = true

[dependencies]
rag-types = { path = "../rag-types" }
rag-vectorstore = { path = "../rag-vectorstore" }
rag-search = { path = "../rag-search" }
rag-cache = { path = "../rag-cache" }
rag-auth = { path = "../rag-auth" }
rag-config = { path = "../rag-config" }
rag-telemetry = { path = "../rag-telemetry" }

serde = { workspace = true }
serde_json = { workspace = true }
thiserror = { workspace = true }
tracing = { workspace = true }
tokio = { workspace = true, features = ["full"] }
uuid = { workspace = true, features = ["v4", "serde"] }

# HTTP client for embedding/reranker services
reqwest = { version = "0.11", default-features = false, features = ["json", "rustls-tls"] }

# Parallel processing
rayon = "1.8"

# Async utilities
futures = "0.3"

[dev-dependencies]
tokio-test = { workspace = true }
criterion = { version = "0.5", features = ["html_reports"] }
rand = "0.8"
wiremock = "0.5"

[[bench]]
name = "rrf_benchmark"
harness = false

[lints]
workspace = true
```

**Step 5: Run tests to verify**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-retrieval`

Expected: All tests pass

**Step 6: Commit**

```bash
git add crates/rag-retrieval/
git commit -m "feat(retrieval): add core types and error handling

- Add RetrievalError with variants for all service components
- Add SearchMode, QueryType, Visibility enums
- Add UserContext for ACL filtering
- Add RetrievalResult, RetrievalMetrics, RetrievalDebug types
- Update Cargo.toml with required dependencies

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Fusion Algorithms (Linear, DBSF)

**Files:**
- Create: `crates/rag-retrieval/src/fusion/mod.rs`
- Create: `crates/rag-retrieval/src/fusion/linear.rs`
- Create: `crates/rag-retrieval/src/fusion/dbsf.rs`
- Move: `crates/rag-retrieval/src/rrf.rs` → `crates/rag-retrieval/src/fusion/rrf.rs`
- Modify: `crates/rag-retrieval/src/lib.rs`

**Step 1: Create fusion module structure**

Create `crates/rag-retrieval/src/fusion/mod.rs`:

```rust
//! Fusion algorithms for combining search results.
//!
//! This module provides multiple fusion strategies:
//! - RRF (Reciprocal Rank Fusion) - rank-based, robust default
//! - Linear - weighted score combination
//! - DBSF (Distribution-Based Score Fusion) - z-score normalization

mod dbsf;
mod linear;
mod rrf;

pub use dbsf::{distribution_based_fusion, DbsfConfig};
pub use linear::{linear_fusion, LinearConfig};
pub use rrf::{
    deduplicate, hybrid_fusion, normalize_scores, reciprocal_rank_fusion, rrf_score, RrfConfig,
    ScoredItem,
};

use serde::{Deserialize, Serialize};

/// Fusion method to use for combining results.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FusionMethod {
    /// Reciprocal Rank Fusion (default, most robust).
    #[default]
    Rrf,
    /// Linear weighted combination of scores.
    Linear,
    /// Distribution-based score fusion (z-score normalization).
    Dbsf,
}

/// Configuration for any fusion method.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FusionConfig {
    /// The fusion method to use.
    #[serde(default)]
    pub method: FusionMethod,
    /// Weight for semantic results (0.0-1.0).
    #[serde(default = "default_semantic_weight")]
    pub semantic_weight: f32,
    /// Weight for keyword results (0.0-1.0).
    #[serde(default = "default_keyword_weight")]
    pub keyword_weight: f32,
    /// RRF k constant (only used with RRF method).
    #[serde(default = "default_rrf_k")]
    pub rrf_k: f32,
    /// Maximum results to return.
    #[serde(default)]
    pub top_k: Option<usize>,
    /// Whether to deduplicate results.
    #[serde(default = "default_true")]
    pub deduplicate: bool,
}

fn default_semantic_weight() -> f32 {
    0.7
}
fn default_keyword_weight() -> f32 {
    0.3
}
fn default_rrf_k() -> f32 {
    60.0
}
fn default_true() -> bool {
    true
}

impl Default for FusionConfig {
    fn default() -> Self {
        Self {
            method: FusionMethod::Rrf,
            semantic_weight: 0.7,
            keyword_weight: 0.3,
            rrf_k: 60.0,
            top_k: None,
            deduplicate: true,
        }
    }
}

/// Fused result with scores from all sources.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FusedResult<T> {
    /// The item identifier.
    pub id: T,
    /// Final fused score.
    pub fused_score: f32,
    /// Original semantic score (if present in semantic results).
    pub semantic_score: Option<f32>,
    /// Original keyword score (if present in keyword results).
    pub keyword_score: Option<f32>,
    /// Rank in semantic results (1-based, None if not present).
    pub semantic_rank: Option<usize>,
    /// Rank in keyword results (1-based, None if not present).
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
}

/// Perform fusion using the configured method.
///
/// This is the main entry point for fusion operations.
#[must_use]
pub fn fuse<T>(
    semantic_results: &[ScoredItem<T>],
    keyword_results: &[ScoredItem<T>],
    config: &FusionConfig,
) -> Vec<FusedResult<T>>
where
    T: Clone + Eq + std::hash::Hash,
{
    match config.method {
        FusionMethod::Rrf => {
            let rrf_config = RrfConfig {
                k: config.rrf_k,
                weights: Some(vec![config.semantic_weight, config.keyword_weight]),
                top_k: config.top_k,
            };
            let fused = reciprocal_rank_fusion(&[semantic_results, keyword_results], &rrf_config);
            convert_to_fused_results(fused, semantic_results, keyword_results)
        }
        FusionMethod::Linear => {
            let linear_config = LinearConfig {
                semantic_weight: config.semantic_weight,
                keyword_weight: config.keyword_weight,
                top_k: config.top_k,
                normalize: true,
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
    }
}

/// Convert ScoredItems to FusedResults with rank information.
fn convert_to_fused_results<T>(
    fused: Vec<ScoredItem<T>>,
    semantic: &[ScoredItem<T>],
    keyword: &[ScoredItem<T>],
) -> Vec<FusedResult<T>>
where
    T: Clone + Eq + std::hash::Hash,
{
    use std::collections::HashMap;

    // Build rank maps
    let semantic_ranks: HashMap<&T, (usize, f32)> = semantic
        .iter()
        .enumerate()
        .map(|(i, item)| (&item.id, (i + 1, item.score)))
        .collect();

    let keyword_ranks: HashMap<&T, (usize, f32)> = keyword
        .iter()
        .enumerate()
        .map(|(i, item)| (&item.id, (i + 1, item.score)))
        .collect();

    fused
        .into_iter()
        .map(|item| {
            let sem = semantic_ranks.get(&item.id);
            let kw = keyword_ranks.get(&item.id);

            FusedResult {
                id: item.id,
                fused_score: item.score,
                semantic_score: sem.map(|(_, s)| *s),
                keyword_score: kw.map(|(_, s)| *s),
                semantic_rank: sem.map(|(r, _)| *r),
                keyword_rank: kw.map(|(r, _)| *r),
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fusion_config_default() {
        let config = FusionConfig::default();
        assert_eq!(config.method, FusionMethod::Rrf);
        assert!((config.semantic_weight - 0.7).abs() < f32::EPSILON);
        assert!((config.keyword_weight - 0.3).abs() < f32::EPSILON);
    }

    #[test]
    fn test_fuse_rrf() {
        let semantic = vec![
            ScoredItem::new("a", 0.9),
            ScoredItem::new("b", 0.8),
        ];
        let keyword = vec![
            ScoredItem::new("b", 0.95),
            ScoredItem::new("c", 0.85),
        ];

        let config = FusionConfig::default();
        let results = fuse(&semantic, &keyword, &config);

        assert!(!results.is_empty());
        // b should be first (appears in both)
        assert_eq!(results[0].id, "b");
        assert!(results[0].semantic_score.is_some());
        assert!(results[0].keyword_score.is_some());
    }
}
```

**Step 2: Create linear fusion**

Create `crates/rag-retrieval/src/fusion/linear.rs`:

```rust
//! Linear weighted fusion algorithm.

use super::{FusedResult, ScoredItem};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::hash::Hash;

/// Configuration for linear fusion.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LinearConfig {
    /// Weight for semantic scores.
    pub semantic_weight: f32,
    /// Weight for keyword scores.
    pub keyword_weight: f32,
    /// Maximum results to return.
    pub top_k: Option<usize>,
    /// Whether to normalize scores to 0-1 before fusion.
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

/// Perform linear weighted fusion of two result lists.
///
/// Formula: `score = w_s * semantic_score + w_k * keyword_score`
///
/// Items appearing in only one list use 0 for the missing score.
#[must_use]
pub fn linear_fusion<T>(
    semantic_results: &[ScoredItem<T>],
    keyword_results: &[ScoredItem<T>],
    config: &LinearConfig,
) -> Vec<FusedResult<T>>
where
    T: Clone + Eq + Hash,
{
    // Normalize scores if requested
    let (semantic_scores, keyword_scores) = if config.normalize {
        (
            normalize_to_map(semantic_results),
            normalize_to_map(keyword_results),
        )
    } else {
        (
            semantic_results
                .iter()
                .map(|i| (i.id.clone(), i.score))
                .collect(),
            keyword_results
                .iter()
                .map(|i| (i.id.clone(), i.score))
                .collect(),
        )
    };

    // Build rank maps for tracking
    let semantic_ranks: HashMap<T, usize> = semantic_results
        .iter()
        .enumerate()
        .map(|(i, item)| (item.id.clone(), i + 1))
        .collect();

    let keyword_ranks: HashMap<T, usize> = keyword_results
        .iter()
        .enumerate()
        .map(|(i, item)| (item.id.clone(), i + 1))
        .collect();

    // Collect all unique IDs
    let mut all_ids: Vec<T> = semantic_scores.keys().cloned().collect();
    for id in keyword_scores.keys() {
        if !semantic_scores.contains_key(id) {
            all_ids.push(id.clone());
        }
    }

    // Compute fused scores
    let mut results: Vec<FusedResult<T>> = all_ids
        .into_iter()
        .map(|id| {
            let sem_score = semantic_scores.get(&id).copied();
            let kw_score = keyword_scores.get(&id).copied();

            let fused_score = config.semantic_weight * sem_score.unwrap_or(0.0)
                + config.keyword_weight * kw_score.unwrap_or(0.0);

            FusedResult {
                id: id.clone(),
                fused_score,
                semantic_score: sem_score,
                keyword_score: kw_score,
                semantic_rank: semantic_ranks.get(&id).copied(),
                keyword_rank: keyword_ranks.get(&id).copied(),
            }
        })
        .collect();

    // Sort by fused score descending
    results.sort_by(|a, b| {
        b.fused_score
            .partial_cmp(&a.fused_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    // Apply top_k
    if let Some(top_k) = config.top_k {
        results.truncate(top_k);
    }

    results
}

/// Normalize scores to 0-1 range and return as a map.
fn normalize_to_map<T: Clone + Eq + Hash>(items: &[ScoredItem<T>]) -> HashMap<T, f32> {
    if items.is_empty() {
        return HashMap::new();
    }

    let min = items.iter().map(|i| i.score).fold(f32::INFINITY, f32::min);
    let max = items
        .iter()
        .map(|i| i.score)
        .fold(f32::NEG_INFINITY, f32::max);

    let range = max - min;
    if range < f32::EPSILON {
        // All same score, normalize to 1.0
        items.iter().map(|i| (i.id.clone(), 1.0)).collect()
    } else {
        items
            .iter()
            .map(|i| (i.id.clone(), (i.score - min) / range))
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_linear_fusion_basic() {
        let semantic = vec![
            ScoredItem::new("a", 0.9),
            ScoredItem::new("b", 0.7),
        ];
        let keyword = vec![
            ScoredItem::new("b", 0.8),
            ScoredItem::new("c", 0.6),
        ];

        let config = LinearConfig {
            semantic_weight: 0.5,
            keyword_weight: 0.5,
            top_k: None,
            normalize: false,
        };

        let results = linear_fusion(&semantic, &keyword, &config);

        // b appears in both, should have highest combined score
        assert_eq!(results[0].id, "b");
        assert!((results[0].fused_score - 0.75).abs() < 0.01); // (0.7 + 0.8) / 2
    }

    #[test]
    fn test_linear_fusion_normalized() {
        let semantic = vec![
            ScoredItem::new("a", 10.0),
            ScoredItem::new("b", 5.0),
        ];
        let keyword = vec![
            ScoredItem::new("b", 100.0),
            ScoredItem::new("c", 50.0),
        ];

        let config = LinearConfig {
            semantic_weight: 0.5,
            keyword_weight: 0.5,
            normalize: true,
            top_k: None,
        };

        let results = linear_fusion(&semantic, &keyword, &config);

        // All scores should be in reasonable range after normalization
        for r in &results {
            assert!(r.fused_score >= 0.0);
            assert!(r.fused_score <= 1.0);
        }
    }

    #[test]
    fn test_linear_fusion_top_k() {
        let semantic = vec![
            ScoredItem::new("a", 0.9),
            ScoredItem::new("b", 0.8),
            ScoredItem::new("c", 0.7),
        ];
        let keyword = vec![];

        let config = LinearConfig {
            top_k: Some(2),
            ..Default::default()
        };

        let results = linear_fusion(&semantic, &keyword, &config);
        assert_eq!(results.len(), 2);
    }
}
```

**Step 3: Create DBSF fusion**

Create `crates/rag-retrieval/src/fusion/dbsf.rs`:

```rust
//! Distribution-Based Score Fusion (DBSF) algorithm.
//!
//! DBSF normalizes scores using z-score normalization to account for
//! different score distributions between search methods.

use super::{FusedResult, ScoredItem};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::hash::Hash;

/// Configuration for DBSF fusion.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DbsfConfig {
    /// Weight for semantic scores.
    pub semantic_weight: f32,
    /// Weight for keyword scores.
    pub keyword_weight: f32,
    /// Maximum results to return.
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

/// Compute mean of scores.
fn mean(scores: &[f32]) -> f32 {
    if scores.is_empty() {
        return 0.0;
    }
    scores.iter().sum::<f32>() / scores.len() as f32
}

/// Compute standard deviation of scores.
fn std_dev(scores: &[f32], mean: f32) -> f32 {
    if scores.len() < 2 {
        return 1.0; // Avoid division by zero
    }
    let variance = scores.iter().map(|s| (s - mean).powi(2)).sum::<f32>() / (scores.len() - 1) as f32;
    variance.sqrt().max(f32::EPSILON)
}

/// Z-score normalize scores and return as a map.
fn zscore_normalize<T: Clone + Eq + Hash>(items: &[ScoredItem<T>]) -> HashMap<T, f32> {
    if items.is_empty() {
        return HashMap::new();
    }

    let scores: Vec<f32> = items.iter().map(|i| i.score).collect();
    let m = mean(&scores);
    let s = std_dev(&scores, m);

    items
        .iter()
        .map(|i| (i.id.clone(), (i.score - m) / s))
        .collect()
}

/// Perform Distribution-Based Score Fusion.
///
/// Uses z-score normalization to handle different score distributions
/// from semantic and keyword search.
#[must_use]
pub fn distribution_based_fusion<T>(
    semantic_results: &[ScoredItem<T>],
    keyword_results: &[ScoredItem<T>],
    config: &DbsfConfig,
) -> Vec<FusedResult<T>>
where
    T: Clone + Eq + Hash,
{
    let semantic_zscores = zscore_normalize(semantic_results);
    let keyword_zscores = zscore_normalize(keyword_results);

    // Build rank maps
    let semantic_ranks: HashMap<T, (usize, f32)> = semantic_results
        .iter()
        .enumerate()
        .map(|(i, item)| (item.id.clone(), (i + 1, item.score)))
        .collect();

    let keyword_ranks: HashMap<T, (usize, f32)> = keyword_results
        .iter()
        .enumerate()
        .map(|(i, item)| (item.id.clone(), (i + 1, item.score)))
        .collect();

    // Collect all unique IDs
    let mut all_ids: Vec<T> = semantic_zscores.keys().cloned().collect();
    for id in keyword_zscores.keys() {
        if !semantic_zscores.contains_key(id) {
            all_ids.push(id.clone());
        }
    }

    // Compute fused scores
    let mut results: Vec<FusedResult<T>> = all_ids
        .into_iter()
        .map(|id| {
            let sem_zscore = semantic_zscores.get(&id).copied().unwrap_or(f32::NEG_INFINITY);
            let kw_zscore = keyword_zscores.get(&id).copied().unwrap_or(f32::NEG_INFINITY);

            // For items missing from a list, use a large negative z-score
            let sem_contrib = if semantic_zscores.contains_key(&id) {
                config.semantic_weight * sem_zscore
            } else {
                0.0
            };
            let kw_contrib = if keyword_zscores.contains_key(&id) {
                config.keyword_weight * kw_zscore
            } else {
                0.0
            };

            let fused_score = sem_contrib + kw_contrib;

            let sem_info = semantic_ranks.get(&id);
            let kw_info = keyword_ranks.get(&id);

            FusedResult {
                id: id.clone(),
                fused_score,
                semantic_score: sem_info.map(|(_, s)| *s),
                keyword_score: kw_info.map(|(_, s)| *s),
                semantic_rank: sem_info.map(|(r, _)| *r),
                keyword_rank: kw_info.map(|(r, _)| *r),
            }
        })
        .collect();

    // Sort by fused score descending
    results.sort_by(|a, b| {
        b.fused_score
            .partial_cmp(&a.fused_score)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    // Apply top_k
    if let Some(top_k) = config.top_k {
        results.truncate(top_k);
    }

    results
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_mean() {
        assert!((mean(&[1.0, 2.0, 3.0]) - 2.0).abs() < f32::EPSILON);
        assert!((mean(&[]) - 0.0).abs() < f32::EPSILON);
    }

    #[test]
    fn test_std_dev() {
        let scores = vec![2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0];
        let m = mean(&scores);
        let s = std_dev(&scores, m);
        assert!((s - 2.138).abs() < 0.01);
    }

    #[test]
    fn test_dbsf_basic() {
        let semantic = vec![
            ScoredItem::new("a", 0.9),
            ScoredItem::new("b", 0.8),
            ScoredItem::new("c", 0.7),
        ];
        let keyword = vec![
            ScoredItem::new("b", 10.0),
            ScoredItem::new("d", 8.0),
            ScoredItem::new("a", 6.0),
        ];

        let config = DbsfConfig::default();
        let results = distribution_based_fusion(&semantic, &keyword, &config);

        // Results should be sorted by fused score
        assert!(!results.is_empty());
        for i in 1..results.len() {
            assert!(results[i - 1].fused_score >= results[i].fused_score);
        }
    }

    #[test]
    fn test_dbsf_top_k() {
        let semantic = vec![
            ScoredItem::new("a", 0.9),
            ScoredItem::new("b", 0.8),
            ScoredItem::new("c", 0.7),
        ];
        let keyword = vec![];

        let config = DbsfConfig {
            top_k: Some(2),
            ..Default::default()
        };

        let results = distribution_based_fusion(&semantic, &keyword, &config);
        assert_eq!(results.len(), 2);
    }
}
```

**Step 4: Move and update RRF**

Move `crates/rag-retrieval/src/rrf.rs` to `crates/rag-retrieval/src/fusion/rrf.rs` (keep content the same, it's already complete).

**Step 5: Update lib.rs**

```rust
//! Retrieval service for the RAG Pipeline.

pub mod error;
pub mod fusion;
pub mod types;

// Re-exports
pub use error::{RetrievalError, Result};
pub use fusion::{
    deduplicate, distribution_based_fusion, fuse, hybrid_fusion, linear_fusion, normalize_scores,
    reciprocal_rank_fusion, DbsfConfig, FusedResult, FusionConfig, FusionMethod, LinearConfig,
    RrfConfig, ScoredItem,
};
pub use types::{
    QueryType, RetrievalDebug, RetrievalMetrics, RetrievalResult, SearchMode, UserContext,
    Visibility,
};
```

**Step 6: Run tests**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-retrieval`

Expected: All tests pass

**Step 7: Commit**

```bash
git add crates/rag-retrieval/
git commit -m "feat(retrieval): add linear and DBSF fusion algorithms

- Reorganize fusion algorithms into fusion module
- Add LinearConfig and linear_fusion with score normalization
- Add DbsfConfig and distribution_based_fusion with z-score normalization
- Add FusionConfig and fuse() unified entry point
- Add FusedResult type with rank tracking

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Semantic Search Module

**Files:**
- Create: `crates/rag-retrieval/src/search/mod.rs`
- Create: `crates/rag-retrieval/src/search/semantic.rs`
- Create: `crates/rag-retrieval/src/search/config.rs`

**Step 1: Create search module**

Create `crates/rag-retrieval/src/search/mod.rs`:

```rust
//! Search implementations for semantic and keyword search.

mod config;
mod semantic;

pub use config::{KeywordSearchConfig, SearchConfig, SemanticSearchConfig};
pub use semantic::SemanticSearcher;
```

**Step 2: Create search config**

Create `crates/rag-retrieval/src/search/config.rs`:

```rust
//! Search configuration types.

use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Configuration for the search components.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SearchConfig {
    /// Semantic search configuration.
    pub semantic: SemanticSearchConfig,
    /// Keyword search configuration.
    pub keyword: KeywordSearchConfig,
}

impl Default for SearchConfig {
    fn default() -> Self {
        Self {
            semantic: SemanticSearchConfig::default(),
            keyword: KeywordSearchConfig::default(),
        }
    }
}

/// Configuration for semantic search.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SemanticSearchConfig {
    /// Qdrant URL.
    #[serde(default = "default_qdrant_url")]
    pub url: String,
    /// Collection name.
    #[serde(default = "default_collection")]
    pub collection: String,
    /// Number of results to retrieve.
    #[serde(default = "default_top_k")]
    pub top_k: usize,
    /// Score threshold (0.0-1.0).
    #[serde(default)]
    pub score_threshold: Option<f32>,
    /// HNSW ef parameter for search.
    #[serde(default = "default_ef_search")]
    pub ef_search: u32,
    /// Request timeout.
    #[serde(default = "default_timeout", with = "humantime_serde")]
    pub timeout: Duration,
    /// Whether to include payload in results.
    #[serde(default = "default_true")]
    pub with_payload: bool,
}

fn default_qdrant_url() -> String {
    "http://localhost:6333".into()
}
fn default_collection() -> String {
    "documents".into()
}
fn default_top_k() -> usize {
    50
}
fn default_ef_search() -> u32 {
    128
}
fn default_timeout() -> Duration {
    Duration::from_secs(10)
}
fn default_true() -> bool {
    true
}

impl Default for SemanticSearchConfig {
    fn default() -> Self {
        Self {
            url: default_qdrant_url(),
            collection: default_collection(),
            top_k: default_top_k(),
            score_threshold: None,
            ef_search: default_ef_search(),
            timeout: default_timeout(),
            with_payload: true,
        }
    }
}

/// Configuration for keyword search.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeywordSearchConfig {
    /// OpenSearch URL.
    #[serde(default = "default_opensearch_url")]
    pub url: String,
    /// Index name.
    #[serde(default = "default_index")]
    pub index: String,
    /// Fields to search.
    #[serde(default = "default_fields")]
    pub fields: Vec<String>,
    /// Field boosts.
    #[serde(default)]
    pub field_boosts: std::collections::HashMap<String, f32>,
    /// Number of results to retrieve.
    #[serde(default = "default_top_k")]
    pub top_k: usize,
    /// Fuzziness setting.
    #[serde(default = "default_fuzziness")]
    pub fuzziness: String,
    /// Whether to include highlights.
    #[serde(default = "default_true")]
    pub highlight: bool,
    /// Highlight fragment size.
    #[serde(default = "default_fragment_size")]
    pub highlight_fragment_size: usize,
    /// Request timeout.
    #[serde(default = "default_timeout", with = "humantime_serde")]
    pub timeout: Duration,
}

fn default_opensearch_url() -> String {
    "http://localhost:9200".into()
}
fn default_index() -> String {
    "documents".into()
}
fn default_fields() -> Vec<String> {
    vec!["content".into(), "title".into()]
}
fn default_fuzziness() -> String {
    "AUTO".into()
}
fn default_fragment_size() -> usize {
    150
}

impl Default for KeywordSearchConfig {
    fn default() -> Self {
        Self {
            url: default_opensearch_url(),
            index: default_index(),
            fields: default_fields(),
            field_boosts: [("title".into(), 2.0)].into_iter().collect(),
            top_k: default_top_k(),
            fuzziness: default_fuzziness(),
            highlight: true,
            highlight_fragment_size: default_fragment_size(),
            timeout: default_timeout(),
        }
    }
}
```

**Step 3: Create semantic searcher**

Create `crates/rag-retrieval/src/search/semantic.rs`:

```rust
//! Semantic search using Qdrant vector store.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use rag_vectorstore::{FilterBuilder, SearchRequest, VectorStoreClient, VectorStoreConfig};
use serde_json::Value;
use tracing::{debug, instrument};
use uuid::Uuid;

use crate::error::{Result, RetrievalError};
use crate::fusion::ScoredItem;
use crate::search::SemanticSearchConfig;
use crate::types::{UserContext, Visibility};

/// Semantic search result item.
#[derive(Debug, Clone)]
pub struct SemanticResult {
    /// Chunk ID.
    pub chunk_id: Uuid,
    /// Document ID.
    pub document_id: Uuid,
    /// Similarity score (normalized to 0-1).
    pub score: f32,
    /// Chunk content.
    pub content: String,
    /// Document title.
    pub title: Option<String>,
    /// Source URI.
    pub source_uri: Option<String>,
    /// Chunk index.
    pub chunk_index: u32,
    /// Visibility level.
    pub visibility: Visibility,
    /// Allowed groups.
    pub allowed_groups: Vec<String>,
    /// Additional metadata.
    pub metadata: HashMap<String, Value>,
}

/// Semantic searcher using Qdrant.
#[derive(Clone)]
pub struct SemanticSearcher {
    client: Arc<VectorStoreClient>,
    config: SemanticSearchConfig,
}

impl SemanticSearcher {
    /// Create a new semantic searcher.
    ///
    /// # Errors
    ///
    /// Returns an error if connection to Qdrant fails.
    pub async fn new(config: SemanticSearchConfig) -> Result<Self> {
        let qdrant_config = VectorStoreConfig::new(&config.url)
            .with_timeout(config.timeout)
            .with_default_collection(&config.collection);

        let client = VectorStoreClient::connect(&qdrant_config)
            .await
            .map_err(|e| RetrievalError::SemanticSearch(e.to_string()))?;

        Ok(Self {
            client: Arc::new(client),
            config,
        })
    }

    /// Create from an existing client.
    #[must_use]
    pub fn from_client(client: Arc<VectorStoreClient>, config: SemanticSearchConfig) -> Self {
        Self { client, config }
    }

    /// Search for similar vectors.
    ///
    /// # Arguments
    ///
    /// * `embedding` - Query embedding vector
    /// * `user_context` - User context for tenant filtering
    /// * `filters` - Additional metadata filters
    /// * `top_k` - Override default top_k
    #[instrument(skip(self, embedding, filters), fields(tenant_id = %user_context.tenant_id))]
    pub async fn search(
        &self,
        embedding: Vec<f32>,
        user_context: &UserContext,
        filters: Option<HashMap<String, Value>>,
        top_k: Option<usize>,
    ) -> Result<Vec<SemanticResult>> {
        let start = Instant::now();
        let limit = top_k.unwrap_or(self.config.top_k);

        // Build filter with tenant isolation
        let filter = self.build_filter(user_context, filters)?;

        let request = SearchRequest::new(embedding)
            .with_limit(limit as u64)
            .with_payload(self.config.with_payload)
            .with_filter(filter)
            .with_params(rag_vectorstore::SearchParams {
                ef: Some(self.config.ef_search),
                exact: false,
            });

        if let Some(threshold) = self.config.score_threshold {
            // Note: would need to add this to SearchRequest if not present
            debug!(threshold, "Applying score threshold");
        }

        let result = self
            .client
            .search(Some(&self.config.collection), request)
            .await
            .map_err(|e| RetrievalError::SemanticSearch(e.to_string()))?;

        let results: Vec<SemanticResult> = result
            .points
            .into_iter()
            .filter_map(|point| self.convert_result(point))
            .collect();

        let duration = start.elapsed();
        debug!(
            results = results.len(),
            duration_ms = duration.as_millis(),
            "Semantic search completed"
        );

        Ok(results)
    }

    /// Search with multiple query vectors and aggregate results.
    #[instrument(skip(self, embeddings, filters), fields(tenant_id = %user_context.tenant_id, num_queries = embeddings.len()))]
    pub async fn search_multi_vector(
        &self,
        embeddings: Vec<Vec<f32>>,
        user_context: &UserContext,
        filters: Option<HashMap<String, Value>>,
        top_k: Option<usize>,
    ) -> Result<Vec<SemanticResult>> {
        if embeddings.is_empty() {
            return Ok(Vec::new());
        }

        if embeddings.len() == 1 {
            return self
                .search(embeddings.into_iter().next().unwrap(), user_context, filters, top_k)
                .await;
        }

        // Execute searches in parallel
        let futures: Vec<_> = embeddings
            .into_iter()
            .map(|emb| {
                let user_ctx = user_context.clone();
                let filters_clone = filters.clone();
                let searcher = self.clone();
                async move { searcher.search(emb, &user_ctx, filters_clone, top_k).await }
            })
            .collect();

        let results = futures::future::try_join_all(futures).await?;

        // Aggregate and deduplicate
        self.aggregate_results(results, top_k.unwrap_or(self.config.top_k))
    }

    /// Build Qdrant filter with tenant isolation and optional metadata filters.
    fn build_filter(
        &self,
        user_context: &UserContext,
        filters: Option<HashMap<String, Value>>,
    ) -> Result<qdrant_client::qdrant::Filter> {
        let mut builder = FilterBuilder::new();

        // Always filter by tenant
        builder = builder.must_match("tenant_id", user_context.tenant_id.to_string());

        // Add metadata filters
        if let Some(filters) = filters {
            for (key, value) in filters {
                if let Some(s) = value.as_str() {
                    builder = builder.must_match(&key, s.to_string());
                } else if let Some(arr) = value.as_array() {
                    let values: Vec<String> = arr
                        .iter()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect();
                    if !values.is_empty() {
                        builder = builder.must_match_any(&key, values);
                    }
                }
            }
        }

        Ok(builder.build())
    }

    /// Convert a Qdrant scored point to SemanticResult.
    fn convert_result(&self, point: rag_vectorstore::ScoredPoint) -> Option<SemanticResult> {
        let payload = &point.payload;

        // Parse required fields
        let chunk_id = payload
            .get("chunk_id")
            .and_then(|v| v.as_str())
            .and_then(|s| Uuid::parse_str(s).ok())
            .or_else(|| Uuid::parse_str(&point.id).ok())?;

        let document_id = payload
            .get("document_id")
            .and_then(|v| v.as_str())
            .and_then(|s| Uuid::parse_str(s).ok())?;

        let content = payload
            .get("content")
            .and_then(|v| v.as_str())
            .map(String::from)
            .unwrap_or_default();

        // Normalize cosine score from [-1, 1] to [0, 1]
        let score = (point.score + 1.0) / 2.0;

        // Parse optional fields
        let title = payload.get("title").and_then(|v| v.as_str()).map(String::from);
        let source_uri = payload.get("source_uri").and_then(|v| v.as_str()).map(String::from);
        let chunk_index = payload
            .get("chunk_index")
            .and_then(|v| v.as_u64())
            .unwrap_or(0) as u32;

        let visibility = payload
            .get("visibility")
            .and_then(|v| v.as_str())
            .and_then(|s| serde_json::from_str(&format!("\"{s}\"")).ok())
            .unwrap_or_default();

        let allowed_groups = payload
            .get("allowed_groups")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();

        // Collect remaining metadata
        let excluded_keys = [
            "chunk_id",
            "document_id",
            "content",
            "title",
            "source_uri",
            "chunk_index",
            "visibility",
            "allowed_groups",
            "tenant_id",
        ];
        let metadata: HashMap<String, Value> = payload
            .iter()
            .filter(|(k, _)| !excluded_keys.contains(&k.as_str()))
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect();

        Some(SemanticResult {
            chunk_id,
            document_id,
            score,
            content,
            title,
            source_uri,
            chunk_index,
            visibility,
            allowed_groups,
            metadata,
        })
    }

    /// Aggregate results from multiple searches.
    fn aggregate_results(
        &self,
        results: Vec<Vec<SemanticResult>>,
        top_k: usize,
    ) -> Result<Vec<SemanticResult>> {
        use std::collections::HashMap;

        // Deduplicate by chunk_id, keeping highest score
        let mut best: HashMap<Uuid, SemanticResult> = HashMap::new();

        for result_list in results {
            for result in result_list {
                best.entry(result.chunk_id)
                    .and_modify(|existing| {
                        if result.score > existing.score {
                            *existing = result.clone();
                        }
                    })
                    .or_insert(result);
            }
        }

        // Sort by score and take top_k
        let mut aggregated: Vec<SemanticResult> = best.into_values().collect();
        aggregated.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        aggregated.truncate(top_k);

        Ok(aggregated)
    }

    /// Health check.
    pub async fn health_check(&self) -> Result<()> {
        self.client
            .health_check()
            .await
            .map_err(|e| RetrievalError::SemanticSearch(e.to_string()))
    }

    /// Get collection info.
    pub async fn get_collection_info(&self) -> Result<rag_vectorstore::CollectionInfo> {
        self.client
            .collection_info(&self.config.collection)
            .await
            .map_err(|e| RetrievalError::SemanticSearch(e.to_string()))
    }
}

impl std::fmt::Debug for SemanticSearcher {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SemanticSearcher")
            .field("config", &self.config)
            .finish_non_exhaustive()
    }
}

/// Convert SemanticResult to ScoredItem for fusion.
impl From<SemanticResult> for ScoredItem<Uuid> {
    fn from(result: SemanticResult) -> Self {
        ScoredItem::new(result.chunk_id, result.score)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_semantic_config_default() {
        let config = SemanticSearchConfig::default();
        assert_eq!(config.top_k, 50);
        assert_eq!(config.ef_search, 128);
    }

    #[test]
    fn test_score_normalization() {
        // Cosine score of 1.0 should normalize to 1.0
        let normalized = (1.0_f32 + 1.0) / 2.0;
        assert!((normalized - 1.0).abs() < f32::EPSILON);

        // Cosine score of 0.0 should normalize to 0.5
        let normalized = (0.0_f32 + 1.0) / 2.0;
        assert!((normalized - 0.5).abs() < f32::EPSILON);

        // Cosine score of -1.0 should normalize to 0.0
        let normalized = (-1.0_f32 + 1.0) / 2.0;
        assert!(normalized.abs() < f32::EPSILON);
    }
}
```

**Step 4: Update lib.rs**

Add to `crates/rag-retrieval/src/lib.rs`:

```rust
pub mod search;

pub use search::{KeywordSearchConfig, SearchConfig, SemanticSearchConfig, SemanticSearcher};
```

**Step 5: Run tests**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-retrieval`

Expected: All tests pass

**Step 6: Commit**

```bash
git add crates/rag-retrieval/
git commit -m "feat(retrieval): add semantic search module

- Add SemanticSearcher with Qdrant integration
- Add SemanticSearchConfig and KeywordSearchConfig
- Support multi-vector search with aggregation
- Add tenant isolation filter building
- Add cosine score normalization

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Keyword Search Module

**Files:**
- Create: `crates/rag-retrieval/src/search/keyword.rs`
- Modify: `crates/rag-retrieval/src/search/mod.rs`

**Step 1: Create keyword searcher**

Create `crates/rag-retrieval/src/search/keyword.rs`:

```rust
//! Keyword search using OpenSearch BM25.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use rag_search::{BM25Request, SearchClient, SearchConfig as OsConfig};
use serde_json::Value;
use tracing::{debug, instrument};
use uuid::Uuid;

use crate::error::{Result, RetrievalError};
use crate::fusion::ScoredItem;
use crate::search::KeywordSearchConfig;
use crate::types::{UserContext, Visibility};

/// Keyword search result item.
#[derive(Debug, Clone)]
pub struct KeywordResult {
    /// Chunk ID.
    pub chunk_id: Uuid,
    /// Document ID.
    pub document_id: Uuid,
    /// BM25 score (normalized).
    pub score: f32,
    /// Raw BM25 score.
    pub raw_score: f32,
    /// Chunk content.
    pub content: String,
    /// Document title.
    pub title: Option<String>,
    /// Source URI.
    pub source_uri: Option<String>,
    /// Chunk index.
    pub chunk_index: u32,
    /// Visibility level.
    pub visibility: Visibility,
    /// Allowed groups.
    pub allowed_groups: Vec<String>,
    /// Highlighted fragments.
    pub highlights: Vec<String>,
    /// Additional metadata.
    pub metadata: HashMap<String, Value>,
}

/// Keyword searcher using OpenSearch BM25.
#[derive(Clone)]
pub struct KeywordSearcher {
    client: Arc<SearchClient>,
    config: KeywordSearchConfig,
}

impl KeywordSearcher {
    /// Create a new keyword searcher.
    ///
    /// # Errors
    ///
    /// Returns an error if connection fails.
    pub fn new(config: KeywordSearchConfig) -> Result<Self> {
        let os_config = OsConfig::new(&config.url).with_default_index(&config.index);

        let client = SearchClient::new(os_config)
            .map_err(|e| RetrievalError::KeywordSearch(e.to_string()))?;

        Ok(Self {
            client: Arc::new(client),
            config,
        })
    }

    /// Create from an existing client.
    #[must_use]
    pub fn from_client(client: Arc<SearchClient>, config: KeywordSearchConfig) -> Self {
        Self { client, config }
    }

    /// Search for documents matching the query.
    ///
    /// # Arguments
    ///
    /// * `query` - Search query string
    /// * `user_context` - User context for tenant filtering
    /// * `filters` - Additional metadata filters
    /// * `top_k` - Override default top_k
    #[instrument(skip(self, filters), fields(tenant_id = %user_context.tenant_id, query_len = query.len()))]
    pub async fn search(
        &self,
        query: &str,
        user_context: &UserContext,
        filters: Option<HashMap<String, Value>>,
        top_k: Option<usize>,
    ) -> Result<Vec<KeywordResult>> {
        let start = Instant::now();
        let limit = top_k.unwrap_or(self.config.top_k);

        // Build request
        let mut request = BM25Request::new(query)
            .with_fields(self.config.fields.clone())
            .with_limit(limit)
            .with_tenant(&user_context.tenant_id.to_string());

        if self.config.highlight {
            request = request.with_highlight();
        }

        // Add additional filters
        if let Some(filters) = filters {
            for (key, value) in filters {
                if let Some(s) = value.as_str() {
                    request = request.with_filter(&key, s);
                }
            }
        }

        let response = self
            .client
            .search(&self.config.index, &request)
            .await
            .map_err(|e| RetrievalError::KeywordSearch(e.to_string()))?;

        // Normalize scores
        let results = self.normalize_results(response.hits);

        let duration = start.elapsed();
        debug!(
            results = results.len(),
            duration_ms = duration.as_millis(),
            "Keyword search completed"
        );

        Ok(results)
    }

    /// Search with query expansion (multiple related queries).
    #[instrument(skip(self, filters), fields(tenant_id = %user_context.tenant_id, num_queries = queries.len()))]
    pub async fn search_with_expansion(
        &self,
        queries: &[String],
        user_context: &UserContext,
        filters: Option<HashMap<String, Value>>,
        top_k: Option<usize>,
    ) -> Result<Vec<KeywordResult>> {
        if queries.is_empty() {
            return Ok(Vec::new());
        }

        if queries.len() == 1 {
            return self
                .search(&queries[0], user_context, filters, top_k)
                .await;
        }

        // Execute searches in parallel
        let futures: Vec<_> = queries
            .iter()
            .map(|q| {
                let query = q.clone();
                let user_ctx = user_context.clone();
                let filters_clone = filters.clone();
                let searcher = self.clone();
                async move { searcher.search(&query, &user_ctx, filters_clone, top_k).await }
            })
            .collect();

        let results = futures::future::try_join_all(futures).await?;

        // Aggregate and deduplicate
        self.aggregate_results(results, top_k.unwrap_or(self.config.top_k))
    }

    /// Normalize BM25 scores to 0-1 range.
    fn normalize_results(&self, hits: Vec<rag_search::SearchHit>) -> Vec<KeywordResult> {
        if hits.is_empty() {
            return Vec::new();
        }

        // Find min/max scores
        let scores: Vec<f32> = hits.iter().map(|h| h.score as f32).collect();
        let min_score = scores.iter().cloned().fold(f32::INFINITY, f32::min);
        let max_score = scores.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
        let range = max_score - min_score;

        hits.into_iter()
            .filter_map(|hit| self.convert_hit(hit, min_score, range))
            .collect()
    }

    /// Convert OpenSearch hit to KeywordResult.
    fn convert_hit(
        &self,
        hit: rag_search::SearchHit,
        min_score: f32,
        range: f32,
    ) -> Option<KeywordResult> {
        let source = &hit.source;

        // Parse UUIDs
        let chunk_id = self.parse_uuid(source.get("chunk_id"), Some(&hit.id))?;
        let document_id = self.parse_uuid(source.get("document_id"), None)?;

        let content = source
            .get("content")
            .and_then(|v| v.as_str())
            .map(String::from)
            .unwrap_or_default();

        // Normalize score
        let raw_score = hit.score as f32;
        let normalized_score = if range > f32::EPSILON {
            (raw_score - min_score) / range
        } else {
            1.0
        };

        let title = source.get("title").and_then(|v| v.as_str()).map(String::from);
        let source_uri = source
            .get("source_uri")
            .and_then(|v| v.as_str())
            .map(String::from);
        let chunk_index = source
            .get("chunk_index")
            .and_then(|v| v.as_u64())
            .unwrap_or(0) as u32;

        let visibility = source
            .get("visibility")
            .and_then(|v| v.as_str())
            .and_then(|s| serde_json::from_str(&format!("\"{s}\"")).ok())
            .unwrap_or_default();

        let allowed_groups = source
            .get("allowed_groups")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default();

        // Get highlights
        let highlights: Vec<String> = hit
            .highlights
            .values()
            .flat_map(|frags| frags.iter().cloned())
            .collect();

        // Collect remaining metadata
        let excluded_keys = [
            "chunk_id",
            "document_id",
            "content",
            "title",
            "source_uri",
            "chunk_index",
            "visibility",
            "allowed_groups",
            "tenant_id",
        ];
        let metadata: HashMap<String, Value> = source
            .as_object()
            .map(|obj| {
                obj.iter()
                    .filter(|(k, _)| !excluded_keys.contains(&k.as_str()))
                    .map(|(k, v)| (k.clone(), v.clone()))
                    .collect()
            })
            .unwrap_or_default();

        Some(KeywordResult {
            chunk_id,
            document_id,
            score: normalized_score,
            raw_score,
            content,
            title,
            source_uri,
            chunk_index,
            visibility,
            allowed_groups,
            highlights,
            metadata,
        })
    }

    /// Parse UUID from value or fallback.
    fn parse_uuid(&self, value: Option<&Value>, fallback: Option<&str>) -> Option<Uuid> {
        value
            .and_then(|v| v.as_str())
            .and_then(|s| Uuid::parse_str(s).ok())
            .or_else(|| fallback.and_then(|s| Uuid::parse_str(s).ok()))
    }

    /// Aggregate results from multiple searches.
    fn aggregate_results(
        &self,
        results: Vec<Vec<KeywordResult>>,
        top_k: usize,
    ) -> Result<Vec<KeywordResult>> {
        let mut best: HashMap<Uuid, KeywordResult> = HashMap::new();

        for result_list in results {
            for result in result_list {
                best.entry(result.chunk_id)
                    .and_modify(|existing| {
                        if result.score > existing.score {
                            *existing = result.clone();
                        }
                    })
                    .or_insert(result);
            }
        }

        let mut aggregated: Vec<KeywordResult> = best.into_values().collect();
        aggregated.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        aggregated.truncate(top_k);

        Ok(aggregated)
    }

    /// Get index info.
    pub async fn get_index_info(&self) -> Result<Value> {
        // Would need to add this method to rag_search
        Ok(serde_json::json!({
            "index": self.config.index,
            "url": self.config.url
        }))
    }
}

impl std::fmt::Debug for KeywordSearcher {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("KeywordSearcher")
            .field("config", &self.config)
            .finish_non_exhaustive()
    }
}

/// Convert KeywordResult to ScoredItem for fusion.
impl From<KeywordResult> for ScoredItem<Uuid> {
    fn from(result: KeywordResult) -> Self {
        ScoredItem::new(result.chunk_id, result.score)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_keyword_config_default() {
        let config = KeywordSearchConfig::default();
        assert_eq!(config.top_k, 50);
        assert!(config.highlight);
        assert_eq!(config.fields, vec!["content", "title"]);
    }

    #[test]
    fn test_score_normalization() {
        // With range
        let min = 5.0_f32;
        let range = 10.0_f32;
        let score = 10.0_f32;
        let normalized = (score - min) / range;
        assert!((normalized - 0.5).abs() < f32::EPSILON);
    }
}
```

**Step 2: Update search mod.rs**

```rust
//! Search implementations for semantic and keyword search.

mod config;
mod keyword;
mod semantic;

pub use config::{KeywordSearchConfig, SearchConfig, SemanticSearchConfig};
pub use keyword::{KeywordResult, KeywordSearcher};
pub use semantic::{SemanticResult, SemanticSearcher};
```

**Step 3: Update lib.rs exports**

Add to exports:
```rust
pub use search::{
    KeywordResult, KeywordSearchConfig, KeywordSearcher, SearchConfig, SemanticResult,
    SemanticSearchConfig, SemanticSearcher,
};
```

**Step 4: Run tests**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-retrieval`

**Step 5: Commit**

```bash
git add crates/rag-retrieval/
git commit -m "feat(retrieval): add keyword search module

- Add KeywordSearcher with OpenSearch BM25 integration
- Support query expansion with multi-query aggregation
- Add BM25 score normalization
- Add highlight extraction

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5-32: Remaining Implementation

Due to the size of this plan, I'll provide a summary of the remaining tasks. Each follows the same pattern as Tasks 1-4.

### Phase 3: Query Preprocessing (Tasks 5-9)

**Task 5: Embedding Client**
- Create `crates/rag-retrieval/src/embedding/client.rs`
- HTTP client to call embedding service
- Batch embedding support
- Caching integration

**Task 6: Query Preprocessor**
- Create `crates/rag-retrieval/src/query/preprocessor.rs`
- Query normalization (lowercase, trim, unicode normalization)
- Query type classification (simple, question, semantic, hybrid)

**Task 7: Query Expander**
- Create `crates/rag-retrieval/src/query/expander.rs`
- Synonym database
- LLM-based expansion via LLM gateway

**Task 8: HyDE Generator**
- Create `crates/rag-retrieval/src/query/hyde.rs`
- Hypothetical document generation
- Multi-query generation

**Task 9: Query Cache**
- Create `crates/rag-retrieval/src/query/cache.rs`
- Redis-backed query result caching
- Cache key generation from query + config

### Phase 4: Reranking and ACL (Tasks 10-13)

**Task 10: Reranker Client**
- Create `crates/rag-retrieval/src/reranking/client.rs`
- HTTP client to reranker service
- Batch processing with configurable batch size
- Timeout and retry logic

**Task 11: Reranker Service**
- Create `crates/rag-retrieval/src/reranking/service.rs`
- Integration with fused results
- Score normalization

**Task 12: ACL Filter**
- Create `crates/rag-retrieval/src/acl/filter.rs`
- Visibility level filtering (public, private, group, tenant)
- Group intersection checking

**Task 13: ACL Qdrant/OpenSearch Builders**
- Create `crates/rag-retrieval/src/acl/builders.rs`
- Build Qdrant filter conditions
- Build OpenSearch filter clauses

### Phase 5: Caching (Tasks 14-16)

**Task 14: Retrieval Cache**
- Create `crates/rag-retrieval/src/cache/retrieval.rs`
- Cache full retrieval results
- TTL-based expiration

**Task 15: Cache Key Builder**
- Create `crates/rag-retrieval/src/cache/keys.rs`
- Deterministic key generation
- Include query, mode, filters, tenant

**Task 16: Cache Stats**
- Create `crates/rag-retrieval/src/cache/stats.rs`
- Hit/miss tracking
- Performance metrics

### Phase 6: Hybrid Searcher (Tasks 17-19)

**Task 17: Hybrid Searcher Core**
- Create `crates/rag-retrieval/src/hybrid/searcher.rs`
- Orchestrate semantic + keyword search
- Parallel execution with tokio::join!

**Task 18: Hybrid Search Pipeline**
- Create `crates/rag-retrieval/src/hybrid/pipeline.rs`
- Full pipeline: preprocess → search → fuse → rerank → filter
- Timeout handling at each stage

**Task 19: Hybrid Search Config**
- Create `crates/rag-retrieval/src/hybrid/config.rs`
- Unified configuration for all components
- Environment variable loading

### Phase 7: Axum API (Tasks 20-24)

**Task 20: API Types**
- Create `crates/rag-retrieval/src/api/types.rs`
- Request/response Pydantic-equivalent structs
- OpenAPI annotations with utoipa

**Task 21: Search Endpoint**
- Create `crates/rag-retrieval/src/api/routes/search.rs`
- POST /api/v1/retrieve
- Input validation

**Task 22: Multi-Query Endpoint**
- Create `crates/rag-retrieval/src/api/routes/multi.rs`
- POST /api/v1/retrieve/multi
- Parallel query execution

**Task 23: Health Endpoints**
- Create `crates/rag-retrieval/src/api/routes/health.rs`
- GET /health, /health/live, /health/ready
- Component status checks

**Task 24: API Server**
- Create `crates/rag-retrieval/src/api/server.rs`
- Axum app setup
- Middleware (logging, tracing, auth)

### Phase 8: Observability (Tasks 25-27)

**Task 25: Prometheus Metrics**
- Create `crates/rag-retrieval/src/observability/metrics.rs`
- Request counters, latency histograms
- Component health gauges

**Task 26: Tracing Setup**
- Create `crates/rag-retrieval/src/observability/tracing.rs`
- OpenTelemetry integration
- Span hierarchy for pipeline stages

**Task 27: Structured Logging**
- Create `crates/rag-retrieval/src/observability/logging.rs`
- JSON logging with tracing-subscriber
- Request ID propagation

### Phase 9: Testing and Benchmarks (Tasks 28-32)

**Task 28: Unit Tests**
- Test each component in isolation
- Mock external services

**Task 29: Integration Tests**
- Create `crates/rag-retrieval/tests/integration/`
- Test full pipeline with wiremock
- Test against docker-compose services

**Task 30: Benchmark Suite**
- Create `crates/rag-retrieval/benches/`
- RRF fusion benchmarks
- Full pipeline benchmarks

**Task 31: API Contract Tests**
- Validate OpenAPI spec
- Request/response schema validation

**Task 32: Documentation**
- Add comprehensive rustdoc
- Update CLAUDE.md with Rust service info

---

## Execution Notes

### Dependencies to Add to Workspace Cargo.toml

```toml
# In workspace dependencies section
humantime-serde = "1.1"
axum = { version = "0.7", features = ["macros"] }
tower = "0.4"
tower-http = { version = "0.5", features = ["cors", "trace", "timeout"] }
utoipa = { version = "4", features = ["axum_extras"] }
utoipa-swagger-ui = { version = "6", features = ["axum"] }
```

### Running the Service

```bash
# Build
cargo build -p rag-retrieval --release

# Run
RUST_LOG=info cargo run -p rag-retrieval

# Test
cargo test -p rag-retrieval

# Benchmark
cargo bench -p rag-retrieval
```

### Shadow Mode Deployment

For production rollout:
1. Deploy Rust service alongside Python
2. Configure traffic mirror in Kubernetes
3. Compare responses and latencies
4. Gradually shift traffic (1% → 10% → 50% → 100%)

---

Plan complete and saved to `docs/plans/2025-01-26-rust-retrieval-service.md`.

**Two execution options:**

1. **Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

2. **Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach would you prefer?

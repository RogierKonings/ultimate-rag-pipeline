//! # RAG Retrieval Service
//!
//! Production-grade retrieval service for RAG (Retrieval-Augmented Generation) pipelines.
//!
//! This crate provides a complete retrieval solution including hybrid search,
//! multiple fusion algorithms, query processing, reranking, and ACL filtering.
//!
//! ## Features
//!
//! - **Hybrid Search**: Combines semantic (Qdrant) and keyword (OpenSearch) search
//! - **Fusion Algorithms**: RRF, Linear, and Distribution-Based Score Fusion (DBSF)
//! - **Query Processing**: Preprocessing, expansion, and HyDE (Hypothetical Document Embeddings)
//! - **Reranking**: Cross-encoder reranking via LLM Gateway
//! - **ACL Filtering**: Visibility-based access control with group memberships
//! - **Caching**: Query result caching with Redis
//! - **Observability**: Prometheus metrics, OpenTelemetry tracing, structured logging
//!
//! ## Architecture
//!
//! The retrieval pipeline follows these stages:
//!
//! 1. **Cache Check** - Check for cached results to avoid redundant computation
//! 2. **Query Preprocessing** - Normalize and classify query intent
//! 3. **Query Expansion** (optional) - Add synonym terms to improve recall
//! 4. **HyDE** (optional) - Generate hypothetical document for embedding
//! 5. **Embedding** - Convert query to vector representation
//! 6. **Hybrid Search** - Parallel semantic + keyword search execution
//! 7. **Fusion** - Combine results using RRF, Linear, or DBSF algorithms
//! 8. **Reranking** (optional) - Cross-encoder reranking for precision
//! 9. **ACL Filtering** - Visibility-based access control enforcement
//! 10. **Cache Store** - Cache results for future queries
//!
//! ## Quick Start
//!
//! ### Fusion Algorithms
//!
//! The crate supports three fusion methods for combining search results:
//!
//! - **RRF (Reciprocal Rank Fusion)**: Best for cases where score distributions
//!   differ significantly between search methods. Uses only rank information.
//! - **Linear**: Simple weighted combination of normalized scores. Best when
//!   score distributions are similar and well-calibrated.
//! - **DBSF**: Uses z-score normalization to account for different score
//!   distributions. Best when distributions have different means/std devs.
//!
//! ```
//! use rag_retrieval::fusion::{fuse, FusionConfig, FusionMethod};
//! use rag_retrieval::ScoredItem;
//!
//! let semantic_results = vec![
//!     ScoredItem::new("doc1", 0.9),
//!     ScoredItem::new("doc2", 0.8),
//!     ScoredItem::new("doc3", 0.7),
//! ];
//!
//! let keyword_results = vec![
//!     ScoredItem::new("doc2", 0.95),
//!     ScoredItem::new("doc4", 0.85),
//!     ScoredItem::new("doc1", 0.75),
//! ];
//!
//! // Use RRF (default) - rank-based fusion
//! let config = FusionConfig::default();
//! let fused = fuse(&semantic_results, &keyword_results, &config).unwrap();
//!
//! // Results in both lists are boosted
//! assert_eq!(fused[0].id, "doc1"); // Rank 1 semantic + Rank 3 keyword
//! assert_eq!(fused[1].id, "doc2"); // Rank 2 semantic + Rank 1 keyword
//!
//! // Use Linear fusion with custom weights
//! let config = FusionConfig::new(FusionMethod::Linear)
//!     .with_weights(0.6, 0.4);  // 60% semantic, 40% keyword
//! let fused = fuse(&semantic_results, &keyword_results, &config).unwrap();
//!
//! // Use DBSF for distribution-aware fusion
//! let config = FusionConfig::new(FusionMethod::Dbsf);
//! let fused = fuse(&semantic_results, &keyword_results, &config).unwrap();
//! ```
//!
//! ### Hybrid Search Configuration
//!
//! Configure hybrid search behavior including search limits, fusion settings,
//! filtering, and timeouts:
//!
//! ```
//! use rag_retrieval::hybrid::HybridSearchConfig;
//! use rag_retrieval::fusion::FusionMethod;
//!
//! let config = HybridSearchConfig::default()
//!     .with_top_k(10)                    // Final results to return
//!     .with_semantic_top_k(50)           // Candidates from vector search
//!     .with_keyword_top_k(50)            // Candidates from keyword search
//!     .with_fusion_method(FusionMethod::Rrf)
//!     .with_weights(0.7, 0.3)            // Semantic vs keyword weight
//!     .with_min_score(0.3)               // Minimum score threshold
//!     .with_deduplicate(true);           // Remove duplicate chunks per doc
//! ```
//!
//! ### Pipeline Configuration
//!
//! Configure the full search pipeline with optional stages:
//!
//! ```
//! use rag_retrieval::hybrid::PipelineConfig;
//!
//! let config = PipelineConfig::new()
//!     .with_query_expansion(true)   // Enable synonym expansion
//!     .with_hyde(false)             // Disable HyDE
//!     .with_reranking(true)         // Enable cross-encoder reranking
//!     .with_caching(true)           // Enable result caching
//!     .with_rerank_top_k(20)        // Rerank top 20 candidates
//!     .with_final_top_k(10);        // Return top 10 results
//! ```
//!
//! ### Access Control
//!
//! Enforce visibility-based access control using user context:
//!
//! ```
//! use rag_retrieval::types::{UserContext, Visibility};
//! use uuid::Uuid;
//!
//! let user = UserContext::new(Uuid::new_v4(), Uuid::new_v4())
//!     .with_groups(vec!["engineering".into(), "backend".into()])
//!     .with_roles(vec!["developer".into()])
//!     .with_admin(false);
//!
//! // Check access to a group-restricted document
//! let can_access = user.can_access(
//!     Visibility::Group,
//!     &["engineering".into(), "sales".into()]
//! );
//! assert!(can_access);  // User is in "engineering" group
//! ```
//!
//! ## Module Overview
//!
//! - [`fusion`]: Fusion algorithms (RRF, Linear, DBSF) for combining search results
//! - [`hybrid`]: Hybrid search orchestration and pipeline configuration
//! - [`search`]: Semantic and keyword search client implementations
//! - [`query`]: Query preprocessing, expansion, and HyDE generation
//! - [`reranking`]: Cross-encoder reranking service integration
//! - [`acl`]: Access control list filtering and visibility enforcement
//! - [`cache`]: Query result caching with Redis
//! - [`embedding`]: Embedding service client for query vectorization
//! - [`api`]: HTTP API types, routes, and server configuration
//! - [`observability`]: Metrics, tracing, and structured logging
//! - [`types`]: Core types (SearchMode, Visibility, UserContext, etc.)
//! - [`error`]: Error types and result handling
//!
//! ## Legacy RRF API
//!
//! For backward compatibility, the RRF functions are still available at the
//! crate root level:
//!
//! ```
//! use rag_retrieval::rrf::{RrfConfig, reciprocal_rank_fusion};
//! use rag_retrieval::ScoredItem;
//!
//! let semantic_results = vec![
//!     ScoredItem::new("doc1", 0.9),
//!     ScoredItem::new("doc2", 0.8),
//! ];
//!
//! let keyword_results = vec![
//!     ScoredItem::new("doc2", 0.95),
//!     ScoredItem::new("doc3", 0.85),
//! ];
//!
//! let config = RrfConfig::default();
//! let fused = reciprocal_rank_fusion(&[&semantic_results, &keyword_results], &config).unwrap();
//! ```
//!
//! ## Performance Targets
//!
//! The retrieval service is designed to meet the following latency targets (p95):
//!
//! | Operation | Target | Timeout |
//! |-----------|--------|---------|
//! | Query embedding | 20ms | 5000ms |
//! | Semantic search | 50ms | 3000ms |
//! | Keyword search | 30ms | 3000ms |
//! | Fusion | 5ms | N/A |
//! | Reranking | 150ms | 8000ms |
//! | Total E2E | 300ms | 15000ms |

pub mod acl;
pub mod api;
pub mod cache;
pub mod embedding;
pub mod error;
pub mod fusion;
pub mod hybrid;
pub mod observability;
pub mod query;
pub mod reranking;
pub mod search;
pub mod types;
pub mod utils;

// Re-export fusion module as `rrf` for backward compatibility
pub use fusion as rrf;

// Re-export key types from fusion module
pub use fusion::{
    fuse, reciprocal_rank_fusion, FusedResult, FusionConfig, FusionError, FusionMethod, RrfConfig,
    RrfError, ScoredItem,
};

// Re-export error types
pub use error::{RetrievalError, Result};

// Re-export core types
pub use types::{
    QueryType, RetrievalDebug, RetrievalMetrics, RetrievalResult, UserContext, Visibility,
};

// Re-export search types
pub use search::{
    KeywordResult, KeywordSearchConfig, KeywordSearchFilters, KeywordSearcher, SearchConfig,
    SemanticResult, SemanticSearchConfig, SemanticSearcher,
};

// Re-export embedding types
pub use embedding::{EmbeddingClient, EmbeddingConfig};

// Re-export reranking types
pub use reranking::{RerankerClient, RerankerConfig, RerankerService, RerankResponse, RerankResult};

// Re-export query types
pub use query::{
    HydeConfig, HydeGenerator, HydeResult, PreprocessedQuery, QueryCache, QueryCacheConfig,
    QueryCacheKey, QueryExpander, QueryExpanderConfig, QueryPreprocessor, QueryPreprocessorConfig,
};

// Re-export ACL types
pub use acl::{
    ACLFilter, ACLFilterConfig, FilterCondition, HasACLFields, MatchType, OpenSearchFilterBuilder,
    QdrantFilterBuilder, UnifiedFilter,
};

// Re-export cache types
pub use cache::{CacheKeyBuilder, CacheStats, CacheStatsSnapshot, RetrievalCache};

// Re-export hybrid search types
pub use hybrid::{
    HybridSearchConfig, HybridSearchResponse, HybridSearchResult, HybridSearcher, PipelineConfig,
    SearchOptions, SearchPipeline, SearchPipelineBuilder, SearchPipelineResponse,
};

// Re-export API types
pub use api::{
    create_router, create_router_with_config, run_server, run_server_with_config, ApiError,
    AppState, RetrieveRequest, RetrieveResponse, ServerConfig,
};

// Re-export observability types
pub use observability::{
    encode_metrics, init_tracing, log_error, log_request_complete, log_request_start,
    log_stage_complete, register_metrics, shutdown_tracing, span_names, RequestContext,
    RetrievalMetricsCollector, TracingConfig,
};

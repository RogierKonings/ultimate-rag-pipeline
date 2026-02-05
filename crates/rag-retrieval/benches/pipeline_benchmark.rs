//! Benchmarks for pipeline operations (preprocessing, caching, key generation).
//!
//! Run with: `cargo bench -p rag-retrieval --bench pipeline_benchmark`
//!
//! These benchmarks measure the performance of query preprocessing,
//! cache key generation, and other pipeline utilities.

use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use uuid::Uuid;

use rag_retrieval::acl::{FilterCondition, UnifiedFilter};
use rag_retrieval::cache::CacheKeyBuilder;
use rag_retrieval::hybrid::{HybridSearchConfig, PipelineConfig, SearchOptions};
use rag_retrieval::query::{QueryPreprocessor, QueryPreprocessorConfig};
use rag_retrieval::types::{SearchMode, UserContext, Visibility};

/// Sample queries for benchmarking.
const SAMPLE_QUERIES: &[&str] = &[
    "What is Rust?",
    "How do I implement a linked list in Rust?",
    "Explain the difference between Arc and Rc in Rust programming language",
    "What are the best practices for error handling in production Rust applications?",
    "How does the Rust borrow checker work and what problems does it solve for memory safety?",
];

/// Long query for edge case testing.
fn generate_long_query(words: usize) -> String {
    (0..words).map(|i| format!("word{i}")).collect::<Vec<_>>().join(" ")
}

/// Benchmark query preprocessing with default config.
fn bench_query_preprocessing(c: &mut Criterion) {
    let mut group = c.benchmark_group("Query Preprocessing");

    let config = QueryPreprocessorConfig::default();
    let preprocessor = QueryPreprocessor::new(config);

    // Different query lengths
    for query in SAMPLE_QUERIES {
        let param = format!("{}_chars", query.len());
        group.throughput(Throughput::Elements(1));

        group.bench_with_input(BenchmarkId::new("preprocess", &param), query, |b, query| {
            b.iter(|| preprocessor.preprocess(black_box(*query)));
        });
    }

    group.finish();
}

/// Benchmark query preprocessing with varying query lengths.
fn bench_preprocessing_by_length(c: &mut Criterion) {
    let mut group = c.benchmark_group("Preprocessing by Length");

    let config = QueryPreprocessorConfig::default();
    let preprocessor = QueryPreprocessor::new(config);

    for word_count in [5, 10, 25, 50, 100, 200].iter() {
        let query = generate_long_query(*word_count);

        group.bench_with_input(
            BenchmarkId::new("words", word_count),
            &query,
            |b, query| {
                b.iter(|| preprocessor.preprocess(black_box(query)));
            },
        );
    }

    group.finish();
}

/// Benchmark cache key generation.
fn bench_cache_key_generation(c: &mut Criterion) {
    let mut group = c.benchmark_group("Cache Key Generation");

    let tenant_id = Uuid::new_v4();
    let user_id = Uuid::new_v4();

    for query in SAMPLE_QUERIES {
        let param = format!("{}_chars", query.len());

        group.bench_with_input(BenchmarkId::new("build_key", &param), query, |b, query| {
            let builder = CacheKeyBuilder::new(tenant_id, *query)
                .with_user_id(user_id)
                .with_search_mode(SearchMode::Hybrid)
                .with_top_k(10);

            b.iter(|| builder.clone().build());
        });
    }

    group.finish();
}

/// Benchmark cache key generation with varying parameters.
fn bench_cache_key_complexity(c: &mut Criterion) {
    let mut group = c.benchmark_group("Cache Key Complexity");

    let query = "test query";
    let tenant_id = Uuid::new_v4();
    let user_id = Uuid::new_v4();

    // Minimal key (query + tenant only)
    group.bench_function("minimal", |b| {
        b.iter(|| {
            CacheKeyBuilder::new(black_box(tenant_id), black_box(query)).build()
        });
    });

    // Standard key (with user and mode)
    group.bench_function("standard", |b| {
        b.iter(|| {
            CacheKeyBuilder::new(black_box(tenant_id), black_box(query))
                .with_user_id(black_box(user_id))
                .with_search_mode(black_box(SearchMode::Hybrid))
                .with_top_k(black_box(10))
                .build()
        });
    });

    // Full key (with filters)
    group.bench_function("with_filters", |b| {
        let filter = UnifiedFilter::new()
            .must(FilterCondition::any_of("allowed_groups", vec!["engineering".to_string(), "backend".to_string()]));

        b.iter(|| {
            CacheKeyBuilder::new(black_box(tenant_id), black_box(query))
                .with_user_id(black_box(user_id))
                .with_search_mode(black_box(SearchMode::Hybrid))
                .with_top_k(black_box(10))
                .with_filters(black_box(&filter))
                .build()
        });
    });

    group.finish();
}

/// Benchmark UserContext creation.
fn bench_user_context_creation(c: &mut Criterion) {
    let mut group = c.benchmark_group("UserContext Creation");

    let user_id = Uuid::new_v4();
    let tenant_id = Uuid::new_v4();

    // Basic context
    group.bench_function("basic", |b| {
        b.iter(|| UserContext::new(black_box(user_id), black_box(tenant_id)));
    });

    // Context with groups
    group.bench_function("with_groups", |b| {
        let groups = vec!["group1".to_string(), "group2".to_string(), "group3".to_string()];

        b.iter(|| {
            UserContext::new(black_box(user_id), black_box(tenant_id))
                .with_groups(black_box(groups.clone()))
        });
    });

    // Full context
    group.bench_function("full", |b| {
        let groups = vec!["group1".to_string(), "group2".to_string()];
        let roles = vec!["developer".to_string(), "viewer".to_string()];

        b.iter(|| {
            UserContext::new(black_box(user_id), black_box(tenant_id))
                .with_groups(black_box(groups.clone()))
                .with_roles(black_box(roles.clone()))
                .with_admin(black_box(false))
        });
    });

    group.finish();
}

/// Benchmark access control checks.
fn bench_access_control(c: &mut Criterion) {
    let mut group = c.benchmark_group("Access Control");

    let ctx = UserContext::new(Uuid::new_v4(), Uuid::new_v4())
        .with_groups(vec!["engineering".to_string(), "backend".to_string()]);

    let allowed_groups_match = vec!["engineering".to_string()];
    let allowed_groups_no_match = vec!["sales".to_string(), "marketing".to_string()];
    let allowed_groups_many = (0..20).map(|i| format!("group{i}")).collect::<Vec<_>>();

    // Public access (always allowed)
    group.bench_function("public", |b| {
        b.iter(|| ctx.can_access(black_box(Visibility::Public), black_box(&[])));
    });

    // Group access with match
    group.bench_function("group_match", |b| {
        b.iter(|| {
            ctx.can_access(black_box(Visibility::Group), black_box(&allowed_groups_match))
        });
    });

    // Group access without match
    group.bench_function("group_no_match", |b| {
        b.iter(|| {
            ctx.can_access(black_box(Visibility::Group), black_box(&allowed_groups_no_match))
        });
    });

    // Group access with many groups to check
    group.bench_function("group_many", |b| {
        b.iter(|| ctx.can_access(black_box(Visibility::Group), black_box(&allowed_groups_many)));
    });

    group.finish();
}

/// Benchmark SearchOptions construction.
fn bench_search_options(c: &mut Criterion) {
    let mut group = c.benchmark_group("SearchOptions Construction");

    // Default options
    group.bench_function("default", |b| {
        b.iter(|| SearchOptions::default());
    });

    // Builder pattern
    group.bench_function("builder", |b| {
        b.iter(|| {
            SearchOptions::new()
                .with_top_k(black_box(20))
                .with_search_mode(black_box(SearchMode::Semantic))
                .with_skip_cache(black_box(true))
                .with_rerank(black_box(false))
        });
    });

    group.finish();
}

/// Benchmark HybridSearchConfig construction.
fn bench_config_construction(c: &mut Criterion) {
    let mut group = c.benchmark_group("Config Construction");

    // Default hybrid config
    group.bench_function("hybrid_default", |b| {
        b.iter(|| HybridSearchConfig::default());
    });

    // Builder pattern
    group.bench_function("hybrid_builder", |b| {
        b.iter(|| {
            HybridSearchConfig::default()
                .with_top_k(black_box(20))
                .with_semantic_top_k(black_box(100))
                .with_keyword_top_k(black_box(100))
                .with_weights(black_box(0.6), black_box(0.4))
                .with_min_score(black_box(0.3))
        });
    });

    // Default pipeline config
    group.bench_function("pipeline_default", |b| {
        b.iter(|| PipelineConfig::default());
    });

    // Pipeline builder
    group.bench_function("pipeline_builder", |b| {
        b.iter(|| {
            PipelineConfig::new()
                .with_query_expansion(black_box(true))
                .with_hyde(black_box(true))
                .with_reranking(black_box(true))
                .with_rerank_top_k(black_box(30))
                .with_final_top_k(black_box(10))
        });
    });

    group.finish();
}

/// Benchmark config serialization.
fn bench_config_serialization(c: &mut Criterion) {
    let mut group = c.benchmark_group("Config Serialization");

    let hybrid_config = HybridSearchConfig::default()
        .with_top_k(20)
        .with_weights(0.6, 0.4);

    let pipeline_config = PipelineConfig::new()
        .with_query_expansion(true)
        .with_hyde(true)
        .with_reranking(true);

    // Serialize hybrid config
    group.bench_function("hybrid_serialize", |b| {
        b.iter(|| serde_json::to_string(black_box(&hybrid_config)));
    });

    // Serialize pipeline config
    group.bench_function("pipeline_serialize", |b| {
        b.iter(|| serde_json::to_string(black_box(&pipeline_config)));
    });

    // Deserialize hybrid config
    let hybrid_json = serde_json::to_string(&hybrid_config).unwrap();
    group.bench_function("hybrid_deserialize", |b| {
        b.iter(|| {
            serde_json::from_str::<HybridSearchConfig>(black_box(&hybrid_json))
        });
    });

    // Deserialize pipeline config
    let pipeline_json = serde_json::to_string(&pipeline_config).unwrap();
    group.bench_function("pipeline_deserialize", |b| {
        b.iter(|| {
            serde_json::from_str::<PipelineConfig>(black_box(&pipeline_json))
        });
    });

    group.finish();
}

/// Benchmark UUID operations (common in retrieval).
fn bench_uuid_operations(c: &mut Criterion) {
    let mut group = c.benchmark_group("UUID Operations");

    // Generate new UUID
    group.bench_function("generate_v4", |b| {
        b.iter(|| Uuid::new_v4());
    });

    // Parse UUID from string
    let uuid_str = "550e8400-e29b-41d4-a716-446655440000";
    group.bench_function("parse", |b| {
        b.iter(|| Uuid::parse_str(black_box(uuid_str)));
    });

    // UUID to string
    let uuid = Uuid::new_v4();
    group.bench_function("to_string", |b| {
        b.iter(|| black_box(&uuid).to_string());
    });

    // UUID equality comparison
    let uuid1 = Uuid::new_v4();
    let uuid2 = uuid1;
    group.bench_function("equality", |b| {
        b.iter(|| black_box(&uuid1) == black_box(&uuid2));
    });

    group.finish();
}

/// Benchmark search mode properties.
fn bench_search_mode_properties(c: &mut Criterion) {
    let mut group = c.benchmark_group("SearchMode Properties");

    // Check uses_semantic
    group.bench_function("uses_semantic", |b| {
        b.iter(|| {
            black_box(SearchMode::Hybrid).uses_semantic();
            black_box(SearchMode::Semantic).uses_semantic();
            black_box(SearchMode::Keyword).uses_semantic();
        });
    });

    // Check uses_keyword
    group.bench_function("uses_keyword", |b| {
        b.iter(|| {
            black_box(SearchMode::Hybrid).uses_keyword();
            black_box(SearchMode::Semantic).uses_keyword();
            black_box(SearchMode::Keyword).uses_keyword();
        });
    });

    group.finish();
}

criterion_group!(
    benches,
    bench_query_preprocessing,
    bench_preprocessing_by_length,
    bench_cache_key_generation,
    bench_cache_key_complexity,
    bench_user_context_creation,
    bench_access_control,
    bench_search_options,
    bench_config_construction,
    bench_config_serialization,
    bench_uuid_operations,
    bench_search_mode_properties,
);

criterion_main!(benches);

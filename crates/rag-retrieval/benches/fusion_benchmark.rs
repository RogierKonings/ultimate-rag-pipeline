//! Benchmarks for fusion algorithms (RRF, Linear, DBSF).
//!
//! Run with: `cargo bench -p rag-retrieval --bench fusion_benchmark`
//!
//! These benchmarks measure the performance of different fusion algorithms
//! for combining semantic and keyword search results.

use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use rand::Rng;
use uuid::Uuid;

use rag_retrieval::fusion::{
    distribution_based_fusion, fuse, linear_fusion, reciprocal_rank_fusion, DbsfConfig,
    FusionConfig, FusionMethod, LinearConfig, RrfConfig, ScoredItem,
};

/// Generate random scored items with UUIDs for benchmarking.
fn generate_uuid_results(count: usize, score_range: (f32, f32)) -> Vec<ScoredItem<Uuid>> {
    let mut rng = rand::thread_rng();
    (0..count)
        .map(|_| ScoredItem::new(Uuid::new_v4(), rng.gen_range(score_range.0..score_range.1)))
        .collect()
}

/// Generate random scored items with String IDs for benchmarking.
fn generate_string_results(count: usize, prefix: &str) -> Vec<ScoredItem<String>> {
    let mut rng = rand::thread_rng();
    (0..count)
        .map(|i| ScoredItem::new(format!("{prefix}_{i}"), rng.gen_range(0.0..1.0)))
        .collect()
}

/// Generate overlapping results (more realistic scenario).
fn generate_overlapping_results(
    count: usize,
    overlap_ratio: f32,
) -> (Vec<ScoredItem<Uuid>>, Vec<ScoredItem<Uuid>>) {
    let mut rng = rand::thread_rng();
    let overlap_count = (count as f32 * overlap_ratio) as usize;
    let unique_count = count - overlap_count;

    // Shared IDs (appear in both lists)
    let shared_ids: Vec<Uuid> = (0..overlap_count).map(|_| Uuid::new_v4()).collect();

    // List 1: shared + unique to list 1
    let mut list1: Vec<ScoredItem<Uuid>> = shared_ids
        .iter()
        .map(|&id| ScoredItem::new(id, rng.gen_range(0.0..1.0)))
        .collect();
    list1.extend(
        (0..unique_count).map(|_| ScoredItem::new(Uuid::new_v4(), rng.gen_range(0.0..1.0))),
    );

    // List 2: shared + unique to list 2 (with different scores for shared items)
    let mut list2: Vec<ScoredItem<Uuid>> = shared_ids
        .iter()
        .map(|&id| ScoredItem::new(id, rng.gen_range(0.0..1.0)))
        .collect();
    list2.extend(
        (0..unique_count).map(|_| ScoredItem::new(Uuid::new_v4(), rng.gen_range(0.0..1.0))),
    );

    (list1, list2)
}

/// Generate results with BM25-like score distribution (larger values).
fn generate_bm25_results(count: usize) -> Vec<ScoredItem<Uuid>> {
    let mut rng = rand::thread_rng();
    (0..count)
        .map(|_| {
            ScoredItem::new(
                Uuid::new_v4(),
                rng.gen_range(5.0..20.0), // BM25-like scores
            )
        })
        .collect()
}

/// Benchmark RRF fusion with varying list sizes.
fn bench_rrf_sizes(c: &mut Criterion) {
    let mut group = c.benchmark_group("RRF List Sizes");

    for size in [10, 25, 50, 100, 250, 500].iter() {
        group.throughput(Throughput::Elements(*size as u64 * 2)); // Two lists

        group.bench_with_input(BenchmarkId::from_parameter(size), size, |b, &size| {
            let semantic = generate_uuid_results(size, (0.0, 1.0));
            let keyword = generate_uuid_results(size, (0.0, 1.0));
            let config = RrfConfig::default();

            b.iter(|| {
                reciprocal_rank_fusion(black_box(&[&semantic, &keyword]), black_box(&config))
            });
        });
    }

    group.finish();
}

/// Benchmark Linear fusion with varying list sizes.
fn bench_linear_sizes(c: &mut Criterion) {
    let mut group = c.benchmark_group("Linear List Sizes");

    for size in [10, 25, 50, 100, 250, 500].iter() {
        group.throughput(Throughput::Elements(*size as u64 * 2));

        group.bench_with_input(BenchmarkId::from_parameter(size), size, |b, &size| {
            let semantic = generate_uuid_results(size, (0.0, 1.0));
            let keyword = generate_uuid_results(size, (0.0, 1.0));
            let config = LinearConfig::default();

            b.iter(|| {
                linear_fusion(
                    black_box(&semantic),
                    black_box(&keyword),
                    black_box(&config),
                )
            });
        });
    }

    group.finish();
}

/// Benchmark DBSF fusion with varying list sizes.
fn bench_dbsf_sizes(c: &mut Criterion) {
    let mut group = c.benchmark_group("DBSF List Sizes");

    for size in [10, 25, 50, 100, 250, 500].iter() {
        group.throughput(Throughput::Elements(*size as u64 * 2));

        group.bench_with_input(BenchmarkId::from_parameter(size), size, |b, &size| {
            let semantic = generate_uuid_results(size, (0.0, 1.0));
            let keyword = generate_bm25_results(size); // Different distribution
            let config = DbsfConfig::default();

            b.iter(|| {
                distribution_based_fusion(
                    black_box(&semantic),
                    black_box(&keyword),
                    black_box(&config),
                )
            });
        });
    }

    group.finish();
}

/// Compare all fusion methods at standard retrieval size (50 results each).
fn bench_fusion_comparison(c: &mut Criterion) {
    let mut group = c.benchmark_group("Fusion Method Comparison");

    let (semantic, keyword) = generate_overlapping_results(50, 0.3);

    // RRF
    group.bench_function("RRF", |b| {
        let config = FusionConfig::new(FusionMethod::Rrf);
        b.iter(|| {
            fuse(
                black_box(&semantic),
                black_box(&keyword),
                black_box(&config),
            )
        });
    });

    // Linear
    group.bench_function("Linear", |b| {
        let config = FusionConfig::new(FusionMethod::Linear);
        b.iter(|| {
            fuse(
                black_box(&semantic),
                black_box(&keyword),
                black_box(&config),
            )
        });
    });

    // DBSF
    group.bench_function("DBSF", |b| {
        let config = FusionConfig::new(FusionMethod::Dbsf);
        b.iter(|| {
            fuse(
                black_box(&semantic),
                black_box(&keyword),
                black_box(&config),
            )
        });
    });

    group.finish();
}

/// Benchmark impact of overlap ratio on fusion performance.
fn bench_overlap_impact(c: &mut Criterion) {
    let mut group = c.benchmark_group("Overlap Impact");

    for overlap in [0.0, 0.25, 0.5, 0.75, 1.0].iter() {
        let param = format!("overlap_{:.0}%", overlap * 100.0);

        group.bench_with_input(BenchmarkId::new("RRF", &param), overlap, |b, &overlap| {
            let (semantic, keyword) = generate_overlapping_results(50, overlap);
            let config = FusionConfig::default();

            b.iter(|| {
                fuse(
                    black_box(&semantic),
                    black_box(&keyword),
                    black_box(&config),
                )
            });
        });
    }

    group.finish();
}

/// Benchmark RRF k parameter impact.
fn bench_rrf_k_parameter(c: &mut Criterion) {
    let mut group = c.benchmark_group("RRF K Parameter");

    let (semantic, keyword) = generate_overlapping_results(50, 0.3);

    for k in [1.0, 10.0, 30.0, 60.0, 100.0].iter() {
        group.bench_with_input(BenchmarkId::from_parameter(k), k, |b, &k| {
            let config = FusionConfig::new(FusionMethod::Rrf).with_rrf_k(k);

            b.iter(|| {
                fuse(
                    black_box(&semantic),
                    black_box(&keyword),
                    black_box(&config),
                )
            });
        });
    }

    group.finish();
}

/// Benchmark fusion with top_k limiting.
fn bench_top_k_limiting(c: &mut Criterion) {
    let mut group = c.benchmark_group("Top-K Limiting");

    let (semantic, keyword) = generate_overlapping_results(100, 0.3);

    for top_k in [5, 10, 25, 50, 100].iter() {
        group.bench_with_input(BenchmarkId::from_parameter(top_k), top_k, |b, &top_k| {
            let config = FusionConfig::default().with_top_k(top_k);

            b.iter(|| {
                fuse(
                    black_box(&semantic),
                    black_box(&keyword),
                    black_box(&config),
                )
            });
        });
    }

    group.finish();
}

/// Benchmark multi-list RRF (more than 2 lists).
fn bench_multi_list_rrf(c: &mut Criterion) {
    let mut group = c.benchmark_group("Multi-List RRF");

    for num_lists in [2, 3, 5, 10].iter() {
        group.bench_with_input(
            BenchmarkId::from_parameter(num_lists),
            num_lists,
            |b, &num_lists| {
                let lists: Vec<Vec<ScoredItem<String>>> = (0..num_lists)
                    .map(|i| generate_string_results(50, &format!("list{i}")))
                    .collect();
                let refs: Vec<&[ScoredItem<String>]> = lists.iter().map(Vec::as_slice).collect();
                let config = RrfConfig::default();

                b.iter(|| reciprocal_rank_fusion(black_box(&refs), black_box(&config)));
            },
        );
    }

    group.finish();
}

/// Benchmark fusion with different weight configurations.
fn bench_weight_configurations(c: &mut Criterion) {
    let mut group = c.benchmark_group("Weight Configurations");

    let (semantic, keyword) = generate_overlapping_results(50, 0.3);

    let weight_configs = [
        (0.5, 0.5, "balanced"),
        (0.7, 0.3, "semantic_heavy"),
        (0.3, 0.7, "keyword_heavy"),
        (0.9, 0.1, "semantic_dominant"),
        (0.1, 0.9, "keyword_dominant"),
    ];

    for (sem_w, kw_w, name) in weight_configs.iter() {
        group.bench_with_input(BenchmarkId::new("Linear", *name), name, |b, _| {
            let config = FusionConfig::new(FusionMethod::Linear).with_weights(*sem_w, *kw_w);

            b.iter(|| {
                fuse(
                    black_box(&semantic),
                    black_box(&keyword),
                    black_box(&config),
                )
            });
        });
    }

    group.finish();
}

/// Benchmark empty and edge case scenarios.
fn bench_edge_cases(c: &mut Criterion) {
    let mut group = c.benchmark_group("Edge Cases");

    // Empty semantic list
    group.bench_function("empty_semantic", |b| {
        let semantic: Vec<ScoredItem<Uuid>> = Vec::new();
        let keyword = generate_uuid_results(50, (0.0, 1.0));
        let config = FusionConfig::default();

        b.iter(|| {
            fuse(
                black_box(&semantic),
                black_box(&keyword),
                black_box(&config),
            )
        });
    });

    // Empty keyword list
    group.bench_function("empty_keyword", |b| {
        let semantic = generate_uuid_results(50, (0.0, 1.0));
        let keyword: Vec<ScoredItem<Uuid>> = Vec::new();
        let config = FusionConfig::default();

        b.iter(|| {
            fuse(
                black_box(&semantic),
                black_box(&keyword),
                black_box(&config),
            )
        });
    });

    // Both empty
    group.bench_function("both_empty", |b| {
        let semantic: Vec<ScoredItem<Uuid>> = Vec::new();
        let keyword: Vec<ScoredItem<Uuid>> = Vec::new();
        let config = FusionConfig::default();

        b.iter(|| {
            fuse(
                black_box(&semantic),
                black_box(&keyword),
                black_box(&config),
            )
        });
    });

    // Very small lists
    group.bench_function("small_lists_3_each", |b| {
        let semantic = generate_uuid_results(3, (0.0, 1.0));
        let keyword = generate_uuid_results(3, (0.0, 1.0));
        let config = FusionConfig::default();

        b.iter(|| {
            fuse(
                black_box(&semantic),
                black_box(&keyword),
                black_box(&config),
            )
        });
    });

    // Large lists
    group.bench_function("large_lists_1000_each", |b| {
        let semantic = generate_uuid_results(1000, (0.0, 1.0));
        let keyword = generate_uuid_results(1000, (0.0, 1.0));
        let config = FusionConfig::default();

        b.iter(|| {
            fuse(
                black_box(&semantic),
                black_box(&keyword),
                black_box(&config),
            )
        });
    });

    group.finish();
}

/// Benchmark realistic retrieval scenario.
fn bench_realistic_scenario(c: &mut Criterion) {
    let mut group = c.benchmark_group("Realistic Scenario");

    // Standard RAG retrieval: 50 candidates from each, return top 10
    group.bench_function("standard_rag", |b| {
        let (semantic, keyword) = generate_overlapping_results(50, 0.3);
        let config = FusionConfig::new(FusionMethod::Rrf)
            .with_weights(0.7, 0.3)
            .with_rrf_k(60.0)
            .with_top_k(10);

        b.iter(|| {
            fuse(
                black_box(&semantic),
                black_box(&keyword),
                black_box(&config),
            )
        });
    });

    // High-throughput scenario: 100 candidates, return top 20
    group.bench_function("high_throughput", |b| {
        let (semantic, keyword) = generate_overlapping_results(100, 0.25);
        let config = FusionConfig::new(FusionMethod::Rrf).with_top_k(20);

        b.iter(|| {
            fuse(
                black_box(&semantic),
                black_box(&keyword),
                black_box(&config),
            )
        });
    });

    // Precision scenario: fewer candidates, more reranking expected
    group.bench_function("precision_focus", |b| {
        let (semantic, keyword) = generate_overlapping_results(25, 0.4);
        let config = FusionConfig::new(FusionMethod::Dbsf).with_top_k(5);

        b.iter(|| {
            fuse(
                black_box(&semantic),
                black_box(&keyword),
                black_box(&config),
            )
        });
    });

    group.finish();
}

criterion_group!(
    benches,
    bench_rrf_sizes,
    bench_linear_sizes,
    bench_dbsf_sizes,
    bench_fusion_comparison,
    bench_overlap_impact,
    bench_rrf_k_parameter,
    bench_top_k_limiting,
    bench_multi_list_rrf,
    bench_weight_configurations,
    bench_edge_cases,
    bench_realistic_scenario,
);

criterion_main!(benches);

//! Benchmarks for RRF fusion algorithm.
//!
//! Run with: `cargo bench -p rag-retrieval`

use criterion::{black_box, criterion_group, criterion_main, BenchmarkId, Criterion, Throughput};
use rag_retrieval::rrf::{hybrid_fusion, reciprocal_rank_fusion, RrfConfig, ScoredItem};
use rand::Rng;

/// Generate random scored items for benchmarking.
fn generate_results(count: usize, prefix: &str) -> Vec<ScoredItem<String>> {
    let mut rng = rand::thread_rng();
    (0..count)
        .map(|i| ScoredItem::new(format!("{prefix}_{i}"), rng.gen_range(0.0..1.0)))
        .collect()
}

/// Generate overlapping results (more realistic scenario).
fn generate_overlapping_results(
    count: usize,
    overlap_ratio: f32,
) -> (Vec<ScoredItem<String>>, Vec<ScoredItem<String>>) {
    let mut rng = rand::thread_rng();
    let overlap_count = (count as f32 * overlap_ratio) as usize;
    let unique_count = count - overlap_count;

    // Shared items (appear in both lists)
    let shared: Vec<String> = (0..overlap_count).map(|i| format!("shared_{i}")).collect();

    // List 1: shared + unique to list 1
    let list1: Vec<ScoredItem<String>> = shared
        .iter()
        .map(|id| ScoredItem::new(id.clone(), rng.gen_range(0.0..1.0)))
        .chain(
            (0..unique_count)
                .map(|i| ScoredItem::new(format!("unique1_{i}"), rng.gen_range(0.0..1.0))),
        )
        .collect();

    // List 2: shared + unique to list 2
    let list2: Vec<ScoredItem<String>> = shared
        .iter()
        .map(|id| ScoredItem::new(id.clone(), rng.gen_range(0.0..1.0)))
        .chain(
            (0..unique_count)
                .map(|i| ScoredItem::new(format!("unique2_{i}"), rng.gen_range(0.0..1.0))),
        )
        .collect();

    (list1, list2)
}

fn rrf_basic_benchmark(c: &mut Criterion) {
    let mut group = c.benchmark_group("RRF Basic");

    for size in [10, 50, 100, 500].iter() {
        group.throughput(Throughput::Elements(*size as u64));

        group.bench_with_input(BenchmarkId::new("single_list", size), size, |b, &size| {
            let list = generate_results(size, "doc");
            let config = RrfConfig::default();

            b.iter(|| reciprocal_rank_fusion(black_box(&[&list]), black_box(&config)));
        });

        group.bench_with_input(BenchmarkId::new("two_lists", size), size, |b, &size| {
            let list1 = generate_results(size, "semantic");
            let list2 = generate_results(size, "keyword");
            let config = RrfConfig::default();

            b.iter(|| reciprocal_rank_fusion(black_box(&[&list1, &list2]), black_box(&config)));
        });
    }

    group.finish();
}

fn rrf_overlapping_benchmark(c: &mut Criterion) {
    let mut group = c.benchmark_group("RRF Overlapping");

    for size in [50, 100, 500].iter() {
        for overlap in [0.25, 0.5, 0.75].iter() {
            let param = format!("size_{}_overlap_{}", size, overlap);
            group.throughput(Throughput::Elements(*size as u64));

            group.bench_with_input(
                BenchmarkId::new("fusion", &param),
                &(*size, *overlap),
                |b, &(size, overlap)| {
                    let (list1, list2) = generate_overlapping_results(size, overlap);
                    let config = RrfConfig::default();

                    b.iter(|| {
                        reciprocal_rank_fusion(black_box(&[&list1, &list2]), black_box(&config))
                    });
                },
            );
        }
    }

    group.finish();
}

fn hybrid_fusion_benchmark(c: &mut Criterion) {
    let mut group = c.benchmark_group("Hybrid Fusion");

    // Standard retrieval scenario: 50 candidates from each search
    let (semantic, keyword) = generate_overlapping_results(50, 0.3);

    group.bench_function("standard_retrieval", |b| {
        b.iter(|| {
            hybrid_fusion(
                black_box(&semantic),
                black_box(&keyword),
                black_box(0.7),
                black_box(0.3),
                black_box(60.0),
                black_box(Some(10)),
            )
        });
    });

    // Large scale: 500 candidates
    let (semantic_large, keyword_large) = generate_overlapping_results(500, 0.3);

    group.bench_function("large_scale_retrieval", |b| {
        b.iter(|| {
            hybrid_fusion(
                black_box(&semantic_large),
                black_box(&keyword_large),
                black_box(0.7),
                black_box(0.3),
                black_box(60.0),
                black_box(Some(10)),
            )
        });
    });

    group.finish();
}

fn rrf_multilist_benchmark(c: &mut Criterion) {
    let mut group = c.benchmark_group("RRF Multi-List");

    for num_lists in [2, 3, 5, 10].iter() {
        group.bench_with_input(
            BenchmarkId::new("lists", num_lists),
            num_lists,
            |b, &num_lists| {
                let lists: Vec<Vec<ScoredItem<String>>> = (0..num_lists)
                    .map(|i| generate_results(50, &format!("list{i}")))
                    .collect();
                let refs: Vec<&[ScoredItem<String>]> = lists.iter().map(Vec::as_slice).collect();
                let config = RrfConfig::default();

                b.iter(|| reciprocal_rank_fusion(black_box(&refs), black_box(&config)));
            },
        );
    }

    group.finish();
}

criterion_group!(
    benches,
    rrf_basic_benchmark,
    rrf_overlapping_benchmark,
    hybrid_fusion_benchmark,
    rrf_multilist_benchmark
);

criterion_main!(benches);

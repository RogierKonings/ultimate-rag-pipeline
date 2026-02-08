//! Memory profiling benchmarks for the retrieval crate.
//!
//! This benchmark measures heap allocations during fusion operations
//! to help identify memory usage patterns and potential optimizations.
//!
//! # Running
//!
//! Run with memory profiling enabled:
//! ```bash
//! cargo bench --bench memory_benchmark --features memory-profiling
//! ```
//!
//! After running, check `dhat-heap.json` for detailed allocation data.
//! You can view it using the DHAT viewer: https://nnethercote.github.io/dh_view/dh_view.html

#![cfg(feature = "memory-profiling")]

use dhat::{Dhat, DhatAlloc};

#[global_allocator]
static ALLOC: DhatAlloc = DhatAlloc;

use rag_retrieval::fusion::{
    distribution_based_fusion, linear_fusion, reciprocal_rank_fusion, DbsfConfig, LinearConfig,
    RrfConfig, ScoredItem,
};

/// Create test results with realistic content.
fn create_test_results(count: usize, prefix: &str) -> Vec<ScoredItem<String>> {
    (0..count)
        .map(|i| {
            ScoredItem::new(
                format!("{}_{:06}", prefix, i),
                1.0 - (i as f32 / count as f32),
            )
        })
        .collect()
}

/// Measure allocation for a single RRF fusion operation.
fn measure_rrf_fusion(semantic_count: usize, keyword_count: usize) -> u64 {
    let semantic = create_test_results(semantic_count, "semantic");
    let keyword = create_test_results(keyword_count, "keyword");
    let config = RrfConfig::default();

    let stats_before = dhat::HeapStats::get();
    let _results = reciprocal_rank_fusion(&[&semantic, &keyword], &config);
    let stats_after = dhat::HeapStats::get();

    stats_after.total_bytes - stats_before.total_bytes
}

/// Measure allocation for a single Linear fusion operation.
fn measure_linear_fusion(semantic_count: usize, keyword_count: usize) -> u64 {
    let semantic = create_test_results(semantic_count, "semantic");
    let keyword = create_test_results(keyword_count, "keyword");
    let config = LinearConfig::default();

    let stats_before = dhat::HeapStats::get();
    let _results = linear_fusion(&semantic, &keyword, &config);
    let stats_after = dhat::HeapStats::get();

    stats_after.total_bytes - stats_before.total_bytes
}

/// Measure allocation for a single DBSF fusion operation.
fn measure_dbsf_fusion(semantic_count: usize, keyword_count: usize) -> u64 {
    let semantic = create_test_results(semantic_count, "semantic");
    let keyword = create_test_results(keyword_count, "keyword");
    let config = DbsfConfig::default();

    let stats_before = dhat::HeapStats::get();
    let _results = distribution_based_fusion(&semantic, &keyword, &config);
    let stats_after = dhat::HeapStats::get();

    stats_after.total_bytes - stats_before.total_bytes
}

fn main() {
    // Initialize the profiler - this creates dhat-heap.json on drop
    let _profiler = Dhat::start_heap_profiling();

    println!("Memory Profiling for Fusion Operations");
    println!("======================================");
    println!();

    let test_sizes = [
        (50, 50),     // Small: typical top-k retrieval
        (100, 100),   // Medium: reranking candidates
        (500, 500),   // Large: extensive search
        (1000, 1000), // Very large: stress test
    ];

    println!("RRF Fusion Memory Usage:");
    println!("------------------------");
    for (semantic_size, keyword_size) in &test_sizes {
        let bytes = measure_rrf_fusion(*semantic_size, *keyword_size);
        println!(
            "  {}+{} items: {:>8} bytes ({:.2} KB)",
            semantic_size,
            keyword_size,
            bytes,
            bytes as f64 / 1024.0
        );
    }
    println!();

    println!("Linear Fusion Memory Usage:");
    println!("---------------------------");
    for (semantic_size, keyword_size) in &test_sizes {
        let bytes = measure_linear_fusion(*semantic_size, *keyword_size);
        println!(
            "  {}+{} items: {:>8} bytes ({:.2} KB)",
            semantic_size,
            keyword_size,
            bytes,
            bytes as f64 / 1024.0
        );
    }
    println!();

    println!("DBSF Fusion Memory Usage:");
    println!("-------------------------");
    for (semantic_size, keyword_size) in &test_sizes {
        let bytes = measure_dbsf_fusion(*semantic_size, *keyword_size);
        println!(
            "  {}+{} items: {:>8} bytes ({:.2} KB)",
            semantic_size,
            keyword_size,
            bytes,
            bytes as f64 / 1024.0
        );
    }
    println!();

    // Per-item cost analysis
    println!("Per-Item Memory Cost Analysis:");
    println!("------------------------------");
    let base_size = 100;
    let large_size = 500;

    let rrf_base = measure_rrf_fusion(base_size, base_size);
    let rrf_large = measure_rrf_fusion(large_size, large_size);
    let rrf_per_item = (rrf_large as f64 - rrf_base as f64) / ((large_size - base_size) * 2) as f64;

    let linear_base = measure_linear_fusion(base_size, base_size);
    let linear_large = measure_linear_fusion(large_size, large_size);
    let linear_per_item =
        (linear_large as f64 - linear_base as f64) / ((large_size - base_size) * 2) as f64;

    let dbsf_base = measure_dbsf_fusion(base_size, base_size);
    let dbsf_large = measure_dbsf_fusion(large_size, large_size);
    let dbsf_per_item =
        (dbsf_large as f64 - dbsf_base as f64) / ((large_size - base_size) * 2) as f64;

    println!("  RRF:    ~{:.1} bytes per item", rrf_per_item);
    println!("  Linear: ~{:.1} bytes per item", linear_per_item);
    println!("  DBSF:   ~{:.1} bytes per item", dbsf_per_item);
    println!();

    // Repeated operations test (for cache analysis)
    println!("Repeated Operations (10 iterations each):");
    println!("-----------------------------------------");
    let stats_before = dhat::HeapStats::get();
    for _ in 0..10 {
        let semantic = create_test_results(100, "sem");
        let keyword = create_test_results(100, "kw");
        let _ = reciprocal_rank_fusion(&[&semantic, &keyword], &RrfConfig::default());
    }
    let stats_after = dhat::HeapStats::get();
    println!(
        "  RRF (10x 100+100): {} bytes total, {} avg per op",
        stats_after.total_bytes - stats_before.total_bytes,
        (stats_after.total_bytes - stats_before.total_bytes) / 10
    );

    println!();
    println!("Profiling complete. See dhat-heap.json for detailed allocation report.");
    println!("View at: https://nnethercote.github.io/dh_view/dh_view.html");
}

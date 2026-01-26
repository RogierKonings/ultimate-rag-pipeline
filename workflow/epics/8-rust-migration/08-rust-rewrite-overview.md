# Epic 8: Rust Rewrite - Overview and Assessment

> **Priority:** Strategic
> **Estimated Effort:** 16-22 months (full team)
> **Dependencies:** None (greenfield rewrite)
> **Risk Level:** High
> **Last Updated:** 2025-01-26

## Executive Summary

This epic series outlines the work required to rewrite the Ultimate RAG Pipeline from Python to Rust. This is a significant undertaking that should be weighed carefully against incremental improvements to the existing Python codebase.

**Update (January 2025):** The codebase has grown ~51% since the initial analysis, with major additions including a video processing pipeline, enhanced observability, and resilience patterns. The Rust ecosystem has matured significantly, improving feasibility for several components.

## Current Codebase Analysis

### Scale Metrics

| Metric | Original (Jan 2025) | Current | Change |
|--------|---------------------|---------|--------|
| Total Python Lines | ~106,000 | ~160,000 | **+51%** |
| Source Files | 436 | ~636 | +46% |
| Main Source Files (excl. tests) | 222 | ~330 | +49% |
| Services | 4 | 5 (+ embedding) | +1 |
| External Dependencies | 60+ | 80+ | +33% |

### Per-Service Breakdown

| Service | Lines of Code | Complexity | Rust Effort | Performance Impact |
|---------|--------------|------------|-------------|-------------------|
| Ingestion | ~47,000 | Very High | Very High | **High** (video, chunking) |
| Retrieval | ~26,000 | Medium-High | Medium | **Very High** (hot path) |
| Orchestrator | ~37,000 | Very High | Very High | Medium (I/O bound) |
| Shared | ~50,000 | Medium-High | Medium-High | High (clients) |
| Embedding | ~230 | Low | Low | **Critical** (CPU-bound) |

### New Components Since Initial Analysis

The following major features have been added and must be considered in migration scope:

#### Video Processing Pipeline (Ingestion Service)

- Scene detection with PySceneDetect
- Keyframe extraction with OpenCV
- OCR processing with Tesseract
- Vision analysis (OpenAI/Ollama providers)
- Audio transcription (Whisper)
- Content fusion and semantic chunking
- Video-specific Qdrant collection (`video_chunks`)

#### Enhanced Observability (Shared)

- Correlation context propagation across services
- Traced clients (Qdrant, OpenSearch) with span instrumentation
- SLI/SLO metrics and alerting
- Business metrics collection
- Auto-instrumentation setup

#### Resilience Patterns (Shared/Services)

- Centralized timeout configuration with cascade validation
- Retry utilities with exponential backoff and jitter
- Graceful degradation handling
- Circuit breaker patterns

#### Dynamic LLM Routing (Orchestrator)

- Model tiering and complexity-based selection
- Automatic fallback between models
- Cost-aware routing

### Critical Python Dependencies

These Python libraries have varying levels of Rust ecosystem support:

#### Well-Supported in Rust (Mature - 2025)

- **FastAPI → Axum 0.7+**: Production-ready, excellent ergonomics
- **Pydantic → Serde + validator**: Superior performance and type safety
- **asyncpg → SQLx 0.7+**: Compile-time checked queries, mature
- **Redis client → redis-rs 0.24+**: Full-featured async Redis with cluster support
- **HTTP clients → reqwest 0.11+**: Industry standard, battle-tested
- **sentence-transformers → candle**: HuggingFace's native Rust ML framework (NEW)

#### Good Support / Minor Workarounds (Improved)

- **Qdrant client → qdrant-client 1.10+**: Official, full-featured, production-ready
- **OpenSearch → opensearch-rs 2.2+**: Improved stability, async support
- **OpenTelemetry → opentelemetry 0.22+**: Significantly improved, tracing integration
- **Tiktoken → tiktoken-rs**: Available binding, well-maintained
- **OpenCV → opencv-rust**: Mature bindings for video/image processing (NEW)
- **Tesseract → tesseract-rs**: OCR bindings available (NEW)

#### No Direct Equivalent (Major Effort)

- **LangGraph/LangChain**: No equivalent - requires custom state machine
- **Celery**: No equivalent - use Redis queues + tokio workers or NATS JetStream
- **Presidio (PII detection)**: No equivalent - regex + rust-bert NER
- **PySceneDetect**: No equivalent - FFmpeg + custom scene detection
- **Whisper**: whisper-rs exists but less mature than Python
- **Unstructured (document parsing)**: No equivalent - custom parsers needed
- **PyMuPDF (PDF)**: pdf-extract or pdfium-render via FFI

## Effort Assessment

### Honest Assessment: Why This Is Hard

1. **ML/AI Ecosystem Gap**: Python dominates ML tooling. Rust's ecosystem is catching up but still behind for NLP and LLM orchestration. However, `candle` (HuggingFace) has significantly improved native Rust ML inference.

2. **LangGraph Has No Equivalent**: The orchestrator's stateful workflow engine would need to be built from scratch or adapted from a generic state machine library.

3. **Video Processing**: The new video pipeline adds significant complexity with PySceneDetect, Whisper, and vision analysis having limited Rust equivalents.

4. **Document Parsing**: Python's unstructured/PyMuPDF ecosystem is years ahead. Rust alternatives exist but lack features.

5. **Team Expertise**: Rust has a steep learning curve. A Python team would need significant upskilling.

6. **Testing Complexity**: All 300+ test files need rewriting with different testing patterns.

### Where Rust Excels (Benefits)

1. **Performance**: 10-100x faster for CPU-bound operations (embedding, chunking, RRF, video frame processing)
2. **Memory Safety**: No runtime errors from null/undefined
3. **Concurrency**: Fearless concurrency with compile-time guarantees
4. **Binary Distribution**: Single binary deployment, no Python environment
5. **Resource Efficiency**: Lower memory footprint, better container density
6. **Predictable Latency**: No GC pauses, critical for p99 latency targets

### Performance-Critical Components (Migration Priority)

Based on profiling targets from CLAUDE.md, these components benefit most from Rust:

| Component              | Current p95 | Target     | Rust Benefit                 |
|------------------------|-------------|------------|------------------------------|
| Query embedding        | 20ms        | 15ms       | High (CPU-bound)             |
| RRF fusion             | 5ms         | <1ms       | **Very High** (pure compute) |
| Semantic search        | 50ms        | 30ms       | Medium (mostly I/O)          |
| Chunking               | varies      | 2x faster  | **Very High** (CPU-bound)    |
| Video frame extraction | varies      | 3x faster  | **Very High** (CPU-bound)    |
| Reranking              | 150ms       | 150ms      | Low (external service)       |

### Updated Rust Equivalent LOC Estimate

| Service | Python LOC | Rust LOC (est.) | Ratio |
|---------|-----------|-----------------|-------|
| Ingestion (+ video) | 47,000 | 55,000-70,000 | 1.2-1.5x |
| Retrieval | 26,000 | 22,000-28,000 | 0.85-1.1x |
| Orchestrator | 37,000 | 55,000-70,000 | 1.5-1.9x |
| Shared | 50,000 | 40,000-50,000 | 0.8-1.0x |
| Embedding | 230 | 500-800 | 2-3x |
| **Total** | **160,000** | **172,000-219,000** | **1.1-1.4x** |

The orchestrator and ingestion inflate significantly due to LangGraph abstractions and video processing complexity.

## Recommended Approach: Performance-Focused Incremental Rewrite

Rather than a big-bang rewrite, prioritize components with highest performance impact:

### Phase 1: CPU-Bound Hot Paths (Months 1-6)

**Goal:** Maximize performance gains with minimal risk

- Rewrite embedding service in Rust with `candle` (critical path, CPU-bound)
- Rewrite RRF fusion algorithm (pure compute, easy validation)
- Rewrite chunking engine in Rust (CPU-bound text processing)
- Expose via PyO3 bindings to existing Python code initially

**Expected Impact:** 2-5x speedup on embedding/chunking, <1ms RRF fusion

### Phase 2: Retrieval Service (Months 7-12)

**Goal:** Full Rust service on the critical query path

- Rewrite retrieval service with Axum (hybrid search, reranking client)
- Port query preprocessing and caching
- Implement ACL filtering
- Shadow mode deployment with traffic comparison

**Expected Impact:** p95 latency from 250ms → 150ms

### Phase 3: Video Processing Pipeline (Months 13-18)

**Goal:** High-throughput video ingestion

- Port keyframe extraction with `opencv-rust`
- Implement scene detection (custom algorithm or FFmpeg)
- Port OCR processing with `tesseract-rs`
- Implement content fusion and video-specific indexing
- Keep vision analysis (OpenAI/Ollama) as HTTP calls

**Expected Impact:** 2-3x faster video processing throughput

### Phase 4: Ingestion Service (Months 19-24)

**Goal:** Complete ingestion rewrite

- Port document parsers (HTML, Markdown, JSON - easy)
- Implement PDF parser (pdfium FFI or fallback to Python service)
- Replace Celery with Redis + tokio workers
- Full async worker system

### Phase 5: Orchestrator (Months 25-32) - Optional

**Goal:** Only if performance is critical

- Design custom state machine framework
- Port workflow nodes
- Implement streaming SSE
- This is mostly I/O-bound, so Rust benefit is lower

**Recommendation:** Keep orchestrator in Python unless latency requirements demand otherwise.

## Child Epics

This overview epic is broken down into the following implementation epics:

1. **[Epic 8.1: Rust Foundation and Shared Libraries](08.1-rust-foundation.md)** - Updated
2. **[Epic 8.2: Rust Retrieval Service](08.2-rust-retrieval-service.md)** - Updated
3. **[Epic 8.3: Rust Ingestion Service](08.3-rust-ingestion-service.md)** - Updated (includes video)
4. **[Epic 8.4: Rust Orchestrator Service](08.4-rust-orchestrator-service.md)** - Optional
5. **[Epic 8.5: Rust Testing and Migration](08.5-rust-testing-migration.md)** - Updated

## Decision Framework

### When to Proceed with Rust Rewrite

- Performance is a critical bottleneck
- Team has Rust expertise or bandwidth to learn
- Long-term maintenance cost reduction is prioritized
- Deployment simplification (single binary) is valuable
- Memory/CPU costs in production are significant

### When to Stay with Python

- Time-to-market pressure
- Rapid iteration on RAG pipeline is needed
- ML/AI experimentation is ongoing
- Team is Python-native
- Current performance is acceptable

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| LangGraph feature gap | High | Keep orchestrator in Python, or design modular state machine early |
| Video processing complexity | High | Start with keyframe/OCR (good Rust support), keep vision analysis in Python |
| Team learning curve | High | Phased approach, pair programming, start with simpler components |
| Ecosystem immaturity | Medium | Contribute to open source, fallback to FFI or HTTP microservices |
| Schedule overrun | High | Incremental delivery, keep Python fallback always available |
| Feature regression | Medium | Comprehensive test suite, shadow mode, parallel running |
| Whisper/transcription gap | Medium | Keep Python transcription service, call via HTTP |

## Quick Wins for Performance (Start Here)

If you want immediate performance gains with minimal risk:

1. **RRF Fusion in Rust** (1-2 days): Pure algorithm, easy to validate, immediate <1ms latency
2. **Embedding Service in Rust** (1-2 weeks): Use `candle` for native inference, 2-3x speedup
3. **Chunking Engine in Rust** (1 week): CPU-bound, easy to benchmark against Python

These can be exposed via PyO3 bindings without changing the service architecture.

## Definition of Done (Performance-Focused)

For the recommended performance-focused approach:

- [ ] Embedding service running in Rust with measured speedup
- [ ] Retrieval service in Rust with p95 < 150ms
- [ ] Video processing pipeline in Rust with 2x throughput
- [ ] Shadow mode validation in production
- [ ] Performance benchmarks documented
- [ ] Python fallback available for all components

## Definition of Done (Full Rewrite - Optional)

- [ ] All five services running in Rust
- [ ] Feature parity with Python implementation
- [ ] Performance benchmarks show improvement across all services
- [ ] All tests passing (rewritten in Rust)
- [ ] Production deployment validated
- [ ] Python codebase deprecated
- [ ] Documentation updated

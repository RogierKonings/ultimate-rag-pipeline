# Epic 8: Rust Rewrite - Overview and Assessment

> **Priority:** Strategic
> **Estimated Effort:** 12-18 months (full team)
> **Dependencies:** None (greenfield rewrite)
> **Risk Level:** High

## Executive Summary

This epic series outlines the work required to rewrite the Ultimate RAG Pipeline from Python to Rust. This is a significant undertaking that should be weighed carefully against incremental improvements to the existing Python codebase.

## Current Codebase Analysis

### Scale Metrics

| Metric | Value |
|--------|-------|
| Total Python Lines | ~106,000 |
| Source Files | 436 |
| Main Source Files (excl. tests) | 222 |
| Services | 4 |
| External Dependencies | 60+ |

### Per-Service Breakdown

| Service | Lines of Code | Complexity | Rust Effort |
|---------|--------------|------------|-------------|
| Ingestion | ~30,000 | High | High |
| Retrieval | ~17,000 | Medium | Medium |
| Orchestrator | ~24,000 | Very High | Very High |
| Shared | ~36,000 | Medium | Medium-High |

### Critical Python Dependencies

These Python libraries have varying levels of Rust ecosystem support:

#### Well-Supported in Rust
- **FastAPI → Axum/Actix-web**: Excellent alternatives
- **Pydantic → Serde**: Superior performance and type safety
- **asyncpg → SQLx/tokio-postgres**: Mature async Postgres support
- **Redis client → redis-rs**: Full-featured async Redis
- **HTTP clients → reqwest**: Industry standard

#### Partial Support / Workarounds Needed
- **Qdrant client → qdrant-client-rust**: Official Rust client exists
- **OpenSearch → opensearch-rs**: Community maintained
- **OpenTelemetry → opentelemetry-rust**: Good but less mature
- **Tiktoken → tiktoken-rs**: Available binding

#### No Direct Equivalent (Major Effort)
- **LangGraph/LangChain**: No equivalent - requires custom state machine
- **Celery**: No equivalent - need custom worker pool or NATS/RabbitMQ direct
- **Presidio (PII detection)**: No equivalent - custom NER/regex implementation
- **Spacy/NLTK (NLP)**: rust-bert exists but less mature
- **Unstructured (document parsing)**: No equivalent - custom parsers needed
- **PyMuPDF (PDF)**: pdf-rs exists but less capable

## Effort Assessment

### Honest Assessment: Why This Is Hard

1. **ML/AI Ecosystem Gap**: Python dominates ML tooling. Rust's ecosystem is catching up but significantly behind for NLP, embeddings, and LLM orchestration.

2. **LangGraph Has No Equivalent**: The orchestrator's stateful workflow engine would need to be built from scratch or adapted from a generic state machine library.

3. **Document Parsing**: Python's unstructured/PyMuPDF ecosystem is years ahead. Rust alternatives exist but lack features.

4. **Team Expertise**: Rust has a steep learning curve. A Python team would need significant upskilling.

5. **Testing Complexity**: All 200+ test files need rewriting with different testing patterns.

### Where Rust Excels (Benefits)

1. **Performance**: 10-100x faster for CPU-bound operations
2. **Memory Safety**: No runtime errors from null/undefined
3. **Concurrency**: Fearless concurrency with compile-time guarantees
4. **Binary Distribution**: Single binary deployment, no Python environment
5. **Resource Efficiency**: Lower memory footprint, better container density

### Realistic Rust Equivalent LOC Estimate

| Service | Python LOC | Rust LOC (est.) | Ratio |
|---------|-----------|-----------------|-------|
| Ingestion | 30,000 | 35,000-45,000 | 1.2-1.5x |
| Retrieval | 17,000 | 15,000-20,000 | 0.9-1.2x |
| Orchestrator | 24,000 | 40,000-50,000 | 1.7-2.0x |
| Shared | 36,000 | 30,000-40,000 | 0.8-1.1x |
| **Total** | **107,000** | **120,000-155,000** | **1.1-1.4x** |

The orchestrator inflates significantly because LangGraph abstractions must be reimplemented.

## Recommended Approach: Incremental Rewrite

Rather than a big-bang rewrite, consider:

### Phase 1: High-Performance Components (Months 1-4)
- Rewrite embedding service in Rust (computation-heavy)
- Rewrite chunking engine in Rust (CPU-bound text processing)
- Expose via PyO3 bindings to existing Python code

### Phase 2: Data Layer (Months 5-8)
- Rewrite retrieval service (hybrid search, reranking)
- Rewrite index writers
- Keep Python API as facade initially

### Phase 3: API Services (Months 9-12)
- Rewrite FastAPI endpoints in Axum
- Migrate authentication middleware
- Full Rust retrieval service

### Phase 4: Orchestration (Months 13-18)
- Design and implement Rust state machine for RAG workflow
- Migrate LLM gateway
- Complete orchestrator rewrite

## Child Epics

This overview epic is broken down into the following implementation epics:

1. **[Epic 8.1: Rust Foundation and Shared Libraries](08.1-rust-foundation.md)**
2. **[Epic 8.2: Rust Retrieval Service](08.2-rust-retrieval-service.md)**
3. **[Epic 8.3: Rust Ingestion Service](08.3-rust-ingestion-service.md)**
4. **[Epic 8.4: Rust Orchestrator Service](08.4-rust-orchestrator-service.md)**
5. **[Epic 8.5: Rust Testing and Migration](08.5-rust-testing-migration.md)**

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
| LangGraph feature gap | High | Design modular state machine early |
| Team learning curve | High | Phased approach, pair programming |
| Ecosystem immaturity | Medium | Contribute to open source, fallback to FFI |
| Schedule overrun | High | Incremental delivery, keep Python fallback |
| Feature regression | Medium | Comprehensive test suite, parallel running |

## Definition of Done (Overall)

- [ ] All four services running in Rust
- [ ] Feature parity with Python implementation
- [ ] Performance benchmarks show improvement
- [ ] All tests passing (rewritten in Rust)
- [ ] Production deployment validated
- [ ] Python codebase deprecated
- [ ] Documentation updated

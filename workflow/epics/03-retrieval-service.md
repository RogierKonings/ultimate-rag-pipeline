# Epic 3: Retrieval Service

> **Priority:** Critical  
> **Estimated Effort:** 2-3 weeks  
> **Dependencies:** Epic 1 (Infrastructure), Epic 2 (Ingestion)

## Overview

Build the retrieval service that handles query processing, hybrid search combining semantic and keyword search, result fusion, reranking, and access control filtering.

## Goals

- Implement hybrid search with configurable fusion
- Enable query rewriting and expansion
- Integrate cross-encoder reranking
- Enforce document-level access control
- Provide low-latency retrieval (<200ms p95)

## User Stories

### US-3.1: Query Preprocessor
**As a** developer  
**I want** query preprocessing and rewriting  
**So that** queries are optimized for retrieval

**Acceptance Criteria:**
- [ ] Query normalization (lowercase, whitespace)
- [ ] Query expansion with synonyms
- [ ] HyDE (Hypothetical Document Embeddings) support
- [ ] Multi-query generation for complex queries
- [ ] Query embedding generation

### US-3.2: Semantic Search
**As a** developer  
**I want** vector similarity search  
**So that** semantically relevant documents are retrieved

**Acceptance Criteria:**
- [ ] Qdrant vector search integration
- [ ] Configurable top-k results
- [ ] Filter support (metadata, ACL)
- [ ] Score normalization
- [ ] HNSW parameters tuned for recall

### US-3.3: Keyword Search
**As a** developer  
**I want** BM25 keyword search  
**So that** exact term matches are found

**Acceptance Criteria:**
- [ ] OpenSearch BM25 search integration
- [ ] Configurable top-k results
- [ ] Filter support (metadata, ACL)
- [ ] Custom analyzers for domain terms
- [ ] Boost configuration for fields

### US-3.4: Hybrid Fusion
**As a** developer  
**I want** result fusion from multiple search methods  
**So that** I get the best of both search approaches

**Acceptance Criteria:**
- [ ] Reciprocal Rank Fusion (RRF) implementation
- [ ] Configurable fusion weights (default 0.7 semantic / 0.3 keyword)
- [ ] Score normalization before fusion
- [ ] Deduplication of results
- [ ] Configurable result limit

### US-3.5: Reranker Integration
**As a** developer  
**I want** cross-encoder reranking  
**So that** results are ordered by true relevance

**Acceptance Criteria:**
- [ ] BGE-reranker-v2-m3 integration
- [ ] Batch processing for efficiency
- [ ] Configurable rerank top-k
- [ ] Score threshold filtering
- [ ] Latency < 100ms for 20 documents

### US-3.6: ACL Filter
**As a** developer  
**I want** access control enforcement  
**So that** users only see permitted documents

**Acceptance Criteria:**
- [ ] Filter by tenant_id
- [ ] Filter by user groups
- [ ] Public/private visibility support
- [ ] Pre-filter in Qdrant/OpenSearch queries
- [ ] ACL context from JWT claims

### US-3.7: Retrieval API
**As a** API consumer  
**I want** REST endpoints for retrieval  
**So that** I can search the document corpus

**Acceptance Criteria:**
- [ ] POST `/retrieve` - search endpoint
- [ ] Support for filters in request body
- [ ] Return ranked results with scores
- [ ] Include metadata in response
- [ ] OpenAPI documentation

### US-3.8: Retrieval Logging
**As a** ML engineer  
**I want** retrieval operations logged  
**So that** I can analyze and improve retrieval quality

**Acceptance Criteria:**
- [ ] Log queries, results, latency
- [ ] OpenTelemetry trace integration
- [ ] Structured logging format
- [ ] Retrieval metrics (recall, latency)

## Technical Tasks

1. Set up FastAPI service structure
2. Implement query preprocessor with expansion
3. Build Qdrant search client
4. Build OpenSearch search client
5. Implement RRF fusion algorithm
6. Integrate reranker model service
7. Implement ACL filter builder
8. Create retrieval API routes
9. Add OpenTelemetry instrumentation
10. Write unit and integration tests
11. Performance testing and optimization

## Definition of Done

- [ ] Hybrid search returns relevant results
- [ ] Reranking improves result quality
- [ ] ACL filtering enforced correctly
- [ ] P95 latency < 200ms
- [ ] API documented and tested
- [ ] Retrieval metrics tracked
- [ ] 80%+ test coverage

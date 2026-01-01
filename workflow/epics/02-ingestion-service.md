# Epic 2: Ingestion Service

> **Priority:** Critical  
> **Estimated Effort:** 3-4 weeks  
> **Dependencies:** Epic 1 (Infrastructure Setup)

## Overview

Build the document ingestion pipeline that handles loading documents from various sources, parsing, chunking, embedding generation, and indexing into vector and keyword stores.

## Goals

- Support multiple document sources (files, databases, APIs, web)
- Implement configurable chunking strategies
- Generate embeddings with batching and caching
- Index documents to Qdrant and OpenSearch
- Enable async processing via Celery workers

## User Stories

### US-2.1: Source Connectors
**As a** data engineer  
**I want** connectors for various data sources  
**So that** I can ingest documents from different systems

**Acceptance Criteria:**
- [ ] Filesystem connector (local + S3)
- [ ] Database connector (PostgreSQL, MySQL)
- [ ] Web scraper connector
- [ ] REST API connector
- [ ] Connector interface for extensibility

### US-2.2: Document Parsers
**As a** data engineer  
**I want** parsers for different document types  
**So that** I can extract text from various formats

**Acceptance Criteria:**
- [ ] PDF parser (PyMuPDF + Unstructured fallback)
- [ ] Word document parser (.docx)
- [ ] HTML parser
- [ ] Markdown parser
- [ ] Plain text parser
- [ ] Table extraction support

### US-2.3: Chunking Engine
**As a** data engineer  
**I want** configurable chunking strategies  
**So that** I can optimize retrieval quality

**Acceptance Criteria:**
- [ ] Recursive character splitter
- [ ] Semantic chunking (sentence boundaries)
- [ ] Configurable chunk size (default 512 tokens)
- [ ] Configurable overlap (default 50 tokens)
- [ ] Metadata preservation across chunks
- [ ] Parent-child chunk relationships

### US-2.4: Embedding Service
**As a** developer  
**I want** efficient embedding generation  
**So that** documents can be vectorized for search

**Acceptance Criteria:**
- [ ] Integration with BGE-large-en-v1.5 model
- [ ] Batch processing support
- [ ] Redis-based embedding cache
- [ ] Retry logic with exponential backoff
- [ ] Embedding normalization

### US-2.5: Index Writers
**As a** developer  
**I want** writers for vector and keyword stores  
**So that** documents are searchable

**Acceptance Criteria:**
- [ ] Qdrant index writer with upsert support
- [ ] OpenSearch index writer with bulk API
- [ ] PostgreSQL metadata writer
- [ ] Transaction support for consistency
- [ ] Idempotent operations

### US-2.6: Metadata Enrichment
**As a** data engineer  
**I want** automatic metadata extraction  
**So that** documents have rich, filterable metadata

**Acceptance Criteria:**
- [ ] Extract document title, author, dates
- [ ] Language detection
- [ ] PII detection (Presidio integration)
- [ ] Custom metadata fields support
- [ ] Tenant/ACL metadata injection

### US-2.7: Async Processing
**As a** developer  
**I want** background job processing  
**So that** large ingestion jobs don't block the API

**Acceptance Criteria:**
- [ ] Celery worker configuration
- [ ] Ingestion task implementation
- [ ] Re-embedding task for model updates
- [ ] Job status tracking
- [ ] Dead letter queue for failures

### US-2.8: Ingestion API
**As a** API consumer  
**I want** REST endpoints for ingestion  
**So that** I can trigger and monitor ingestion jobs

**Acceptance Criteria:**
- [ ] POST `/ingest` - trigger ingestion job
- [ ] GET `/ingest/{job_id}` - job status
- [ ] GET `/documents` - list documents
- [ ] DELETE `/documents/{id}` - delete document
- [ ] OpenAPI documentation

## Technical Tasks

1. Set up FastAPI service structure
2. Implement connector base class and concrete connectors
3. Implement parser base class and concrete parsers
4. Build chunking engine with strategy pattern
5. Create embedding service with caching
6. Implement index writers for Qdrant, OpenSearch, PostgreSQL
7. Set up Celery with Redis broker
8. Create API routes with Pydantic schemas
9. Add comprehensive error handling
10. Write unit and integration tests

## Definition of Done

- [ ] All connectors functional
- [ ] All parsers tested with sample documents
- [ ] Chunking produces expected output
- [ ] Embeddings cached correctly
- [ ] Documents searchable in Qdrant and OpenSearch
- [ ] Async jobs complete successfully
- [ ] API endpoints documented and tested
- [ ] 80%+ test coverage

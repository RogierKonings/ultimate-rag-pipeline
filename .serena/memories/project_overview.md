# Ultimate RAG Pipeline - Project Overview

## Purpose
A production-grade Retrieval-Augmented Generation (RAG) architecture that is modular, observable, and data-centric. The architecture cleanly separates ingestion, retrieval, orchestration, and evaluation concerns.

## Tech Stack
- **Language**: Python 3.11+
- **Package Manager**: uv or poetry
- **API Framework**: FastAPI + Pydantic v2
- **Task Queue**: Celery + Redis
- **Vector Database**: Qdrant
- **Keyword Search**: OpenSearch
- **Metadata DB**: PostgreSQL 16+
- **Object Storage**: MinIO / S3
- **Cache**: Redis
- **Orchestration**: LangGraph (LangChain)
- **LLM Serving**: vLLM
- **Embedding Models**: BAAI/bge-large-en-v1.5
- **Reranker**: BAAI/bge-reranker-v2-m3
- **Evaluation**: Ragas + Arize Phoenix
- **Tracing**: OpenTelemetry → Jaeger
- **Metrics**: Prometheus + Grafana

## Core Services
1. **Ingestion Service** (:8001) - Load, chunk, embed, and index documents
2. **Retrieval Service** (:8002) - Find relevant context for queries (hybrid search)
3. **Orchestrator Service** (:8003) - Coordinate LLM calls and business logic
4. **LLM Gateway** (:8004) - Model routing, request batching

## Data Stores
- PostgreSQL (:5432) - Metadata and relational data
- Qdrant (:6333) - Vector embeddings
- OpenSearch (:9200) - Keyword search / BM25
- Redis (:6379) - Caching
- MinIO (:9000) - Object storage

## Project Structure
- `services/` - Microservices code
- `k8s/` - Kubernetes manifests (base + overlays for dev/prod)
- `docs/` - Architecture and documentation
- `workflow/` - Epics and user stories (refined specs)
- `scripts/` - Development and operational scripts
- `config/` - Configuration files

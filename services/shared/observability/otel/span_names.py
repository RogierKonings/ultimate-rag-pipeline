"""
Span Naming Conventions for RAG Pipeline.

All spans follow the pattern: {service}.{component}.{operation}

Services:
- qdrant, opensearch, postgres, redis (external)
- retrieval, orchestrator, ingestion (internal)

This module defines canonical span names for consistent tracing
across all services, enabling meaningful trace hierarchy visualization.
"""


class SpanNames:
    """Canonical span names for client/external operations."""

    # Qdrant operations
    QDRANT_QUERY = "qdrant.query.search"
    QDRANT_UPSERT = "qdrant.mutation.upsert"
    QDRANT_DELETE = "qdrant.mutation.delete"

    # OpenSearch operations
    OPENSEARCH_QUERY = "opensearch.query.search"
    OPENSEARCH_INDEX = "opensearch.mutation.index"
    OPENSEARCH_BULK = "opensearch.mutation.bulk"
    OPENSEARCH_DELETE = "opensearch.mutation.delete"

    # PostgreSQL (auto-instrumented, but for reference)
    POSTGRES_QUERY = "postgres.query.select"
    POSTGRES_INSERT = "postgres.mutation.insert"
    POSTGRES_UPDATE = "postgres.mutation.update"

    # Redis (auto-instrumented, but for reference)
    REDIS_GET = "redis.query.get"
    REDIS_SET = "redis.mutation.set"
    REDIS_DELETE = "redis.mutation.delete"

    # Retrieval service spans
    RETRIEVAL_SEARCH = "retrieval.search.hybrid"
    RETRIEVAL_PREPROCESS = "retrieval.preprocess.query"
    RETRIEVAL_EMBED_QUERY = "retrieval.embed.query"
    RETRIEVAL_SEMANTIC = "retrieval.search.semantic"
    RETRIEVAL_KEYWORD = "retrieval.search.keyword"
    RETRIEVAL_FUSION = "retrieval.fusion.rrf"
    RETRIEVAL_RERANK = "retrieval.rerank.crossencoder"
    RETRIEVAL_ACL = "retrieval.filter.acl"

    # Orchestrator service spans
    ORCHESTRATOR_QUERY = "orchestrator.query.process"
    ORCHESTRATOR_ROUTING = "orchestrator.workflow.routing"
    ORCHESTRATOR_RETRIEVAL = "orchestrator.workflow.retrieval"
    ORCHESTRATOR_PROMPT = "orchestrator.workflow.prompt_building"
    ORCHESTRATOR_GENERATION = "orchestrator.workflow.generation"
    ORCHESTRATOR_VERIFICATION = "orchestrator.workflow.verification"
    ORCHESTRATOR_VALIDATION = "orchestrator.workflow.validation"
    ORCHESTRATOR_INPUT_VALIDATION = "orchestrator.workflow.input_validation"
    ORCHESTRATOR_OUTPUT_VALIDATION = "orchestrator.workflow.output_validation"
    ORCHESTRATOR_CACHE_CHECK = "orchestrator.cache.check"
    ORCHESTRATOR_CACHE_STORE = "orchestrator.cache.store"
    ORCHESTRATOR_DECOMPOSITION = "orchestrator.workflow.decomposition"  # US-10.4.3

    # Ingestion service spans
    INGESTION_DOCUMENT = "ingestion.document.process"
    INGESTION_PARSE = "ingestion.parse.document"
    INGESTION_CHUNK = "ingestion.chunk.split"
    INGESTION_EMBED = "ingestion.embed.batch"
    INGESTION_INDEX_QDRANT = "ingestion.index.qdrant"
    INGESTION_INDEX_OPENSEARCH = "ingestion.index.opensearch"

    # LLM/Embedding
    LLM_COMPLETION = "llm.completion.generate"
    LLM_STREAMING = "llm.completion.stream"
    EMBEDDING_ENCODE = "embedding.encode.batch"

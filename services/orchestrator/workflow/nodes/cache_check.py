"""Cache check node for the RAG workflow.

Implements US-10.5.3: Check answer cache before expensive retrieval/generation.
On cache hit, returns stored response and citations, skipping retrieval and LLM.
"""

import time
from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace

from orchestrator.observability.otel.span_names import SpanNames

if TYPE_CHECKING:
    from cache.answer_cache import AnswerCache
    from workflow.state import RAGState

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


def _compute_config_hash_from_options(
    options: dict,
    answer_cache: "AnswerCache",
) -> str:
    """Compute config hash from request options.

    Args:
        options: Request options dict.
        answer_cache: AnswerCache instance for hash computation.

    Returns:
        Configuration hash string.
    """
    return answer_cache._compute_config_hash(
        retrieval_mode=options.get("retrieval_mode", "hybrid"),
        top_k=options.get("top_k", 10),
        rerank=options.get("rerank", True),
        semantic_weight=options.get("semantic_weight", 0.7),
        keyword_weight=options.get("keyword_weight", 0.3),
        extra_config={
            "temperature": options.get("temperature"),
            "max_tokens": options.get("max_tokens"),
        }
        if options.get("temperature") or options.get("max_tokens")
        else None,
    )


async def cache_check_node(state: "RAGState") -> "RAGState":
    """Check cache before expensive retrieval/generation.

    This node:
    - Checks if answer caching is enabled
    - Looks up the cache using tenant_id, query, and config hash
    - On hit: populates response, citations, and sets cache_hit=True
    - On miss: sets cache_hit=False and continues normal workflow

    Args:
        state: Current RAGState with query and tenant_id.

    Returns:
        Updated RAGState with cache results or cache_hit=False.
    """
    with tracer.start_as_current_span(SpanNames.ORCHESTRATOR_CACHE_CHECK) as span:
        start = time.time()

        timing = dict(state.get("timing", {}))
        options = state.get("options", {})

        # Check if answer caching is enabled
        enable_answer_cache = options.get("enable_answer_cache", True)
        answer_cache = options.get("answer_cache")

        if not enable_answer_cache or answer_cache is None:
            span.set_attribute("orchestrator.cache_enabled", False)
            timing["cache_check"] = (time.time() - start) * 1000
            return {
                **state,
                "cache_hit": False,
                "timing": timing,
            }

        span.set_attribute("orchestrator.cache_enabled", True)

        tenant_id = state.get("tenant_id")
        query = state.get("query", "")

        if not tenant_id or not query:
            span.set_attribute("orchestrator.cache_skip_reason", "missing_tenant_or_query")
            timing["cache_check"] = (time.time() - start) * 1000
            return {
                **state,
                "cache_hit": False,
                "timing": timing,
            }

        # Compute config hash
        config_hash = _compute_config_hash_from_options(options, answer_cache)
        span.set_attribute("orchestrator.config_hash", config_hash)

        # Check cache
        cached = await answer_cache.get(
            tenant_id=tenant_id,
            query=query,
            config_hash=config_hash,
        )

        if cached:
            span.set_attribute("orchestrator.cache_hit", True)
            logger.info(
                "answer_cache_hit",
                extra={
                    "query_preview": query[:50],
                    "tenant_id": tenant_id,
                    "cached_at": cached.cached_at,
                },
            )

            # Convert citations to documents format
            documents = []
            for citation in cached.citations:
                documents.append(
                    {
                        "content": citation.get("content", ""),
                        "score": citation.get("score", 0.0),
                        "chunk_id": citation.get("chunk_id"),
                        "document_id": citation.get("document_id"),
                        "metadata": citation.get("metadata", {}),
                        "source": citation.get("source", ""),
                    }
                )

            timing["cache_check"] = (time.time() - start) * 1000

            return {
                **state,
                "response": cached.response,
                "documents": documents,
                "cache_hit": True,
                "model_used": cached.model_used,
                "strategy": cached.strategy,
                "timing": timing,
                "retrieval_quality": {
                    "degradation_level": "normal",
                    "mode": cached.retrieval_mode,
                    "components_used": ["cache"],
                    "components_skipped": [],
                },
                "context_quality": "full",
            }

        # Cache miss
        span.set_attribute("orchestrator.cache_hit", False)
        timing["cache_check"] = (time.time() - start) * 1000

        # Store config hash for later use when caching the response
        options_with_hash = {**options, "_config_hash": config_hash}

        return {
            **state,
            "cache_hit": False,
            "options": options_with_hash,
            "timing": timing,
        }


async def cache_store_node(state: "RAGState") -> "RAGState":
    """Store response in cache after generation.

    This node runs after generation and stores the response for future cache hits.
    Only stores if:
    - Answer caching is enabled
    - This was a cache miss (not already from cache)
    - Response was successfully generated

    Args:
        state: Current RAGState with response and documents.

    Returns:
        Updated RAGState (unchanged, just adds cache entry).
    """
    with tracer.start_as_current_span(SpanNames.ORCHESTRATOR_CACHE_STORE) as span:
        start = time.time()

        timing = dict(state.get("timing", {}))
        options = state.get("options", {})

        # Skip if caching disabled or already a cache hit
        enable_answer_cache = options.get("enable_answer_cache", True)
        answer_cache = options.get("answer_cache")
        cache_hit = state.get("cache_hit", False)

        if not enable_answer_cache or answer_cache is None or cache_hit:
            span.set_attribute("orchestrator.cache_store_skipped", True)
            timing["cache_store"] = (time.time() - start) * 1000
            return {**state, "timing": timing}

        tenant_id = state.get("tenant_id")
        query = state.get("query", "")
        response = state.get("response")

        if not tenant_id or not query or not response:
            span.set_attribute("orchestrator.cache_store_skip_reason", "missing_data")
            timing["cache_store"] = (time.time() - start) * 1000
            return {**state, "timing": timing}

        # Get config hash computed during cache check
        config_hash = options.get("_config_hash")
        if not config_hash:
            config_hash = _compute_config_hash_from_options(options, answer_cache)

        # Build cached answer
        documents = state.get("documents", [])
        citations = []
        document_ids = []

        for doc in documents:
            citations.append(
                {
                    "content": doc.get("content", ""),
                    "score": doc.get("score", 0.0),
                    "chunk_id": doc.get("chunk_id"),
                    "document_id": doc.get("document_id"),
                    "metadata": doc.get("metadata", {}),
                    "source": doc.get("source", ""),
                }
            )
            if doc.get("document_id"):
                document_ids.append(doc["document_id"])

        from cache.answer_cache import CachedAnswer

        cached_answer = CachedAnswer(
            response=response,
            citations=citations,
            model_used=state.get("model_used", "unknown"),
            retrieval_mode=state.get("retrieval_quality", {}).get("mode", "hybrid"),
            strategy=state.get("strategy", "simple"),
            document_ids=document_ids,
        )

        # Store in cache
        success = await answer_cache.set(
            tenant_id=tenant_id,
            query=query,
            config_hash=config_hash,
            answer=cached_answer,
        )

        span.set_attribute("orchestrator.cache_store_success", success)
        timing["cache_store"] = (time.time() - start) * 1000

        return {**state, "timing": timing}

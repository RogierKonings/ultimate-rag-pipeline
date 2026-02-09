"""Multi-retrieval node for parallel sub-question retrieval (US-10.4.4).

This node retrieves context for multiple sub-questions in parallel,
then aggregates and deduplicates the results.
"""

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import structlog
from opentelemetry import trace

from config import get_config
from orchestrator.observability.otel.span_names import SpanNames
from shared.http_clients import get_retrieval_client

if TYPE_CHECKING:
    from workflow.state import RAGState

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass
class SubQueryResult:
    """Result from a single sub-question retrieval."""

    sub_question: str
    documents: list[dict]
    latency_ms: float


@dataclass
class AggregatedContext:
    """Aggregated and deduplicated context from all sub-questions."""

    documents: list[dict]
    sub_question_mapping: dict[str, list[str]]  # chunk_id -> list of sub_questions
    total_retrieved: int
    deduplicated_count: int


async def _retrieve_for_sub_question(
    client: httpx.AsyncClient,
    sub_question: str,
    tenant_id: str | None,
    top_k: int,
) -> SubQueryResult:
    """
    Retrieve documents for a single sub-question.

    Args:
        client: Shared HTTP client for retrieval service (has base_url configured)
        sub_question: The sub-question to retrieve for
        tenant_id: Optional tenant filter
        top_k: Number of results to retrieve per sub-question

    Returns:
        SubQueryResult with documents and latency
    """
    start = time.time()

    payload = {
        "query": sub_question,
        "mode": "hybrid",
        "top_k": top_k,
        "rerank": False,
        "include_metadata": True,
        "include_highlights": True,
    }

    if tenant_id:
        payload["filters"] = {"tenant_id": tenant_id}

    try:
        response = await client.post(
            "/api/v1/retrieve",
            json=payload,
        )
        response.raise_for_status()

        result = response.json()
        raw_results = result.get("results", [])

        documents = []
        for item in raw_results:
            doc = {
                "content": item.get("content", ""),
                "score": item.get("score", 0.0),
                "chunk_id": item.get("chunk_id"),
                "document_id": item.get("document_id"),
                "metadata": item.get("metadata", {}),
                "title": item.get("title") or item.get("metadata", {}).get("title"),
                "source": item.get("source") or item.get("metadata", {}).get("source_uri", "unknown"),
            }
            documents.append(doc)

        return SubQueryResult(
            sub_question=sub_question,
            documents=documents,
            latency_ms=(time.time() - start) * 1000,
        )

    except Exception as e:
        logger.warning(
            "sub_question_retrieval_failed",
            extra={"sub_question": sub_question[:50], "error": str(e)},
        )
        return SubQueryResult(
            sub_question=sub_question,
            documents=[],
            latency_ms=(time.time() - start) * 1000,
        )


def _aggregate_results(
    results: list[SubQueryResult],
    max_documents: int = 20,
) -> AggregatedContext:
    """
    Aggregate and deduplicate results from multiple sub-questions.

    Documents appearing in multiple sub-question results get a score boost.
    Final results are sorted by boosted score and limited to max_documents.

    Args:
        results: List of SubQueryResult from parallel retrieval
        max_documents: Maximum documents to return after deduplication

    Returns:
        AggregatedContext with deduplicated documents and attribution mapping
    """
    seen_chunks: dict[str, dict] = {}
    sub_question_mapping: dict[str, list[str]] = {}
    total_retrieved = 0

    for result in results:
        total_retrieved += len(result.documents)

        for doc in result.documents:
            chunk_id = doc.get("chunk_id")
            if not chunk_id:
                continue

            if chunk_id not in seen_chunks:
                # First time seeing this chunk
                seen_chunks[chunk_id] = doc.copy()
                sub_question_mapping[chunk_id] = [result.sub_question]
            else:
                # Document seen before - add sub-question attribution
                sub_question_mapping[chunk_id].append(result.sub_question)
                # Boost score for documents relevant to multiple sub-questions
                seen_chunks[chunk_id]["score"] += doc.get("score", 0.0) * 0.5

    # Sort by boosted score and take top K
    sorted_docs = sorted(
        seen_chunks.values(),
        key=lambda d: d.get("score", 0.0),
        reverse=True,
    )[:max_documents]

    # Filter mapping to only include documents in final result
    final_chunk_ids = {d.get("chunk_id") for d in sorted_docs}
    filtered_mapping = {
        chunk_id: subs
        for chunk_id, subs in sub_question_mapping.items()
        if chunk_id in final_chunk_ids
    }

    return AggregatedContext(
        documents=sorted_docs,
        sub_question_mapping=filtered_mapping,
        total_retrieved=total_retrieved,
        deduplicated_count=len(sorted_docs),
    )


async def multi_retrieval_node(state: "RAGState") -> "RAGState":
    """
    Retrieve context for all sub-questions in parallel.

    If no sub-questions are present, falls back to using the original query.
    Aggregates results with deduplication and score boosting for documents
    that appear across multiple sub-questions.

    Args:
        state: Current RAGState with query and optional sub_questions

    Returns:
        Updated RAGState with documents, context, sub_question_mapping, and retrieval_stats
    """
    with tracer.start_as_current_span(SpanNames.ORCHESTRATOR_RETRIEVAL) as span:
        start = time.time()

        timing = dict(state.get("timing", {}))
        fallbacks_used = list(state.get("fallbacks_used", []))

        config = get_config()
        query = state.get("query", "")
        tenant_id = state.get("tenant_id")
        options = state.get("options", {})

        # Get sub-questions, falling back to original query
        sub_questions = state.get("sub_questions", [])
        if not sub_questions:
            sub_questions = [query]

        # Set span attributes
        span.set_attribute("orchestrator.sub_questions_count", len(sub_questions))
        span.set_attribute("orchestrator.query_length", len(query) if query else 0)
        if tenant_id:
            span.set_attribute("orchestrator.tenant_id", tenant_id)

        # Configuration for parallel retrieval
        sub_question_top_k = options.get("sub_question_top_k", 10)
        max_total_documents = options.get("max_total_documents", 20)

        # Perform parallel retrieval for all sub-questions
        client = get_retrieval_client()
        tasks = [
            _retrieve_for_sub_question(
                client=client,
                sub_question=sq,
                tenant_id=tenant_id,
                top_k=sub_question_top_k,
            )
            for sq in sub_questions
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out exceptions and collect valid results
        sub_query_results: list[SubQueryResult] = []
        for sq, result in zip(sub_questions, results, strict=True):
            if isinstance(result, Exception):
                logger.warning(
                    "sub_query_retrieval_failed",
                    extra={"sub_question": sq[:50], "error": str(result)},
                )
                sub_query_results.append(SubQueryResult(sq, [], 0))
            else:
                sub_query_results.append(result)

        # Aggregate and deduplicate results
        aggregated = _aggregate_results(
            sub_query_results,
            max_documents=max_total_documents,
        )

        # Build context string from aggregated documents
        context = _format_multi_hop_context(
            aggregated.documents,
            aggregated.sub_question_mapping,
            sub_questions,
        )

        # Build retrieval stats
        retrieval_stats = {
            "sub_questions": len(sub_questions),
            "total_retrieved": aggregated.total_retrieved,
            "after_dedup": aggregated.deduplicated_count,
            "latency_ms": (time.time() - start) * 1000,
        }

        # Set span attributes for results
        span.set_attribute("orchestrator.documents_retrieved", len(aggregated.documents))
        span.set_attribute("orchestrator.total_before_dedup", aggregated.total_retrieved)
        span.set_attribute(
            "orchestrator.dedup_removed", aggregated.total_retrieved - aggregated.deduplicated_count
        )

        logger.info(
            "multi_retrieval_complete",
            extra={
                "sub_questions": len(sub_questions),
                "total_documents": len(aggregated.documents),
                "dedup_removed": aggregated.total_retrieved - aggregated.deduplicated_count,
            },
        )

        timing["multi_retrieval"] = (time.time() - start) * 1000

        return {
            **state,
            "documents": aggregated.documents,
            "context": context,
            "sub_question_mapping": aggregated.sub_question_mapping,
            "retrieval_stats": retrieval_stats,
            "timing": timing,
            "fallbacks_used": fallbacks_used,
        }


def _format_multi_hop_context(
    documents: list[dict],
    sub_question_mapping: dict[str, list[str]],
    sub_questions: list[str],
) -> str:
    """
    Format context with sub-question attribution.

    Groups documents by which sub-questions they answer, providing
    organized context for multi-hop reasoning.

    Args:
        documents: Deduplicated list of retrieved documents
        sub_question_mapping: Maps chunk_id to list of sub-questions
        sub_questions: List of all sub-questions

    Returns:
        Formatted context string organized by sub-question
    """
    if not documents:
        return ""

    # If only one sub-question (original query), use simple format
    if len(sub_questions) == 1:
        context_parts = []
        for i, doc in enumerate(documents, 1):
            content = doc.get("content", "")
            source = doc.get("source", doc.get("metadata", {}).get("source_uri", "unknown"))
            context_parts.append(f"[Document {i}: {source}]\n{content}")
        return "\n\n".join(context_parts)

    # Multi-hop format: group by sub-question
    context_parts = []

    for i, sq in enumerate(sub_questions, 1):
        # Find documents relevant to this sub-question
        sq_docs = [
            doc for doc in documents if sq in sub_question_mapping.get(doc.get("chunk_id", ""), [])
        ]

        if sq_docs:
            context_parts.append(f"\n### Context for Sub-question {i}: {sq}\n")
            for doc in sq_docs[:5]:  # Limit per sub-question
                content = doc.get("content", "")
                chunk_id = doc.get("chunk_id", "unknown")[:8]
                context_parts.append(f"[{chunk_id}] {content}")

    return "\n".join(context_parts)

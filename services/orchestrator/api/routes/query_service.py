"""Query orchestration service logic.

This module contains the business logic extracted from query route handlers:
- Document transformation
- Workflow execution (RAG pipeline and direct LLM fallback)
- Output guardrail processing
- Verification info building and persistence
- Quality metadata assembly
- Business metrics recording
- Token usage tracking
- Source reordering by citation usage
"""

import re
from typing import Any

import structlog
from api.models.responses import (
    QueryResponse,
    SourceDocument,
    UsageInfo,
    VerificationInfo,
)
from database.models.verification_log import VerificationLog
from observability.metrics_collector import QueryMetrics, metrics_collector
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def transform_documents(documents: list[dict[str, Any]]) -> list[SourceDocument]:
    """Transform raw documents to SourceDocument models.

    Args:
        documents: List of raw document dictionaries.

    Returns:
        List of SourceDocument models.
    """
    sources = []
    for doc in documents:
        sources.append(
            SourceDocument(
                id=doc.get("id", doc.get("chunk_id", "")),
                title=doc.get("metadata", {}).get("title") or doc.get("title"),
                uri=doc.get("source") or doc.get("uri"),
                score=doc.get("score"),
                snippet=doc.get("content", "")[:200] if doc.get("content") else None,
            ),
        )
    return sources


def reorder_sources_by_citations(
    response_text: str,
    documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Reorder documents so that cited sources appear first.

    Parses [N] citation markers from the LLM response and moves cited
    documents to the front of the list (in order of first citation),
    followed by uncited documents in their original order.

    Args:
        response_text: The generated LLM response text.
        documents: List of raw document dictionaries in retrieval order.

    Returns:
        Reordered list of documents with cited ones first.
    """
    if not documents or not response_text:
        return documents

    # Parse all [N] citations from response text
    citation_matches = re.findall(r"\[(\d+)\]", response_text)
    # Convert to 0-indexed, deduplicate while preserving first-occurrence order
    seen: set[int] = set()
    cited_indices: list[int] = []
    for match in citation_matches:
        idx = int(match) - 1  # Convert 1-indexed to 0-indexed
        if 0 <= idx < len(documents) and idx not in seen:
            seen.add(idx)
            cited_indices.append(idx)

    if not cited_indices:
        return documents

    # Build reordered list: cited first, then uncited in original order
    reordered = [documents[i] for i in cited_indices]
    for i, doc in enumerate(documents):
        if i not in seen:
            reordered.append(doc)

    return reordered


async def execute_workflow(
    workflow: Any,
    request_id: str,
    query: str,
    session_id: str | None,
    user_id: str | None,
    tenant_id: str | None,
    options: dict[str, Any] | None,
    answer_cache: Any | None = None,
    model_gateway: Any | None = None,
) -> dict[str, Any]:
    """Execute the RAG workflow pipeline.

    Args:
        workflow: The compiled LangGraph workflow.
        request_id: Unique request identifier.
        query: The user's query string.
        session_id: Optional session identifier.
        user_id: Optional user identifier.
        tenant_id: Optional tenant identifier.
        options: Optional query options.
        answer_cache: Optional server-managed AnswerCache instance.
        model_gateway: Optional shared ModelGateway instance for
            connection reuse in workflow nodes (e.g. verification).

    Returns:
        Dictionary with workflow results including response, documents,
        model_used, usage, strategy_used, verification_result, and
        quality metadata.
    """
    # Merge server-managed resources into workflow options
    merged_options = dict(options or {})
    if answer_cache is not None:
        merged_options.setdefault("answer_cache", answer_cache)
        merged_options.setdefault("enable_answer_cache", True)
    if model_gateway is not None:
        merged_options["model_gateway"] = model_gateway

    result = await workflow.ainvoke(
        {
            "request_id": request_id,
            "query": query,
            "session_id": session_id,
            "user_id": user_id,
            "tenant_id": tenant_id,
            "options": merged_options,
        },
    )

    documents = result.get("documents", [])
    return {
        "response_text": result.get("response") or "",
        "documents": documents,
        "model_used": result.get("model_used", "unknown"),
        "usage": result.get("usage", {}),
        "strategy_used": result.get("strategy_used"),
        "verification_result": result.get("verification_result"),
        "retrieval_quality": result.get("retrieval_quality", {}),
        "context_quality": result.get("context_quality", "full"),
        "fallbacks_used": result.get("fallbacks_used", []),
        "component_timings": result.get("timing", {}),
        "context_relevance_score": documents[0].get("score") if documents else None,
    }


async def execute_direct_llm(
    model_gateway: Any,
    query: str,
) -> dict[str, Any]:
    """Execute a direct LLM call without retrieval.

    Args:
        model_gateway: The model gateway client.
        query: The user's query string.

    Returns:
        Dictionary with LLM results in the same format as execute_workflow.
    """
    from gateway import ChatCompletionRequest, ChatMessage

    chat_request = ChatCompletionRequest(
        model=model_gateway.default_model,
        messages=[ChatMessage(role="user", content=query)],
    )
    llm_response = await model_gateway.chat_completion(chat_request)

    return {
        "response_text": llm_response.choices[0].message.content,
        "documents": [],
        "model_used": llm_response.model,
        "usage": {
            "prompt_tokens": llm_response.usage.prompt_tokens,
            "completion_tokens": llm_response.usage.completion_tokens,
            "total_tokens": llm_response.usage.total_tokens,
        },
        "strategy_used": "direct",
        "verification_result": None,
        "retrieval_quality": {},
        "context_quality": "full",
        "fallbacks_used": [],
        "component_timings": {},
        "context_relevance_score": None,
    }


async def build_verification_info(
    verification_result: dict[str, Any] | None,
    request_id: str,
    tenant_id: str | None,
    db: AsyncSession,
) -> VerificationInfo | None:
    """Build verification info and persist verification log.

    Args:
        verification_result: Raw verification result dictionary.
        request_id: The request identifier for correlation.
        tenant_id: Optional tenant identifier.
        db: Database session.

    Returns:
        VerificationInfo if verification_result is provided, None otherwise.
    """
    if not verification_result:
        return None

    verification_info = VerificationInfo(
        score=verification_result.get("score", 1.0),
        label=verification_result.get("label", "skipped"),
        claims_total=verification_result.get("claims_total", 0),
        claims_supported=verification_result.get("claims_supported", 0),
        claims_partial=verification_result.get("claims_partial", 0),
        claims_unsupported=verification_result.get("claims_unsupported", 0),
        verification_time_ms=verification_result.get("verification_time_ms", 0.0),
        skipped=verification_result.get("skipped", True),
        skip_reason=verification_result.get("skip_reason"),
    )

    # Store verification log for correlation analysis (US-10.4.2)
    verification_log = VerificationLog(
        request_id=request_id,
        tenant_id=tenant_id,
        score=verification_result.get("score", 1.0),
        label=verification_result.get("label", "skipped"),
        claims_total=verification_result.get("claims_total", 0),
        claims_supported=verification_result.get("claims_supported", 0),
        claims_partial=verification_result.get("claims_partial", 0),
        claims_unsupported=verification_result.get("claims_unsupported", 0),
        verification_time_ms=verification_result.get("verification_time_ms", 0.0),
    )
    db.add(verification_log)
    await db.commit()

    return verification_info


def build_components_available(
    retrieval_quality: dict[str, Any],
) -> dict[str, bool] | None:
    """Build components_available map from retrieval quality metadata.

    Args:
        retrieval_quality: Retrieval quality information dictionary.

    Returns:
        Dictionary mapping component names to availability booleans,
        or None if no components information is available.
    """
    if not retrieval_quality:
        return None

    components_used = retrieval_quality.get("components_used", [])
    components_skipped = retrieval_quality.get("components_skipped", [])
    all_components = set(components_used) | set(components_skipped)

    if not all_components:
        return None

    return {comp: comp in components_used for comp in all_components}


def record_query_metrics(
    request_id: str,
    tenant_id: str | None,
    options: dict[str, Any] | None,
    strategy_used: str | None,
    retrieval_quality: dict[str, Any],
    context_quality: str,
    fallbacks_used: list[str],
    component_timings: dict[str, Any],
    context_relevance_score: float | None,
    documents: list[dict[str, Any]],
    latency_ms: float,
) -> None:
    """Record business metrics for a query (US-10.3.3).

    Args:
        request_id: Unique request identifier.
        tenant_id: Optional tenant identifier.
        options: Query options containing tenant_tier.
        strategy_used: The strategy used for the query.
        retrieval_quality: Retrieval quality information.
        context_quality: Quality level of context.
        fallbacks_used: List of fallback strategies used.
        component_timings: Timing information per component.
        context_relevance_score: Top document relevance score.
        documents: Retrieved documents.
        latency_ms: End-to-end latency in milliseconds.
    """
    is_degraded = context_quality != "full"
    metrics_collector.record_query(
        QueryMetrics(
            request_id=request_id,
            tenant_id=tenant_id,
            tenant_tier=options.get("tenant_tier", "standard") if options else "standard",
            strategy=strategy_used or "direct",
            rag_used=strategy_used != "direct",
            degraded=is_degraded,
            degradation_mode=retrieval_quality.get("mode") if is_degraded else None,
            fallbacks_used=fallbacks_used,
            e2e_latency_ms=latency_ms,
            component_timings=component_timings,
            context_relevance_score=context_relevance_score,
            citation_count=len(documents),
            status="success",
        )
    )


async def record_token_usage(
    usage_tracker: Any,
    tenant_id: str | None,
    model_used: str,
    usage: dict[str, int],
) -> None:
    """Record token usage for quota tracking (US-10.5.4).

    Args:
        usage_tracker: Token usage tracker instance.
        tenant_id: Tenant identifier.
        model_used: Model that was used.
        usage: Usage statistics dictionary.
    """
    if usage_tracker and tenant_id:
        await usage_tracker.record_llm_usage(
            tenant_id=tenant_id,
            model=model_used,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )


def build_query_response(
    request_id: str,
    response_text: str,
    documents: list[dict[str, Any]],
    session_id: Any,
    model_used: str,
    usage: dict[str, int],
    latency_ms: float,
    strategy_used: str | None,
    verification_info: VerificationInfo | None,
    retrieval_quality: dict[str, Any],
    context_quality: str,
    components_available: dict[str, bool] | None,
    fallbacks_used: list[str],
) -> QueryResponse:
    """Build the final QueryResponse object.

    Args:
        request_id: Unique request identifier.
        response_text: The generated response text.
        documents: Retrieved source documents.
        session_id: Optional session identifier.
        model_used: Model identifier used.
        usage: Token usage statistics.
        latency_ms: End-to-end latency.
        strategy_used: Strategy used for the query.
        verification_info: Verification information.
        retrieval_quality: Retrieval quality metadata.
        context_quality: Quality level of context.
        components_available: Component availability map.
        fallbacks_used: List of fallback strategies used.

    Returns:
        Assembled QueryResponse.
    """
    return QueryResponse(
        request_id=request_id,
        response=response_text,
        sources=transform_documents(documents),
        session_id=session_id,
        model=model_used,
        usage=UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ),
        latency_ms=round(latency_ms, 2),
        strategy_used=strategy_used,
        verification=verification_info,
        retrieval_mode=retrieval_quality.get("mode") if retrieval_quality else None,
        context_quality=context_quality,
        components_available=components_available,
        fallbacks_used=fallbacks_used,
    )

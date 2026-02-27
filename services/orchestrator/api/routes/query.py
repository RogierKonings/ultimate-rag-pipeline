"""Query endpoints for the Orchestrator Service.

This module provides endpoints for RAG queries:
- POST /api/v1/query - Synchronous RAG query
- POST /api/v1/query/stream - Streaming RAG query (SSE)
- POST /api/v1/feedback - Submit user feedback

Route handlers are kept thin; orchestration logic lives in query_service.
"""

import time
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Any

import structlog
from api.dependencies import (
    GuardrailPipelineDep,
    ModelGatewayDep,
    SessionManagerDep,
    StreamManagerDep,
    UsageTrackerDep,
)
from api.models.requests import FeedbackRequest, QueryRequest, StreamQueryRequest
from api.models.responses import (
    ErrorResponse,
    FeedbackResponse,
    QueryResponse,
    SourceDocument,
)
from database.connection import get_db
from database.models.feedback import QueryFeedback
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from model_policy import select_generation_model
from observability.business_metrics import rag_feedback_total
from retrieval.policy import coerce_positive_int, get_retrieval_option, should_enable_rerank
from routing import QueryRouter
from sqlalchemy.ext.asyncio import AsyncSession
from workflow.nodes.retrieval import _format_context

from config import get_config

from . import query_service

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Query"])
_stream_query_router = QueryRouter()

# Type alias for database session dependency
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]


# Re-export for backward compatibility (used by tests)
def _transform_documents(documents: list[dict[str, Any]]) -> list[SourceDocument]:
    """Transform raw documents to SourceDocument models.

    Args:
        documents: List of raw document dictionaries.

    Returns:
        List of SourceDocument models.
    """
    return query_service.transform_documents(documents)


@router.post(
    "/query",
    response_model=QueryResponse,
    summary="Synchronous RAG query",
    description="Submit a query and receive a complete response with sources.",
    responses={
        200: {"description": "Query processed successfully"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        422: {"model": ErrorResponse, "description": "Validation error"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
)
async def query(
    request: Request,
    query_request: QueryRequest,
    session_manager: SessionManagerDep,
    guardrail_pipeline: GuardrailPipelineDep,
    model_gateway: ModelGatewayDep,
    db: DbSessionDep,
    usage_tracker: UsageTrackerDep,
) -> QueryResponse:
    """Process a synchronous RAG query.

    This endpoint:
    1. Checks quota limits (if enabled)
    2. Validates input through guardrails
    3. Retrieves relevant documents
    4. Generates a response with the LLM
    5. Validates output through guardrails
    6. Records token usage
    7. Returns the response with sources

    Args:
        request: The FastAPI request object.
        query_request: The query request payload.
        session_manager: Injected session manager.
        guardrail_pipeline: Injected guardrail pipeline.
        model_gateway: Injected model gateway.
        db: Database session.
        usage_tracker: Token usage tracker (US-10.5.4).

    Returns:
        QueryResponse with generated answer and sources.

    Raises:
        HTTPException: On validation failure, quota exceeded, or processing error.
    """
    request_id = str(uuid.uuid4())
    start_time = time.perf_counter()
    tenant_id = str(query_request.tenant_id) if query_request.tenant_id else None

    # Check quota before processing (US-10.5.4)
    if usage_tracker and tenant_id:
        allowed, remaining = await usage_tracker.check_quota(tenant_id)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Quota exceeded",
                    "tenant_id": tenant_id,
                    "remaining_tokens": remaining,
                    "request_id": request_id,
                },
                headers={"Retry-After": "3600"},
            )

    # Check input guardrails
    input_result = await guardrail_pipeline.check_input(query_request.query)
    if not input_result.passed:
        violations = [v.description for v in input_result.violations]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Input validation failed",
                "violations": violations,
                "request_id": request_id,
            },
        )

    # Execute query via workflow or direct LLM
    workflow = getattr(request.app.state, "workflow", None)

    if workflow is not None:
        try:
            answer_cache = getattr(request.app.state, "answer_cache", None)
            result = await query_service.execute_workflow(
                workflow=workflow,
                request_id=request_id,
                query=query_request.query,
                session_id=str(query_request.session_id) if query_request.session_id else None,
                user_id=str(query_request.user_id) if query_request.user_id else None,
                tenant_id=str(query_request.tenant_id) if query_request.tenant_id else None,
                options=query_request.options.model_dump(exclude_none=True) if query_request.options else None,
                answer_cache=answer_cache,
                model_gateway=model_gateway,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "Workflow execution failed",
                    "message": str(e),
                    "request_id": request_id,
                },
            ) from e
    else:
        try:
            result = await query_service.execute_direct_llm(
                model_gateway=model_gateway,
                query=query_request.query,
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "LLM request failed",
                    "message": str(e),
                    "request_id": request_id,
                },
            ) from e

    response_text = result["response_text"]
    documents = result["documents"]
    model_used = result["model_used"]
    usage = result["usage"]
    strategy_used = result["strategy_used"]
    verification_result = result["verification_result"]
    retrieval_quality = result["retrieval_quality"]
    context_quality = result["context_quality"]
    fallbacks_used = result["fallbacks_used"]
    component_timings = result["component_timings"]
    context_relevance_score = result["context_relevance_score"]

    # Check output guardrails
    output_result = await guardrail_pipeline.check_output(response_text)
    if not output_result.passed:
        response_text = guardrail_pipeline.sanitize_output(response_text)

    latency_ms = (time.perf_counter() - start_time) * 1000

    # Build verification info and persist log
    verification_info = await query_service.build_verification_info(
        verification_result=verification_result,
        request_id=request_id,
        tenant_id=tenant_id,
        db=db,
    )

    # Build components_available from retrieval_quality (US-10.2.2)
    components_available = query_service.build_components_available(retrieval_quality)

    # Record business metrics (US-10.3.3)
    options_dict = query_request.options.model_dump(exclude_none=True) if query_request.options else None
    query_service.record_query_metrics(
        request_id=request_id,
        tenant_id=tenant_id,
        options=options_dict,
        strategy_used=strategy_used,
        retrieval_quality=retrieval_quality,
        context_quality=context_quality,
        fallbacks_used=fallbacks_used,
        component_timings=component_timings,
        context_relevance_score=context_relevance_score,
        documents=documents,
        latency_ms=latency_ms,
    )

    # Record token usage (US-10.5.4)
    await query_service.record_token_usage(
        usage_tracker=usage_tracker,
        tenant_id=tenant_id,
        model_used=model_used,
        usage=usage,
    )

    return query_service.build_query_response(
        request_id=request_id,
        response_text=response_text,
        documents=documents,
        session_id=query_request.session_id,
        model_used=model_used,
        usage=usage,
        latency_ms=latency_ms,
        strategy_used=strategy_used,
        verification_info=verification_info,
        retrieval_quality=retrieval_quality,
        context_quality=context_quality,
        components_available=components_available,
        fallbacks_used=fallbacks_used,
    )


@router.post(
    "/query/stream",
    summary="Streaming RAG query",
    description="Submit a query and receive a streaming response via Server-Sent Events.",
    responses={
        200: {
            "description": "Streaming response started",
            "content": {"text/event-stream": {}},
        },
        400: {"model": ErrorResponse, "description": "Invalid request"},
        503: {"model": ErrorResponse, "description": "Service unavailable"},
    },
)
async def query_stream(
    request: Request,
    query_request: StreamQueryRequest,
    session_manager: SessionManagerDep,
    guardrail_pipeline: GuardrailPipelineDep,
    stream_manager: StreamManagerDep,
    model_gateway: ModelGatewayDep,
) -> StreamingResponse:
    """Process a streaming RAG query.

    This endpoint returns a Server-Sent Events stream with:
    - START event: Stream metadata
    - DELTA events: Token chunks
    - CITATIONS event: Source documents
    - DONE event: Completion with usage stats
    - ERROR event: On failure

    Args:
        request: The FastAPI request object.
        query_request: The streaming query request payload.
        session_manager: Injected session manager.
        guardrail_pipeline: Injected guardrail pipeline.
        stream_manager: Injected stream manager.
        model_gateway: Injected model gateway.

    Returns:
        StreamingResponse with SSE content.

    Raises:
        HTTPException: On input validation failure.
    """
    request_id = str(uuid.uuid4())

    # Check input guardrails before streaming
    input_result = await guardrail_pipeline.check_input(query_request.query)
    if not input_result.passed:
        violations = [v.description for v in input_result.violations]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Input validation failed",
                "violations": violations,
                "request_id": request_id,
            },
        )

    async def generate_stream() -> AsyncGenerator[str, None]:
        """Generate SSE stream."""
        options = query_request.options.model_dump(exclude_none=True) if query_request.options else {}
        stage_models = options.get("stage_models", {})

        # Infer strategy/intent for stream model selection, unless explicitly provided.
        stream_strategy = options.get("strategy", "simple")
        stream_intent = options.get("intent")
        try:
            routing_result = await _stream_query_router.route(query_request.query)
            if "strategy" not in options:
                stream_strategy = routing_result.strategy.value
            if "intent" not in options:
                stream_intent = routing_result.intent.value.upper()
        except Exception as exc:
            logger.warning(
                "stream_query_routing_failed",
                request_id=request_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

        # Get retrieval client for documents (if available)
        retrieval_client = getattr(request.app.state, "retrieval_client", None)
        documents = []
        degradation = None
        retrieval_quality = None

        if retrieval_client is not None:
            try:
                tenant_id = str(query_request.tenant_id) if query_request.tenant_id else None
                retrieval_mode = str(
                    get_retrieval_option(
                        options,
                        key="mode",
                        default="hybrid",
                        legacy_key="retrieval_mode",
                    )
                    or "hybrid"
                )
                rerank_enabled = should_enable_rerank(
                    strategy=stream_strategy,
                    intent=stream_intent,
                    rerank_override=get_retrieval_option(options, key="rerank", default=None),
                )
                top_k_value = get_retrieval_option(options, key="top_k", default=None)
                top_k = (
                    coerce_positive_int(top_k_value, get_config().retrieval_top_k)
                    if top_k_value is not None
                    else None
                )
                retrieval_result = await retrieval_client.search(
                    query_request.query,
                    tenant_id=tenant_id,
                    top_k=top_k,
                    mode=retrieval_mode,
                    rerank=rerank_enabled,
                )
                # Handle both old format (list) and new format (dict with documents)
                if isinstance(retrieval_result, dict):
                    documents = retrieval_result.get("documents", [])
                    # Extract degradation info (US-10.2.2)
                    degradation_mode = retrieval_result.get("degradation_mode", "hybrid_full")
                    components_used = retrieval_result.get("components_used", [])
                    components_skipped = retrieval_result.get("components_skipped", [])

                    # Build retrieval_quality
                    if degradation_mode == "hybrid_full":
                        degradation_level = "normal"
                    elif degradation_mode == "minimal":
                        degradation_level = "minimal"
                    else:
                        degradation_level = "degraded"

                    retrieval_quality = {
                        "degradation_level": degradation_level,
                        "mode": degradation_mode,
                        "components_used": components_used,
                        "components_skipped": components_skipped,
                    }

                    # Build degradation info for start event (only if degraded)
                    if degradation_level != "normal":
                        mode_messages = {
                            "semantic_only": "Keyword search unavailable",
                            "keyword_only": "Semantic search unavailable",
                            "rerank_skipped": "Reranking unavailable",
                            "partial_queries_failed": "Some query expansions failed",
                            "minimal": "Search capabilities significantly limited",
                        }
                        degradation = {
                            "level": degradation_level,
                            "mode": degradation_mode,
                            "message": mode_messages.get(
                                degradation_mode, "Search running in degraded mode"
                            ),
                        }
                else:
                    # Old format: just a list of documents
                    documents = retrieval_result
            except Exception as exc:
                # Continue without documents on retrieval failure, but log
                # the specific reason so operators can diagnose issues.
                logger.warning(
                    "stream_retrieval_failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    request_id=request_id,
                    query_length=len(query_request.query),
                )

        # Build messages for LLM
        messages = [{"role": "user", "content": query_request.query}]

        # If we have documents, add context (with budget limits)
        if documents:
            context = _format_context(documents)

            context_message = (
                "You are a helpful assistant that answers questions based on the provided documents. "
                "When comparing values (amounts, dates, quantities), carefully extract the relevant "
                "value from EACH document before making comparisons. "
                "ALWAYS cite sources using bracket notation like [1], [2], etc. matching the document numbers. "
                "Place citations inline immediately after the relevant claim, e.g. 'The total was €500 [3].'\n\n"
                f"Documents:\n\n{context}"
            )
            messages.insert(0, {"role": "system", "content": context_message})

        # Stream response from LLM (with degradation info if present - US-10.2.2)
        config = get_config()
        model_selection = select_generation_model(
            config=config,
            tenant_tier=options.get("tenant_tier", "standard"),
            strategy=stream_strategy,
            intent=stream_intent,
            model_override=stage_models.get("streaming") or options.get("model"),
        )
        async for event in stream_manager.stream_response(
            request_id=request_id,
            model=model_selection.model,
            messages=messages,
            session_id=str(query_request.session_id) if query_request.session_id else None,
            documents=documents,
            gateway=model_gateway,
            degradation=degradation,
            retrieval_quality=retrieval_quality,
        ):
            yield event.to_sse()

    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Request-ID": request_id,
        },
    )


def _rating_to_label(rating: int) -> str:
    """Convert numeric rating (1-5) to feedback label.

    Args:
        rating: User rating from 1 to 5.

    Returns:
        Label: "positive" (4-5), "neutral" (3), or "negative" (1-2).
    """
    if rating >= 4:
        return "positive"
    if rating == 3:
        return "neutral"
    return "negative"


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    summary="Submit user feedback",
    description="Submit feedback for a previous query response.",
    responses={
        200: {"description": "Feedback recorded"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
    },
)
async def submit_feedback(
    feedback_request: FeedbackRequest,
    db: DbSessionDep,
    request: Request,
) -> FeedbackResponse:
    """Submit user feedback for a query response.

    This endpoint records user feedback which can be used for:
    - Quality monitoring
    - Model fine-tuning
    - Retrieval improvement

    Args:
        feedback_request: The feedback request payload.
        db: Database session for storing feedback.
        request: The FastAPI request object.

    Returns:
        FeedbackResponse confirming the feedback was recorded.
    """
    feedback_id = uuid.uuid4()

    # Get tenant_id from request context if available
    tenant_id = getattr(request.state, "tenant_id", None)

    # Store feedback in database (US-10.3.3)
    feedback_record = QueryFeedback(
        id=feedback_id,
        request_id=feedback_request.request_id,
        tenant_id=tenant_id,
        rating=feedback_request.rating,
        feedback_type=feedback_request.feedback_type,
        comment=feedback_request.comment,
        session_id=str(feedback_request.session_id) if feedback_request.session_id else None,
    )
    db.add(feedback_record)
    await db.commit()

    # Record Prometheus metrics (US-10.3.3)
    rating_label = _rating_to_label(feedback_request.rating)
    rag_feedback_total.labels(
        rating=rating_label,
        tenant_id=tenant_id or "anonymous",
    ).inc()

    logger.info(
        "feedback_recorded",
        feedback_id=str(feedback_id),
        request_id=feedback_request.request_id,
        rating=feedback_request.rating,
        rating_label=rating_label,
        tenant_id=tenant_id,
    )

    return FeedbackResponse(
        success=True,
        message="Feedback recorded successfully",
        feedback_id=str(feedback_id),
    )

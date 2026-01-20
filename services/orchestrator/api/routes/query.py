"""Query endpoints for the Orchestrator Service.

This module provides endpoints for RAG queries:
- POST /api/v1/query - Synchronous RAG query
- POST /api/v1/query/stream - Streaming RAG query (SSE)
- POST /api/v1/feedback - Submit user feedback
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
    UsageInfo,
    VerificationInfo,
)
from database.connection import get_db
from database.models.feedback import QueryFeedback
from database.models.verification_log import VerificationLog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from observability.business_metrics import rag_feedback_total
from observability.metrics_collector import QueryMetrics, metrics_collector
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Query"])

# Type alias for database session dependency
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]


def _transform_documents(documents: list[dict[str, Any]]) -> list[SourceDocument]:
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

    # Get workflow from app state
    workflow = getattr(request.app.state, "workflow", None)

    if workflow is not None:
        # Use the workflow for full RAG pipeline
        try:
            result = await workflow.ainvoke(
                {
                    "request_id": request_id,
                    "query": query_request.query,
                    "session_id": str(query_request.session_id)
                    if query_request.session_id
                    else None,
                    "user_id": str(query_request.user_id) if query_request.user_id else None,
                    "tenant_id": str(query_request.tenant_id) if query_request.tenant_id else None,
                    "options": query_request.options or {},
                },
            )

            response_text = result.get("response") or ""
            documents = result.get("documents", [])
            model_used = result.get("model_used", "unknown")
            usage = result.get("usage", {})
            strategy_used = result.get("strategy_used")
            verification_result = result.get("verification_result")
            # Quality metadata (US-10.2.2)
            retrieval_quality = result.get("retrieval_quality", {})
            context_quality = result.get("context_quality", "full")
            fallbacks_used = result.get("fallbacks_used", [])

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
        # Fallback: Direct LLM call without retrieval
        from gateway import ChatCompletionRequest, ChatMessage

        try:
            # Use the gateway's default model from config
            chat_request = ChatCompletionRequest(
                model=model_gateway.default_model,
                messages=[ChatMessage(role="user", content=query_request.query)],
            )
            llm_response = await model_gateway.chat_completion(chat_request)
            response_text = llm_response.choices[0].message.content
            documents = []
            model_used = llm_response.model
            usage = {
                "prompt_tokens": llm_response.usage.prompt_tokens,
                "completion_tokens": llm_response.usage.completion_tokens,
                "total_tokens": llm_response.usage.total_tokens,
            }
            strategy_used = "direct"
            verification_result = None  # No verification in direct mode
            # Quality metadata defaults for direct mode (US-10.2.2)
            retrieval_quality = {}
            context_quality = "full"  # No retrieval = no degradation
            fallbacks_used = []
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "LLM request failed",
                    "message": str(e),
                    "request_id": request_id,
                },
            ) from e

    # Check output guardrails
    output_result = await guardrail_pipeline.check_output(response_text)
    if not output_result.passed:
        # Sanitize the response instead of failing
        response_text = guardrail_pipeline.sanitize_output(response_text)

    latency_ms = (time.perf_counter() - start_time) * 1000

    # Build verification info if available
    verification_info = None
    if verification_result:
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
            tenant_id=str(query_request.tenant_id) if query_request.tenant_id else None,
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

    # Build components_available from retrieval_quality (US-10.2.2)
    components_available = None
    if retrieval_quality:
        components_used = retrieval_quality.get("components_used", [])
        components_skipped = retrieval_quality.get("components_skipped", [])
        all_components = set(components_used) | set(components_skipped)
        if all_components:
            components_available = {comp: comp in components_used for comp in all_components}

    # Record business metrics (US-10.3.3)
    is_degraded = context_quality != "full"
    metrics_collector.record_query(
        QueryMetrics(
            request_id=request_id,
            tenant_id=tenant_id,
            tenant_tier="standard",  # TODO: Get from tenant config
            strategy=strategy_used or "direct",
            rag_used=strategy_used != "direct",
            degraded=is_degraded,
            degradation_mode=retrieval_quality.get("mode") if is_degraded else None,
            fallbacks_used=fallbacks_used,
            e2e_latency_ms=latency_ms,
            component_timings={},  # TODO: Collect from workflow state
            context_relevance_score=None,  # TODO: Get from reranker scores
            citation_count=len(documents),
            status="success",
        )
    )

    # Record token usage (US-10.5.4)
    if usage_tracker and tenant_id:
        await usage_tracker.record_llm_usage(
            tenant_id=tenant_id,
            model=model_used,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    return QueryResponse(
        request_id=request_id,
        response=response_text,
        sources=_transform_documents(documents),
        session_id=query_request.session_id,
        model=model_used,
        usage=UsageInfo(
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        ),
        latency_ms=round(latency_ms, 2),
        strategy_used=strategy_used,
        verification=verification_info,
        # Quality metadata (US-10.2.2)
        retrieval_mode=retrieval_quality.get("mode") if retrieval_quality else None,
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
        # Get retrieval client for documents (if available)
        retrieval_client = getattr(request.app.state, "retrieval_client", None)
        documents = []
        degradation = None
        retrieval_quality = None

        if retrieval_client is not None:
            try:
                retrieval_result = await retrieval_client.search(query_request.query)
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
                            "hybrid_no_rerank": "Reranking unavailable",
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
            except Exception:  # noqa: S110
                # Continue without documents on retrieval failure
                pass

        # Build messages for LLM
        messages = [{"role": "user", "content": query_request.query}]

        # If we have documents, add context
        if documents:
            context = "\n\n".join(
                [f"[{i + 1}] {doc.get('content', '')}" for i, doc in enumerate(documents)],
            )
            context_message = f"Use the following context to answer the question:\n\n{context}"
            messages.insert(0, {"role": "system", "content": context_message})

        # Stream response from LLM (with degradation info if present - US-10.2.2)
        async for event in stream_manager.stream_response(
            request_id=request_id,
            model="meta-llama/Llama-3.1-8B-Instruct",
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

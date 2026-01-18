"""Retrieval endpoints for the Retrieval Service."""

import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from acl.filter import ACLFilter
from acl.safety_net import ACLSafetyNet
from fastapi import APIRouter, HTTPException, Request, status
from observability.metrics import record_retrieval_metrics
from query.preprocessor import QueryPreprocessor
from reranking.reranker import RerankerService
from resilience.degradation import get_degradation_manager
from search.fusion import HybridSearchConfig
from search.hybrid import HybridSearcher
from tier_config import get_effective_params

from api.dependencies import UserContextDep
from api.schemas.retrieve import (
    DebugInfo,
    ExplainResponse,
    MultiQueryRequest,
    RetrievedDocument,
    RetrieveRequest,
    RetrieveResponse,
    SearchMetrics,
    SearchMode,
)

router = APIRouter()


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve(
    request: Request,
    body: RetrieveRequest,
    user: UserContextDep,
) -> RetrieveResponse:
    """
    Retrieve relevant documents for a query.

    Performs hybrid search (semantic + keyword) with ACL filtering
    and optional reranking.

    **Search Modes:**
    - `hybrid`: Combines semantic and keyword search (default)
    - `semantic`: Vector similarity search only
    - `keyword`: BM25 keyword search only

    **Reranking:**
    When enabled, top results are reranked using a cross-encoder
    model for improved relevance ordering.

    **Filters:**
    Additional filters can be applied to narrow results by metadata
    (e.g., source_type, date range, custom fields).
    """
    start_time = time.time()
    query_id = uuid4()

    # Get components from app state
    preprocessor: QueryPreprocessor = request.app.state.preprocessor
    hybrid: HybridSearcher = request.app.state.hybrid
    reranker: RerankerService = request.app.state.reranker
    acl_filter: ACLFilter = request.app.state.acl_filter

    # Build ACL filter
    filters = acl_filter.build_filter(user, body.filters)

    # Preprocess query
    preprocess_start = time.time()
    processed = await preprocessor.process(body.query)
    preprocess_time = (time.time() - preprocess_start) * 1000

    # Get dynamic parameters based on tenant tier and query type (US-10.5.1)
    dynamic_params = get_effective_params(
        tenant_tier=user.tier.value,
        query_type=processed.query_type.value,
    )

    # Record metrics for top_k used
    record_retrieval_metrics(
        tier=dynamic_params.tenant_tier,
        query_type=dynamic_params.query_type,
        semantic_top_k=dynamic_params.semantic_top_k,
        keyword_top_k=dynamic_params.keyword_top_k,
        use_reranker=dynamic_params.use_reranker,
    )

    # Execute search based on mode
    semantic_time = None
    keyword_time = None
    fusion_time = None
    semantic_count = 0
    keyword_count = 0
    fused_count = 0

    if body.mode == SearchMode.HYBRID:
        # Update hybrid config with request weights and dynamic top_k (US-10.5.1)
        config = HybridSearchConfig(
            semantic_weight=body.semantic_weight,
            keyword_weight=body.keyword_weight,
            semantic_top_k=dynamic_params.semantic_top_k,
            keyword_top_k=dynamic_params.keyword_top_k,
            top_k=body.rerank_top_k if body.rerank else body.top_k,
        )

        search_start = time.time()
        search_response = await hybrid.search(
            query=body.query,
            query_embedding=processed.embedding,
            filters=filters,
            config=config,
        )
        search_time = (time.time() - search_start) * 1000

        semantic_count = search_response.total_semantic
        keyword_count = search_response.total_keyword
        fused_count = len(search_response.results)
        fusion_time = search_time

    elif body.mode == SearchMode.SEMANTIC:
        search_start = time.time()
        search_response = await hybrid.search_semantic_only(
            query_embedding=processed.embedding,
            top_k=body.rerank_top_k if body.rerank else body.top_k,
            filters=filters,
        )
        semantic_time = (time.time() - search_start) * 1000

        semantic_count = search_response.total_semantic
        keyword_count = 0
        fused_count = len(search_response.results)

    else:  # KEYWORD
        search_start = time.time()
        search_response = await hybrid.search_keyword_only(
            query=body.query,
            top_k=body.rerank_top_k if body.rerank else body.top_k,
            filters=filters,
        )
        keyword_time = (time.time() - search_start) * 1000

        semantic_count = 0
        keyword_count = search_response.total_keyword
        fused_count = len(search_response.results)

    # Rerank if enabled (based on dynamic params or explicit request)
    rerank_time = None
    results = search_response.results
    reranker_used = False

    # Use dynamic reranker decision if not explicitly overridden by request
    should_rerank = body.rerank or (dynamic_params.use_reranker and not body.rerank)

    if should_rerank and results:
        rerank_start = time.time()
        results = await reranker.rerank_fused_results(
            query=body.query,
            fused_results=results,
            top_k=dynamic_params.rerank_top_k if dynamic_params.use_reranker else body.top_k,
        )
        rerank_time = (time.time() - rerank_start) * 1000
        reranker_used = True

    # Apply ACL safety net (defense in depth)
    # This should filter nothing if query-level ACL is correct
    safety_net: ACLSafetyNet = request.app.state.safety_net
    pre_safety_count = len(results)
    results = safety_net.filter(results, user)
    _safety_net_filtered = pre_safety_count - len(results)  # noqa: F841 - tracked for future debug metrics

    # Apply score threshold
    if body.min_score > 0:
        results = [r for r in results if r.fused_score >= body.min_score]

    # Limit to top_k
    results = results[: body.top_k]

    # Convert to response format
    response_results = _convert_to_response_documents(
        results,
        body.include_metadata,
        body.include_highlights,
    )

    total_time = (time.time() - start_time) * 1000

    # Get degradation status (US-10.2.2)
    degradation_manager = get_degradation_manager()
    degradation_status = degradation_manager.get_status()

    return RetrieveResponse(
        results=response_results,
        total_results=len(response_results),
        query=body.query,
        mode=body.mode,
        metrics=SearchMetrics(
            query_preprocessing_ms=preprocess_time,
            embedding_ms=processed.processing_time_ms,
            semantic_search_ms=semantic_time,
            keyword_search_ms=keyword_time,
            fusion_ms=fusion_time,
            rerank_ms=rerank_time,
            total_ms=total_time,
            semantic_results_count=semantic_count,
            keyword_results_count=keyword_count,
            fused_results_count=fused_count,
            final_results_count=len(response_results),
        ),
        query_id=query_id,
        processed_at=datetime.now(tz=UTC),
        # Debug info with effective parameters (US-10.5.1)
        debug=DebugInfo(
            semantic_candidates=semantic_count,
            keyword_candidates=keyword_count,
            after_fusion=fused_count,
            after_rerank=len(results) if reranker_used else 0,
            after_acl=len(response_results),
            preprocessing_latency_ms=preprocess_time,
            embedding_latency_ms=processed.processing_time_ms,
            semantic_search_latency_ms=semantic_time or 0.0,
            keyword_search_latency_ms=keyword_time or 0.0,
            fusion_latency_ms=fusion_time or 0.0,
            rerank_latency_ms=rerank_time or 0.0,
            total_latency_ms=total_time,
            semantic_weight=body.semantic_weight,
            keyword_weight=body.keyword_weight,
            top_k_semantic=dynamic_params.semantic_top_k,
            top_k_keyword=dynamic_params.keyword_top_k,
            rerank_top_k=dynamic_params.rerank_top_k,
            effective_semantic_top_k=dynamic_params.semantic_top_k,
            effective_keyword_top_k=dynamic_params.keyword_top_k,
            effective_use_reranker=dynamic_params.use_reranker,
            effective_rerank_top_k=dynamic_params.rerank_top_k,
            tenant_tier=dynamic_params.tenant_tier,
            query_type_detected=dynamic_params.query_type,
        ),
        # Degradation info (US-10.2.2)
        degradation_mode=degradation_status.mode.value,
        components_used=degradation_status.components_available,
        components_skipped=degradation_status.components_unavailable,
    )


@router.post("/retrieve/multi", response_model=RetrieveResponse)
async def retrieve_multi(
    request: Request,
    body: MultiQueryRequest,
    user: UserContextDep,
) -> RetrieveResponse:
    """
    Retrieve using multiple query variations.

    Useful for complex queries where different phrasings
    might match different relevant documents.

    **Aggregation Methods:**
    - `max`: Use maximum score across queries
    - `avg`: Average scores across queries
    - `rrf`: Reciprocal Rank Fusion
    """
    start_time = time.time()
    query_id = uuid4()

    preprocessor: QueryPreprocessor = request.app.state.preprocessor
    hybrid: HybridSearcher = request.app.state.hybrid
    reranker: RerankerService = request.app.state.reranker
    acl_filter: ACLFilter = request.app.state.acl_filter

    filters = acl_filter.build_filter(user, body.filters)

    # Process all queries and collect results
    all_results: dict[UUID, Any] = {}

    for query in body.queries:
        processed = await preprocessor.process(query)

        # Run hybrid search for each query
        search_response = await hybrid.search(
            query=query,
            query_embedding=processed.embedding,
            filters=filters,
            top_k=body.top_k * 2,  # Get more for aggregation
        )

        # Aggregate results
        for result in search_response.results:
            if result.chunk_id in all_results:
                existing = all_results[result.chunk_id]
                if body.aggregation == "max":
                    if result.fused_score > existing.fused_score:
                        all_results[result.chunk_id] = result
                elif body.aggregation == "avg":
                    # Track scores for averaging
                    if not hasattr(existing, "_score_sum"):
                        existing._score_sum = existing.fused_score
                        existing._score_count = 1
                    existing._score_sum += result.fused_score
                    existing._score_count += 1
                    existing.fused_score = existing._score_sum / existing._score_count
                # RRF handled by rank positions below
            else:
                all_results[result.chunk_id] = result

    # For RRF aggregation
    if body.aggregation == "rrf":
        rrf_k = 60
        rrf_scores: dict[UUID, float] = {}

        for _i, query in enumerate(body.queries):
            processed = await preprocessor.process(query)
            search_response = await hybrid.search(
                query=query,
                query_embedding=processed.embedding,
                filters=filters,
                top_k=body.top_k * 2,
            )

            for rank, result in enumerate(search_response.results, 1):
                if result.chunk_id not in rrf_scores:
                    rrf_scores[result.chunk_id] = 0
                rrf_scores[result.chunk_id] += 1.0 / (rrf_k + rank)

        # Update scores
        for chunk_id, score in rrf_scores.items():
            if chunk_id in all_results:
                all_results[chunk_id].fused_score = score

    # Sort by score
    results = sorted(all_results.values(), key=lambda r: r.fused_score, reverse=True)

    # Rerank
    if body.rerank and results:
        results = await reranker.rerank_fused_results(
            query=body.queries[0],  # Use first query for reranking
            fused_results=results,
            top_k=body.top_k,
        )

    # Apply ACL safety net (defense in depth)
    # This should filter nothing if query-level ACL is correct
    safety_net: ACLSafetyNet = request.app.state.safety_net
    results = safety_net.filter(results, user)

    results = results[: body.top_k]

    # Convert to response
    response_results = _convert_to_response_documents(results, True, True)

    total_time = (time.time() - start_time) * 1000

    return RetrieveResponse(
        results=response_results,
        total_results=len(response_results),
        query="; ".join(body.queries),
        mode=SearchMode.HYBRID,
        metrics=SearchMetrics(
            query_preprocessing_ms=0,
            total_ms=total_time,
            final_results_count=len(response_results),
        ),
        query_id=query_id,
        processed_at=datetime.now(tz=UTC),
    )


@router.get("/retrieve/explain/{chunk_id}", response_model=ExplainResponse)
async def explain_retrieval(
    request: Request,
    chunk_id: UUID,
    query: str,
    user: UserContextDep,
) -> ExplainResponse:
    """
    Explain why a specific chunk was retrieved for a query.

    Returns score breakdown and relevance analysis.
    """
    preprocessor: QueryPreprocessor = request.app.state.preprocessor
    reranker: RerankerService = request.app.state.reranker
    hybrid: HybridSearcher = request.app.state.hybrid
    acl_filter: ACLFilter = request.app.state.acl_filter

    filters = acl_filter.build_filter(user)

    # Process query
    processed = await preprocessor.process(query)

    # Run hybrid search to find this chunk
    search_response = await hybrid.search(
        query=query,
        query_embedding=processed.embedding,
        filters=filters,
        top_k=100,  # Get more results to find the specific chunk
    )

    # Find the chunk in results
    chunk_result = None
    chunk_rank = None
    for i, result in enumerate(search_response.results):
        if result.chunk_id == chunk_id:
            chunk_result = result
            chunk_rank = i + 1
            break

    if chunk_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chunk {chunk_id} not found in search results for this query",
        )

    # Get rerank score
    rerank_score = None
    if chunk_result.content:
        rerank_response = await reranker.rerank(
            query=query,
            documents=[chunk_result.content],
            document_ids=[chunk_id],
        )
        if rerank_response.results:
            rerank_score = rerank_response.results[0].relevance_score

    explanation = {
        "semantic_similarity": chunk_result.semantic_score,
        "keyword_score": chunk_result.keyword_score,
        "fused_score": chunk_result.fused_score,
        "rerank_score": rerank_score,
        "semantic_rank": chunk_result.semantic_rank,
        "keyword_rank": chunk_result.keyword_rank,
        "final_rank": chunk_rank,
        "query_type": processed.query_type.value,
        "metadata": chunk_result.metadata,
    }

    return ExplainResponse(
        chunk_id=chunk_id,
        query=query,
        explanation=explanation,
    )


def _convert_to_response_documents(
    results: list,
    include_metadata: bool,
    include_highlights: bool,
) -> list[RetrievedDocument]:
    """Convert FusedResult objects to RetrievedDocument response format."""
    response_results = []

    for r in results:
        metadata_dict = r.metadata.copy() if r.metadata else {}

        # Extract standard fields from metadata
        source_type = metadata_dict.pop("source_type", None)
        chunk_index = metadata_dict.pop("chunk_index", 0)
        total_chunks = metadata_dict.pop("total_chunks", 1)
        created_at = metadata_dict.pop("created_at", None)
        updated_at = metadata_dict.pop("updated_at", None)
        rerank_score = metadata_dict.pop("rerank_score", None)

        response_results.append(
            RetrievedDocument(
                chunk_id=r.chunk_id,
                document_id=r.document_id,
                content=r.content,
                score=r.fused_score,
                title=r.title,
                source=r.source,
                source_type=source_type,
                chunk_index=chunk_index,
                total_chunks=total_chunks,
                created_at=created_at,
                updated_at=updated_at,
                semantic_score=r.semantic_score,
                keyword_score=r.keyword_score,
                rerank_score=rerank_score,
                metadata=metadata_dict if include_metadata else {},
                highlights=None,  # TODO: Implement highlights extraction
            ),
        )

    return response_results

"""Retrieval node for the RAG workflow.

This node fetches relevant documents from the retrieval service
based on the query and routing strategy.
"""

import time
from typing import TYPE_CHECKING

import httpx
import structlog
from opentelemetry import trace
from retrieval.policy import coerce_positive_int, get_retrieval_option, should_enable_rerank

from config import get_config
from orchestrator.observability.otel.span_names import SpanNames
from shared.http_clients import get_retrieval_client

if TYPE_CHECKING:
    from workflow.state import RAGState

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


def _extract_display_name(source: str, title: str | None, default: str) -> str:
    """Extract a meaningful display name for a document.

    For S3-uploaded files, extracts the clean filename from the source path.
    Falls back to title or default if not an S3 document.
    """
    # Check if this is an S3-uploaded document
    if source and source.startswith("uploads/"):
        # Extract filename from S3 key
        filename = source.split("/")[-1] if "/" in source else source
        # Strip timestamp prefix if present (format: {timestamp}-{filename})
        if "-" in filename and filename.split("-")[0].isdigit():
            return filename.split("-", 1)[1]
        return filename

    # Fall back to title or default
    return title or default


def _format_context(
    documents: list[dict],
    max_context_chars: int = 16384,
    max_docs: int = 10,
) -> str:
    """
    Format retrieved documents into a context string with budget limits.

    Applies character-based budgeting to prevent excessive context from
    inflating token usage and latency. Uses ~4 chars/token heuristic,
    so the default 16384 chars corresponds to roughly 4096 tokens.

    Args:
        documents: List of retrieved documents
        max_context_chars: Maximum total characters for the context string (default 16384)
        max_docs: Maximum number of documents to include (default 10)

    Returns:
        Formatted context string for prompt building
    """
    if not documents:
        return ""

    docs_to_use = documents[:max_docs]
    per_doc_budget = max_context_chars // len(docs_to_use)

    context_parts = []
    total_chars = 0
    for i, doc in enumerate(docs_to_use, 1):
        content = doc.get("content", "")
        source = doc.get("source", doc.get("metadata", {}).get("source_uri", "unknown"))
        title = doc.get("metadata", {}).get("title", "")
        # For S3 uploads, prefer filename over auto-extracted title
        source_label = _extract_display_name(source, title, f"Document {i}")

        # Truncate content to per-doc budget
        if len(content) > per_doc_budget:
            content = content[:per_doc_budget] + "..."

        part = f"[Document {i}: {source_label}]\n{content}"

        # Check total budget (always include at least the first document)
        if total_chars + len(part) > max_context_chars and context_parts:
            break

        context_parts.append(part)
        total_chars += len(part) + 2  # +2 for "\n\n" separator

    return "\n\n".join(context_parts)


async def retrieval_node(state: "RAGState") -> "RAGState":
    """
    Retrieve relevant context for the query.

    This node:
    - Calls the retrieval service
    - Processes and ranks results
    - Formats context for prompt building
    - Handles retrieval failures gracefully
    - Parses degradation info from retrieval response (US-10.2.2)

    Args:
        state: Current RAGState with query and strategy

    Returns:
        Updated RAGState with documents, context, and retrieval quality info
    """
    with tracer.start_as_current_span(SpanNames.ORCHESTRATOR_RETRIEVAL) as span:
        start = time.time()

        timing = dict(state.get("timing", {}))
        fallbacks_used = list(state.get("fallbacks_used", []))

        config = get_config()
        query = state.get("query", "")
        tenant_id = state.get("tenant_id")
        options = state.get("options", {})
        strategy = state.get("strategy", "simple")
        intent = state.get("intent")
        complexity_score = state.get("complexity_score")

        mode = str(
            get_retrieval_option(
                options,
                key="mode",
                default="hybrid",
                legacy_key="retrieval_mode",
            )
            or "hybrid"
        )
        top_k = coerce_positive_int(
            get_retrieval_option(options, key="top_k", default=config.retrieval_top_k),
            default=config.retrieval_top_k,
        )
        rerank_enabled = should_enable_rerank(
            strategy=strategy,
            intent=intent,
            complexity_score=complexity_score,
            rerank_override=get_retrieval_option(options, key="rerank", default=None),
        )

        # Set span attributes for query context
        span.set_attribute("orchestrator.query_length", len(query) if query else 0)
        span.set_attribute("orchestrator.retrieval_mode", mode)
        span.set_attribute("orchestrator.retrieval_rerank", rerank_enabled)
        span.set_attribute("orchestrator.retrieval_top_k", top_k)
        if tenant_id:
            span.set_attribute("orchestrator.tenant_id", tenant_id)

        documents: list[dict] = []
        retrieval_quality: dict | None = None
        context_quality: str | None = None

        try:
            client = get_retrieval_client()

            # Build request payload
            payload = {
                "query": query,
                "mode": mode,
                "top_k": top_k,
                "rerank": rerank_enabled,
                "include_metadata": True,
                "include_highlights": True,
            }

            # Add tenant filter and header if available
            headers = {}
            if tenant_id:
                payload["filters"] = {"tenant_id": tenant_id}
                headers["X-Tenant-Id"] = tenant_id

            response = await client.post(
                "/api/v1/retrieve",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

            result = response.json()
            raw_results = result.get("results", [])

            # Transform results to document format
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

            # Parse degradation info (US-10.2.2)
            degradation_mode = result.get("degradation_mode", "hybrid_full")
            components_used = result.get("components_used", [])
            components_skipped = result.get("components_skipped", [])

            # Determine degradation level from mode
            if degradation_mode == "hybrid_full":
                degradation_level = "normal"
            elif degradation_mode == "minimal":
                degradation_level = "minimal"
            else:
                degradation_level = "degraded"

            # Build retrieval quality info
            retrieval_quality = {
                "degradation_level": degradation_level,
                "mode": degradation_mode,
                "components_used": components_used,
                "components_skipped": components_skipped,
            }

            # Set context quality based on degradation
            if degradation_level == "minimal":
                context_quality = "minimal"
            elif degradation_level == "degraded":
                context_quality = "partial"
            else:
                context_quality = "full"

            # Track degradation as fallback if not normal
            if degradation_level != "normal":
                fallbacks_used.append(f"retrieval:{degradation_mode}")

            logger.info(f"Retrieved {len(documents)} documents for query: {query[:50]}...")

        except httpx.HTTPStatusError as e:
            logger.warning(f"Retrieval service returned error: {e.response.status_code}")
            fallbacks_used.append("retrieval_error")
            span.set_attribute("orchestrator.retrieval_error", "http_status_error")
        except httpx.RequestError as e:
            logger.warning(f"Failed to connect to retrieval service: {e}")
            fallbacks_used.append("retrieval_unavailable")
            span.set_attribute("orchestrator.retrieval_error", "request_error")
        except Exception as e:
            logger.exception(f"Unexpected error during retrieval: {e}")
            fallbacks_used.append("retrieval_exception")
            span.set_attribute("orchestrator.retrieval_error", "exception")

        # Set default retrieval quality if retrieval failed
        if retrieval_quality is None:
            retrieval_quality = {
                "degradation_level": "unknown",
                "mode": "unknown",
                "components_used": [],
                "components_skipped": [],
            }
            context_quality = "minimal"

        # Format context from retrieved documents
        context = _format_context(documents)

        # Set span attributes for retrieval results
        span.set_attribute("orchestrator.documents_retrieved", len(documents))
        span.set_attribute("orchestrator.context_quality", context_quality or "unknown")

        timing["retrieval"] = (time.time() - start) * 1000

        return {
            **state,
            "documents": documents,
            "context": context,
            "timing": timing,
            "fallbacks_used": fallbacks_used,
            "retrieval_quality": retrieval_quality,
            "context_quality": context_quality,
        }

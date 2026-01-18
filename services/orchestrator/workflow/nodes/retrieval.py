"""Retrieval node for the RAG workflow.

This node fetches relevant documents from the retrieval service
based on the query and routing strategy.
"""

import logging
import time
from typing import TYPE_CHECKING

import httpx

from config import get_config

if TYPE_CHECKING:
    from workflow.state import RAGState

logger = logging.getLogger(__name__)


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


def _format_context(documents: list[dict]) -> str:
    """
    Format retrieved documents into a context string.

    Args:
        documents: List of retrieved documents

    Returns:
        Formatted context string for prompt building
    """
    if not documents:
        return ""

    context_parts = []
    for i, doc in enumerate(documents, 1):
        content = doc.get("content", "")
        source = doc.get("source", doc.get("metadata", {}).get("source_uri", "unknown"))
        title = doc.get("metadata", {}).get("title", "")
        # For S3 uploads, prefer filename over auto-extracted title
        source_label = _extract_display_name(source, title, f"Document {i}")
        context_parts.append(f"[Document {i}: {source_label}]\n{content}")

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
    start = time.time()

    timing = dict(state.get("timing", {}))
    fallbacks_used = list(state.get("fallbacks_used", []))

    config = get_config()
    query = state.get("query", "")
    tenant_id = state.get("tenant_id")

    documents: list[dict] = []
    retrieval_quality: dict | None = None
    context_quality: str | None = None

    try:
        async with httpx.AsyncClient(timeout=config.retrieval_timeout) as client:
            # Build request payload
            payload = {
                "query": query,
                "mode": "hybrid",
                "top_k": config.retrieval_top_k,
                "rerank": False,  # Disable reranking for faster results
                "include_metadata": True,
                "include_highlights": True,
            }

            # Add tenant filter if available
            if tenant_id:
                payload["filters"] = {"tenant_id": tenant_id}

            response = await client.post(
                f"{config.retrieval_url}/api/v1/retrieve",
                json=payload,
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
                    "source": item.get("metadata", {}).get("source_uri", "unknown"),
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
    except httpx.RequestError as e:
        logger.warning(f"Failed to connect to retrieval service: {e}")
        fallbacks_used.append("retrieval_unavailable")
    except Exception as e:
        logger.exception(f"Unexpected error during retrieval: {e}")
        fallbacks_used.append("retrieval_exception")

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

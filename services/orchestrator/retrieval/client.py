"""Retrieval service client for the Orchestrator.

Provides a high-level async client that wraps the shared
``httpx.AsyncClient`` from :mod:`shared.http_clients` and
exposes a :meth:`search` method with the exact contract
expected by the streaming query path.

The client is intentionally thin: it delegates HTTP
configuration (timeouts, connection pooling) to
``shared.http_clients`` and focuses on payload
construction and response normalisation.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from config import get_config
from shared.http_clients import get_retrieval_client as _get_http_client

logger = structlog.get_logger(__name__)


class RetrievalClient:
    """High-level async client for the retrieval service.

    This client wraps the shared httpx.AsyncClient and provides:
    - A ``search()`` method returning a dict with ``documents``,
      ``degradation_mode``, ``components_used``, and
      ``components_skipped`` keys.
    - A ``health_check()`` method for readiness probing.
    - Structured logging for every retrieval attempt.

    The instance does *not* own the underlying HTTP client;
    lifecycle (init/close) is managed by
    :func:`shared.http_clients.init_http_clients` /
    :func:`shared.http_clients.close_http_clients`.
    """

    def __init__(self, *, top_k: int | None = None) -> None:
        config = get_config()
        self._top_k = top_k if top_k is not None else config.retrieval_top_k

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        *,
        tenant_id: str | None = None,
        top_k: int | None = None,
        mode: str = "hybrid",
    ) -> dict[str, Any]:
        """Search the retrieval service for documents matching *query*.

        Args:
            query: The user query string.
            tenant_id: Optional tenant scope for multi-tenant filtering.
            top_k: Override the default ``retrieval_top_k`` for this call.
            mode: Retrieval mode (``"hybrid"``, ``"semantic"``, ``"keyword"``).

        Returns:
            A dict with keys:
            - ``documents``: list of document dicts (content, score, metadata, ...).
            - ``degradation_mode``: str describing the retrieval path used.
            - ``components_used``: list of components that participated.
            - ``components_skipped``: list of components that were unavailable.

        Raises:
            httpx.HTTPStatusError: On non-2xx responses from the retrieval service.
            httpx.RequestError: On network/connection failures.
        """
        client = _get_http_client()
        effective_top_k = top_k if top_k is not None else self._top_k

        payload: dict[str, Any] = {
            "query": query,
            "mode": mode,
            "top_k": effective_top_k,
            "rerank": False,
            "include_metadata": True,
            "include_highlights": True,
        }

        headers: dict[str, str] = {}
        if tenant_id:
            payload["filters"] = {"tenant_id": tenant_id}
            headers["X-Tenant-Id"] = tenant_id

        logger.debug(
            "retrieval_search_start",
            query_length=len(query),
            tenant_id=tenant_id,
            top_k=effective_top_k,
            mode=mode,
        )

        response = await client.post(
            "/api/v1/retrieve",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()

        result = response.json()
        raw_results = result.get("results", [])

        documents = []
        for item in raw_results:
            documents.append(
                {
                    "content": item.get("content", ""),
                    "score": item.get("score", 0.0),
                    "chunk_id": item.get("chunk_id"),
                    "document_id": item.get("document_id"),
                    "metadata": item.get("metadata", {}),
                    "source": item.get("metadata", {}).get("source_uri", "unknown"),
                }
            )

        degradation_mode = result.get("degradation_mode", "hybrid_full")
        components_used = result.get("components_used", [])
        components_skipped = result.get("components_skipped", [])

        logger.info(
            "retrieval_search_complete",
            document_count=len(documents),
            degradation_mode=degradation_mode,
            components_used=components_used,
            components_skipped=components_skipped,
        )

        return {
            "documents": documents,
            "degradation_mode": degradation_mode,
            "components_used": components_used,
            "components_skipped": components_skipped,
        }

    async def health_check(self) -> dict[str, Any]:
        """Probe the retrieval service health endpoint.

        Returns:
            A dict with at least a ``"status"`` key (``"healthy"`` or ``"unhealthy"``).
        """
        try:
            client = _get_http_client()
            response = await client.get("/health")
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning("retrieval_health_check_failed", error=str(exc))
            return {"status": "unhealthy", "error": str(exc)}

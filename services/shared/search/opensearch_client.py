"""OpenSearch client wrapper for BM25 keyword search."""

import logging
import os
import ssl
from pathlib import Path
from typing import Any

from opensearchpy import OpenSearch, helpers

logger = logging.getLogger(__name__)


class OpenSearchClient:
    """Client wrapper for OpenSearch BM25 keyword search operations."""

    def __init__(
        self,
        url: str | None = None,
        index_name: str | None = None,
        username: str | None = None,
        password: str | None = None,
        use_ssl: bool | None = None,
        verify_certs: bool | None = None,
        ca_cert_path: str | None = None,
        client_cert_path: str | None = None,
        client_key_path: str | None = None,
    ):
        """Initialize OpenSearch client.

        Args:
            url: OpenSearch URL. Defaults to OPENSEARCH_URL env var or localhost.
            index_name: Index name. Defaults to OPENSEARCH_INDEX env var or 'documents'.
            username: OpenSearch username. Defaults to OPENSEARCH_USERNAME env var.
            password: OpenSearch password. Defaults to OPENSEARCH_PASSWORD env var.
            use_ssl: Enable SSL/TLS. Defaults to OPENSEARCH_USE_SSL env var.
            verify_certs: Verify SSL certificates. Defaults to OPENSEARCH_VERIFY_CERTS env var.
            ca_cert_path: Path to CA certificate. Defaults to OPENSEARCH_CA_CERT env var.
            client_cert_path: Path to client certificate for mTLS. Defaults to OPENSEARCH_CLIENT_CERT env var.
            client_key_path: Path to client key for mTLS. Defaults to OPENSEARCH_CLIENT_KEY env var.
        """
        self.url = url or os.getenv("OPENSEARCH_URL", "http://localhost:9200")
        self.index_name = index_name or os.getenv("OPENSEARCH_INDEX", "documents")

        # Authentication configuration
        self._username = username or os.getenv("OPENSEARCH_USERNAME")
        self._password = password or os.getenv("OPENSEARCH_PASSWORD")

        # SSL configuration
        self._use_ssl = (
            use_ssl
            if use_ssl is not None
            else (os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true")
        )
        self._verify_certs = (
            verify_certs
            if verify_certs is not None
            else (os.getenv("OPENSEARCH_VERIFY_CERTS", "true").lower() == "true")
        )
        self._ca_cert_path = ca_cert_path or os.getenv("OPENSEARCH_CA_CERT")

        # Client certificate authentication (mTLS)
        self._client_cert_path = client_cert_path or os.getenv("OPENSEARCH_CLIENT_CERT")
        self._client_key_path = client_key_path or os.getenv("OPENSEARCH_CLIENT_KEY")

        self._client: OpenSearch | None = None

    def _create_ssl_context(self) -> ssl.SSLContext | None:
        """Create SSL context for secure connections.

        Supports:
        - CA certificate verification
        - Client certificate authentication (mTLS)
        - Environment-based verification mode

        Returns:
            SSL context configured for OpenSearch, or None if SSL disabled.
        """
        if not self._use_ssl:
            return None

        ssl_context = ssl.create_default_context()
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

        # Load CA certificate for server verification
        if self._ca_cert_path and Path(self._ca_cert_path).exists():
            ssl_context.load_verify_locations(self._ca_cert_path)

        # Load client certificate for mutual TLS authentication
        if (
            self._client_cert_path
            and self._client_key_path
            and Path(self._client_cert_path).exists()
            and Path(self._client_key_path).exists()
        ):
            ssl_context.load_cert_chain(
                certfile=self._client_cert_path,
                keyfile=self._client_key_path,
            )

        # Configure verification based on settings
        if not self._verify_certs:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        else:
            # In production with verification enabled, enforce strict checking
            environment = os.getenv("ENVIRONMENT", "development")
            if environment == "production":
                ssl_context.check_hostname = True
                ssl_context.verify_mode = ssl.CERT_REQUIRED

        return ssl_context

    @property
    def client(self) -> OpenSearch:
        """Lazy-initialize and return the OpenSearch client."""
        if self._client is None:
            # Build authentication tuple if credentials provided
            http_auth = None
            if self._username and self._password:
                http_auth = (self._username, self._password)

            # Build SSL context
            ssl_context = self._create_ssl_context()

            self._client = OpenSearch(
                hosts=[self.url],
                http_auth=http_auth,
                use_ssl=self._use_ssl,
                verify_certs=self._verify_certs,
                ssl_context=ssl_context,
                ssl_show_warn=False,
                http_compress=True,
                timeout=30,
                max_retries=3,
                retry_on_timeout=True,
            )
        return self._client

    async def bulk_index(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        """Bulk index documents.

        Args:
            documents: List of documents to index. Each must have a 'chunk_id' field.

        Returns:
            Dict with 'success' count and 'errors' list.
        """
        actions = [
            {
                "_index": self.index_name,
                "_id": doc["chunk_id"],
                "_source": doc,
            }
            for doc in documents
        ]

        success, errors = helpers.bulk(
            self.client,
            actions,
            raise_on_error=False,
        )

        return {"success": success, "errors": errors}

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filter_conditions: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """BM25 keyword search.

        Args:
            query: Search query string.
            top_k: Maximum number of results to return.
            filter_conditions: Optional dict of field->value filters.

        Returns:
            List of search results with id, score, and source.
        """
        must = [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["content^1.0", "title^2.0"],
                    "type": "best_fields",
                },
            },
        ]

        filter_clauses = []
        if filter_conditions:
            for key, value in filter_conditions.items():
                filter_clauses.append({"term": {key: value}})

        body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": must,
                    "filter": filter_clauses,
                },
            },
            "_source": True,
        }

        response = self.client.search(index=self.index_name, body=body)

        return [
            {
                "id": hit["_id"],
                "score": hit["_score"],
                "source": hit["_source"],
            }
            for hit in response["hits"]["hits"]
        ]

    async def delete_by_document_id(
        self,
        document_id: str,
        tenant_id: str | None = None,
    ) -> int:
        """Delete all chunks for a document.

        Args:
            document_id: The document ID whose chunks should be deleted.
            tenant_id: Optional tenant ID for scoped deletion (recommended for safety).

        Returns:
            Number of documents deleted.
        """
        must_conditions = [{"term": {"document_id": document_id}}]

        if tenant_id:
            must_conditions.append({"term": {"tenant_id": tenant_id}})

        body = {
            "query": {
                "bool": {
                    "must": must_conditions,
                },
            },
        }

        response = self.client.delete_by_query(
            index=self.index_name,
            body=body,
            refresh=True,  # Make deletion immediately visible
        )

        return response.get("deleted", 0)

    def health_check(self) -> dict:
        """Check OpenSearch connectivity and return health status.

        Returns:
            Dict with 'healthy' boolean, cluster status, 'ssl_enabled', and latency.
        """
        import time

        start = time.monotonic()
        try:
            health = self.client.cluster.health()
            latency_ms = (time.monotonic() - start) * 1000

            return {
                "healthy": health["status"] in ["green", "yellow"],
                "cluster_status": health["status"],
                "ssl_enabled": self._use_ssl,
                "latency_ms": round(latency_ms, 2),
            }
        except Exception as e:
            latency_ms = (time.monotonic() - start) * 1000
            return {
                "healthy": False,
                "cluster_status": "unavailable",
                "ssl_enabled": self._use_ssl,
                "latency_ms": round(latency_ms, 2),
                "error": str(e),
            }

    async def get_document_count(self) -> int:
        """Get the total number of documents in the index.

        Returns:
            Document count.
        """
        try:
            response = self.client.count(index=self.index_name)
            return response["count"]
        except Exception:
            return 0

    async def get_existing_chunk_ids(
        self,
        tenant_id: str,
        chunk_ids: list[str],
    ) -> list[str]:
        """Check which chunk IDs exist in OpenSearch.

        Used by the reconciliation process to find missing chunks.

        Args:
            tenant_id: The tenant ID to filter by.
            chunk_ids: List of chunk IDs to check.

        Returns:
            List of chunk IDs that exist in OpenSearch.
        """
        if not chunk_ids:
            return []

        # Use mget to retrieve documents by ID
        body = {"ids": chunk_ids}
        response = self.client.mget(index=self.index_name, body=body)

        # Filter to only include docs matching the tenant
        existing_ids = []
        for doc in response.get("docs", []):
            if doc.get("found"):
                source = doc.get("_source", {})
                if source.get("tenant_id") == tenant_id:
                    existing_ids.append(doc["_id"])

        return existing_ids

    async def get_all_chunk_ids(
        self,
        tenant_id: str,
        batch_size: int = 1000,
    ) -> list[str]:
        """Get all chunk IDs for a tenant.

        Used by the reconciliation process to find orphaned entries.

        Args:
            tenant_id: The tenant ID to filter by.
            batch_size: Number of documents to retrieve per scroll batch.

        Returns:
            List of all chunk IDs for the tenant.
        """
        chunk_ids: list[str] = []

        # Use scroll API for efficient iteration over large result sets
        body = {
            "query": {"term": {"tenant_id": tenant_id}},
            "_source": False,
            "size": batch_size,
        }

        # Initial search with scroll
        response = self.client.search(
            index=self.index_name,
            body=body,
            scroll="2m",
        )

        scroll_id = response.get("_scroll_id")
        hits = response.get("hits", {}).get("hits", [])

        while hits:
            for hit in hits:
                chunk_ids.append(hit["_id"])

            # Get next batch
            response = self.client.scroll(scroll_id=scroll_id, scroll="2m")
            scroll_id = response.get("_scroll_id")
            hits = response.get("hits", {}).get("hits", [])

        # Clean up scroll context
        if scroll_id:
            try:
                self.client.clear_scroll(scroll_id=scroll_id)
            except Exception as e:
                logger.debug("Failed to clear scroll context: %s", e)

        return chunk_ids

    async def delete_by_chunk_id(self, chunk_id: str, tenant_id: str) -> None:
        """Delete a single document by chunk ID.

        Used by the reconciliation process to clean up orphaned entries.

        Args:
            chunk_id: The chunk ID (document ID) to delete.
            tenant_id: The tenant ID for validation (unused but kept for API consistency).
        """
        try:
            self.client.delete(index=self.index_name, id=chunk_id)
        except Exception as e:
            # Document may not exist, log and continue
            logger.debug("Failed to delete chunk %s: %s", chunk_id, e)


def get_opensearch_client(
    url: str | None = None,
    index_name: str | None = None,
) -> OpenSearchClient:
    """Factory function to get an OpenSearch client with security configuration.

    Args:
        url: Optional OpenSearch URL override.
        index_name: Optional index name override.

    Returns:
        Configured OpenSearchClient instance.
    """
    return OpenSearchClient(url=url, index_name=index_name)

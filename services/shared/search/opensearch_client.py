"""OpenSearch client wrapper for BM25 keyword search."""

import os
import ssl
from typing import Any

from opensearchpy import OpenSearch, helpers


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

        self._client: OpenSearch | None = None

    def _create_ssl_context(self) -> ssl.SSLContext | None:
        """Create SSL context for secure connections.

        Returns:
            SSL context configured for OpenSearch, or None if SSL disabled.
        """
        if not self._use_ssl:
            return None

        ssl_context = ssl.create_default_context()

        if self._ca_cert_path and os.path.exists(self._ca_cert_path):
            ssl_context.load_verify_locations(self._ca_cert_path)

        if not self._verify_certs:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

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

    async def delete_by_document_id(self, document_id: str) -> dict[str, Any]:
        """Delete all chunks for a document.

        Args:
            document_id: The document ID whose chunks should be deleted.

        Returns:
            Delete by query response with counts.
        """
        body = {"query": {"term": {"document_id": document_id}}}
        return self.client.delete_by_query(index=self.index_name, body=body)

    def health_check(self) -> bool:
        """Check OpenSearch connectivity.

        Returns:
            True if cluster is healthy (green or yellow), False otherwise.
        """
        try:
            health = self.client.cluster.health()
            return health["status"] in ["green", "yellow"]
        except Exception:
            return False

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

"""OpenSearch indexer for video chunks.

This module provides the OpenSearchVideoIndexer class for indexing
video chunks in OpenSearch for BM25 keyword search.
"""

import logging
import os
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from opensearchpy import OpenSearch, helpers
from processors.video.content_fusion import VideoChunk

logger = logging.getLogger(__name__)

# Progress callback type
ProgressCallback = Callable[[int, int, str], None]

# Index configuration
VIDEO_CHUNKS_INDEX = "video_chunks"


# Index mapping for video chunks
VIDEO_CHUNKS_MAPPING = {
    "settings": {
        "number_of_shards": 2,
        "number_of_replicas": 1,
        "analysis": {
            "analyzer": {
                "default": {
                    "type": "standard",
                    "stopwords": "_english_",
                },
            },
        },
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "video_id": {"type": "keyword"},
            "tenant_id": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "start_time_ms": {"type": "integer"},
            "end_time_ms": {"type": "integer"},
            "fused_text": {
                "type": "text",
                "analyzer": "standard",
            },
            "transcript_text": {
                "type": "text",
                "analyzer": "standard",
            },
            "scene_description": {
                "type": "text",
                "analyzer": "standard",
            },
            "ocr_text": {
                "type": "text",
                "analyzer": "standard",
            },
            "video_title": {
                "type": "text",
                "fields": {
                    "keyword": {"type": "keyword"},
                },
            },
            "visibility": {"type": "keyword"},
            "allowed_groups": {"type": "keyword"},
            "source_modalities": {"type": "keyword"},
            "keyframe_path": {"type": "keyword"},
            "created_at": {"type": "date"},
        },
    },
}


@dataclass
class OpenSearchIndexerConfig:
    """Configuration for OpenSearch video indexer.

    Attributes:
        url: OpenSearch URL.
        index_name: Index name for video chunks.
        username: OpenSearch username.
        password: OpenSearch password.
        use_ssl: Enable SSL.
        verify_certs: Verify SSL certificates.
        ca_cert_path: Path to CA certificate.
        batch_size: Documents per bulk batch.
        timeout: Request timeout.
    """

    url: str = ""
    index_name: str = VIDEO_CHUNKS_INDEX
    username: str = ""
    password: str = ""
    use_ssl: bool = False
    verify_certs: bool = True
    ca_cert_path: str = ""
    batch_size: int = 100
    timeout: int = 60

    def __post_init__(self):
        if not self.url:
            self.url = os.getenv("OPENSEARCH_URL", "http://localhost:9200")
        if not self.username:
            self.username = os.getenv("OPENSEARCH_USERNAME", "")
        if not self.password:
            self.password = os.getenv("OPENSEARCH_PASSWORD", "")
        if not self.use_ssl:
            self.use_ssl = os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true"


@dataclass
class IndexResult:
    """Result of indexing operation.

    Attributes:
        indexed_count: Number of documents indexed.
        error_count: Number of indexing errors.
        index_name: Target index name.
        video_id: Video that was indexed.
    """

    indexed_count: int
    error_count: int
    index_name: str
    video_id: UUID


class OpenSearchVideoIndexer:
    """Indexes video chunks in OpenSearch for keyword search.

    Creates and manages the video_chunks index with proper mappings
    for BM25 search across fused_text, transcript, scene descriptions,
    and OCR text.

    Example:
        indexer = OpenSearchVideoIndexer()
        await indexer.ensure_index()
        result = await indexer.index_chunks(chunks=video_chunks)
    """

    def __init__(self, config: OpenSearchIndexerConfig | None = None):
        """Initialize OpenSearch video indexer.

        Args:
            config: Indexer configuration.
        """
        self.config = config or OpenSearchIndexerConfig()
        self._client: OpenSearch | None = None

    def _create_ssl_context(self) -> ssl.SSLContext | None:
        """Create SSL context for secure connections."""
        if not self.config.use_ssl:
            return None

        ssl_context = ssl.create_default_context()

        if self.config.ca_cert_path and Path(self.config.ca_cert_path).exists():
            ssl_context.load_verify_locations(self.config.ca_cert_path)

        if not self.config.verify_certs:
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        return ssl_context

    @property
    def client(self) -> OpenSearch:
        """Get or create OpenSearch client."""
        if self._client is None:
            http_auth = None
            if self.config.username and self.config.password:
                http_auth = (self.config.username, self.config.password)

            ssl_context = self._create_ssl_context()

            self._client = OpenSearch(
                hosts=[self.config.url],
                http_auth=http_auth,
                use_ssl=self.config.use_ssl,
                verify_certs=self.config.verify_certs,
                ssl_context=ssl_context,
                ssl_show_warn=False,
                http_compress=True,
                timeout=self.config.timeout,
                max_retries=3,
                retry_on_timeout=True,
            )
        return self._client

    async def ensure_index(self) -> bool:
        """Ensure video_chunks index exists with proper mappings.

        Creates the index if it doesn't exist with:
        - Standard analyzer with English stopwords
        - Text fields for full-text search
        - Keyword fields for filtering

        Returns:
            True if index was created, False if already exists.
        """
        index_name = self.config.index_name

        if self.client.indices.exists(index=index_name):
            logger.info("Index %s already exists", index_name)
            return False

        self.client.indices.create(
            index=index_name,
            body=VIDEO_CHUNKS_MAPPING,
        )

        logger.info("Created index %s with video chunks mapping", index_name)
        return True

    async def index_chunks(
        self,
        chunks: list[VideoChunk],
        video_title: str = "",
        visibility: str = "private",
        allowed_groups: list[str] | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> IndexResult:
        """Index video chunks in OpenSearch.

        Args:
            chunks: List of VideoChunk objects.
            video_title: Title of the video.
            visibility: Visibility level.
            allowed_groups: Allowed groups for ACL.
            progress_callback: Optional progress callback.

        Returns:
            IndexResult with counts and metadata.
        """
        if not chunks:
            return IndexResult(
                indexed_count=0,
                error_count=0,
                index_name=self.config.index_name,
                video_id=UUID(int=0),
            )

        total = len(chunks)
        video_id = chunks[0].video_id
        tenant_id = chunks[0].tenant_id

        logger.info(
            "Indexing %d chunks for video_id=%s in OpenSearch",
            total,
            video_id,
        )

        # Build documents
        documents = []
        for chunk in chunks:
            doc = {
                "chunk_id": str(chunk.id),
                "video_id": str(video_id),
                "tenant_id": str(tenant_id),
                "chunk_index": chunk.chunk_index,
                "start_time_ms": chunk.start_time_ms,
                "end_time_ms": chunk.end_time_ms,
                "fused_text": chunk.fused_text,
                "transcript_text": chunk.transcript_text,
                "scene_description": chunk.scene_description,
                "ocr_text": chunk.ocr_text,
                "video_title": video_title,
                "visibility": visibility,
                "allowed_groups": allowed_groups or [],
                "source_modalities": chunk.source_modalities,
                "keyframe_path": chunk.keyframe_path,
            }
            documents.append(doc)

        # Bulk index in batches
        indexed_count = 0
        error_count = 0

        for i in range(0, len(documents), self.config.batch_size):
            batch = documents[i : i + self.config.batch_size]

            actions = [
                {
                    "_index": self.config.index_name,
                    "_id": doc["chunk_id"],
                    "_source": doc,
                }
                for doc in batch
            ]

            success, errors = helpers.bulk(
                self.client,
                actions,
                raise_on_error=False,
            )

            indexed_count += success
            if errors:
                error_count += len(errors)
                logger.warning(
                    "Bulk indexing had %d errors: %s",
                    len(errors),
                    errors[:3],
                )

            if progress_callback:
                progress_callback(
                    indexed_count,
                    total,
                    f"Indexed {indexed_count}/{total} chunks in OpenSearch",
                )

        logger.info(
            "Indexed %d chunks (%d errors) for video_id=%s in index %s",
            indexed_count,
            error_count,
            video_id,
            self.config.index_name,
        )

        return IndexResult(
            indexed_count=indexed_count,
            error_count=error_count,
            index_name=self.config.index_name,
            video_id=video_id,
        )

    async def delete_by_video_id(self, video_id: UUID) -> int:
        """Delete all chunks for a video from OpenSearch.

        Args:
            video_id: Video UUID whose chunks should be deleted.

        Returns:
            Number of documents deleted.
        """
        body = {
            "query": {
                "term": {"video_id": str(video_id)},
            },
        }

        response = self.client.delete_by_query(
            index=self.config.index_name,
            body=body,
        )

        deleted = response.get("deleted", 0)
        logger.info(
            "Deleted %d chunks for video_id=%s from OpenSearch",
            deleted,
            video_id,
        )

        return deleted

    async def search(
        self,
        query: str,
        tenant_id: UUID,
        top_k: int = 10,
        video_id: UUID | None = None,
        allowed_groups: list[str] | None = None,
        search_fields: list[str] | None = None,
    ) -> list[dict]:
        """BM25 keyword search for video chunks.

        Args:
            query: Search query string.
            tenant_id: Tenant for filtering.
            top_k: Number of results.
            video_id: Optional filter to specific video.
            allowed_groups: User's groups for ACL filtering.
            search_fields: Fields to search (defaults to all text fields).

        Returns:
            List of search results with id, score, and source.
        """
        # Default search fields with boosts
        if search_fields is None:
            search_fields = [
                "fused_text^1.0",
                "transcript_text^1.2",
                "scene_description^0.8",
                "ocr_text^0.6",
                "video_title^1.5",
            ]

        # Build must clauses
        must = [
            {
                "multi_match": {
                    "query": query,
                    "fields": search_fields,
                    "type": "best_fields",
                    "fuzziness": "AUTO",
                },
            },
        ]

        # Build filter clauses
        filter_clauses = [
            {"term": {"tenant_id": str(tenant_id)}},
        ]

        if video_id:
            filter_clauses.append({"term": {"video_id": str(video_id)}})

        # ACL filtering - public OR in allowed groups
        if allowed_groups:
            filter_clauses.append({
                "bool": {
                    "should": [
                        {"term": {"visibility": "public"}},
                        {"terms": {"allowed_groups": allowed_groups}},
                    ],
                    "minimum_should_match": 1,
                },
            })

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

        response = self.client.search(
            index=self.config.index_name,
            body=body,
        )

        return [
            {
                "id": hit["_id"],
                "score": hit["_score"],
                "source": hit["_source"],
            }
            for hit in response["hits"]["hits"]
        ]

    def health_check(self) -> bool:
        """Check OpenSearch connectivity.

        Returns:
            True if healthy.
        """
        try:
            health = self.client.cluster.health()
            return health["status"] in ["green", "yellow"]
        except Exception:
            return False

    async def get_document_count(self) -> int:
        """Get total document count in index.

        Returns:
            Document count.
        """
        try:
            response = self.client.count(index=self.config.index_name)
            return response["count"]
        except Exception:
            return 0

    def close(self) -> None:
        """Close client connection."""
        if self._client is not None:
            self._client.close()
            self._client = None

"""Tenant-aware search wrappers for multi-tenant index isolation.

Provides searchers that automatically route to the correct collection/index
based on tenant configuration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from .fusion import HybridSearchResponse
from .hybrid import HybridSearchConfig, HybridSearcher
from .keyword import KeywordSearcher
from .models import OpenSearchConfig, QdrantConfig
from .semantic import SemanticSearcher

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from shared.tenant.config_service import TenantConfigService, TenantIndexConfig

logger = structlog.get_logger(__name__)


class TenantAwareHybridSearcher:
    """Hybrid searcher with tenant-based collection/index routing.

    Maintains a cache of searcher instances per tenant to avoid
    reconnecting on every request. For shared tenants, uses the
    default searcher. For dedicated tenants, creates and caches
    tenant-specific searchers.

    Example:
        searcher = TenantAwareHybridSearcher(
            base_qdrant_config=QdrantConfig(url="http://localhost:6333"),
            base_opensearch_config=OpenSearchConfig(url="http://localhost:9200"),
            hybrid_config=HybridSearchConfig(),
            config_service=get_tenant_config_service(),
        )
        await searcher.connect()

        results = await searcher.search(
            tenant_id=tenant_uuid,
            session=db_session,
            query="search query",
            query_embedding=[0.1, 0.2, ...],
        )
    """

    def __init__(
        self,
        base_qdrant_config: QdrantConfig,
        base_opensearch_config: OpenSearchConfig,
        hybrid_config: HybridSearchConfig | None = None,
        config_service: TenantConfigService | None = None,
    ):
        """Initialize tenant-aware hybrid searcher.

        Args:
            base_qdrant_config: Base Qdrant configuration (used for URL, auth).
            base_opensearch_config: Base OpenSearch configuration (used for URL, auth).
            hybrid_config: Configuration for hybrid search fusion.
            config_service: TenantConfigService for tenant config lookups.
                If not provided, will use singleton.
        """
        self.base_qdrant_config = base_qdrant_config
        self.base_opensearch_config = base_opensearch_config
        self.hybrid_config = hybrid_config or HybridSearchConfig()

        # Config service - lazy load if not provided
        self._config_service = config_service

        # Default searcher for shared collection
        self._default_hybrid: HybridSearcher | None = None

        # Cache of tenant-specific searchers
        self._tenant_searchers: dict[UUID, HybridSearcher] = {}

    def _get_config_service(self) -> TenantConfigService:
        """Get or create config service."""
        if self._config_service is None:
            from shared.tenant.config_service import get_tenant_config_service
            self._config_service = get_tenant_config_service()
        return self._config_service

    async def connect(self) -> None:
        """Initialize default searcher for shared tenants."""
        semantic = SemanticSearcher(self.base_qdrant_config)
        await semantic.connect()

        keyword = KeywordSearcher(self.base_opensearch_config)
        await keyword.connect()

        self._default_hybrid = HybridSearcher(
            semantic,
            keyword,
            self.hybrid_config,
        )

        logger.info("tenant_aware_searcher_connected")

    async def close(self) -> None:
        """Close all searchers."""
        if self._default_hybrid:
            await self._default_hybrid.close()

        for tenant_id, searcher in self._tenant_searchers.items():
            try:
                await searcher.close()
            except Exception as e:
                logger.warning(
                    "tenant_searcher_close_failed",
                    tenant_id=str(tenant_id),
                    error=str(e),
                )

        self._tenant_searchers.clear()
        logger.info("tenant_aware_searcher_closed")

    async def get_searcher_for_tenant(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> HybridSearcher:
        """Get hybrid searcher for tenant.

        Returns default searcher for shared tenants, or creates/returns
        tenant-specific searcher for isolated tenants.

        Args:
            tenant_id: Tenant UUID.
            session: Database session for config lookup.

        Returns:
            HybridSearcher configured for the tenant's collection/index.
        """
        config = await self._get_config_service().get_index_config(
            tenant_id, session
        )

        if config.isolation_mode == "shared":
            return self._default_hybrid

        # Check cache
        if tenant_id in self._tenant_searchers:
            return self._tenant_searchers[tenant_id]

        # Create tenant-specific searcher
        searcher = await self._create_tenant_searcher(config)
        self._tenant_searchers[tenant_id] = searcher

        logger.info(
            "tenant_searcher_created",
            tenant_id=str(tenant_id),
            collection=config.qdrant_collection,
            index=config.opensearch_index,
        )

        return searcher

    async def _create_tenant_searcher(
        self,
        config: TenantIndexConfig,
    ) -> HybridSearcher:
        """Create searcher for isolated tenant.

        Args:
            config: TenantIndexConfig with collection/index names.

        Returns:
            New HybridSearcher connected to tenant's stores.
        """
        # Create config with tenant-specific collection/index
        qdrant_config = QdrantConfig(
            url=self.base_qdrant_config.url,
            api_key=self.base_qdrant_config.api_key,
            collection_name=config.qdrant_collection,
            timeout=self.base_qdrant_config.timeout,
            hnsw_ef=self.base_qdrant_config.hnsw_ef,
            exact_search=self.base_qdrant_config.exact_search,
            use_quantization=self.base_qdrant_config.use_quantization,
            quantization_rescore=self.base_qdrant_config.quantization_rescore,
        )

        opensearch_config = OpenSearchConfig(
            url=self.base_opensearch_config.url,
            username=self.base_opensearch_config.username,
            password=self.base_opensearch_config.password,
            index_name=config.opensearch_index,
            timeout=self.base_opensearch_config.timeout,
            use_ssl=self.base_opensearch_config.use_ssl,
            verify_certs=self.base_opensearch_config.verify_certs,
            default_operator=self.base_opensearch_config.default_operator,
            fuzziness=self.base_opensearch_config.fuzziness,
            analyzer=self.base_opensearch_config.analyzer,
        )

        semantic = SemanticSearcher(qdrant_config)
        await semantic.connect()

        keyword = KeywordSearcher(opensearch_config)
        await keyword.connect()

        return HybridSearcher(semantic, keyword, self.hybrid_config)

    async def search(
        self,
        tenant_id: UUID,
        session: AsyncSession,
        query: str,
        query_embedding: list[float],
        filters: dict | None = None,
        top_k: int = 10,
        **kwargs,
    ) -> HybridSearchResponse:
        """Execute hybrid search for tenant.

        Automatically routes to correct collection/index based on
        tenant configuration.

        Args:
            tenant_id: Tenant UUID.
            session: Database session for config lookup.
            query: Search query string.
            query_embedding: Query embedding vector.
            filters: Optional ACL/metadata filters.
            top_k: Number of results to return.
            **kwargs: Additional arguments passed to HybridSearcher.search().

        Returns:
            HybridSearchResponse with search results.
        """
        searcher = await self.get_searcher_for_tenant(tenant_id, session)
        return await searcher.search(
            query=query,
            query_embedding=query_embedding,
            filters=filters,
            top_k=top_k,
            **kwargs,
        )

    async def search_semantic_only(
        self,
        tenant_id: UUID,
        session: AsyncSession,
        query_embedding: list[float],
        filters: dict | None = None,
        top_k: int = 10,
    ) -> HybridSearchResponse:
        """Execute semantic-only search for tenant.

        Args:
            tenant_id: Tenant UUID.
            session: Database session for config lookup.
            query_embedding: Query embedding vector.
            filters: Optional ACL/metadata filters.
            top_k: Number of results to return.

        Returns:
            HybridSearchResponse with semantic results only.
        """
        searcher = await self.get_searcher_for_tenant(tenant_id, session)
        return await searcher.search_semantic_only(
            query_embedding=query_embedding,
            filters=filters,
            top_k=top_k,
        )

    async def search_keyword_only(
        self,
        tenant_id: UUID,
        session: AsyncSession,
        query: str,
        filters: dict | None = None,
        top_k: int = 10,
    ) -> HybridSearchResponse:
        """Execute keyword-only search for tenant.

        Args:
            tenant_id: Tenant UUID.
            session: Database session for config lookup.
            query: Search query string.
            filters: Optional ACL/metadata filters.
            top_k: Number of results to return.

        Returns:
            HybridSearchResponse with keyword results only.
        """
        searcher = await self.get_searcher_for_tenant(tenant_id, session)
        return await searcher.search_keyword_only(
            query=query,
            filters=filters,
            top_k=top_k,
        )

    def invalidate_tenant(self, tenant_id: UUID) -> None:
        """Invalidate cached searcher for tenant.

        Call when tenant config changes (e.g., migration to dedicated).

        Args:
            tenant_id: Tenant UUID to invalidate.
        """
        if tenant_id in self._tenant_searchers:
            # Note: Searcher should be closed but we can't await here
            # The old searcher will be garbage collected
            del self._tenant_searchers[tenant_id]
            logger.info("tenant_searcher_invalidated", tenant_id=str(tenant_id))

        self._get_config_service().invalidate_cache(tenant_id)

    async def health_check(self) -> dict:
        """Check health of searchers.

        Returns:
            Dictionary with health status.
        """
        if self._default_hybrid is None:
            return {"status": "unhealthy", "error": "Not connected"}

        try:
            default_health = await self._default_hybrid.health_check()
            return {
                "status": "healthy",
                "default_searcher": default_health,
                "cached_tenant_searchers": len(self._tenant_searchers),
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

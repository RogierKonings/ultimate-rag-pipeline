"""Service for tenant configuration with caching.

Provides fast lookups for tenant index routing decisions during
ingestion and retrieval operations.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


@dataclass
class TenantIndexConfig:
    """Cached tenant index configuration.

    Contains the resolved collection/index names for a tenant,
    avoiding repeated database lookups during request processing.
    """

    tenant_id: UUID
    isolation_mode: str
    qdrant_collection: str
    opensearch_index: str
    qdrant_settings: dict | None = None
    opensearch_settings: dict | None = None


class TenantConfigService:
    """Service for tenant configuration with in-memory caching.

    Provides fast lookups for tenant index routing decisions.
    Uses TTL-based caching to balance freshness with performance.

    Example:
        service = TenantConfigService(cache_ttl_seconds=300)
        config = await service.get_index_config(tenant_id, session)
        print(f"Collection: {config.qdrant_collection}")
    """

    def __init__(self, cache_ttl_seconds: int = 300):
        """Initialize the config service.

        Args:
            cache_ttl_seconds: Time-to-live for cached configs (default 5 min).
        """
        self._cache: dict[UUID, TenantIndexConfig] = {}
        self._cache_ttl = cache_ttl_seconds
        self._cache_timestamps: dict[UUID, float] = {}
        self._lock = asyncio.Lock()

    async def get_index_config(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> TenantIndexConfig:
        """Get index configuration for tenant.

        Uses cache with TTL for performance. Returns default shared
        config for unknown tenants.

        Args:
            tenant_id: Tenant UUID
            session: Database session for loading config

        Returns:
            TenantIndexConfig with collection/index names
        """
        now = time.time()

        # Check cache (fast path)
        if tenant_id in self._cache:
            timestamp = self._cache_timestamps.get(tenant_id, 0)
            if now - timestamp < self._cache_ttl:
                return self._cache[tenant_id]

        # Load from database (slow path with lock)
        async with self._lock:
            # Double-check after acquiring lock
            if tenant_id in self._cache:
                timestamp = self._cache_timestamps.get(tenant_id, 0)
                if now - timestamp < self._cache_ttl:
                    return self._cache[tenant_id]

            config = await self._load_from_db(tenant_id, session)
            self._cache[tenant_id] = config
            self._cache_timestamps[tenant_id] = now

            logger.debug(
                "tenant_config_cached",
                tenant_id=str(tenant_id),
                isolation_mode=config.isolation_mode,
            )

            return config

    async def _load_from_db(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> TenantIndexConfig:
        """Load tenant config from database.

        Returns default config for unknown tenants to handle edge cases
        gracefully (e.g., race conditions during tenant creation).
        """
        from shared.database.models import Tenant

        result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()

        if tenant is None:
            # Return default config for unknown tenant
            logger.warning(
                "tenant_not_found_using_defaults",
                tenant_id=str(tenant_id),
            )
            return TenantIndexConfig(
                tenant_id=tenant_id,
                isolation_mode="shared",
                qdrant_collection="documents",
                opensearch_index="documents",
            )

        return TenantIndexConfig(
            tenant_id=tenant_id,
            isolation_mode=tenant.isolation_mode,
            qdrant_collection=tenant.get_qdrant_collection(),
            opensearch_index=tenant.get_opensearch_index(),
            qdrant_settings=tenant.qdrant_settings,
            opensearch_settings=tenant.opensearch_settings,
        )

    def invalidate_cache(self, tenant_id: UUID) -> None:
        """Invalidate cached config for tenant.

        Call this after updating tenant isolation settings to ensure
        subsequent requests use the new configuration.

        Args:
            tenant_id: Tenant UUID to invalidate
        """
        self._cache.pop(tenant_id, None)
        self._cache_timestamps.pop(tenant_id, None)
        logger.info("tenant_config_cache_invalidated", tenant_id=str(tenant_id))

    def clear_cache(self) -> None:
        """Clear entire cache.

        Useful for testing or when making bulk configuration changes.
        """
        self._cache.clear()
        self._cache_timestamps.clear()
        logger.info("tenant_config_cache_cleared")

    def get_cached_tenant_ids(self) -> list[UUID]:
        """Get list of tenant IDs currently in cache.

        Useful for monitoring and debugging.
        """
        return list(self._cache.keys())


# Singleton instance
_config_service: TenantConfigService | None = None


def get_tenant_config_service() -> TenantConfigService:
    """Get singleton TenantConfigService instance.

    Creates the service on first call with default settings.

    Returns:
        The global TenantConfigService instance
    """
    global _config_service
    if _config_service is None:
        _config_service = TenantConfigService()
    return _config_service


def reset_tenant_config_service() -> None:
    """Reset the singleton instance.

    Primarily for testing purposes.
    """
    global _config_service
    _config_service = None

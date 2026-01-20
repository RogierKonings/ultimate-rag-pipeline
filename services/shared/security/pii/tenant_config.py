"""Tenant-specific PII configuration service.

Provides loading, caching, and management of per-tenant PII settings
stored in the Tenant.settings JSONB column.
"""

import asyncio
import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import PIIEntityConfig, PIIHandlingMode, PIISettings
from .detector import PIIDetector
from .response_filter import PIIQueryFilter, PIIResponseFilter

logger = logging.getLogger(__name__)


# Default PII settings when tenant has no configuration
DEFAULT_PII_CONFIG: dict[str, Any] = {
    "enabled": True,
    "default_handling_mode": "flag",
    "confidence_threshold": 0.7,
    "ingestion": {
        "enabled": True,
        "handling_mode": None,
        "reject_on_high_sensitivity": False,
        "store_pii_metadata": True,
    },
    "query": {
        "enabled": True,
        "handling_mode": None,
        "redact_in_logs": True,
        "reject_queries_with_pii": False,
    },
    "response": {
        "enabled": True,
        "handling_mode": None,
        "block_on_high_sensitivity": False,
    },
    "entity_configs": {},
    "custom_patterns": [],
}


class TenantPIIConfigService:
    """Service for loading and caching tenant-specific PII configuration.

    Provides efficient access to tenant PII settings with in-memory caching.
    Settings are merged with system defaults when loaded.

    Example:
        ```python
        service = TenantPIIConfigService(cache_ttl_seconds=300)

        # Get settings for a tenant
        settings = await service.get_pii_settings(tenant_id, session)

        # Get a configured detector
        detector = await service.get_detector(tenant_id, session)
        result = await detector.detect("some text")

        # Invalidate cache after settings change
        service.invalidate_cache(tenant_id)
        ```
    """

    def __init__(self, cache_ttl_seconds: int = 300):
        """Initialize the config service.

        Args:
            cache_ttl_seconds: Time-to-live for cached configs (default 5 min).
        """
        self._cache: dict[UUID, PIISettings] = {}
        self._cache_ttl = cache_ttl_seconds
        self._cache_timestamps: dict[UUID, float] = {}
        self._raw_config_cache: dict[UUID, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get_pii_settings(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> PIISettings:
        """Get merged PII settings for tenant.

        Loads tenant configuration from database and merges with defaults.
        Results are cached for performance.

        Args:
            tenant_id: Tenant UUID
            session: Database session

        Returns:
            PIISettings configured for the tenant
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

            raw_config = await self._load_raw_config(tenant_id, session)
            settings = self._build_settings(raw_config)

            self._cache[tenant_id] = settings
            self._raw_config_cache[tenant_id] = raw_config
            self._cache_timestamps[tenant_id] = now

            logger.debug(
                "tenant_pii_config_cached",
                extra={
                    "tenant_id": str(tenant_id),
                    "enabled": settings.enabled,
                    "handling_mode": settings.default_handling_mode.value,
                },
            )

            return settings

    async def get_raw_config(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> dict[str, Any]:
        """Get raw PII configuration dict for tenant.

        Useful for API responses where we need the original structure.

        Args:
            tenant_id: Tenant UUID
            session: Database session

        Returns:
            Raw configuration dict merged with defaults
        """
        now = time.time()

        # Check cache
        if tenant_id in self._raw_config_cache:
            timestamp = self._cache_timestamps.get(tenant_id, 0)
            if now - timestamp < self._cache_ttl:
                return self._raw_config_cache[tenant_id]

        # Load and cache
        await self.get_pii_settings(tenant_id, session)
        return self._raw_config_cache[tenant_id]

    async def _load_raw_config(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> dict[str, Any]:
        """Load raw PII config from database and merge with defaults."""
        from database.models import Tenant

        result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()

        if tenant is None:
            logger.warning(
                "tenant_not_found_using_pii_defaults",
                extra={"tenant_id": str(tenant_id)},
            )
            return DEFAULT_PII_CONFIG.copy()

        # Get PII config from settings, default to empty dict
        tenant_pii_config = (tenant.settings or {}).get("pii", {})

        # Deep merge with defaults
        return self._merge_configs(DEFAULT_PII_CONFIG, tenant_pii_config)

    def _merge_configs(
        self,
        defaults: dict[str, Any],
        overrides: dict[str, Any],
    ) -> dict[str, Any]:
        """Deep merge override config into defaults."""
        result = defaults.copy()

        for key, value in overrides.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value

        return result

    def _build_settings(self, raw_config: dict[str, Any]) -> PIISettings:
        """Build PIISettings from raw config dict."""
        # Convert entity configs (handle None values from tenant overrides)
        entity_configs = {}
        entity_configs_raw = raw_config.get("entity_configs") or {}
        for entity_type, config in entity_configs_raw.items():
            handling_mode = None
            if config.get("handling_mode"):
                handling_mode = PIIHandlingMode(config["handling_mode"])

            entity_configs[entity_type] = PIIEntityConfig(
                enabled=config.get("enabled", True),
                handling_mode=handling_mode,
                min_score=config.get("min_score"),
            )

        # Get handling mode
        default_mode = PIIHandlingMode(raw_config.get("default_handling_mode", "flag"))

        # Build settings (handle None values from tenant overrides)
        ingestion_config = raw_config.get("ingestion") or {}
        return PIISettings(
            enabled=raw_config.get("enabled", True),
            default_handling_mode=default_mode,
            confidence_threshold=raw_config.get("confidence_threshold", 0.7),
            entity_configs=entity_configs,
            reject_on_high_sensitivity=ingestion_config.get("reject_on_high_sensitivity", False),
            store_pii_metadata=ingestion_config.get("store_pii_metadata", True),
            log_detections=True,
        )

    async def get_detector(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> PIIDetector:
        """Get a configured PIIDetector for tenant.

        Args:
            tenant_id: Tenant UUID
            session: Database session

        Returns:
            PIIDetector configured with tenant settings
        """
        settings = await self.get_pii_settings(tenant_id, session)
        detector = PIIDetector(settings)

        # Load custom patterns if any (handle None values from tenant overrides)
        raw_config = await self.get_raw_config(tenant_id, session)
        custom_patterns = raw_config.get("custom_patterns") or []

        for pattern in custom_patterns:
            detector.add_custom_pattern(
                tenant_id=str(tenant_id),
                name=pattern["name"],
                pattern=pattern["pattern"],
                entity_type=pattern.get("entity_type", "CUSTOM"),
                score=pattern.get("score", 0.85),
            )

        return detector

    async def get_response_filter(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> PIIResponseFilter:
        """Get a configured PIIResponseFilter for tenant.

        Args:
            tenant_id: Tenant UUID
            session: Database session

        Returns:
            PIIResponseFilter configured with tenant settings
        """
        settings = await self.get_pii_settings(tenant_id, session)
        detector = await self.get_detector(tenant_id, session)
        return PIIResponseFilter(settings=settings, detector=detector)

    async def get_query_filter(
        self,
        tenant_id: UUID,
        session: AsyncSession,
    ) -> PIIQueryFilter:
        """Get a configured PIIQueryFilter for tenant.

        Args:
            tenant_id: Tenant UUID
            session: Database session

        Returns:
            PIIQueryFilter configured with tenant settings
        """
        settings = await self.get_pii_settings(tenant_id, session)
        detector = await self.get_detector(tenant_id, session)
        return PIIQueryFilter(settings=settings, detector=detector)

    async def update_tenant_config(
        self,
        tenant_id: UUID,
        session: AsyncSession,
        updates: dict[str, Any],
        merge: bool = True,
    ) -> dict[str, Any]:
        """Update tenant PII configuration.

        Args:
            tenant_id: Tenant UUID
            session: Database session
            updates: Configuration updates
            merge: If True, merge with existing. If False, replace entirely.

        Returns:
            Updated configuration
        """
        from database.models import Tenant

        result = await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()

        if tenant is None:
            raise ValueError(f"Tenant not found: {tenant_id}")

        # Get current settings
        current_settings = tenant.settings or {}
        current_pii = current_settings.get("pii", {})

        # Deep merge or replace entirely
        new_pii = self._merge_configs(current_pii, updates) if merge else updates

        # Update tenant settings
        current_settings["pii"] = new_pii
        tenant.settings = current_settings

        await session.flush()

        # Invalidate cache
        self.invalidate_cache(tenant_id)

        logger.info(
            "tenant_pii_config_updated",
            extra={
                "tenant_id": str(tenant_id),
                "merge": merge,
            },
        )

        # Return merged with defaults for consistency
        return self._merge_configs(DEFAULT_PII_CONFIG, new_pii)

    async def add_custom_pattern(
        self,
        tenant_id: UUID,
        session: AsyncSession,
        name: str,
        pattern: str,
        entity_type: str,
        score: float = 0.85,
    ) -> dict[str, Any]:
        """Add a custom pattern to tenant configuration.

        Args:
            tenant_id: Tenant UUID
            session: Database session
            name: Pattern name (must be unique for tenant)
            pattern: Regex pattern
            entity_type: Entity type for matches
            score: Confidence score

        Returns:
            Updated configuration
        """
        raw_config = await self.get_raw_config(tenant_id, session)
        patterns = raw_config.get("custom_patterns") or []

        # Check for duplicate name
        if any(p["name"] == name for p in patterns):
            raise ValueError(f"Pattern with name '{name}' already exists")

        # Add new pattern
        patterns.append(
            {
                "name": name,
                "pattern": pattern,
                "entity_type": entity_type,
                "score": score,
            }
        )

        return await self.update_tenant_config(
            tenant_id,
            session,
            {"custom_patterns": patterns},
            merge=True,
        )

    async def remove_custom_pattern(
        self,
        tenant_id: UUID,
        session: AsyncSession,
        pattern_name: str,
    ) -> dict[str, Any]:
        """Remove a custom pattern from tenant configuration.

        Args:
            tenant_id: Tenant UUID
            session: Database session
            pattern_name: Name of pattern to remove

        Returns:
            Updated configuration
        """
        raw_config = await self.get_raw_config(tenant_id, session)
        patterns = raw_config.get("custom_patterns") or []

        # Find and remove pattern
        new_patterns = [p for p in patterns if p["name"] != pattern_name]

        if len(new_patterns) == len(patterns):
            raise ValueError(f"Pattern with name '{pattern_name}' not found")

        return await self.update_tenant_config(
            tenant_id,
            session,
            {"custom_patterns": new_patterns},
            merge=True,
        )

    def invalidate_cache(self, tenant_id: UUID) -> None:
        """Invalidate cached config for tenant.

        Call this after updating tenant PII settings.

        Args:
            tenant_id: Tenant UUID to invalidate
        """
        self._cache.pop(tenant_id, None)
        self._raw_config_cache.pop(tenant_id, None)
        self._cache_timestamps.pop(tenant_id, None)
        logger.info(
            "tenant_pii_config_cache_invalidated",
            extra={"tenant_id": str(tenant_id)},
        )

    def clear_cache(self) -> None:
        """Clear entire cache."""
        self._cache.clear()
        self._raw_config_cache.clear()
        self._cache_timestamps.clear()
        logger.info("tenant_pii_config_cache_cleared")

    def get_cached_tenant_ids(self) -> list[UUID]:
        """Get list of tenant IDs currently in cache."""
        return list(self._cache.keys())


# Global singleton instance
_tenant_pii_config_service: TenantPIIConfigService | None = None


def get_tenant_pii_config_service() -> TenantPIIConfigService:
    """Get or create the global TenantPIIConfigService instance."""
    global _tenant_pii_config_service
    if _tenant_pii_config_service is None:
        _tenant_pii_config_service = TenantPIIConfigService()
    return _tenant_pii_config_service


def reset_tenant_pii_config_service() -> None:
    """Reset the global service instance (for testing)."""
    global _tenant_pii_config_service
    if _tenant_pii_config_service is not None:
        _tenant_pii_config_service.clear_cache()
    _tenant_pii_config_service = None

"""Tenant configuration and isolation utilities.

This module provides services for managing tenant index configuration
with caching for fast routing decisions during ingestion and retrieval.
"""

from tenant.config_service import (
    TenantConfigService,
    TenantIndexConfig,
    get_tenant_config_service,
)

__all__ = [
    "TenantConfigService",
    "TenantIndexConfig",
    "get_tenant_config_service",
]

"""Tests for tenant PII configuration service.

Tests the TenantPIIConfigService for loading, caching, and managing
per-tenant PII settings.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.shared.security.pii import (
    PIIHandlingMode,
    PIISettings,
    TenantPIIConfigService,
    reset_tenant_pii_config_service,
)
from services.shared.security.pii.tenant_config import DEFAULT_PII_CONFIG


@pytest.fixture
def config_service():
    """Create a fresh config service for each test."""
    reset_tenant_pii_config_service()
    return TenantPIIConfigService(cache_ttl_seconds=300)


@pytest.fixture
def mock_session():
    """Create a mock async database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_tenant_no_pii_config():
    """Create a mock tenant with no PII config."""
    tenant = MagicMock()
    tenant.id = uuid4()
    tenant.settings = {}
    return tenant


@pytest.fixture
def mock_tenant_with_pii_config():
    """Create a mock tenant with PII config."""
    tenant = MagicMock()
    tenant.id = uuid4()
    tenant.settings = {
        "pii": {
            "enabled": True,
            "default_handling_mode": "redact",
            "confidence_threshold": 0.8,
            "ingestion": {
                "reject_on_high_sensitivity": True,
            },
            "entity_configs": {
                "US_SSN": {
                    "enabled": True,
                    "handling_mode": "reject",
                    "min_score": 0.95,
                },
            },
            "custom_patterns": [
                {
                    "name": "employee_id",
                    "pattern": "EMP-\\d{6}",
                    "entity_type": "EMPLOYEE_ID",
                    "score": 0.85,
                },
            ],
        },
    }
    return tenant


class TestTenantPIIConfigService:
    """Tests for TenantPIIConfigService."""

    @pytest.mark.asyncio
    async def test_get_settings_for_tenant_not_found(
        self,
        config_service,
        mock_session,
    ):
        """Test that missing tenant returns default settings."""
        tenant_id = uuid4()

        # Mock no tenant found
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with patch("services.shared.security.pii.tenant_config.select"):
            settings = await config_service.get_pii_settings(tenant_id, mock_session)

        assert isinstance(settings, PIISettings)
        assert settings.enabled is True
        assert settings.default_handling_mode == PIIHandlingMode.FLAG

    @pytest.mark.asyncio
    async def test_get_settings_for_tenant_no_pii_config(
        self,
        config_service,
        mock_session,
        mock_tenant_no_pii_config,
    ):
        """Test tenant with no PII config uses defaults."""
        tenant_id = mock_tenant_no_pii_config.id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant_no_pii_config
        mock_session.execute.return_value = mock_result

        with patch("services.shared.security.pii.tenant_config.select"):
            settings = await config_service.get_pii_settings(tenant_id, mock_session)

        assert settings.enabled is True
        assert settings.default_handling_mode == PIIHandlingMode.FLAG
        assert settings.confidence_threshold == 0.7

    @pytest.mark.asyncio
    async def test_get_settings_for_tenant_with_config(
        self,
        config_service,
        mock_session,
        mock_tenant_with_pii_config,
    ):
        """Test tenant with PII config uses merged settings."""
        tenant_id = mock_tenant_with_pii_config.id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant_with_pii_config
        mock_session.execute.return_value = mock_result

        with patch("services.shared.security.pii.tenant_config.select"):
            settings = await config_service.get_pii_settings(tenant_id, mock_session)

        assert settings.enabled is True
        assert settings.default_handling_mode == PIIHandlingMode.REDACT
        assert settings.confidence_threshold == 0.8
        assert settings.reject_on_high_sensitivity is True

        # Check entity config
        assert "US_SSN" in settings.entity_configs
        assert settings.entity_configs["US_SSN"].handling_mode == PIIHandlingMode.REJECT
        assert settings.entity_configs["US_SSN"].min_score == 0.95

    @pytest.mark.asyncio
    async def test_cache_hit(
        self,
        config_service,
        mock_session,
        mock_tenant_with_pii_config,
    ):
        """Test that second call uses cached settings."""
        tenant_id = mock_tenant_with_pii_config.id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant_with_pii_config
        mock_session.execute.return_value = mock_result

        with patch("services.shared.security.pii.tenant_config.select"):
            # First call - loads from DB
            settings1 = await config_service.get_pii_settings(tenant_id, mock_session)

            # Second call - should use cache
            settings2 = await config_service.get_pii_settings(tenant_id, mock_session)

        # Should only have queried DB once
        assert mock_session.execute.call_count == 1
        assert settings1 is settings2

    @pytest.mark.asyncio
    async def test_cache_invalidation(
        self,
        config_service,
        mock_session,
        mock_tenant_with_pii_config,
    ):
        """Test that cache invalidation causes reload."""
        tenant_id = mock_tenant_with_pii_config.id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant_with_pii_config
        mock_session.execute.return_value = mock_result

        with patch("services.shared.security.pii.tenant_config.select"):
            # First call
            await config_service.get_pii_settings(tenant_id, mock_session)

            # Invalidate cache
            config_service.invalidate_cache(tenant_id)

            # Second call - should reload
            await config_service.get_pii_settings(tenant_id, mock_session)

        # Should have queried DB twice
        assert mock_session.execute.call_count == 2

    def test_clear_cache(self, config_service):
        """Test clearing entire cache."""
        # Add some fake cached data
        tenant_id = uuid4()
        config_service._cache[tenant_id] = PIISettings()
        config_service._cache_timestamps[tenant_id] = 1234567890.0

        config_service.clear_cache()

        assert len(config_service._cache) == 0
        assert len(config_service._cache_timestamps) == 0

    def test_get_cached_tenant_ids(self, config_service):
        """Test getting list of cached tenant IDs."""
        tenant1 = uuid4()
        tenant2 = uuid4()

        config_service._cache[tenant1] = PIISettings()
        config_service._cache[tenant2] = PIISettings()

        cached_ids = config_service.get_cached_tenant_ids()

        assert tenant1 in cached_ids
        assert tenant2 in cached_ids
        assert len(cached_ids) == 2


class TestTenantPIIConfigMerging:
    """Tests for configuration merging logic."""

    @pytest.fixture
    def config_service(self):
        """Create a fresh config service."""
        return TenantPIIConfigService()

    def test_merge_configs_shallow(self, config_service):
        """Test merging shallow config values."""
        defaults = {"enabled": True, "threshold": 0.7}
        overrides = {"threshold": 0.9}

        merged = config_service._merge_configs(defaults, overrides)

        assert merged["enabled"] is True
        assert merged["threshold"] == 0.9

    def test_merge_configs_deep(self, config_service):
        """Test merging nested config values."""
        defaults = {
            "enabled": True,
            "ingestion": {
                "enabled": True,
                "handling_mode": None,
                "reject_on_high_sensitivity": False,
            },
        }
        overrides = {
            "ingestion": {
                "reject_on_high_sensitivity": True,
            },
        }

        merged = config_service._merge_configs(defaults, overrides)

        assert merged["enabled"] is True
        assert merged["ingestion"]["enabled"] is True
        assert merged["ingestion"]["handling_mode"] is None
        assert merged["ingestion"]["reject_on_high_sensitivity"] is True

    def test_merge_configs_preserves_defaults(self, config_service):
        """Test that empty overrides preserve defaults."""
        merged = config_service._merge_configs(DEFAULT_PII_CONFIG, {})

        assert merged == DEFAULT_PII_CONFIG


class TestTenantPIIConfigUpdate:
    """Tests for configuration update functionality."""

    @pytest.fixture
    def config_service(self):
        """Create a fresh config service."""
        return TenantPIIConfigService()

    @pytest.mark.asyncio
    async def test_update_tenant_config_merge(
        self,
        config_service,
        mock_session,
        mock_tenant_no_pii_config,
    ):
        """Test updating tenant config with merge."""
        tenant_id = mock_tenant_no_pii_config.id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant_no_pii_config
        mock_session.execute.return_value = mock_result

        updates = {"enabled": False, "confidence_threshold": 0.9}

        with patch("services.shared.security.pii.tenant_config.select"):
            config = await config_service.update_tenant_config(
                tenant_id,
                mock_session,
                updates,
                merge=True,
            )

        assert config["enabled"] is False
        assert config["confidence_threshold"] == 0.9
        # Should have merged with defaults
        assert "ingestion" in config
        assert "query" in config
        assert "response" in config

    @pytest.mark.asyncio
    async def test_update_tenant_config_replace(
        self,
        config_service,
        mock_session,
        mock_tenant_with_pii_config,
    ):
        """Test updating tenant config with replace."""
        tenant_id = mock_tenant_with_pii_config.id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant_with_pii_config
        mock_session.execute.return_value = mock_result

        updates = {"enabled": False}

        with patch("services.shared.security.pii.tenant_config.select"):
            config = await config_service.update_tenant_config(
                tenant_id,
                mock_session,
                updates,
                merge=False,  # Replace, not merge
            )

        assert config["enabled"] is False
        # Should have merged with defaults (since we always merge with defaults)
        assert "ingestion" in config

    @pytest.mark.asyncio
    async def test_update_tenant_not_found(
        self,
        config_service,
        mock_session,
    ):
        """Test update fails for non-existent tenant."""
        tenant_id = uuid4()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        with (
            patch("services.shared.security.pii.tenant_config.select"),
            pytest.raises(ValueError, match="Tenant not found"),
        ):
            await config_service.update_tenant_config(
                tenant_id,
                mock_session,
                {"enabled": False},
            )


class TestCustomPatterns:
    """Tests for custom pattern management."""

    @pytest.fixture
    def config_service(self):
        """Create a fresh config service."""
        return TenantPIIConfigService()

    @pytest.mark.asyncio
    async def test_add_custom_pattern(
        self,
        config_service,
        mock_session,
        mock_tenant_no_pii_config,
    ):
        """Test adding a custom pattern."""
        tenant_id = mock_tenant_no_pii_config.id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant_no_pii_config
        mock_session.execute.return_value = mock_result

        with patch("services.shared.security.pii.tenant_config.select"):
            # Prime the cache
            await config_service.get_raw_config(tenant_id, mock_session)

            config = await config_service.add_custom_pattern(
                tenant_id,
                mock_session,
                name="test_pattern",
                pattern="TEST-\\d+",
                entity_type="TEST_ID",
                score=0.9,
            )

        assert len(config["custom_patterns"]) == 1
        assert config["custom_patterns"][0]["name"] == "test_pattern"
        assert config["custom_patterns"][0]["pattern"] == "TEST-\\d+"
        assert config["custom_patterns"][0]["entity_type"] == "TEST_ID"
        assert config["custom_patterns"][0]["score"] == 0.9

    @pytest.mark.asyncio
    async def test_add_duplicate_pattern_fails(
        self,
        config_service,
        mock_session,
        mock_tenant_with_pii_config,
    ):
        """Test adding duplicate pattern name fails."""
        tenant_id = mock_tenant_with_pii_config.id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant_with_pii_config
        mock_session.execute.return_value = mock_result

        with patch("services.shared.security.pii.tenant_config.select"):
            # Prime the cache
            await config_service.get_raw_config(tenant_id, mock_session)

            with pytest.raises(ValueError, match="already exists"):
                await config_service.add_custom_pattern(
                    tenant_id,
                    mock_session,
                    name="employee_id",  # Already exists in fixture
                    pattern="EMP-\\d+",
                    entity_type="EMPLOYEE_ID",
                )

    @pytest.mark.asyncio
    async def test_remove_custom_pattern(
        self,
        config_service,
        mock_session,
        mock_tenant_with_pii_config,
    ):
        """Test removing a custom pattern."""
        tenant_id = mock_tenant_with_pii_config.id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant_with_pii_config
        mock_session.execute.return_value = mock_result

        with patch("services.shared.security.pii.tenant_config.select"):
            # Prime the cache
            await config_service.get_raw_config(tenant_id, mock_session)

            config = await config_service.remove_custom_pattern(
                tenant_id,
                mock_session,
                pattern_name="employee_id",
            )

        assert len(config["custom_patterns"]) == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent_pattern_fails(
        self,
        config_service,
        mock_session,
        mock_tenant_no_pii_config,
    ):
        """Test removing non-existent pattern fails."""
        tenant_id = mock_tenant_no_pii_config.id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant_no_pii_config
        mock_session.execute.return_value = mock_result

        with patch("services.shared.security.pii.tenant_config.select"):
            # Prime the cache
            await config_service.get_raw_config(tenant_id, mock_session)

            with pytest.raises(ValueError, match="not found"):
                await config_service.remove_custom_pattern(
                    tenant_id,
                    mock_session,
                    pattern_name="nonexistent",
                )


class TestDetectorFactory:
    """Tests for detector factory methods."""

    @pytest.fixture
    def config_service(self):
        """Create a fresh config service."""
        return TenantPIIConfigService()

    @pytest.mark.asyncio
    async def test_get_detector(
        self,
        config_service,
        mock_session,
        mock_tenant_with_pii_config,
    ):
        """Test getting a configured detector."""
        tenant_id = mock_tenant_with_pii_config.id

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_tenant_with_pii_config
        mock_session.execute.return_value = mock_result

        with patch("services.shared.security.pii.tenant_config.select"):
            detector = await config_service.get_detector(tenant_id, mock_session)

        from services.shared.security.pii import PIIDetector

        assert isinstance(detector, PIIDetector)
        assert detector.settings.default_handling_mode == PIIHandlingMode.REDACT
        assert detector.settings.confidence_threshold == 0.8

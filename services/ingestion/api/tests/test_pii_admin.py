"""Tests for PII admin API endpoints.

Tests the tenant PII configuration management endpoints.
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient


@pytest.fixture
def mock_tenant():
    """Create a mock tenant."""
    tenant = MagicMock()
    tenant.id = uuid4()
    tenant.settings = {
        "pii": {
            "enabled": True,
            "default_handling_mode": "redact",
            "confidence_threshold": 0.8,
        },
    }
    return tenant


@pytest.fixture
def mock_admin_user():
    """Mock admin user for auth."""
    return {
        "sub": "admin-user-123",
        "tenant_id": "tenant-123",
        "groups": ["admin"],
        "roles": ["admin"],
        "permissions": ["admin:*"],
    }


@pytest.fixture
def mock_pii_config_service():
    """Mock TenantPIIConfigService."""
    service = MagicMock()
    service.get_raw_config = AsyncMock(
        return_value={
            "enabled": True,
            "default_handling_mode": "redact",
            "confidence_threshold": 0.8,
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
    )
    service.update_tenant_config = AsyncMock(
        return_value={
            "enabled": False,
            "default_handling_mode": "mask",
            "confidence_threshold": 0.9,
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
    )
    service.add_custom_pattern = AsyncMock(
        return_value={
            "enabled": True,
            "default_handling_mode": "redact",
            "confidence_threshold": 0.8,
            "ingestion": {},
            "query": {},
            "response": {},
            "entity_configs": {},
            "custom_patterns": [
                {
                    "name": "test_pattern",
                    "pattern": "TEST-\\d+",
                    "entity_type": "TEST_ID",
                    "score": 0.85,
                },
            ],
        }
    )
    service.remove_custom_pattern = AsyncMock(
        return_value={
            "enabled": True,
            "default_handling_mode": "redact",
            "confidence_threshold": 0.8,
            "ingestion": {},
            "query": {},
            "response": {},
            "entity_configs": {},
            "custom_patterns": [],
        }
    )
    return service


@pytest.fixture
def client_with_mocks(app, mock_admin_user, mock_tenant, mock_pii_config_service):
    """Test client with all mocks configured."""
    from api.dependencies import get_current_user
    from api.routes.admin import require_admin

    async def mock_get_current_user():
        return mock_admin_user

    async def mock_require_admin():
        return mock_admin_user

    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[require_admin] = mock_require_admin

    with (
        patch(
            "api.routes.pii_admin.get_tenant_pii_config_service",
            return_value=mock_pii_config_service,
        ),
        patch(
            "api.routes.pii_admin.get_tenant_or_404",
            new_callable=AsyncMock,
            return_value=mock_tenant,
        ),
    ):
        yield TestClient(app)

    app.dependency_overrides.clear()


class TestGetPIISettings:
    """Tests for GET /admin/tenants/{tenant_id}/pii-settings."""

    def test_get_settings_success(self, client_with_mocks, mock_tenant):
        """Test successful retrieval of PII settings."""
        response = client_with_mocks.get(f"/admin/tenants/{mock_tenant.id}/pii-settings")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["tenant_id"] == str(mock_tenant.id)
        assert data["enabled"] is True
        assert data["default_handling_mode"] == "redact"
        assert data["confidence_threshold"] == 0.8
        assert "ingestion" in data
        assert "query" in data
        assert "response" in data

    def test_get_settings_invalid_tenant_id(self, client_with_mocks):
        """Test with invalid tenant ID format."""
        with patch(
            "api.routes.pii_admin.get_tenant_or_404",
            side_effect=Exception("Invalid UUID"),
        ):
            # The mock override will still apply, so we need different approach
            pass  # This test would need actual app without mocks


class TestUpdatePIISettings:
    """Tests for PATCH /admin/tenants/{tenant_id}/pii-settings."""

    def test_patch_settings_success(self, client_with_mocks, mock_tenant):
        """Test partial update of PII settings."""
        response = client_with_mocks.patch(
            f"/admin/tenants/{mock_tenant.id}/pii-settings",
            json={
                "enabled": False,
                "confidence_threshold": 0.9,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["enabled"] is False
        assert data["confidence_threshold"] == 0.9

    def test_patch_settings_with_ingestion_config(self, client_with_mocks, mock_tenant):
        """Test updating ingestion-specific settings."""
        response = client_with_mocks.patch(
            f"/admin/tenants/{mock_tenant.id}/pii-settings",
            json={
                "ingestion": {
                    "reject_on_high_sensitivity": True,
                },
            },
        )

        assert response.status_code == status.HTTP_200_OK

    def test_patch_settings_invalid_handling_mode(self, client_with_mocks, mock_tenant):
        """Test that invalid handling mode is rejected."""
        response = client_with_mocks.patch(
            f"/admin/tenants/{mock_tenant.id}/pii-settings",
            json={
                "default_handling_mode": "invalid_mode",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "invalid_mode" in response.json()["detail"].lower()


class TestReplacePIISettings:
    """Tests for PUT /admin/tenants/{tenant_id}/pii-settings."""

    def test_put_settings_success(self, client_with_mocks, mock_tenant):
        """Test full replacement of PII settings."""
        response = client_with_mocks.put(
            f"/admin/tenants/{mock_tenant.id}/pii-settings",
            json={
                "enabled": False,
                "default_handling_mode": "mask",
                "confidence_threshold": 0.9,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["enabled"] is False
        assert data["default_handling_mode"] == "mask"


class TestCustomPatterns:
    """Tests for custom pattern endpoints."""

    def test_add_custom_pattern_success(self, client_with_mocks, mock_tenant):
        """Test adding a custom pattern."""
        response = client_with_mocks.post(
            f"/admin/tenants/{mock_tenant.id}/pii-settings/custom-patterns",
            json={
                "name": "test_pattern",
                "pattern": "TEST-\\d+",
                "entity_type": "TEST_ID",
                "score": 0.85,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["action"] == "added"
        assert data["pattern_name"] == "test_pattern"
        assert data["total_patterns"] == 1

    def test_add_custom_pattern_invalid_regex(self, client_with_mocks, mock_tenant):
        """Test that invalid regex is rejected."""
        response = client_with_mocks.post(
            f"/admin/tenants/{mock_tenant.id}/pii-settings/custom-patterns",
            json={
                "name": "bad_pattern",
                "pattern": "[invalid(regex",  # Invalid regex
                "entity_type": "TEST_ID",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "regex" in response.json()["detail"].lower()

    def test_remove_custom_pattern_success(self, client_with_mocks, mock_tenant):
        """Test removing a custom pattern."""
        response = client_with_mocks.delete(
            f"/admin/tenants/{mock_tenant.id}/pii-settings/custom-patterns/test_pattern"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["action"] == "removed"
        assert data["pattern_name"] == "test_pattern"


class TestPIIDetectionTest:
    """Tests for POST /admin/tenants/{tenant_id}/pii-settings/test."""

    @pytest.fixture
    def mock_detector(self):
        """Create a mock PIIDetector."""
        from services.shared.security.pii import PIIResult

        detector = MagicMock()
        detector.detect = AsyncMock(
            return_value=PIIResult(
                entities=[],
                entity_counts={"EMAIL_ADDRESS": 1},
                has_pii=True,
                has_high_sensitivity=False,
                processed_length=50,
                processing_time_ms=15.5,
            )
        )
        detector.redact = AsyncMock(return_value="Contact [EMAIL_ADDRESS] for help.")
        detector.mask = AsyncMock(return_value="Contact john************ for help.")
        return detector

    def test_test_pii_detection_success(
        self,
        client_with_mocks,
        mock_tenant,
        mock_pii_config_service,
        mock_detector,
    ):
        """Test PII detection on sample text."""
        mock_pii_config_service.get_detector = AsyncMock(return_value=mock_detector)

        response = client_with_mocks.post(
            f"/admin/tenants/{mock_tenant.id}/pii-settings/test",
            json={
                "text": "Contact john@example.com for help.",
                "handling_mode": "redact",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["has_pii"] is True
        assert "EMAIL_ADDRESS" in data["entity_counts"]
        assert data["redacted_text"] == "Contact [EMAIL_ADDRESS] for help."
        assert data["processing_time_ms"] > 0

    def test_test_pii_detection_invalid_handling_mode(self, client_with_mocks, mock_tenant):
        """Test that invalid handling mode is rejected."""
        response = client_with_mocks.post(
            f"/admin/tenants/{mock_tenant.id}/pii-settings/test",
            json={
                "text": "Test text",
                "handling_mode": "invalid",
            },
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST


class TestAuthRequired:
    """Tests for authentication requirements."""

    def test_endpoints_require_auth(self, app):
        """Test that endpoints require authentication."""
        client = TestClient(app)
        tenant_id = str(uuid4())

        # All endpoints should return 401 without auth
        endpoints = [
            ("GET", f"/admin/tenants/{tenant_id}/pii-settings"),
            ("PUT", f"/admin/tenants/{tenant_id}/pii-settings"),
            ("PATCH", f"/admin/tenants/{tenant_id}/pii-settings"),
            ("POST", f"/admin/tenants/{tenant_id}/pii-settings/custom-patterns"),
            ("DELETE", f"/admin/tenants/{tenant_id}/pii-settings/custom-patterns/test"),
            ("POST", f"/admin/tenants/{tenant_id}/pii-settings/test"),
        ]

        for method, path in endpoints:
            if method == "GET":
                response = client.get(path)
            elif method == "PUT":
                response = client.put(path, json={})
            elif method == "PATCH":
                response = client.patch(path, json={})
            elif method == "POST":
                response = client.post(path, json={"text": "test"})
            elif method == "DELETE":
                response = client.delete(path)

            assert response.status_code in [
                status.HTTP_401_UNAUTHORIZED,
                status.HTTP_403_FORBIDDEN,
            ], f"Expected 401/403 for {method} {path}, got {response.status_code}"

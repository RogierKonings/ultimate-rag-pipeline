"""Tests for admin API endpoints.

Reference: US-10.5.4 - Token Usage Accounting
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from api.routes.admin import router
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create test FastAPI app."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def mock_db_session():
    """Create mock database session."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def mock_request():
    """Create mock FastAPI Request (no Redis available)."""
    req = MagicMock()
    req.app.state = MagicMock(spec=[])  # empty spec → no session_manager
    return req


class TestGetUsageStats:
    """Tests for GET /admin/usage/{tenant_id}."""

    @pytest.mark.asyncio
    async def test_get_usage_stats_empty(self, mock_db_session, mock_request):
        """Test getting usage stats when no data exists."""
        from api.routes.admin import get_usage_stats

        # Mock empty result
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = await get_usage_stats(
            tenant_id="tenant-123",
            request=mock_request,
            period="month",
            db=mock_db_session,
        )

        assert response.tenant_id == "tenant-123"
        assert response.period == "month"
        assert response.usage_by_model == []
        assert response.total_tokens == 0

    @pytest.mark.asyncio
    async def test_get_usage_stats_with_data(self, mock_db_session, mock_request):
        """Test getting usage stats with existing data."""
        from api.routes.admin import get_usage_stats

        # Mock result with data
        mock_row1 = MagicMock()
        mock_row1.model = "gpt-4"
        mock_row1.prompt_tokens = 1000
        mock_row1.completion_tokens = 500
        mock_row1.embedding_tokens = 200

        mock_row2 = MagicMock()
        mock_row2.model = "claude-3"
        mock_row2.prompt_tokens = 2000
        mock_row2.completion_tokens = 800
        mock_row2.embedding_tokens = 0

        mock_result = MagicMock()
        mock_result.all.return_value = [mock_row1, mock_row2]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = await get_usage_stats(
            tenant_id="tenant-123",
            request=mock_request,
            period="month",
            db=mock_db_session,
        )

        assert response.tenant_id == "tenant-123"
        assert len(response.usage_by_model) == 2
        assert response.total_prompt_tokens == 3000
        assert response.total_completion_tokens == 1300
        assert response.total_embedding_tokens == 200
        assert response.total_tokens == 4500

    @pytest.mark.asyncio
    async def test_get_usage_stats_day_period(self, mock_db_session, mock_request):
        """Test getting usage stats for day period."""
        from api.routes.admin import get_usage_stats

        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = await get_usage_stats(
            tenant_id="tenant-123",
            request=mock_request,
            period="day",
            db=mock_db_session,
        )

        assert response.period == "day"
        assert response.start_date == response.end_date

    @pytest.mark.asyncio
    async def test_get_usage_stats_week_period(self, mock_db_session, mock_request):
        """Test getting usage stats for week period."""
        from api.routes.admin import get_usage_stats

        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = await get_usage_stats(
            tenant_id="tenant-123",
            request=mock_request,
            period="week",
            db=mock_db_session,
        )

        assert response.period == "week"
        assert (response.end_date - response.start_date).days == 7


class TestGetQuotaStatus:
    """Tests for GET /admin/usage/{tenant_id}/quota."""

    @pytest.mark.asyncio
    async def test_get_quota_status_no_config(self, mock_db_session, mock_request):
        """Test getting quota status when no config exists."""
        from api.routes.admin import get_quota_status

        # Mock no quota config
        mock_quota_result = MagicMock()
        mock_quota_result.scalar_one_or_none.return_value = None

        # Mock usage result
        mock_usage_result = MagicMock()
        mock_usage_result.scalar.return_value = 50000

        mock_db_session.execute = AsyncMock(side_effect=[mock_quota_result, mock_usage_result])

        response = await get_quota_status(
            tenant_id="tenant-123",
            request=mock_request,
            db=mock_db_session,
        )

        assert response.tenant_id == "tenant-123"
        assert response.quota_enabled is False
        assert response.monthly_limit is None
        assert response.current_usage == 50000
        assert response.remaining is None
        assert response.is_over_limit is False

    @pytest.mark.asyncio
    async def test_get_quota_status_with_limit(self, mock_db_session, mock_request):
        """Test getting quota status with limit configured."""
        from api.routes.admin import get_quota_status

        # Mock quota config
        mock_quota = MagicMock()
        mock_quota.quota_enabled = True
        mock_quota.monthly_token_limit = 1000000
        mock_quota.alert_threshold_percent = 80

        mock_quota_result = MagicMock()
        mock_quota_result.scalar_one_or_none.return_value = mock_quota

        # Mock usage result
        mock_usage_result = MagicMock()
        mock_usage_result.scalar.return_value = 500000

        mock_db_session.execute = AsyncMock(side_effect=[mock_quota_result, mock_usage_result])

        response = await get_quota_status(
            tenant_id="tenant-123",
            request=mock_request,
            db=mock_db_session,
        )

        assert response.quota_enabled is True
        assert response.monthly_limit == 1000000
        assert response.current_usage == 500000
        assert response.remaining == 500000
        assert response.usage_percent == 50.0
        assert response.is_over_limit is False

    @pytest.mark.asyncio
    async def test_get_quota_status_over_limit(self, mock_db_session, mock_request):
        """Test getting quota status when over limit."""
        from api.routes.admin import get_quota_status

        # Mock quota config
        mock_quota = MagicMock()
        mock_quota.quota_enabled = True
        mock_quota.monthly_token_limit = 1000000
        mock_quota.alert_threshold_percent = 80

        mock_quota_result = MagicMock()
        mock_quota_result.scalar_one_or_none.return_value = mock_quota

        # Mock usage over limit
        mock_usage_result = MagicMock()
        mock_usage_result.scalar.return_value = 1200000

        mock_db_session.execute = AsyncMock(side_effect=[mock_quota_result, mock_usage_result])

        response = await get_quota_status(
            tenant_id="tenant-123",
            request=mock_request,
            db=mock_db_session,
        )

        assert response.current_usage == 1200000
        assert response.remaining == 0  # Clamped to 0
        assert response.usage_percent == 120.0
        assert response.is_over_limit is True


class TestSetQuota:
    """Tests for PUT /admin/usage/{tenant_id}/quota."""

    @pytest.mark.asyncio
    async def test_set_quota_create_new(self, mock_db_session):
        """Test creating new quota configuration."""
        from api.models.usage import QuotaUpdateRequest
        from api.routes.admin import set_quota

        # Mock no existing config
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        request = QuotaUpdateRequest(
            monthly_token_limit=1000000,
            quota_enabled=True,
            alert_threshold_percent=75,
        )

        response = await set_quota(
            tenant_id="tenant-123",
            request=request,
            db=mock_db_session,
        )

        assert response.tenant_id == "tenant-123"
        assert response.monthly_token_limit == 1000000
        assert response.quota_enabled is True
        assert response.alert_threshold_percent == 75
        mock_db_session.add.assert_called_once()
        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_quota_update_existing(self, mock_db_session):
        """Test updating existing quota configuration."""
        from api.models.usage import QuotaUpdateRequest
        from api.routes.admin import set_quota

        # Mock existing config
        mock_quota = MagicMock()
        mock_quota.monthly_token_limit = 500000
        mock_quota.quota_enabled = False
        mock_quota.alert_threshold_percent = 80

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_quota
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        request = QuotaUpdateRequest(
            monthly_token_limit=2000000,
            quota_enabled=True,
            alert_threshold_percent=90,
        )

        await set_quota(
            tenant_id="tenant-123",
            request=request,
            db=mock_db_session,
        )

        # Should update existing, not add new
        mock_db_session.add.assert_not_called()
        mock_db_session.commit.assert_called_once()

        # Verify updates
        assert mock_quota.monthly_token_limit == 2000000
        assert mock_quota.quota_enabled is True
        assert mock_quota.alert_threshold_percent == 90


class TestDeleteQuota:
    """Tests for DELETE /admin/usage/{tenant_id}/quota."""

    @pytest.mark.asyncio
    async def test_delete_quota_success(self, mock_db_session):
        """Test successful quota deletion."""
        from api.routes.admin import delete_quota

        # Mock existing config
        mock_quota = MagicMock()

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_quota
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        response = await delete_quota(
            tenant_id="tenant-123",
            db=mock_db_session,
        )

        assert response["tenant_id"] == "tenant-123"
        mock_db_session.delete.assert_called_once_with(mock_quota)
        mock_db_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_quota_not_found(self, mock_db_session):
        """Test deletion when no config exists."""
        from api.routes.admin import delete_quota
        from fastapi import HTTPException

        # Mock no config
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(HTTPException) as exc_info:
            await delete_quota(
                tenant_id="tenant-123",
                db=mock_db_session,
            )

        assert exc_info.value.status_code == 404

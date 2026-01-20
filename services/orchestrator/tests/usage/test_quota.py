"""Tests for quota enforcement.

Reference: US-10.5.4 - Token Usage Accounting
"""

import pytest
from usage.quota import QuotaExceededError


class TestQuotaExceededError:
    """Tests for QuotaExceededError exception."""

    def test_basic_error(self):
        """Test basic error creation."""
        error = QuotaExceededError(
            tenant_id="tenant-123",
            limit=1000000,
            used=1100000,
        )

        assert error.tenant_id == "tenant-123"
        assert error.limit == 1000000
        assert error.used == 1100000
        assert error.remaining == 0  # Can't go negative

    def test_error_message(self):
        """Test error message formatting."""
        error = QuotaExceededError(
            tenant_id="tenant-abc",
            limit=500000,
            used=600000,
        )

        assert "tenant-abc" in str(error)
        assert "600,000" in str(error)
        assert "500,000" in str(error)

    def test_remaining_calculation(self):
        """Test that remaining is calculated correctly."""
        error = QuotaExceededError(
            tenant_id="tenant-123",
            limit=1000,
            used=1500,
        )

        # Remaining should be 0, not negative
        assert error.remaining == 0

    def test_exact_limit(self):
        """Test when usage exactly matches limit."""
        error = QuotaExceededError(
            tenant_id="tenant-123",
            limit=1000,
            used=1000,
        )

        assert error.remaining == 0

    def test_just_over_limit(self):
        """Test when usage is just over limit."""
        error = QuotaExceededError(
            tenant_id="tenant-123",
            limit=1000,
            used=1001,
        )

        assert error.remaining == 0

    def test_exception_inheritance(self):
        """Test that error is a proper Exception."""
        error = QuotaExceededError(
            tenant_id="tenant-123",
            limit=1000,
            used=2000,
        )

        assert isinstance(error, Exception)

        # Can be raised and caught
        with pytest.raises(QuotaExceededError) as exc_info:
            raise error

        assert exc_info.value.tenant_id == "tenant-123"

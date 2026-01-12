"""
Unit tests for Security & Auth (US-5.8).

Tests JWT authentication, API key validation, and rate limiting.
"""

import time

import pytest
from gateway.security.auth import AuthConfig, AuthContext, JWTAuth
from gateway.security.rate_limit import RateLimitConfig, RateLimiter, RateLimitResult


class TestAuthContext:
    """Tests for AuthContext."""

    def test_auth_context_creation(self):
        """Test creating auth context."""
        context = AuthContext(
            tenant_id="tenant-123",
            user_id="user-456",
            roles=["admin", "user"],
            scopes=["read", "write"],
        )

        assert context.tenant_id == "tenant-123"
        assert context.user_id == "user-456"
        assert context.auth_method == "jwt"

    def test_has_role(self):
        """Test role checking."""
        context = AuthContext(
            tenant_id="t",
            user_id="u",
            roles=["admin", "user"],
        )

        assert context.has_role("admin") is True
        assert context.has_role("user") is True
        assert context.has_role("superadmin") is False

    def test_has_scope(self):
        """Test scope checking."""
        context = AuthContext(
            tenant_id="t",
            user_id="u",
            scopes=["read", "write"],
        )

        assert context.has_scope("read") is True
        assert context.has_scope("delete") is False

    def test_to_headers(self):
        """Test converting to headers."""
        context = AuthContext(
            tenant_id="tenant-123",
            user_id="user-456",
            roles=["admin"],
            auth_method="api_key",
        )

        headers = context.to_headers()

        assert headers["X-Tenant-ID"] == "tenant-123"
        assert headers["X-User-ID"] == "user-456"
        assert headers["X-Roles"] == "admin"
        assert headers["X-Auth-Method"] == "api_key"


class TestAuthConfig:
    """Tests for AuthConfig."""

    def test_default_config(self):
        """Test default auth configuration."""
        config = AuthConfig()

        assert config.jwt_algorithm == "RS256"
        assert config.api_keys_enabled is True
        assert config.require_auth is True
        assert "/health" in config.skip_paths

    def test_custom_config(self):
        """Test custom auth configuration."""
        config = AuthConfig(
            jwt_algorithm="HS256",
            jwt_secret="my-secret",
            jwt_issuer="https://auth.example.com",
            require_auth=False,
        )

        assert config.jwt_algorithm == "HS256"
        assert config.jwt_secret == "my-secret"
        assert config.jwt_issuer == "https://auth.example.com"
        assert config.require_auth is False


class TestJWTAuth:
    """Tests for JWTAuth."""

    @pytest.fixture
    def auth_with_secret(self):
        """Create JWTAuth with HS256 secret."""
        config = AuthConfig(
            jwt_algorithm="HS256",
            jwt_secret="test-secret-key-for-testing-only",
        )
        return JWTAuth(config)

    @pytest.fixture
    def auth_with_api_keys(self):
        """Create JWTAuth with API keys."""
        config = AuthConfig(
            api_keys={
                "test-key-123": {
                    "tenant_id": "tenant-1",
                    "user_id": "api-user-1",
                    "roles": ["api"],
                },
                "admin-key-456": {
                    "tenant_id": "tenant-1",
                    "user_id": "admin",
                    "roles": ["admin", "api"],
                },
            },
        )
        return JWTAuth(config)

    def test_is_path_public(self, auth_with_secret):
        """Test public path detection."""
        assert auth_with_secret.is_path_public("/health") is True
        assert auth_with_secret.is_path_public("/health/live") is True
        assert auth_with_secret.is_path_public("/docs") is True
        assert auth_with_secret.is_path_public("/v1/chat/completions") is False

    def test_validate_api_key_valid(self, auth_with_api_keys):
        """Test validating a valid API key."""
        context = auth_with_api_keys.validate_api_key("test-key-123")

        assert context is not None
        assert context.tenant_id == "tenant-1"
        assert context.user_id == "api-user-1"
        assert context.auth_method == "api_key"
        assert "api" in context.roles

    def test_validate_api_key_invalid(self, auth_with_api_keys):
        """Test validating an invalid API key."""
        context = auth_with_api_keys.validate_api_key("invalid-key")

        assert context is None

    def test_validate_api_key_disabled(self, auth_with_secret):
        """Test API key validation when disabled."""
        auth_with_secret.config.api_keys_enabled = False
        context = auth_with_secret.validate_api_key("any-key")

        assert context is None

    @pytest.mark.asyncio
    async def test_authenticate_with_api_key(self, auth_with_api_keys):
        """Test authentication with API key."""
        context = await auth_with_api_keys.authenticate(
            api_key="test-key-123",
        )

        assert context is not None
        assert context.tenant_id == "tenant-1"

    @pytest.mark.asyncio
    async def test_authenticate_no_credentials(self, auth_with_api_keys):
        """Test authentication with no credentials."""
        context = await auth_with_api_keys.authenticate()

        assert context is None

    @pytest.mark.asyncio
    async def test_validate_token_no_key(self, auth_with_secret):
        """Test token validation without signing key."""
        auth_with_secret.config.jwt_secret = None
        context = await auth_with_secret.validate_token("some.jwt.token")

        assert context is None


class TestRateLimitConfig:
    """Tests for RateLimitConfig."""

    def test_default_config(self):
        """Test default rate limit configuration."""
        config = RateLimitConfig()

        assert config.default_rpm == 60
        assert config.default_tpm == 100000
        assert config.burst_multiplier == 1.5

    def test_custom_config(self):
        """Test custom rate limit configuration."""
        config = RateLimitConfig(
            default_rpm=100,
            tenant_rpm={"premium": 500},
            user_rpm={"power-user": 200},
        )

        assert config.default_rpm == 100
        assert config.tenant_rpm["premium"] == 500
        assert config.user_rpm["power-user"] == 200


class TestRateLimitResult:
    """Tests for RateLimitResult."""

    def test_allowed_result(self):
        """Test allowed rate limit result."""
        result = RateLimitResult(
            allowed=True,
            remaining=59,
            limit=60,
            reset_at=time.time() + 60,
        )

        assert result.allowed is True
        assert result.remaining == 59
        assert result.retry_after is None

    def test_blocked_result(self):
        """Test blocked rate limit result."""
        result = RateLimitResult(
            allowed=False,
            remaining=0,
            limit=60,
            reset_at=time.time() + 30,
            retry_after=30,
        )

        assert result.allowed is False
        assert result.retry_after == 30

    def test_to_headers(self):
        """Test converting to headers."""
        result = RateLimitResult(
            allowed=True,
            remaining=50,
            limit=60,
            reset_at=1234567890,
        )

        headers = result.to_headers()

        assert headers["X-RateLimit-Limit"] == "60"
        assert headers["X-RateLimit-Remaining"] == "50"
        assert headers["X-RateLimit-Reset"] == "1234567890"
        assert "Retry-After" not in headers

    def test_to_headers_with_retry(self):
        """Test headers with retry-after."""
        result = RateLimitResult(
            allowed=False,
            remaining=0,
            limit=60,
            reset_at=1234567890,
            retry_after=30,
        )

        headers = result.to_headers()

        assert headers["Retry-After"] == "30"


class TestRateLimiter:
    """Tests for RateLimiter."""

    @pytest.fixture
    def rate_limiter(self):
        """Create a rate limiter."""
        config = RateLimitConfig(
            default_rpm=60,
            burst_multiplier=1.5,
            window_size_seconds=60,
        )
        return RateLimiter(config)

    @pytest.mark.asyncio
    async def test_check_rate_limit_allowed(self, rate_limiter):
        """Test rate limit check when allowed."""
        result = await rate_limiter.check_rate_limit(
            tenant_id="tenant-1",
            user_id="user-1",
        )

        assert result.allowed is True
        assert result.remaining > 0
        assert result.limit == 60

    @pytest.mark.asyncio
    async def test_check_rate_limit_burst(self, rate_limiter):
        """Test burst allowance."""
        # Make requests up to burst limit
        burst_limit = int(60 * 1.5)  # 90

        for i in range(burst_limit):
            result = await rate_limiter.check_rate_limit(
                tenant_id="burst-test",
            )
            assert result.allowed is True, f"Request {i+1} should be allowed"

        # Next request should be denied
        result = await rate_limiter.check_rate_limit(
            tenant_id="burst-test",
        )
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_check_rate_limit_exceeded(self, rate_limiter):
        """Test rate limit when exceeded."""
        tenant = "exceeded-tenant"

        # Exhaust rate limit
        for _ in range(100):  # More than burst
            await rate_limiter.check_rate_limit(tenant_id=tenant)

        result = await rate_limiter.check_rate_limit(tenant_id=tenant)

        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after is not None
        assert result.retry_after > 0

    @pytest.mark.asyncio
    async def test_check_rate_limit_different_tenants(self, rate_limiter):
        """Test rate limits are separate per tenant."""
        # Exhaust tenant-1
        for _ in range(100):
            await rate_limiter.check_rate_limit(tenant_id="tenant-1")

        # tenant-2 should still have allowance
        result = await rate_limiter.check_rate_limit(tenant_id="tenant-2")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_check_token_limit(self, rate_limiter):
        """Test token-based rate limiting."""
        result = await rate_limiter.check_token_limit(
            tenant_id="token-tenant",
            tokens=1000,
        )

        assert result.allowed is True
        # With burst_multiplier=1.5, effective limit is 150000 tokens
        # After using 1000, remaining should be 149000
        burst_adjusted_limit = int(
            rate_limiter.config.default_tpm * rate_limiter.config.burst_multiplier,
        )
        assert result.remaining < burst_adjusted_limit

    @pytest.mark.asyncio
    async def test_check_token_limit_exceeded(self, rate_limiter):
        """Test token limit when exceeded."""
        tenant = "token-exceeded"

        # Request more than limit
        result = await rate_limiter.check_token_limit(
            tenant_id=tenant,
            tokens=200000,  # More than 100000 TPM
        )

        assert result.allowed is False
        assert result.retry_after is not None

    def test_get_limit_defaults(self, rate_limiter):
        """Test getting default limits."""
        rpm = rate_limiter._get_limit("unknown-tenant", None, "rpm")
        tpm = rate_limiter._get_limit("unknown-tenant", None, "tpm")

        assert rpm == 60
        assert tpm == 100000

    def test_get_limit_tenant_override(self, rate_limiter):
        """Test tenant-specific limit override."""
        rate_limiter.config.tenant_rpm["premium"] = 500

        rpm = rate_limiter._get_limit("premium", None, "rpm")
        assert rpm == 500

    def test_get_limit_user_override(self, rate_limiter):
        """Test user-specific limit override."""
        rate_limiter.config.user_rpm["power-user"] = 200

        rpm = rate_limiter._get_limit("any-tenant", "power-user", "rpm")
        assert rpm == 200

    def test_get_usage_stats(self, rate_limiter):
        """Test getting usage statistics."""
        stats = rate_limiter.get_usage_stats(
            tenant_id="stats-tenant",
            user_id="stats-user",
        )

        assert "tenant_id" in stats
        assert "requests" in stats
        assert "tokens" in stats
        assert stats["requests"]["limit"] == 60

    @pytest.mark.asyncio
    async def test_reset_limits(self, rate_limiter):
        """Test resetting rate limits."""
        # Make some requests
        await rate_limiter.check_rate_limit(tenant_id="reset-tenant")
        await rate_limiter.check_rate_limit(tenant_id="reset-tenant")

        # Reset
        await rate_limiter.reset_limits(tenant_id="reset-tenant")

        # Should have full allowance again
        result = await rate_limiter.check_rate_limit(tenant_id="reset-tenant")
        assert result.remaining >= 60 * 1.5 - 1  # Near burst limit

    @pytest.mark.asyncio
    async def test_reset_all_limits(self, rate_limiter):
        """Test resetting all rate limits."""
        # Make requests for multiple tenants
        await rate_limiter.check_rate_limit(tenant_id="tenant-a")
        await rate_limiter.check_rate_limit(tenant_id="tenant-b")

        # Reset all
        await rate_limiter.reset_limits()

        # Both should have full allowance
        assert rate_limiter._buckets == {}

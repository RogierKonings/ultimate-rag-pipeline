"""
Tests for JWT authentication module.

This module tests JWT token creation, validation, refresh flows,
and middleware functionality.
"""

import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from services.shared.security.jwt import (
    InMemoryTokenBlocklist,
    JWTAlgorithm,
    JWTHandler,
    JWTSettings,
    TokenClaims,
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
    TokenType,
)

# Test data
TEST_USER_ID = uuid4()
TEST_TENANT_ID = uuid4()
TEST_ROLES = ["user", "analyst"]
TEST_GROUPS = ["engineering", "ml-team"]


@pytest.fixture
def jwt_settings_hs256():
    """JWT settings for HS256 (development)."""
    return JWTSettings(
        secret_key="test-secret-key-for-development-only-32chars",
        algorithm=JWTAlgorithm.HS256,
        access_token_expire_minutes=30,
        refresh_token_expire_days=7,
        issuer="test-issuer",
        audience="test-audience",
    )


@pytest.fixture
def jwt_handler(jwt_settings_hs256):
    """JWT handler with HS256 for testing."""
    return JWTHandler(jwt_settings_hs256)


@pytest.fixture
def jwt_handler_with_blocklist(jwt_settings_hs256):
    """JWT handler with blocklist enabled."""
    blocklist = InMemoryTokenBlocklist()
    return JWTHandler(jwt_settings_hs256, blocklist=blocklist), blocklist


@pytest.fixture
def sample_claims():
    """Sample token claims for testing."""
    return TokenClaims(
        sub=TEST_USER_ID,
        tenant_id=TEST_TENANT_ID,
        roles=TEST_ROLES,
        groups=TEST_GROUPS,
        email="test@example.com",
        name="Test User",
    )


class TestJWTSettings:
    """Tests for JWT settings configuration."""

    def test_default_settings(self):
        """Test default JWT settings."""
        settings = JWTSettings(secret_key="test-secret")
        assert settings.algorithm == JWTAlgorithm.RS256
        assert settings.access_token_expire_minutes == 30
        assert settings.refresh_token_expire_days == 7
        assert settings.issuer == "rag-pipeline"
        assert settings.audience == "rag-api"

    def test_hs256_settings(self):
        """Test HS256 algorithm settings."""
        settings = JWTSettings(
            secret_key="test-secret",
            algorithm=JWTAlgorithm.HS256,
        )
        assert not settings.is_asymmetric
        assert not settings.requires_private_key

    def test_rs256_settings(self):
        """Test RS256 algorithm settings."""
        settings = JWTSettings(algorithm=JWTAlgorithm.RS256)
        assert settings.is_asymmetric
        assert settings.requires_private_key

    def test_algorithm_validation(self):
        """Test algorithm string validation."""
        settings = JWTSettings(secret_key="test", algorithm="hs256")
        assert settings.algorithm == JWTAlgorithm.HS256


class TestTokenClaims:
    """Tests for token claims model."""

    def test_claims_creation(self, sample_claims):
        """Test creating token claims."""
        assert sample_claims.sub == TEST_USER_ID
        assert sample_claims.tenant_id == TEST_TENANT_ID
        assert sample_claims.roles == TEST_ROLES
        assert sample_claims.groups == TEST_GROUPS

    def test_claims_to_dict(self, sample_claims):
        """Test converting claims to dictionary."""
        data = sample_claims.to_dict()
        assert data["sub"] == str(TEST_USER_ID)
        assert data["tenant_id"] == str(TEST_TENANT_ID)
        assert data["roles"] == TEST_ROLES
        assert data["groups"] == TEST_GROUPS

    def test_claims_from_dict(self, sample_claims):
        """Test creating claims from dictionary."""
        data = sample_claims.to_dict()
        restored = TokenClaims.from_dict(data)
        assert restored.sub == sample_claims.sub
        assert restored.tenant_id == sample_claims.tenant_id
        assert restored.roles == sample_claims.roles

    def test_claims_role_check(self, sample_claims):
        """Test role checking methods."""
        assert sample_claims.has_role("user")
        assert sample_claims.has_role("analyst")
        assert not sample_claims.has_role("admin")
        assert not sample_claims.is_admin()

    def test_claims_group_membership(self, sample_claims):
        """Test group membership checking."""
        assert sample_claims.is_member_of("engineering")
        assert not sample_claims.is_member_of("finance")


class TestJWTHandler:
    """Tests for JWT handler."""

    def test_create_access_token(self, jwt_handler, sample_claims):
        """Test creating an access token."""
        token = jwt_handler.create_access_token(sample_claims)
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_create_refresh_token(self, jwt_handler, sample_claims):
        """Test creating a refresh token."""
        token = jwt_handler.create_refresh_token(sample_claims)
        assert token is not None
        assert isinstance(token, str)

    def test_create_token_pair(self, jwt_handler, sample_claims):
        """Test creating a token pair."""
        pair = jwt_handler.create_token_pair(sample_claims)
        assert pair.access_token is not None
        assert pair.refresh_token is not None
        assert pair.token_type == "Bearer"
        assert pair.expires_in == 30 * 60  # 30 minutes in seconds

    def test_verify_access_token(self, jwt_handler, sample_claims):
        """Test verifying an access token."""
        token = jwt_handler.create_access_token(sample_claims)
        verified = jwt_handler.verify_token(token, expected_type=TokenType.ACCESS)

        assert verified.sub == sample_claims.sub
        assert verified.tenant_id == sample_claims.tenant_id
        assert verified.roles == sample_claims.roles
        assert verified.groups == sample_claims.groups
        assert verified.token_type == TokenType.ACCESS

    def test_verify_refresh_token(self, jwt_handler, sample_claims):
        """Test verifying a refresh token."""
        token = jwt_handler.create_refresh_token(sample_claims)
        verified = jwt_handler.verify_token(token, expected_type=TokenType.REFRESH)

        assert verified.sub == sample_claims.sub
        assert verified.token_type == TokenType.REFRESH

    def test_verify_token_wrong_type(self, jwt_handler, sample_claims):
        """Test that verifying with wrong token type fails."""
        access_token = jwt_handler.create_access_token(sample_claims)

        with pytest.raises(TokenInvalidError, match="Expected refresh token"):
            jwt_handler.verify_token(access_token, expected_type=TokenType.REFRESH)

    def test_verify_expired_token(self, jwt_handler, sample_claims):
        """Test that expired tokens are rejected."""
        # Create token that expires immediately
        token = jwt_handler.create_access_token(
            sample_claims, expires_delta=timedelta(seconds=-1),
        )

        with pytest.raises(TokenExpiredError):
            jwt_handler.verify_token(token)

    def test_verify_invalid_signature(self, jwt_handler, sample_claims):
        """Test that tokens with invalid signatures are rejected."""
        token = jwt_handler.create_access_token(sample_claims)
        # Tamper with the token
        tampered = token[:-5] + "xxxxx"

        with pytest.raises(TokenInvalidError):
            jwt_handler.verify_token(tampered)

    def test_verify_malformed_token(self, jwt_handler):
        """Test that malformed tokens are rejected."""
        with pytest.raises(TokenInvalidError):
            jwt_handler.verify_token("not-a-valid-token")

    def test_refresh_tokens(self, jwt_handler, sample_claims):
        """Test refreshing tokens."""
        # Create initial token pair
        pair = jwt_handler.create_token_pair(sample_claims)

        # Refresh using refresh token
        new_pair = jwt_handler.refresh_tokens(pair.refresh_token)

        assert new_pair.access_token != pair.access_token
        assert new_pair.refresh_token != pair.refresh_token

        # Verify new access token works
        verified = jwt_handler.verify_token(new_pair.access_token)
        assert verified.sub == sample_claims.sub

    def test_refresh_with_access_token_fails(self, jwt_handler, sample_claims):
        """Test that refresh with access token fails."""
        pair = jwt_handler.create_token_pair(sample_claims)

        with pytest.raises(TokenInvalidError, match="Expected refresh token"):
            jwt_handler.refresh_tokens(pair.access_token)

    def test_decode_token_unverified(self, jwt_handler, sample_claims):
        """Test decoding token without verification."""
        token = jwt_handler.create_access_token(sample_claims)
        payload = jwt_handler.decode_token_unverified(token)

        assert payload["sub"] == str(sample_claims.sub)
        assert payload["tenant_id"] == str(sample_claims.tenant_id)

    def test_token_contains_jti(self, jwt_handler, sample_claims):
        """Test that tokens contain unique JTI."""
        token1 = jwt_handler.create_access_token(sample_claims)
        token2 = jwt_handler.create_access_token(sample_claims)

        payload1 = jwt_handler.decode_token_unverified(token1)
        payload2 = jwt_handler.decode_token_unverified(token2)

        assert payload1["jti"] != payload2["jti"]


class TestTokenBlocklist:
    """Tests for token blocklist functionality."""

    def test_revoke_token(self, jwt_handler_with_blocklist, sample_claims):
        """Test revoking a token."""
        handler, blocklist = jwt_handler_with_blocklist

        token = handler.create_access_token(sample_claims)
        handler.verify_token(token)  # Should work

        # Revoke the token
        assert handler.revoke_token(token) is True

        # Should now be blocked
        with pytest.raises(TokenRevokedError):
            handler.verify_token(token)

    def test_blocklist_expiry(self, jwt_handler_with_blocklist, sample_claims):
        """Test that blocklist entries expire."""
        handler, blocklist = jwt_handler_with_blocklist

        # Create token with short expiry
        token = handler.create_access_token(
            sample_claims, expires_delta=timedelta(seconds=1),
        )
        payload = handler.decode_token_unverified(token)
        jti = payload["jti"]

        # Block the token
        blocklist.block(jti, ttl=1)

        # Should be blocked
        assert blocklist.is_blocked(jti) is True

        # Wait for TTL to expire
        time.sleep(1.5)

        # Should no longer be blocked (cleanup happens on access)
        assert blocklist.is_blocked(jti) is False

    def test_unblock_token(self, jwt_handler_with_blocklist, sample_claims):
        """Test unblocking a token."""
        handler, blocklist = jwt_handler_with_blocklist

        token = handler.create_access_token(sample_claims)
        payload = handler.decode_token_unverified(token)
        jti = payload["jti"]

        # Block then unblock
        blocklist.block(jti, ttl=3600)
        assert blocklist.is_blocked(jti) is True

        blocklist.unblock(jti)
        assert blocklist.is_blocked(jti) is False

    def test_clear_blocklist(self):
        """Test clearing the blocklist."""
        blocklist = InMemoryTokenBlocklist()

        blocklist.block("jti1", ttl=3600)
        blocklist.block("jti2", ttl=3600)

        assert blocklist.is_blocked("jti1") is True
        assert blocklist.is_blocked("jti2") is True

        blocklist.clear()

        assert blocklist.is_blocked("jti1") is False
        assert blocklist.is_blocked("jti2") is False


class TestTokenClaimsHelpers:
    """Tests for token claims helper methods."""

    def test_admin_check(self):
        """Test admin role checking."""
        admin_claims = TokenClaims(
            sub=uuid4(),
            tenant_id=uuid4(),
            roles=["admin"],
        )
        assert admin_claims.is_admin() is True

        super_admin_claims = TokenClaims(
            sub=uuid4(),
            tenant_id=uuid4(),
            roles=["super_admin"],
        )
        assert super_admin_claims.is_admin() is True

        user_claims = TokenClaims(
            sub=uuid4(),
            tenant_id=uuid4(),
            roles=["user"],
        )
        assert user_claims.is_admin() is False

    def test_permission_check(self):
        """Test permission checking."""
        claims = TokenClaims(
            sub=uuid4(),
            tenant_id=uuid4(),
            permissions=["documents:read", "documents:write"],
        )
        assert claims.has_permission("documents:read") is True
        assert claims.has_permission("documents:delete") is False


class TestCustomExpiration:
    """Tests for custom token expiration."""

    def test_custom_access_token_expiration(self, jwt_handler, sample_claims):
        """Test custom access token expiration."""
        custom_delta = timedelta(minutes=5)
        token = jwt_handler.create_access_token(sample_claims, expires_delta=custom_delta)

        payload = jwt_handler.decode_token_unverified(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        iat = datetime.fromtimestamp(payload["iat"], tz=UTC)

        # Check expiration is approximately 5 minutes from issue time
        diff = exp - iat
        assert abs(diff.total_seconds() - 300) < 2  # Allow 2 seconds tolerance

    def test_custom_refresh_token_expiration(self, jwt_handler, sample_claims):
        """Test custom refresh token expiration."""
        custom_delta = timedelta(days=1)
        token = jwt_handler.create_refresh_token(sample_claims, expires_delta=custom_delta)

        payload = jwt_handler.decode_token_unverified(token)
        exp = datetime.fromtimestamp(payload["exp"], tz=UTC)
        iat = datetime.fromtimestamp(payload["iat"], tz=UTC)

        # Check expiration is approximately 1 day from issue time
        diff = exp - iat
        assert abs(diff.total_seconds() - 86400) < 2


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_roles_and_groups(self, jwt_handler):
        """Test token with empty roles and groups."""
        claims = TokenClaims(
            sub=uuid4(),
            tenant_id=uuid4(),
            roles=[],
            groups=[],
        )
        token = jwt_handler.create_access_token(claims)
        verified = jwt_handler.verify_token(token)

        assert verified.roles == []
        assert verified.groups == []
        assert verified.is_admin() is False

    def test_many_roles_and_groups(self, jwt_handler):
        """Test token with many roles and groups."""
        many_roles = [f"role_{i}" for i in range(50)]
        many_groups = [f"group_{i}" for i in range(50)]

        claims = TokenClaims(
            sub=uuid4(),
            tenant_id=uuid4(),
            roles=many_roles,
            groups=many_groups,
        )
        token = jwt_handler.create_access_token(claims)
        verified = jwt_handler.verify_token(token)

        assert verified.roles == many_roles
        assert verified.groups == many_groups

    def test_unicode_in_claims(self, jwt_handler):
        """Test token with unicode characters in claims."""
        claims = TokenClaims(
            sub=uuid4(),
            tenant_id=uuid4(),
            name="用户名 Пользователь 🔒",
            email="test@例え.jp",
        )
        token = jwt_handler.create_access_token(claims)
        verified = jwt_handler.verify_token(token)

        assert verified.name == claims.name
        assert verified.email == claims.email

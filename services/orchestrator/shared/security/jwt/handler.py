"""
JWT handler for token creation and validation.

This module provides the main JWTHandler class for creating and validating
JWT tokens with support for RS256 (RSA) and HS256 (HMAC) algorithms.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from jwt.exceptions import (
    DecodeError,
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
)

from .config import JWTSettings
from .models import ServiceTokenClaims, TokenClaims, TokenPair, TokenType


class JWTError(Exception):
    """Base exception for JWT errors."""


class TokenExpiredError(JWTError):
    """Token has expired."""


class TokenInvalidError(JWTError):
    """Token is invalid."""


class TokenRevokedError(JWTError):
    """Token has been revoked."""


class KeyLoadError(JWTError):
    """Error loading cryptographic keys."""


class JWTHandler:
    """
    JWT handler for creating and validating tokens.

    Supports:
    - RS256/RS384/RS512: RSA signing (recommended for production)
    - HS256/HS384/HS512: HMAC signing (development only)
    - JWKS endpoint for external IdP integration
    - Token blocklist for logout/revocation

    Example:
        ```python
        settings = JWTSettings()
        handler = JWTHandler(settings)

        # Create tokens
        claims = TokenClaims(
            sub=user_id,
            tenant_id=tenant_id,
            roles=["user"],
            groups=["engineering"]
        )
        token_pair = handler.create_token_pair(claims)

        # Verify token
        verified_claims = handler.verify_token(token_pair.access_token)
        ```
    """

    def __init__(
        self,
        settings: JWTSettings | None = None,
        blocklist: TokenBlocklist | None = None,
    ):
        """
        Initialize JWT handler.

        Args:
            settings: JWT configuration settings
            blocklist: Optional token blocklist for revocation
        """
        self.settings = settings or JWTSettings()
        self.blocklist = blocklist
        self._private_key: str | None = None
        self._public_key: str | None = None
        self._jwks_client: jwt.PyJWKClient | None = None

        # Load keys based on algorithm
        self._load_keys()

    def _load_keys(self) -> None:
        """
        Load cryptographic keys based on configuration.

        For asymmetric algorithms (RS256, etc.):
        - Load private key for signing
        - Load public key for verification

        For symmetric algorithms (HS256, etc.):
        - Use secret key for both signing and verification
        """
        if self.settings.is_asymmetric:
            self._load_rsa_keys()
        else:
            self._load_hmac_secret()

        # Set up JWKS client for external IdP
        if self.settings.jwks_url:
            self._jwks_client = jwt.PyJWKClient(self.settings.jwks_url)

    def _load_rsa_keys(self) -> None:
        """Load RSA private and public keys."""
        # Load private key for signing
        if self.settings.secret_key:
            self._private_key = self._load_key_content(self.settings.secret_key)

        # Load public key for verification
        if self.settings.public_key:
            self._public_key = self._load_key_content(self.settings.public_key)
        elif self._private_key:
            # Extract public key from private key if not provided separately
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.serialization import load_pem_private_key

            try:
                private_key = load_pem_private_key(
                    self._private_key.encode(),
                    password=None,
                )
                public_key = private_key.public_key()
                self._public_key = public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo,
                ).decode()
            except Exception as e:
                raise KeyLoadError(f"Failed to extract public key: {e}") from e

    def _load_hmac_secret(self) -> None:
        """Load HMAC secret key."""
        if not self.settings.secret_key:
            raise KeyLoadError(
                f"JWT_SECRET_KEY required for {self.settings.algorithm.value}",
            )
        self._private_key = self.settings.secret_key
        self._public_key = self.settings.secret_key

    def _load_key_content(self, key_path_or_content: str) -> str:
        """
        Load key from file path or return content directly.

        Args:
            key_path_or_content: File path or key content

        Returns:
            Key content as string
        """
        # Check if it's a file path
        path = Path(key_path_or_content)
        if path.exists() and path.is_file():
            try:
                return path.read_text()
            except Exception as e:
                raise KeyLoadError(f"Failed to read key file {path}: {e}") from e

        # Check if it looks like a PEM key
        if "-----BEGIN" in key_path_or_content:
            return key_path_or_content

        # Assume it's a secret for HMAC
        return key_path_or_content

    def create_access_token(
        self,
        claims: TokenClaims,
        expires_delta: timedelta | None = None,
    ) -> str:
        """
        Create an access token.

        Args:
            claims: Token claims to encode
            expires_delta: Custom expiration time (default from settings)

        Returns:
            Encoded JWT access token
        """
        if expires_delta is None:
            expires_delta = timedelta(minutes=self.settings.access_token_expire_minutes)

        return self._create_token(claims, TokenType.ACCESS, expires_delta)

    def create_refresh_token(
        self,
        claims: TokenClaims,
        expires_delta: timedelta | None = None,
    ) -> str:
        """
        Create a refresh token.

        Args:
            claims: Token claims to encode
            expires_delta: Custom expiration time (default from settings)

        Returns:
            Encoded JWT refresh token
        """
        if expires_delta is None:
            expires_delta = timedelta(days=self.settings.refresh_token_expire_days)

        return self._create_token(claims, TokenType.REFRESH, expires_delta)

    def create_token_pair(
        self,
        claims: TokenClaims,
        access_expires: timedelta | None = None,
        refresh_expires: timedelta | None = None,
    ) -> TokenPair:
        """
        Create an access/refresh token pair.

        Args:
            claims: Token claims to encode
            access_expires: Custom access token expiration
            refresh_expires: Custom refresh token expiration

        Returns:
            TokenPair with access and refresh tokens
        """
        access_delta = access_expires or timedelta(
            minutes=self.settings.access_token_expire_minutes,
        )
        refresh_delta = refresh_expires or timedelta(
            days=self.settings.refresh_token_expire_days,
        )

        access_token = self._create_token(claims, TokenType.ACCESS, access_delta)
        refresh_token = self._create_token(claims, TokenType.REFRESH, refresh_delta)

        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",  # noqa: S106
            expires_in=int(access_delta.total_seconds()),
            refresh_expires_in=int(refresh_delta.total_seconds()),
        )

    def _create_token(
        self,
        claims: TokenClaims,
        token_type: TokenType,
        expires_delta: timedelta,
    ) -> str:
        """
        Create a JWT token.

        Args:
            claims: Token claims
            token_type: Access or refresh token
            expires_delta: Token expiration time

        Returns:
            Encoded JWT token
        """
        if not self._private_key:
            raise JWTError("Private key not configured for token creation")

        now = datetime.now(UTC)
        expires = now + expires_delta

        # Build token claims
        token_claims = claims.model_copy()
        token_claims.token_type = token_type
        token_claims.iss = self.settings.issuer
        token_claims.aud = self.settings.audience
        token_claims.iat = now
        token_claims.exp = expires
        token_claims.nbf = now
        token_claims.jti = str(uuid.uuid4())

        # Encode token
        payload = token_claims.to_dict()
        return jwt.encode(
            payload,
            self._private_key,
            algorithm=self.settings.algorithm.value,
        )

    def verify_token(
        self,
        token: str,
        expected_type: TokenType | None = None,
    ) -> TokenClaims:
        """
        Verify and decode a JWT token.

        Args:
            token: JWT token string
            expected_type: Expected token type (access/refresh)

        Returns:
            Decoded token claims

        Raises:
            TokenExpiredError: Token has expired
            TokenInvalidError: Token is invalid
            TokenRevokedError: Token has been revoked
        """
        try:
            # Try JWKS validation first if configured
            if self._jwks_client and self._is_external_token(token):
                return self._verify_with_jwks(token, expected_type)

            # Local validation
            return self._verify_local(token, expected_type)

        except ExpiredSignatureError:
            raise TokenExpiredError("Token has expired") from None
        except (InvalidSignatureError, DecodeError):
            raise TokenInvalidError("Invalid token signature") from None
        except InvalidAudienceError:
            raise TokenInvalidError("Invalid token audience") from None
        except InvalidIssuerError:
            raise TokenInvalidError("Invalid token issuer") from None
        except InvalidTokenError as e:
            raise TokenInvalidError(f"Invalid token: {e}") from e

    def _is_external_token(self, token: str) -> bool:
        """Check if token is from external IdP based on issuer."""
        try:
            # Decode without verification to check issuer
            unverified = jwt.decode(token, options={"verify_signature": False})
            return unverified.get("iss") == self.settings.idp_issuer
        except Exception:
            return False

    def _verify_local(
        self,
        token: str,
        expected_type: TokenType | None,
    ) -> TokenClaims:
        """Verify token using local keys."""
        if not self._public_key:
            raise JWTError("Public key not configured for token verification")

        # Decode and verify
        options = {
            "verify_signature": True,
            "verify_exp": self.settings.verify_exp,
            "verify_aud": self.settings.verify_aud,
            "verify_iss": True,
            "require": ["exp", "iat", "sub", "tenant_id"],
        }

        payload = jwt.decode(
            token,
            self._public_key,
            algorithms=[self.settings.algorithm.value],
            audience=self.settings.audience if self.settings.verify_aud else None,
            issuer=self.settings.issuer,
            leeway=self.settings.leeway_seconds,
            options=options,
        )

        claims = TokenClaims.from_dict(payload)

        # Verify token type
        if expected_type and claims.token_type != expected_type:
            raise TokenInvalidError(
                f"Expected {expected_type.value} token, got {claims.token_type.value}",
            )

        # Check blocklist
        if self.blocklist and claims.jti and self.blocklist.is_blocked(claims.jti):
            raise TokenRevokedError("Token has been revoked")

        return claims

    def _verify_with_jwks(
        self,
        token: str,
        expected_type: TokenType | None,
    ) -> TokenClaims:
        """Verify token using external JWKS endpoint."""
        if not self._jwks_client:
            raise JWTError("JWKS client not configured")

        # Get signing key from JWKS
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)

        # Decode and verify
        options = {
            "verify_signature": True,
            "verify_exp": self.settings.verify_exp,
            "verify_aud": self.settings.verify_aud,
            "require": ["exp", "sub"],
        }

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512"],
            audience=self.settings.audience if self.settings.verify_aud else None,
            issuer=self.settings.idp_issuer,
            leeway=self.settings.leeway_seconds,
            options=options,
        )

        # Map external claims to our format
        # External IdPs may use different claim names
        claims_dict = {
            "sub": payload.get("sub"),
            "tenant_id": payload.get("tenant_id")
            or payload.get("org_id")
            or payload.get("custom:tenant_id"),
            "roles": payload.get("roles") or payload.get("custom:roles", []),
            "groups": payload.get("groups") or payload.get("custom:groups", []),
            "permissions": payload.get("permissions") or payload.get("scope", "").split(),
            "email": payload.get("email"),
            "name": payload.get("name") or payload.get("preferred_username"),
            "iss": payload.get("iss"),
            "aud": payload.get("aud"),
            "exp": payload.get("exp"),
            "iat": payload.get("iat"),
            "jti": payload.get("jti"),
        }

        # Ensure tenant_id is set (required)
        if not claims_dict["tenant_id"]:
            raise TokenInvalidError("Token missing tenant_id claim")

        claims = TokenClaims.from_dict(claims_dict)

        # Verify token type if specified
        if expected_type and claims.token_type != expected_type:
            raise TokenInvalidError(
                f"Expected {expected_type.value} token, got {claims.token_type.value}",
            )

        return claims

    def refresh_tokens(self, refresh_token: str) -> TokenPair:
        """
        Refresh tokens using a refresh token.

        Args:
            refresh_token: Valid refresh token

        Returns:
            New token pair

        Raises:
            TokenInvalidError: If refresh token is invalid
        """
        # Verify refresh token
        claims = self.verify_token(refresh_token, expected_type=TokenType.REFRESH)

        # Revoke old refresh token - calculate remaining TTL
        if self.blocklist and claims.jti and claims.exp:
            ttl = int((claims.exp - datetime.now(UTC)).total_seconds())
            if ttl > 0:
                self.blocklist.block(claims.jti, ttl)

        # Create new token pair with same claims
        new_claims = TokenClaims(
            sub=claims.sub,
            tenant_id=claims.tenant_id,
            roles=claims.roles,
            groups=claims.groups,
            permissions=claims.permissions,
            email=claims.email,
            name=claims.name,
        )

        return self.create_token_pair(new_claims)

    def revoke_token(self, token: str) -> bool:
        """
        Revoke a token by adding it to the blocklist.

        Args:
            token: Token to revoke

        Returns:
            True if revoked successfully
        """
        if not self.blocklist:
            return False

        try:
            # Decode without full verification to get JTI and expiration
            claims = jwt.decode(
                token,
                options={"verify_signature": False, "verify_exp": False},
            )

            jti = claims.get("jti")
            exp = claims.get("exp")

            if not jti:
                return False

            # Calculate TTL (block until token would have expired)
            ttl = None
            if exp:
                ttl = int(exp - datetime.now(UTC).timestamp())
                if ttl <= 0:
                    # Token already expired, no need to block
                    return True

            self.blocklist.block(jti, ttl)
            return True

        except Exception:
            return False

    def decode_token_unverified(self, token: str) -> dict:
        """
        Decode a token without verification.

        Useful for extracting claims from expired tokens.

        Args:
            token: JWT token string

        Returns:
            Decoded payload dictionary
        """
        return jwt.decode(
            token,
            options={"verify_signature": False, "verify_exp": False},
        )

    # -------------------------------------------------------------------------
    # Service-to-Service Authentication Methods
    # -------------------------------------------------------------------------

    def create_service_token(
        self,
        service_name: str,
        target_service: str,
        allowed_endpoints: list[str] | None = None,
        expires_delta: timedelta | None = None,
    ) -> str:
        """
        Create a JWT token for service-to-service authentication.

        Args:
            service_name: Name of the calling service (e.g., "orchestrator")
            target_service: Name of the target service (e.g., "retrieval")
            allowed_endpoints: List of endpoint patterns the service can access
                              (e.g., ["/internal/*", "/api/v1/search"])
            expires_delta: Token expiration time (default: 5 minutes)

        Returns:
            Encoded JWT service token

        Example:
            ```python
            token = handler.create_service_token(
                service_name="orchestrator",
                target_service="retrieval",
                allowed_endpoints=["/internal/*"],
            )
            headers = {"Authorization": f"Bearer {token}"}
            ```
        """
        if not self._private_key:
            raise JWTError("Private key not configured for token creation")

        if expires_delta is None:
            expires_delta = timedelta(minutes=5)  # Short-lived by default

        now = datetime.now(UTC)
        expires = now + expires_delta

        claims = ServiceTokenClaims(
            service_name=service_name,
            target_service=target_service,
            allowed_endpoints=allowed_endpoints or [],
            iss=self.settings.issuer,
            aud=target_service,  # Audience is the target service
            iat=now,
            exp=expires,
            jti=str(uuid.uuid4()),
            token_type=TokenType.SERVICE,
        )

        payload = claims.to_dict()
        return jwt.encode(
            payload,
            self._private_key,
            algorithm=self.settings.algorithm.value,
        )

    def verify_service_token(
        self,
        token: str,
        expected_audience: str,
        endpoint: str | None = None,
    ) -> ServiceTokenClaims:
        """
        Verify a service-to-service JWT token.

        Args:
            token: JWT token string
            expected_audience: Expected target service (must match token's audience)
            endpoint: Optional endpoint to check against allowed_endpoints

        Returns:
            Decoded service token claims

        Raises:
            TokenExpiredError: Token has expired
            TokenInvalidError: Token is invalid or not a service token
            TokenRevokedError: Token has been revoked

        Example:
            ```python
            claims = handler.verify_service_token(
                token=bearer_token,
                expected_audience="retrieval",
                endpoint="/internal/search",
            )
            print(f"Request from service: {claims.service_name}")
            ```
        """
        if not self._public_key:
            raise JWTError("Public key not configured for token verification")

        try:
            # Decode and verify
            options = {
                "verify_signature": True,
                "verify_exp": self.settings.verify_exp,
                "verify_aud": True,
                "verify_iss": True,
                "require": ["exp", "iat", "service_name", "target_service"],
            }

            payload = jwt.decode(
                token,
                self._public_key,
                algorithms=[self.settings.algorithm.value],
                audience=expected_audience,
                issuer=self.settings.issuer,
                leeway=self.settings.leeway_seconds,
                options=options,
            )

            # Verify this is a service token
            if payload.get("token_type") != TokenType.SERVICE.value:
                raise TokenInvalidError(f"Expected service token, got {payload.get('token_type')}")

            claims = ServiceTokenClaims.from_dict(payload)

            # Check endpoint authorization if provided
            if endpoint and not claims.can_access_endpoint(endpoint):
                raise TokenInvalidError(
                    f"Service '{claims.service_name}' not authorized for endpoint '{endpoint}'"
                )

            # Check blocklist
            if self.blocklist and claims.jti and self.blocklist.is_blocked(claims.jti):
                raise TokenRevokedError("Token has been revoked")

            return claims

        except ExpiredSignatureError:
            raise TokenExpiredError("Service token has expired") from None
        except (InvalidSignatureError, DecodeError):
            raise TokenInvalidError("Invalid service token signature") from None
        except InvalidAudienceError:
            raise TokenInvalidError("Invalid service token audience") from None
        except InvalidIssuerError:
            raise TokenInvalidError("Invalid service token issuer") from None
        except InvalidTokenError as e:
            raise TokenInvalidError(f"Invalid service token: {e}") from e

    def is_service_token(self, token: str) -> bool:
        """
        Check if a token is a service-to-service token.

        Args:
            token: JWT token string

        Returns:
            True if the token is a service token
        """
        try:
            payload = self.decode_token_unverified(token)
            return payload.get("token_type") == TokenType.SERVICE.value
        except Exception:
            return False


class TokenBlocklist:
    """
    Interface for token blocklist implementations.

    Implement this interface with Redis or another backing store
    to enable token revocation.
    """

    def block(self, jti: str, ttl: int | None = None) -> None:
        """
        Add a token JTI to the blocklist.

        Args:
            jti: Token JWT ID
            ttl: Time-to-live in seconds
        """
        raise NotImplementedError

    def is_blocked(self, jti: str) -> bool:
        """
        Check if a token JTI is blocked.

        Args:
            jti: Token JWT ID

        Returns:
            True if token is blocked
        """
        raise NotImplementedError

    def unblock(self, jti: str) -> None:
        """
        Remove a token JTI from the blocklist.

        Args:
            jti: Token JWT ID
        """
        raise NotImplementedError

"""
JWT Authentication for the Gateway.

Provides JWT validation with RS256 support, tenant/user extraction,
and role-based access control.
"""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AuthConfig(BaseModel):
    """Authentication configuration."""

    # JWT settings
    jwt_secret: Optional[str] = None  # For HS256
    jwt_public_key: Optional[str] = None  # For RS256
    jwt_algorithm: str = "RS256"
    jwt_issuer: Optional[str] = None
    jwt_audience: Optional[str] = None

    # JWKS settings (for RS256 with key rotation)
    jwks_url: Optional[str] = None
    jwks_cache_ttl: int = 3600  # seconds

    # API key settings (alternative auth)
    api_keys_enabled: bool = True
    api_keys: dict[str, dict] = {}  # key -> {tenant_id, user_id, roles}

    # Validation settings
    require_auth: bool = True
    skip_paths: list[str] = ["/health", "/health/live", "/health/ready", "/docs", "/redoc", "/openapi.json", "/"]


@dataclass
class AuthContext:
    """Authentication context extracted from JWT or API key."""

    tenant_id: str
    user_id: str
    roles: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    claims: dict = field(default_factory=dict)
    auth_method: str = "jwt"  # jwt, api_key, none

    def has_role(self, role: str) -> bool:
        """Check if user has a specific role."""
        return role in self.roles

    def has_scope(self, scope: str) -> bool:
        """Check if user has a specific scope."""
        return scope in self.scopes

    def to_headers(self) -> dict[str, str]:
        """Convert to headers for downstream services."""
        return {
            "X-Tenant-ID": self.tenant_id,
            "X-User-ID": self.user_id,
            "X-Roles": ",".join(self.roles),
            "X-Auth-Method": self.auth_method,
        }


class JWTAuth:
    """JWT authentication handler."""

    def __init__(self, config: Optional[AuthConfig] = None):
        """
        Initialize JWT auth handler.

        Args:
            config: Authentication configuration
        """
        self.config = config or AuthConfig()
        self._jwks_cache: Optional[dict] = None
        self._jwks_cache_time: float = 0

    @classmethod
    def from_env(cls) -> "JWTAuth":
        """Create JWTAuth from environment variables."""
        config = AuthConfig(
            jwt_secret=os.getenv("JWT_SECRET"),
            jwt_public_key=os.getenv("JWT_PUBLIC_KEY"),
            jwt_algorithm=os.getenv("JWT_ALGORITHM", "RS256"),
            jwt_issuer=os.getenv("JWT_ISSUER"),
            jwt_audience=os.getenv("JWT_AUDIENCE"),
            jwks_url=os.getenv("JWKS_URL"),
            require_auth=os.getenv("REQUIRE_AUTH", "true").lower() == "true",
        )

        # Parse API keys from environment (format: KEY1:tenant1:user1:role1,role2;KEY2:...)
        api_keys_str = os.getenv("API_KEYS", "")
        if api_keys_str:
            for key_spec in api_keys_str.split(";"):
                if ":" in key_spec:
                    parts = key_spec.split(":")
                    if len(parts) >= 3:
                        key, tenant, user = parts[0], parts[1], parts[2]
                        roles = parts[3].split(",") if len(parts) > 3 else []
                        config.api_keys[key] = {
                            "tenant_id": tenant,
                            "user_id": user,
                            "roles": roles,
                        }

        return cls(config)

    async def _fetch_jwks(self) -> Optional[dict]:
        """Fetch JWKS from configured URL."""
        if not self.config.jwks_url:
            return None

        # Check cache
        if (
            self._jwks_cache
            and time.time() - self._jwks_cache_time < self.config.jwks_cache_ttl
        ):
            return self._jwks_cache

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.config.jwks_url, timeout=10.0)
                response.raise_for_status()
                self._jwks_cache = response.json()
                self._jwks_cache_time = time.time()
                return self._jwks_cache
        except Exception as e:
            logger.error(f"Failed to fetch JWKS: {e}")
            return self._jwks_cache  # Return stale cache if available

    def _get_signing_key(self, token: str) -> Optional[str]:
        """Get the signing key for token verification."""
        if self.config.jwt_algorithm.startswith("HS"):
            return self.config.jwt_secret
        elif self.config.jwt_public_key:
            return self.config.jwt_public_key
        return None

    async def validate_token(self, token: str) -> Optional[AuthContext]:
        """
        Validate a JWT token.

        Args:
            token: JWT token string

        Returns:
            AuthContext if valid, None if invalid
        """
        try:
            # Get signing key
            key = self._get_signing_key(token)
            if not key:
                # Try JWKS
                jwks = await self._fetch_jwks()
                if not jwks:
                    logger.error("No signing key available for JWT validation")
                    return None
                # For JWKS, use the jose library's built-in support
                key = jwks

            # Build validation options
            options = {}
            if self.config.jwt_issuer:
                options["iss"] = self.config.jwt_issuer
            if self.config.jwt_audience:
                options["aud"] = self.config.jwt_audience

            # Decode and validate
            if isinstance(key, dict):
                # JWKS case - decode header to get kid
                header = jwt.get_unverified_header(token)
                kid = header.get("kid")
                if kid and "keys" in key:
                    for k in key["keys"]:
                        if k.get("kid") == kid:
                            key = k
                            break

            payload = jwt.decode(
                token,
                key,
                algorithms=[self.config.jwt_algorithm],
                options={"verify_aud": bool(self.config.jwt_audience)},
                audience=self.config.jwt_audience,
                issuer=self.config.jwt_issuer,
            )

            # Extract context from claims
            return AuthContext(
                tenant_id=payload.get("tenant_id", payload.get("tid", "default")),
                user_id=payload.get("sub", payload.get("user_id", "anonymous")),
                roles=payload.get("roles", payload.get("role", [])),
                scopes=payload.get("scope", "").split() if payload.get("scope") else [],
                claims=payload,
                auth_method="jwt",
            )

        except ExpiredSignatureError:
            logger.warning("JWT token expired")
            return None
        except JWTError as e:
            logger.warning(f"JWT validation failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error validating JWT: {e}")
            return None

    def validate_api_key(self, api_key: str) -> Optional[AuthContext]:
        """
        Validate an API key.

        Args:
            api_key: API key string

        Returns:
            AuthContext if valid, None if invalid
        """
        if not self.config.api_keys_enabled:
            return None

        key_data = self.config.api_keys.get(api_key)
        if not key_data:
            return None

        return AuthContext(
            tenant_id=key_data.get("tenant_id", "default"),
            user_id=key_data.get("user_id", "api-user"),
            roles=key_data.get("roles", []),
            auth_method="api_key",
        )

    async def authenticate(
        self,
        authorization: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> Optional[AuthContext]:
        """
        Authenticate a request using JWT or API key.

        Args:
            authorization: Authorization header value (Bearer <token>)
            api_key: X-API-Key header value

        Returns:
            AuthContext if authenticated, None if not
        """
        # Try API key first (simpler)
        if api_key:
            context = self.validate_api_key(api_key)
            if context:
                return context

        # Try Bearer token
        if authorization and authorization.startswith("Bearer "):
            token = authorization[7:]
            context = await self.validate_token(token)
            if context:
                return context

        return None

    def is_path_public(self, path: str) -> bool:
        """Check if a path is public (doesn't require auth)."""
        for skip_path in self.config.skip_paths:
            if path == skip_path or path.startswith(skip_path + "/"):
                return True
        return False


# Global auth instance
_jwt_auth: Optional[JWTAuth] = None


def get_auth_context() -> JWTAuth:
    """Get the global JWT auth instance."""
    global _jwt_auth
    if _jwt_auth is None:
        _jwt_auth = JWTAuth.from_env()
    return _jwt_auth

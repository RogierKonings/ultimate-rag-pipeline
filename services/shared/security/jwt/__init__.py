"""
JWT Authentication module for the RAG Pipeline.

This module provides JWT token creation, validation, and management
with support for RS256 (production) and HS256 (development) algorithms.
"""

from .blocklist import (
    AsyncRedisTokenBlocklist,
    InMemoryTokenBlocklist,
    RedisTokenBlocklist,
)
from .config import JWTAlgorithm, JWTSettings
from .handler import (
    JWTError,
    JWTHandler,
    KeyLoadError,
    TokenBlocklist,
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
)
from .middleware import (
    CurrentUser,
    JWTAuthMiddleware,
    OptionalUser,
    create_auth_dependencies,
    require_permissions,
    require_roles,
    require_tenant,
)
from .models import (
    TokenClaims,
    TokenIntrospectionResponse,
    TokenPair,
    TokenRequest,
    TokenRevocationRequest,
    TokenType,
)

__all__ = [
    # Config
    "JWTAlgorithm",
    "JWTSettings",
    # Models
    "TokenClaims",
    "TokenIntrospectionResponse",
    "TokenPair",
    "TokenRequest",
    "TokenRevocationRequest",
    "TokenType",
    # Handler
    "JWTError",
    "JWTHandler",
    "KeyLoadError",
    "TokenBlocklist",
    "TokenExpiredError",
    "TokenInvalidError",
    "TokenRevokedError",
    # Blocklist implementations
    "AsyncRedisTokenBlocklist",
    "InMemoryTokenBlocklist",
    "RedisTokenBlocklist",
    # Middleware
    "CurrentUser",
    "JWTAuthMiddleware",
    "OptionalUser",
    "create_auth_dependencies",
    "require_permissions",
    "require_roles",
    "require_tenant",
]

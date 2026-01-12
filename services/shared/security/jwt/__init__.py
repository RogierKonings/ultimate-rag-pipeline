"""
JWT Authentication module for the RAG Pipeline.

This module provides JWT token creation, validation, and management
with support for RS256 (production) and HS256 (development) algorithms.
"""

from .config import JWTAlgorithm, JWTSettings
from .models import (
    TokenClaims,
    TokenIntrospectionResponse,
    TokenPair,
    TokenRequest,
    TokenRevocationRequest,
    TokenType,
)
from .handler import (
    JWTError,
    JWTHandler,
    KeyLoadError,
    TokenBlocklist,
    TokenExpiredError,
    TokenInvalidError,
    TokenRevokedError,
)
from .blocklist import (
    AsyncRedisTokenBlocklist,
    InMemoryTokenBlocklist,
    RedisTokenBlocklist,
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

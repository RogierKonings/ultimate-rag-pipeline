"""ACL (Access Control List) module for the Retrieval Service.

This module provides access control enforcement for search results,
ensuring users only see documents they are permitted to access.
"""

from .context import UserContextExtractor
from .filter import ACLFilter, AnonymousAccessFilter
from .middleware import ACLMiddleware, create_acl_dependencies
from .models import (
    ACLFilterConfig,
    DocumentACL,
    UserContext,
    Visibility,
)

__all__ = [
    # Models
    "ACLFilterConfig",
    "DocumentACL",
    "UserContext",
    "Visibility",
    # Filter
    "ACLFilter",
    "AnonymousAccessFilter",
    # Context
    "UserContextExtractor",
    # Middleware
    "ACLMiddleware",
    "create_acl_dependencies",
]

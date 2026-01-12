"""
Security API routers.

This module provides FastAPI routers for authentication, authorization,
and security-related endpoints.
"""

from .auth import create_auth_router

__all__ = ["create_auth_router"]

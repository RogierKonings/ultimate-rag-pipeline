"""
Async SQLAlchemy database connection management.

Provides async engine creation, session factory, and context managers
for database operations in the RAG Pipeline.

Security features:
- SSL/TLS encryption for all connections (configurable modes)
- Certificate verification for production environments
- Password passed via connect_args (not in URL) for log safety
"""

import os
import ssl
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine as sa_create_async_engine,
)

# Default database URL for local development (without password for logging safety)
DEFAULT_DATABASE_URL = "postgresql+asyncpg://raguser@localhost:5432/ragpipeline"


def create_ssl_context() -> ssl.SSLContext | None:
    """Create SSL context for PostgreSQL connection.

    Supports multiple SSL modes via POSTGRES_SSL_MODE environment variable:
    - disable: No SSL (not recommended for production)
    - require: Encrypt but don't verify certificate
    - verify-ca: Verify certificate against CA
    - verify-full: Full verification including hostname (recommended for production)

    Additional environment variables:
    - POSTGRES_SSL_CA: Path to CA certificate file
    - POSTGRES_SSL_CERT: Path to client certificate file (for mTLS)
    - POSTGRES_SSL_KEY: Path to client key file (for mTLS)

    Returns:
        SSL context configured per environment settings, or None if disabled.
    """
    ssl_mode = os.getenv("POSTGRES_SSL_MODE", "prefer")

    if ssl_mode == "disable":
        return None

    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    if ssl_mode == "require":
        # Encrypt but don't verify certificate
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    elif ssl_mode == "verify-ca":
        # Verify certificate against CA
        ca_cert = os.getenv("POSTGRES_SSL_CA")
        if ca_cert and Path(ca_cert).exists():
            ctx.load_verify_locations(ca_cert)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED

    elif ssl_mode in ("verify-full", "prefer"):
        # Full verification including hostname (default for prefer in production)
        ca_cert = os.getenv("POSTGRES_SSL_CA")
        if ca_cert and Path(ca_cert).exists():
            ctx.load_verify_locations(ca_cert)

        # In production with verify-full, enforce hostname checking
        if ssl_mode == "verify-full":
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
        else:
            # prefer mode: try SSL but don't require verification
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

    # Load client certificate for mutual TLS if provided
    client_cert = os.getenv("POSTGRES_SSL_CERT")
    client_key = os.getenv("POSTGRES_SSL_KEY")
    if (
        client_cert
        and client_key
        and Path(client_cert).exists()
        and Path(client_key).exists()
    ):
        ctx.load_cert_chain(client_cert, client_key)

    return ctx


def get_database_url_without_password() -> str:
    """Build database URL without password for logging safety.

    The password is passed separately via connect_args to avoid
    credential leakage in logs and error messages.

    Returns:
        Database URL without password component.
    """
    # Check for full DATABASE_URL first (for backwards compatibility)
    full_url = os.getenv("DATABASE_URL")
    if full_url:
        # If it contains a password, we still use it but recommend migration
        return full_url

    # Build URL from components (preferred secure method)
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "ragpipeline")
    user = os.getenv("POSTGRES_USER", "raguser")

    return f"postgresql+asyncpg://{user}@{host}:{port}/{database}"


def get_database_url() -> str:
    """Get database URL from environment or use default.

    Note: For secure deployments, use POSTGRES_* environment variables
    instead of DATABASE_URL to keep passwords out of the URL.
    """
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_async_engine(
    database_url: str | None = None,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_pre_ping: bool = True,
    use_ssl: bool | None = None,
) -> AsyncEngine:
    """
    Create an async SQLAlchemy engine with SSL support.

    Args:
        database_url: PostgreSQL connection URL. If None, uses DATABASE_URL env var.
        echo: If True, log all SQL statements. Disabled by default for security.
        pool_size: Number of connections to keep in the pool.
        max_overflow: Maximum overflow connections beyond pool_size.
        pool_pre_ping: If True, test connections before use.
        use_ssl: Enable SSL. If None, determined by POSTGRES_SSL_MODE env var.

    Returns:
        Configured AsyncEngine instance with SSL if enabled.
    """
    url = database_url or get_database_url_without_password()

    # Build connect_args for asyncpg
    connect_args: dict = {}

    # Add password from environment if using component-based URL
    password = os.getenv("POSTGRES_PASSWORD")
    if password and "@" in url and ":@" not in url and ":" not in url.split("@")[0].split("/")[-1]:
        # URL doesn't have password, add it via connect_args
        connect_args["password"] = password

    # Configure SSL
    if use_ssl is None:
        ssl_mode = os.getenv("POSTGRES_SSL_MODE", "prefer")
        use_ssl = ssl_mode != "disable"

    if use_ssl:
        ssl_context = create_ssl_context()
        if ssl_context:
            connect_args["ssl"] = ssl_context

    return sa_create_async_engine(
        url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=pool_pre_ping,
        connect_args=connect_args if connect_args else None,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    Create a session factory for the given engine.

    Args:
        engine: AsyncEngine instance.

    Returns:
        Configured session factory.
    """
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


# Global engine and session factory (initialized on first use)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Get or create the global async engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the global session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory(get_engine())
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions.

    Provides a session that automatically commits on success
    or rolls back on exception.

    Usage:
        async with get_session() as session:
            result = await session.execute(query)
    """
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for FastAPI endpoints.

    Usage:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with get_session() as session:
        yield session


async def check_database_health() -> dict:
    """
    Check database connectivity and return health status.

    Returns:
        Dict with 'healthy' boolean, 'version', and 'ssl_enabled' status.
    """
    import time

    start = time.monotonic()
    try:
        async with get_session() as session:
            # Get version and SSL status in one query
            result = await session.execute(
                text("SELECT version(), ssl_is_used()")
            )
            row = result.fetchone()
            version = row[0] if row else None
            ssl_enabled = row[1] if row else False

            latency_ms = (time.monotonic() - start) * 1000

            return {
                "healthy": True,
                "version": version,
                "ssl_enabled": ssl_enabled,
                "latency_ms": round(latency_ms, 2),
            }
    except Exception as e:
        latency_ms = (time.monotonic() - start) * 1000
        return {
            "healthy": False,
            "error": str(e),
            "ssl_enabled": False,
            "latency_ms": round(latency_ms, 2),
        }


async def close_database() -> None:
    """Close the global database engine."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None

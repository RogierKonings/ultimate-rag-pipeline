"""
Async SQLAlchemy database connection management.

Provides async engine creation, session factory, and context managers
for database operations in the RAG Pipeline.
"""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine as sa_create_async_engine,
)

# Default database URL for local development
DEFAULT_DATABASE_URL = "postgresql+asyncpg://raguser:ragpass@localhost:5432/ragpipeline"


def get_database_url() -> str:
    """Get database URL from environment or use default."""
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def create_async_engine(
    database_url: str | None = None,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_pre_ping: bool = True,
) -> AsyncEngine:
    """
    Create an async SQLAlchemy engine.

    Args:
        database_url: PostgreSQL connection URL. If None, uses DATABASE_URL env var.
        echo: If True, log all SQL statements.
        pool_size: Number of connections to keep in the pool.
        max_overflow: Maximum overflow connections beyond pool_size.
        pool_pre_ping: If True, test connections before use.

    Returns:
        Configured AsyncEngine instance.
    """
    url = database_url or get_database_url()

    return sa_create_async_engine(
        url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=pool_pre_ping,
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
        Dict with 'healthy' boolean and 'version' if connected.
    """
    try:
        async with get_session() as session:
            result = await session.execute(text("SELECT version()"))
            version = result.scalar()
            return {
                "healthy": True,
                "version": version,
            }
    except Exception as e:
        return {
            "healthy": False,
            "error": str(e),
        }


async def close_database() -> None:
    """Close the global database engine."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None

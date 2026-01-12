"""
Redis-based token blocklist for JWT revocation.

This module provides a Redis-backed implementation of the token blocklist
for supporting logout and token revocation.
"""

import logging

from .handler import TokenBlocklist

logger = logging.getLogger(__name__)


class RedisTokenBlocklist(TokenBlocklist):
    """
    Redis-based token blocklist implementation.

    Uses Redis to store revoked token JTIs with TTL based on token expiration.
    This ensures revoked tokens are automatically cleaned up when they would
    have expired anyway.

    Example:
        ```python
        from redis.asyncio import Redis
        from services.shared.security.jwt import RedisTokenBlocklist, JWTHandler

        redis = Redis.from_url("redis://localhost:6379")
        blocklist = RedisTokenBlocklist(redis)
        handler = JWTHandler(blocklist=blocklist)

        # Revoke a token
        handler.revoke_token(access_token)

        # Token will now be rejected
        try:
            handler.verify_token(access_token)
        except TokenRevokedError:
            print("Token was revoked!")
        ```
    """

    def __init__(
        self,
        redis_client,
        prefix: str = "jwt:blocklist:",
        default_ttl: int = 86400,  # 24 hours
    ):
        """
        Initialize Redis blocklist.

        Args:
            redis_client: Redis client instance (sync or async)
            prefix: Key prefix for blocklist entries
            default_ttl: Default TTL in seconds if not specified
        """
        self._redis = redis_client
        self._prefix = prefix
        self._default_ttl = default_ttl

    def _make_key(self, jti: str) -> str:
        """Create Redis key for JTI."""
        return f"{self._prefix}{jti}"

    def block(self, jti: str, ttl: int | None = None) -> None:
        """
        Add a token JTI to the blocklist.

        Args:
            jti: Token JWT ID
            ttl: Time-to-live in seconds (default: 24 hours or until expiry)
        """
        key = self._make_key(jti)
        effective_ttl = ttl if ttl and ttl > 0 else self._default_ttl

        try:
            self._redis.setex(key, effective_ttl, "1")
            logger.debug(f"Blocked token JTI: {jti} for {effective_ttl}s")
        except Exception as e:
            logger.error(f"Failed to block token JTI {jti}: {e}")
            raise

    def is_blocked(self, jti: str) -> bool:
        """
        Check if a token JTI is blocked.

        Args:
            jti: Token JWT ID

        Returns:
            True if token is blocked
        """
        key = self._make_key(jti)

        try:
            result = self._redis.exists(key)
            return bool(result)
        except Exception as e:
            logger.error(f"Failed to check blocklist for JTI {jti}: {e}")
            # Fail open to avoid blocking all requests if Redis is down
            # In production, you may want to fail closed instead
            return False

    def unblock(self, jti: str) -> None:
        """
        Remove a token JTI from the blocklist.

        Args:
            jti: Token JWT ID
        """
        key = self._make_key(jti)

        try:
            self._redis.delete(key)
            logger.debug(f"Unblocked token JTI: {jti}")
        except Exception as e:
            logger.error(f"Failed to unblock token JTI {jti}: {e}")
            raise


class AsyncRedisTokenBlocklist(TokenBlocklist):
    """
    Async Redis-based token blocklist implementation.

    Same as RedisTokenBlocklist but uses async Redis client.

    Example:
        ```python
        from redis.asyncio import Redis
        from services.shared.security.jwt import AsyncRedisTokenBlocklist

        redis = Redis.from_url("redis://localhost:6379")
        blocklist = AsyncRedisTokenBlocklist(redis)
        ```
    """

    def __init__(
        self,
        redis_client,
        prefix: str = "jwt:blocklist:",
        default_ttl: int = 86400,
    ):
        """
        Initialize async Redis blocklist.

        Args:
            redis_client: Async Redis client instance
            prefix: Key prefix for blocklist entries
            default_ttl: Default TTL in seconds
        """
        self._redis = redis_client
        self._prefix = prefix
        self._default_ttl = default_ttl

    def _make_key(self, jti: str) -> str:
        """Create Redis key for JTI."""
        return f"{self._prefix}{jti}"

    def block(self, jti: str, ttl: int | None = None) -> None:
        """
        Add a token JTI to the blocklist (sync wrapper).

        Note: This method is synchronous for compatibility with JWTHandler.
        For async code, use block_async().
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, schedule the coroutine
                asyncio.create_task(self.block_async(jti, ttl))
            else:
                loop.run_until_complete(self.block_async(jti, ttl))
        except RuntimeError:
            # No event loop, create one
            asyncio.run(self.block_async(jti, ttl))

    async def block_async(self, jti: str, ttl: int | None = None) -> None:
        """
        Add a token JTI to the blocklist (async).

        Args:
            jti: Token JWT ID
            ttl: Time-to-live in seconds
        """
        key = self._make_key(jti)
        effective_ttl = ttl if ttl and ttl > 0 else self._default_ttl

        try:
            await self._redis.setex(key, effective_ttl, "1")
            logger.debug(f"Blocked token JTI: {jti} for {effective_ttl}s")
        except Exception as e:
            logger.error(f"Failed to block token JTI {jti}: {e}")
            raise

    def is_blocked(self, jti: str) -> bool:
        """
        Check if a token JTI is blocked (sync wrapper).

        Note: This method is synchronous for compatibility with JWTHandler.
        For async code, use is_blocked_async().
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context, need to handle differently
                # Create a new event loop in a thread
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(
                        asyncio.run, self.is_blocked_async(jti),
                    )
                    return future.result()
            else:
                return loop.run_until_complete(self.is_blocked_async(jti))
        except RuntimeError:
            return asyncio.run(self.is_blocked_async(jti))

    async def is_blocked_async(self, jti: str) -> bool:
        """
        Check if a token JTI is blocked (async).

        Args:
            jti: Token JWT ID

        Returns:
            True if token is blocked
        """
        key = self._make_key(jti)

        try:
            result = await self._redis.exists(key)
            return bool(result)
        except Exception as e:
            logger.error(f"Failed to check blocklist for JTI {jti}: {e}")
            return False

    def unblock(self, jti: str) -> None:
        """
        Remove a token JTI from the blocklist (sync wrapper).
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.unblock_async(jti))
            else:
                loop.run_until_complete(self.unblock_async(jti))
        except RuntimeError:
            asyncio.run(self.unblock_async(jti))

    async def unblock_async(self, jti: str) -> None:
        """
        Remove a token JTI from the blocklist (async).

        Args:
            jti: Token JWT ID
        """
        key = self._make_key(jti)

        try:
            await self._redis.delete(key)
            logger.debug(f"Unblocked token JTI: {jti}")
        except Exception as e:
            logger.error(f"Failed to unblock token JTI {jti}: {e}")
            raise


class InMemoryTokenBlocklist(TokenBlocklist):
    """
    In-memory token blocklist for development/testing.

    This implementation stores blocked tokens in memory and does NOT
    persist across restarts. Use only for development and testing.

    Example:
        ```python
        from services.shared.security.jwt import InMemoryTokenBlocklist, JWTHandler

        blocklist = InMemoryTokenBlocklist()
        handler = JWTHandler(blocklist=blocklist)
        ```
    """

    def __init__(self):
        """Initialize in-memory blocklist."""
        self._blocked: dict[str, float] = {}  # jti -> expiry timestamp

    def block(self, jti: str, ttl: int | None = None) -> None:
        """Add a token JTI to the blocklist."""
        import time

        if ttl and ttl > 0:
            expiry = time.time() + ttl
        else:
            # Default to 24 hours
            expiry = time.time() + 86400

        self._blocked[jti] = expiry
        self._cleanup()

    def is_blocked(self, jti: str) -> bool:
        """Check if a token JTI is blocked."""
        import time

        self._cleanup()

        if jti not in self._blocked:
            return False

        # Check if entry has expired
        return self._blocked[jti] > time.time()

    def unblock(self, jti: str) -> None:
        """Remove a token JTI from the blocklist."""
        self._blocked.pop(jti, None)

    def _cleanup(self) -> None:
        """Remove expired entries from blocklist."""
        import time

        current_time = time.time()
        expired = [
            jti for jti, expiry in self._blocked.items() if expiry <= current_time
        ]
        for jti in expired:
            del self._blocked[jti]

    def clear(self) -> None:
        """Clear all blocked tokens (for testing)."""
        self._blocked.clear()

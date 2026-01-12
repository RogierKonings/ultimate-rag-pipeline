"""Redis client wrapper for caching operations with Sentinel HA and TLS support."""

import hashlib
import json
import os
import ssl
from typing import Any

import redis.asyncio as redis
from redis.asyncio.sentinel import Sentinel


def get_ssl_context() -> ssl.SSLContext | None:
    """Create SSL context for Redis TLS connections.

    Returns:
        SSL context if TLS is enabled and certs exist, None otherwise.
    """
    tls_enabled = os.getenv("REDIS_TLS_ENABLED", "false").lower() == "true"
    if not tls_enabled:
        return None

    ca_cert = os.getenv("REDIS_TLS_CA_CERT", "/tls/ca.crt")
    client_cert = os.getenv("REDIS_TLS_CERT", "/tls/tls.crt")
    client_key = os.getenv("REDIS_TLS_KEY", "/tls/tls.key")

    ssl_context = ssl.create_default_context(cafile=ca_cert)
    ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

    if os.path.exists(client_cert) and os.path.exists(client_key):
        ssl_context.load_cert_chain(certfile=client_cert, keyfile=client_key)

    return ssl_context


class RedisCache:
    """Async Redis cache client with environment-based configuration, Sentinel, and TLS support."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        password: str | None = None,
        db: int = 0,
        decode_responses: bool = True,
        use_sentinel: bool | None = None,
        sentinel_hosts: str | None = None,
        sentinel_master: str | None = None,
        use_tls: bool | None = None,
    ):
        """Initialize Redis cache client.

        Args:
            host: Redis server host. Defaults to REDIS_HOST env var or localhost.
            port: Redis server port. Defaults to REDIS_PORT env var or 6379.
            password: Redis password. Defaults to REDIS_PASSWORD env var.
            db: Redis database number. Defaults to 0.
            decode_responses: Whether to decode responses to strings.
            use_sentinel: Whether to use Sentinel. Defaults to REDIS_USE_SENTINEL env var.
            sentinel_hosts: Comma-separated sentinel hosts. Defaults to REDIS_SENTINEL_HOSTS env var.
            sentinel_master: Sentinel master name. Defaults to REDIS_SENTINEL_MASTER env var.
            use_tls: Whether to use TLS. Defaults to REDIS_TLS_ENABLED env var.
        """
        self._password = password or os.getenv("REDIS_PASSWORD", "ragredis")
        self._db = db
        self._decode_responses = decode_responses
        self.default_ttl = int(os.getenv("REDIS_DEFAULT_TTL", 3600))

        # Determine TLS settings
        if use_tls is None:
            use_tls = os.getenv("REDIS_TLS_ENABLED", "false").lower() == "true"
        self._ssl_context = get_ssl_context() if use_tls else None

        # Determine if we should use Sentinel
        if use_sentinel is None:
            use_sentinel = os.getenv("REDIS_USE_SENTINEL", "false").lower() == "true"

        if use_sentinel:
            self.redis = self._create_sentinel_client(
                sentinel_hosts=sentinel_hosts,
                sentinel_master=sentinel_master,
            )
        else:
            self.redis = redis.Redis(
                host=host or os.getenv("REDIS_HOST", "localhost"),
                port=port or int(os.getenv("REDIS_PORT", 6379)),
                password=self._password,
                db=db,
                decode_responses=decode_responses,
                ssl=self._ssl_context is not None,
                ssl_context=self._ssl_context,
            )

    def _create_sentinel_client(
        self,
        sentinel_hosts: str | None = None,
        sentinel_master: str | None = None,
    ) -> redis.Redis:
        """Create Redis client via Sentinel for HA.

        Args:
            sentinel_hosts: Comma-separated list of host:port pairs.
            sentinel_master: Name of the master to connect to.

        Returns:
            Redis client connected to the master via Sentinel.
        """
        hosts_str = sentinel_hosts or os.getenv(
            "REDIS_SENTINEL_HOSTS",
            "redis-sentinel.rag-pipeline.svc.cluster.local:26379",
        )
        master_name = sentinel_master or os.getenv("REDIS_SENTINEL_MASTER", "mymaster")

        # Parse sentinel hosts
        sentinels = []
        for host_port in hosts_str.split(","):
            host_port = host_port.strip()
            if ":" in host_port:
                host, port = host_port.rsplit(":", 1)
                sentinels.append((host, int(port)))
            else:
                sentinels.append((host_port, 26379))

        sentinel_kwargs = {"password": self._password}
        if self._ssl_context:
            sentinel_kwargs["ssl"] = True
            sentinel_kwargs["ssl_context"] = self._ssl_context

        sentinel = Sentinel(
            sentinels,
            password=self._password,
            sentinel_kwargs=sentinel_kwargs,
        )

        master_kwargs = {
            "password": self._password,
            "db": self._db,
            "decode_responses": self._decode_responses,
        }
        if self._ssl_context:
            master_kwargs["ssl"] = True
            master_kwargs["ssl_context"] = self._ssl_context

        return sentinel.master_for(master_name, **master_kwargs)

    async def get(self, key: str) -> Any | None:
        """Get value from cache.

        Args:
            key: Cache key.

        Returns:
            Cached value or None if not found.
        """
        value = await self.redis.get(key)
        if value:
            return json.loads(value)
        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: int | None = None,
    ) -> None:
        """Set value in cache with optional TTL.

        Args:
            key: Cache key.
            value: Value to cache (will be JSON serialized).
            ttl: Time to live in seconds. Defaults to REDIS_DEFAULT_TTL.
        """
        await self.redis.set(
            key,
            json.dumps(value),
            ex=ttl or self.default_ttl,
        )

    async def delete(self, key: str) -> None:
        """Delete key from cache.

        Args:
            key: Cache key to delete.
        """
        await self.redis.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if key exists in cache.

        Args:
            key: Cache key to check.

        Returns:
            True if key exists, False otherwise.
        """
        return await self.redis.exists(key) > 0

    async def get_many(self, keys: list[str]) -> dict[str, Any | None]:
        """Get multiple values from cache.

        Args:
            keys: List of cache keys.

        Returns:
            Dict mapping keys to values (None for missing keys).
        """
        if not keys:
            return {}

        async with self.redis.pipeline() as pipe:
            for key in keys:
                pipe.get(key)
            results = await pipe.execute()

        return {keys[i]: json.loads(r) if r else None for i, r in enumerate(results)}

    async def set_many(
        self,
        items: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """Set multiple values in cache.

        Args:
            items: Dict mapping keys to values.
            ttl: Time to live in seconds.
        """
        if not items:
            return

        async with self.redis.pipeline() as pipe:
            for key, value in items.items():
                pipe.set(key, json.dumps(value), ex=ttl or self.default_ttl)
            await pipe.execute()

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern.

        Args:
            pattern: Redis key pattern (e.g., "prefix:*").

        Returns:
            Number of keys deleted.
        """
        keys = []
        async for key in self.redis.scan_iter(match=pattern):
            keys.append(key)

        if keys:
            return await self.redis.delete(*keys)
        return 0

    @staticmethod
    def generate_hash(*args: Any) -> str:
        """Generate a hash from arguments.

        Args:
            *args: Values to hash.

        Returns:
            16-character MD5 hash.
        """
        content = ":".join(str(arg) for arg in args)
        return hashlib.md5(content.encode()).hexdigest()[:16]

    async def health_check(self) -> bool:
        """Check Redis connectivity.

        Returns:
            True if Redis is reachable, False otherwise.
        """
        try:
            await self.redis.ping()
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close Redis connection."""
        await self.redis.close()

    async def __aenter__(self) -> "RedisCache":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()


def get_redis_client():
    """Get synchronous Redis client with Sentinel and TLS support.

    Returns:
        Redis client (sync) connected via Sentinel or directly.
    """
    import redis as sync_redis
    from redis.sentinel import Sentinel as SyncSentinel

    use_sentinel = os.getenv("REDIS_USE_SENTINEL", "false").lower() == "true"
    use_tls = os.getenv("REDIS_TLS_ENABLED", "false").lower() == "true"
    password = os.getenv("REDIS_PASSWORD", "ragredis")

    ssl_context = get_ssl_context() if use_tls else None

    if use_sentinel:
        sentinel_hosts = os.getenv(
            "REDIS_SENTINEL_HOSTS",
            "redis-sentinel.rag-pipeline.svc.cluster.local:26379",
        )
        sentinel_master = os.getenv("REDIS_SENTINEL_MASTER", "mymaster")

        sentinels = []
        for host_port in sentinel_hosts.split(","):
            host_port = host_port.strip()
            if ":" in host_port:
                host, port = host_port.rsplit(":", 1)
                sentinels.append((host, int(port)))
            else:
                sentinels.append((host_port, 26379))

        sentinel_kwargs = {"password": password}
        if ssl_context:
            sentinel_kwargs["ssl"] = True
            sentinel_kwargs["ssl_context"] = ssl_context

        sentinel = SyncSentinel(
            sentinels,
            socket_timeout=0.5,
            password=password,
            sentinel_kwargs=sentinel_kwargs,
        )

        master_kwargs = {
            "socket_timeout": 0.5,
            "password": password,
            "decode_responses": True,
        }
        if ssl_context:
            master_kwargs["ssl"] = True
            master_kwargs["ssl_context"] = ssl_context

        return sentinel.master_for(sentinel_master, **master_kwargs)
    kwargs = {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", 6379)),
        "password": password,
        "decode_responses": True,
    }
    if ssl_context:
        kwargs["ssl"] = True
        kwargs["ssl_context"] = ssl_context

    return sync_redis.Redis(**kwargs)


async def get_async_redis_client() -> redis.Redis:
    """Get async Redis client with Sentinel and TLS support.

    Returns:
        Async Redis client connected via Sentinel or directly.
    """
    use_sentinel = os.getenv("REDIS_USE_SENTINEL", "false").lower() == "true"
    use_tls = os.getenv("REDIS_TLS_ENABLED", "false").lower() == "true"
    password = os.getenv("REDIS_PASSWORD", "ragredis")

    ssl_context = get_ssl_context() if use_tls else None

    if use_sentinel:
        sentinel_hosts = os.getenv(
            "REDIS_SENTINEL_HOSTS",
            "redis-sentinel.rag-pipeline.svc.cluster.local:26379",
        )
        sentinel_master = os.getenv("REDIS_SENTINEL_MASTER", "mymaster")

        sentinels = []
        for host_port in sentinel_hosts.split(","):
            host_port = host_port.strip()
            if ":" in host_port:
                host, port = host_port.rsplit(":", 1)
                sentinels.append((host, int(port)))
            else:
                sentinels.append((host_port, 26379))

        sentinel_kwargs = {"password": password}
        if ssl_context:
            sentinel_kwargs["ssl"] = True
            sentinel_kwargs["ssl_context"] = ssl_context

        sentinel = Sentinel(
            sentinels,
            password=password,
            sentinel_kwargs=sentinel_kwargs,
        )

        master_kwargs = {"password": password}
        if ssl_context:
            master_kwargs["ssl"] = True
            master_kwargs["ssl_context"] = ssl_context

        return sentinel.master_for(sentinel_master, **master_kwargs)
    kwargs = {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", 6379)),
        "password": password,
        "decode_responses": True,
    }
    if ssl_context:
        kwargs["ssl"] = True
        kwargs["ssl_context"] = ssl_context

    return redis.Redis(**kwargs)

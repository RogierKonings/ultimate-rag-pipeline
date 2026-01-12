"""
Custom Prometheus Collectors.

Provides collectors for external systems:
- VectorDatabaseCollector: Qdrant statistics
- PostgreSQLCollector: Connection pool statistics
- RedisCollector: Redis connection statistics
"""

import logging
from collections.abc import Callable
from typing import Any

from prometheus_client import REGISTRY, Gauge

logger = logging.getLogger(__name__)


class VectorDatabaseCollector:
    """
    Collector for Qdrant vector database statistics.

    Collects:
    - Collection point counts
    - Collection segment counts
    - Collection status
    """

    def __init__(
        self,
        client_factory: Callable[[], Any],
        service_name: str = "rag_service",
        collections: list[str] | None = None,
    ):
        """
        Initialize the collector.

        Args:
            client_factory: Factory function that returns Qdrant client
            service_name: Service name for labels
            collections: List of collections to monitor (monitors all if None)
        """
        self.client_factory = client_factory
        self.service_name = service_name
        self.collections = collections

        # Metrics
        self.points_count = Gauge(
            "rag_vectordb_points_count",
            "Number of points in collection",
            ["service", "collection"],
            registry=REGISTRY,
        )

        self.segments_count = Gauge(
            "rag_vectordb_segments_count",
            "Number of segments in collection",
            ["service", "collection"],
            registry=REGISTRY,
        )

        self.collection_status = Gauge(
            "rag_vectordb_collection_status",
            "Collection status (1=green, 0.5=yellow, 0=red)",
            ["service", "collection"],
            registry=REGISTRY,
        )

        self.indexed_vectors = Gauge(
            "rag_vectordb_indexed_vectors",
            "Number of indexed vectors",
            ["service", "collection"],
            registry=REGISTRY,
        )

    async def collect_async(self) -> None:
        """
        Collect metrics asynchronously.

        Call this periodically to update metrics.
        """
        try:
            client = self.client_factory()

            # Get collections to monitor
            if self.collections:
                collection_names = self.collections
            else:
                collections_response = await client.get_collections()
                collection_names = [c.name for c in collections_response.collections]

            for name in collection_names:
                try:
                    info = await client.get_collection(name)

                    self.points_count.labels(
                        service=self.service_name,
                        collection=name,
                    ).set(info.points_count or 0)

                    self.segments_count.labels(
                        service=self.service_name,
                        collection=name,
                    ).set(info.segments_count or 0)

                    # Map status to numeric value
                    status_value = {
                        "green": 1.0,
                        "yellow": 0.5,
                        "red": 0.0,
                    }.get(info.status.lower(), 0.0)

                    self.collection_status.labels(
                        service=self.service_name,
                        collection=name,
                    ).set(status_value)

                    self.indexed_vectors.labels(
                        service=self.service_name,
                        collection=name,
                    ).set(info.indexed_vectors_count or 0)

                except Exception as e:
                    logger.warning(f"Error collecting metrics for collection {name}: {e}")

        except Exception as e:
            logger.error(f"Error collecting vector DB metrics: {e}")

    def collect_sync(self) -> None:
        """
        Collect metrics synchronously.

        Use this for synchronous contexts.
        """
        try:
            client = self.client_factory()

            if self.collections:
                collection_names = self.collections
            else:
                collections_response = client.get_collections()
                collection_names = [c.name for c in collections_response.collections]

            for name in collection_names:
                try:
                    info = client.get_collection(name)

                    self.points_count.labels(
                        service=self.service_name,
                        collection=name,
                    ).set(info.points_count or 0)

                    self.segments_count.labels(
                        service=self.service_name,
                        collection=name,
                    ).set(info.segments_count or 0)

                    status_value = {
                        "green": 1.0,
                        "yellow": 0.5,
                        "red": 0.0,
                    }.get(info.status.lower(), 0.0)

                    self.collection_status.labels(
                        service=self.service_name,
                        collection=name,
                    ).set(status_value)

                except Exception as e:
                    logger.warning(f"Error collecting metrics for collection {name}: {e}")

        except Exception as e:
            logger.error(f"Error collecting vector DB metrics: {e}")


class PostgreSQLCollector:
    """
    Collector for PostgreSQL connection pool statistics.

    Collects:
    - Active connections
    - Idle connections
    - Total connections
    - Pool size
    """

    def __init__(
        self,
        pool_factory: Callable[[], Any],
        service_name: str = "rag_service",
        pool_name: str = "default",
    ):
        """
        Initialize the collector.

        Args:
            pool_factory: Factory function that returns connection pool
            service_name: Service name for labels
            pool_name: Pool name for labels
        """
        self.pool_factory = pool_factory
        self.service_name = service_name
        self.pool_name = pool_name

        # Metrics
        self.active_connections = Gauge(
            "rag_postgres_connections_active",
            "Number of active PostgreSQL connections",
            ["service", "pool"],
            registry=REGISTRY,
        )

        self.idle_connections = Gauge(
            "rag_postgres_connections_idle",
            "Number of idle PostgreSQL connections",
            ["service", "pool"],
            registry=REGISTRY,
        )

        self.total_connections = Gauge(
            "rag_postgres_connections_total",
            "Total PostgreSQL connections in pool",
            ["service", "pool"],
            registry=REGISTRY,
        )

        self.pool_size = Gauge(
            "rag_postgres_pool_size",
            "PostgreSQL connection pool size",
            ["service", "pool"],
            registry=REGISTRY,
        )

        self.waiting_count = Gauge(
            "rag_postgres_waiting_count",
            "Number of operations waiting for connection",
            ["service", "pool"],
            registry=REGISTRY,
        )

    async def collect_async(self) -> None:
        """
        Collect metrics asynchronously for asyncpg pools.
        """
        try:
            pool = self.pool_factory()

            if pool is None:
                return

            # asyncpg pool attributes
            if hasattr(pool, "get_size"):
                size = pool.get_size()
                free = pool.get_idle_size()
                max_size = pool.get_max_size()

                self.total_connections.labels(
                    service=self.service_name,
                    pool=self.pool_name,
                ).set(size)

                self.idle_connections.labels(
                    service=self.service_name,
                    pool=self.pool_name,
                ).set(free)

                self.active_connections.labels(
                    service=self.service_name,
                    pool=self.pool_name,
                ).set(size - free)

                self.pool_size.labels(
                    service=self.service_name,
                    pool=self.pool_name,
                ).set(max_size)

        except Exception as e:
            logger.error(f"Error collecting PostgreSQL metrics: {e}")

    def collect_sync(self) -> None:
        """
        Collect metrics synchronously for psycopg2 pools.
        """
        try:
            pool = self.pool_factory()

            if pool is None:
                return

            # Try different pool interfaces
            if hasattr(pool, "getconn") and hasattr(pool, "_pool"):
                # ThreadedConnectionPool
                size = len(pool._pool) + len(pool._used)
                idle = len(pool._pool)

                self.total_connections.labels(
                    service=self.service_name,
                    pool=self.pool_name,
                ).set(size)

                self.idle_connections.labels(
                    service=self.service_name,
                    pool=self.pool_name,
                ).set(idle)

                self.active_connections.labels(
                    service=self.service_name,
                    pool=self.pool_name,
                ).set(size - idle)

        except Exception as e:
            logger.error(f"Error collecting PostgreSQL metrics: {e}")


class RedisCollector:
    """
    Collector for Redis statistics.

    Collects:
    - Connected clients
    - Memory usage
    - Commands processed
    - Cache hit rate
    """

    def __init__(
        self,
        client_factory: Callable[[], Any],
        service_name: str = "rag_service",
    ):
        """
        Initialize the collector.

        Args:
            client_factory: Factory function that returns Redis client
            service_name: Service name for labels
        """
        self.client_factory = client_factory
        self.service_name = service_name

        # Metrics
        self.connected_clients = Gauge(
            "rag_redis_connected_clients",
            "Number of connected Redis clients",
            ["service"],
            registry=REGISTRY,
        )

        self.memory_used = Gauge(
            "rag_redis_memory_used_bytes",
            "Redis memory usage in bytes",
            ["service"],
            registry=REGISTRY,
        )

        self.commands_processed = Gauge(
            "rag_redis_commands_processed_total",
            "Total commands processed by Redis",
            ["service"],
            registry=REGISTRY,
        )

        self.keyspace_hits = Gauge(
            "rag_redis_keyspace_hits_total",
            "Redis keyspace hits",
            ["service"],
            registry=REGISTRY,
        )

        self.keyspace_misses = Gauge(
            "rag_redis_keyspace_misses_total",
            "Redis keyspace misses",
            ["service"],
            registry=REGISTRY,
        )

    async def collect_async(self) -> None:
        """
        Collect metrics asynchronously.
        """
        try:
            client = self.client_factory()
            info = await client.info()

            self.connected_clients.labels(
                service=self.service_name,
            ).set(info.get("connected_clients", 0))

            self.memory_used.labels(
                service=self.service_name,
            ).set(info.get("used_memory", 0))

            self.commands_processed.labels(
                service=self.service_name,
            ).set(info.get("total_commands_processed", 0))

            self.keyspace_hits.labels(
                service=self.service_name,
            ).set(info.get("keyspace_hits", 0))

            self.keyspace_misses.labels(
                service=self.service_name,
            ).set(info.get("keyspace_misses", 0))

        except Exception as e:
            logger.error(f"Error collecting Redis metrics: {e}")

    def collect_sync(self) -> None:
        """
        Collect metrics synchronously.
        """
        try:
            client = self.client_factory()
            info = client.info()

            self.connected_clients.labels(
                service=self.service_name,
            ).set(info.get("connected_clients", 0))

            self.memory_used.labels(
                service=self.service_name,
            ).set(info.get("used_memory", 0))

            self.commands_processed.labels(
                service=self.service_name,
            ).set(info.get("total_commands_processed", 0))

            self.keyspace_hits.labels(
                service=self.service_name,
            ).set(info.get("keyspace_hits", 0))

            self.keyspace_misses.labels(
                service=self.service_name,
            ).set(info.get("keyspace_misses", 0))

        except Exception as e:
            logger.error(f"Error collecting Redis metrics: {e}")


class OpenSearchCollector:
    """
    Collector for OpenSearch statistics.

    Collects:
    - Index document counts
    - Index size
    - Cluster health
    """

    def __init__(
        self,
        client_factory: Callable[[], Any],
        service_name: str = "rag_service",
        indices: list[str] | None = None,
    ):
        """
        Initialize the collector.

        Args:
            client_factory: Factory function that returns OpenSearch client
            service_name: Service name for labels
            indices: List of indices to monitor
        """
        self.client_factory = client_factory
        self.service_name = service_name
        self.indices = indices

        # Metrics
        self.docs_count = Gauge(
            "rag_opensearch_docs_count",
            "Number of documents in index",
            ["service", "index"],
            registry=REGISTRY,
        )

        self.store_size_bytes = Gauge(
            "rag_opensearch_store_size_bytes",
            "Index size in bytes",
            ["service", "index"],
            registry=REGISTRY,
        )

        self.cluster_health = Gauge(
            "rag_opensearch_cluster_health",
            "Cluster health (1=green, 0.5=yellow, 0=red)",
            ["service"],
            registry=REGISTRY,
        )

    async def collect_async(self) -> None:
        """
        Collect metrics asynchronously.
        """
        try:
            client = self.client_factory()

            # Cluster health
            health = await client.cluster.health()
            status_value = {
                "green": 1.0,
                "yellow": 0.5,
                "red": 0.0,
            }.get(health.get("status", "red"), 0.0)

            self.cluster_health.labels(
                service=self.service_name,
            ).set(status_value)

            # Index stats
            indices_to_check = self.indices or ["*"]
            for index in indices_to_check:
                try:
                    stats = await client.indices.stats(index=index)
                    for idx_name, idx_stats in stats.get("indices", {}).items():
                        primaries = idx_stats.get("primaries", {})

                        self.docs_count.labels(
                            service=self.service_name,
                            index=idx_name,
                        ).set(primaries.get("docs", {}).get("count", 0))

                        self.store_size_bytes.labels(
                            service=self.service_name,
                            index=idx_name,
                        ).set(primaries.get("store", {}).get("size_in_bytes", 0))

                except Exception as e:
                    logger.warning(f"Error collecting stats for index {index}: {e}")

        except Exception as e:
            logger.error(f"Error collecting OpenSearch metrics: {e}")

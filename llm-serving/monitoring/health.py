"""
Health checking for LLM Serving Layer.

Provides health check implementations for Kubernetes liveness/readiness probes
and detailed component health status.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from .models import ComponentHealth, HealthStatus, ServiceHealth

logger = logging.getLogger(__name__)


class HealthChecker:
    """
    Health checking for LLM serving components.

    Provides both liveness and readiness checks for Kubernetes
    probes, as well as detailed component health status.
    """

    def __init__(
        self,
        service_name: str,
        model_name: str | None = None,
        check_interval: float = 30.0,
    ):
        """
        Initialize health checker.

        Args:
            service_name: Name of the service
            model_name: Name of the model being served
            check_interval: Interval between automatic health checks
        """
        self.service_name = service_name
        self.model_name = model_name
        self.check_interval = check_interval

        self._startup_time = time.time()
        self._last_request_time: datetime | None = None
        self._is_model_loaded = False
        self._components: dict[str, Callable] = {}

        self._check_task: asyncio.Task | None = None
        self._running = False
        self._last_health: ServiceHealth | None = None

    async def start(self) -> None:
        """Start periodic health checking."""
        self._running = True
        self._check_task = asyncio.create_task(self._check_loop())
        logger.info(f"Health checker started for {self.service_name}")

    async def stop(self) -> None:
        """Stop health checking."""
        self._running = False
        if self._check_task:
            self._check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._check_task
        logger.info(f"Health checker stopped for {self.service_name}")

    async def _check_loop(self) -> None:
        """Periodic health check loop."""
        while self._running:
            try:
                self._last_health = await self.run_checks()
            except Exception as e:
                logger.error(f"Health check error: {e}")

            await asyncio.sleep(self.check_interval)

    async def run_checks(self) -> ServiceHealth:
        """Run all health checks."""
        components = []
        overall_status = HealthStatus.HEALTHY

        # Check model status
        model_health = await self._check_model()
        components.append(model_health)
        if model_health.status != HealthStatus.HEALTHY:
            overall_status = HealthStatus.DEGRADED

        # Check GPU
        gpu_health = await self._check_gpu()
        components.append(gpu_health)
        if gpu_health.status == HealthStatus.UNHEALTHY:
            overall_status = HealthStatus.UNHEALTHY
        elif gpu_health.status == HealthStatus.DEGRADED:
            if overall_status == HealthStatus.HEALTHY:
                overall_status = HealthStatus.DEGRADED

        # Check custom components
        for name, check_fn in self._components.items():
            try:
                if asyncio.iscoroutinefunction(check_fn):
                    component = await check_fn()
                else:
                    component = check_fn()
                components.append(component)
                if component.status == HealthStatus.UNHEALTHY:
                    overall_status = HealthStatus.DEGRADED
            except Exception as e:
                components.append(
                    ComponentHealth(
                        name=name,
                        status=HealthStatus.UNHEALTHY,
                        message=str(e),
                    ),
                )
                overall_status = HealthStatus.DEGRADED

        # Get GPU details if available
        gpu_memory_used_mb = None
        gpu_memory_total_mb = None
        gpu_utilization = None
        gpu_available = False

        for c in components:
            if c.name == "gpu" and c.details:
                gpu_available = c.status != HealthStatus.UNHEALTHY
                gpu_memory_used_mb = c.details.get("memory_allocated_mb")
                gpu_memory_total_mb = c.details.get("memory_total_mb")
                gpu_utilization = c.details.get("utilization_percent")

        return ServiceHealth(
            service_name=self.service_name,
            status=overall_status,
            components=components,
            model_loaded=self._is_model_loaded,
            model_name=self.model_name,
            gpu_available=gpu_available,
            gpu_memory_used_mb=gpu_memory_used_mb,
            gpu_memory_total_mb=gpu_memory_total_mb,
            gpu_utilization_percent=gpu_utilization,
            uptime_seconds=time.time() - self._startup_time,
            last_request_time=self._last_request_time,
        )

    async def _check_model(self) -> ComponentHealth:
        """Check if model is loaded and responsive."""
        start = time.time()

        try:
            if self._is_model_loaded:
                return ComponentHealth(
                    name="model",
                    status=HealthStatus.HEALTHY,
                    message=f"Model {self.model_name} loaded",
                    latency_ms=(time.time() - start) * 1000,
                )
            return ComponentHealth(
                name="model",
                status=HealthStatus.UNHEALTHY,
                message="Model not loaded",
            )
        except Exception as e:
            return ComponentHealth(
                name="model",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )

    async def _check_gpu(self) -> ComponentHealth:
        """Check GPU availability and health."""
        start = time.time()

        try:
            import torch

            if not torch.cuda.is_available():
                return ComponentHealth(
                    name="gpu",
                    status=HealthStatus.UNKNOWN,
                    message="CUDA not available (CPU mode)",
                )

            # Check GPU memory
            memory_allocated = torch.cuda.memory_allocated()
            memory_total = torch.cuda.get_device_properties(0).total_memory
            memory_percent = (memory_allocated / memory_total) * 100

            status = HealthStatus.HEALTHY
            if memory_percent > 95:
                status = HealthStatus.DEGRADED

            return ComponentHealth(
                name="gpu",
                status=status,
                message=f"GPU memory: {memory_percent:.1f}%",
                latency_ms=(time.time() - start) * 1000,
                details={
                    "memory_allocated_mb": memory_allocated / 1024 / 1024,
                    "memory_total_mb": memory_total / 1024 / 1024,
                    "memory_percent": memory_percent,
                },
            )
        except ImportError:
            return ComponentHealth(
                name="gpu",
                status=HealthStatus.UNKNOWN,
                message="PyTorch not available",
            )
        except Exception as e:
            return ComponentHealth(
                name="gpu",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )

    def register_component(self, name: str, check_fn: Callable) -> None:
        """
        Register a component health check.

        Args:
            name: Name of the component
            check_fn: Function that returns ComponentHealth
        """
        self._components[name] = check_fn

    def unregister_component(self, name: str) -> None:
        """Unregister a component health check."""
        if name in self._components:
            del self._components[name]

    def set_model_loaded(self, loaded: bool) -> None:
        """Update model loaded status."""
        self._is_model_loaded = loaded

    def record_request(self) -> None:
        """Record that a request was processed."""
        self._last_request_time = datetime.now(tz=UTC)

    def liveness_check(self) -> bool:
        """Simple liveness check for Kubernetes."""
        return True  # Service is alive if this code runs

    def readiness_check(self) -> bool:
        """Readiness check for Kubernetes."""
        return self._is_model_loaded

    def get_last_health(self) -> ServiceHealth | None:
        """Get the last health check result."""
        return self._last_health

    def is_running(self) -> bool:
        """Check if health checking is running."""
        return self._running


class VLLMHealthChecker(HealthChecker):
    """Health checker for vLLM service."""

    def __init__(
        self,
        vllm_url: str = "http://localhost:8000",
        model_name: str = "vllm-model",
    ):
        """
        Initialize vLLM health checker.

        Args:
            vllm_url: URL of the vLLM service
            model_name: Expected model name
        """
        super().__init__(service_name="vllm", model_name=model_name)
        self.vllm_url = vllm_url

    async def _check_model(self) -> ComponentHealth:
        """Check vLLM model status."""
        start = time.time()

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.vllm_url}/v1/models",
                    timeout=5.0,
                )

                if response.status_code == 200:
                    data = response.json()
                    models = data.get("data", [])

                    if models:
                        self._is_model_loaded = True
                        self.model_name = models[0].get("id", "unknown")

                        return ComponentHealth(
                            name="model",
                            status=HealthStatus.HEALTHY,
                            message=f"Model {self.model_name} loaded",
                            latency_ms=(time.time() - start) * 1000,
                            details={"models": [m.get("id") for m in models]},
                        )

                self._is_model_loaded = False
                return ComponentHealth(
                    name="model",
                    status=HealthStatus.UNHEALTHY,
                    message="No models loaded",
                )

        except httpx.ConnectError:
            self._is_model_loaded = False
            return ComponentHealth(
                name="model",
                status=HealthStatus.UNHEALTHY,
                message=f"Cannot connect to vLLM at {self.vllm_url}",
            )
        except Exception as e:
            self._is_model_loaded = False
            return ComponentHealth(
                name="model",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )


class EmbeddingHealthChecker(HealthChecker):
    """Health checker for embedding service."""

    def __init__(
        self,
        embedding_url: str = "http://localhost:8001",
        model_name: str = "BAAI/bge-large-en-v1.5",
    ):
        """
        Initialize embedding health checker.

        Args:
            embedding_url: URL of the embedding service
            model_name: Expected model name
        """
        super().__init__(service_name="embedding", model_name=model_name)
        self.embedding_url = embedding_url

    async def _check_model(self) -> ComponentHealth:
        """Check embedding model status via health endpoint."""
        start = time.time()

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.embedding_url}/health",
                    timeout=5.0,
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("model_loaded"):
                        self._is_model_loaded = True
                        return ComponentHealth(
                            name="model",
                            status=HealthStatus.HEALTHY,
                            message="Embedding model loaded",
                            latency_ms=(time.time() - start) * 1000,
                            details={
                                "embedding_dim": data.get("embedding_dim"),
                            },
                        )

                self._is_model_loaded = False
                return ComponentHealth(
                    name="model",
                    status=HealthStatus.UNHEALTHY,
                    message="Model not loaded",
                )

        except httpx.ConnectError:
            self._is_model_loaded = False
            return ComponentHealth(
                name="model",
                status=HealthStatus.UNHEALTHY,
                message=f"Cannot connect to embedding service at {self.embedding_url}",
            )
        except Exception as e:
            self._is_model_loaded = False
            return ComponentHealth(
                name="model",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )


class RerankerHealthChecker(HealthChecker):
    """Health checker for reranker service."""

    def __init__(
        self,
        reranker_url: str = "http://localhost:8002",
        model_name: str = "BAAI/bge-reranker-v2-m3",
    ):
        """
        Initialize reranker health checker.

        Args:
            reranker_url: URL of the reranker service
            model_name: Expected model name
        """
        super().__init__(service_name="reranker", model_name=model_name)
        self.reranker_url = reranker_url

    async def _check_model(self) -> ComponentHealth:
        """Check reranker model status via health endpoint."""
        start = time.time()

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.reranker_url}/health",
                    timeout=5.0,
                )

                if response.status_code == 200:
                    data = response.json()
                    if data.get("model_loaded"):
                        self._is_model_loaded = True
                        return ComponentHealth(
                            name="model",
                            status=HealthStatus.HEALTHY,
                            message="Reranker model loaded",
                            latency_ms=(time.time() - start) * 1000,
                        )

                self._is_model_loaded = False
                return ComponentHealth(
                    name="model",
                    status=HealthStatus.UNHEALTHY,
                    message="Model not loaded",
                )

        except httpx.ConnectError:
            self._is_model_loaded = False
            return ComponentHealth(
                name="model",
                status=HealthStatus.UNHEALTHY,
                message=f"Cannot connect to reranker service at {self.reranker_url}",
            )
        except Exception as e:
            self._is_model_loaded = False
            return ComponentHealth(
                name="model",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )

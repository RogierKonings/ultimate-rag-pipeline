"""
GPU Monitor for LLM Serving Layer.

Monitors GPU metrics using nvidia-smi, providing real-time
GPU utilization, memory usage, temperature, and power consumption.
"""

import asyncio
import contextlib
import logging
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Callable

from prometheus_client import Gauge

from .models import GPUMetrics

logger = logging.getLogger(__name__)

# Prometheus metrics for GPU monitoring
GPU_MEMORY_USED = Gauge(
    "gpu_memory_used_bytes",
    "GPU memory used in bytes",
    ["gpu_id", "gpu_name"],
)

GPU_MEMORY_TOTAL = Gauge(
    "gpu_memory_total_bytes",
    "GPU memory total in bytes",
    ["gpu_id", "gpu_name"],
)

GPU_UTILIZATION = Gauge(
    "gpu_utilization_percent",
    "GPU utilization percentage",
    ["gpu_id", "gpu_name"],
)

GPU_TEMPERATURE = Gauge(
    "gpu_temperature_celsius",
    "GPU temperature in Celsius",
    ["gpu_id", "gpu_name"],
)

GPU_POWER_DRAW = Gauge(
    "gpu_power_draw_watts",
    "GPU power draw in watts",
    ["gpu_id", "gpu_name"],
)


class GPUMonitor:
    """
    Monitor GPU metrics using nvidia-smi.

    Provides real-time GPU utilization, memory usage,
    temperature, and power consumption metrics.
    """

    def __init__(self, poll_interval: float = 5.0):
        """
        Initialize GPU monitor.

        Args:
            poll_interval: Interval in seconds between metric collections
        """
        self.poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task | None = None
        self._latest_metrics: dict[int, GPUMetrics] = {}
        self._callbacks: list[Callable] = []

    async def start(self) -> None:
        """Start GPU monitoring."""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("GPU monitoring started")

    async def stop(self) -> None:
        """Stop GPU monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("GPU monitoring stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                metrics = await self._collect_metrics()
                self._latest_metrics = {m.gpu_id: m for m in metrics}
                self._update_prometheus_metrics(metrics)
                await self._notify_callbacks(metrics)
            except Exception as e:
                logger.error(f"GPU monitoring error: {e}")

            await asyncio.sleep(self.poll_interval)

    async def _collect_metrics(self) -> list[GPUMetrics]:
        """Collect GPU metrics using nvidia-smi."""
        loop = asyncio.get_event_loop()

        def _run_nvidia_smi():
            result = subprocess.run(
                ["nvidia-smi", "-q", "-x"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout

        try:
            xml_output = await loop.run_in_executor(None, _run_nvidia_smi)
            return self._parse_nvidia_smi_xml(xml_output)
        except FileNotFoundError:
            logger.warning("nvidia-smi not found - GPU monitoring unavailable")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("nvidia-smi timeout")
            return []
        except Exception as e:
            logger.error(f"Error collecting GPU metrics: {e}")
            return []

    def _parse_nvidia_smi_xml(self, xml_str: str) -> list[GPUMetrics]:
        """Parse nvidia-smi XML output."""
        root = ET.fromstring(xml_str)
        metrics = []

        for i, gpu in enumerate(root.findall("gpu")):
            try:
                fb_memory = gpu.find("fb_memory_usage")
                utilization = gpu.find("utilization")
                temperature = gpu.find("temperature")
                power = gpu.find("power_readings")
                clocks = gpu.find("clocks")

                metrics.append(
                    GPUMetrics(
                        gpu_id=i,
                        name=gpu.find("product_name").text,
                        memory_total=self._parse_memory(fb_memory.find("total").text),
                        memory_used=self._parse_memory(fb_memory.find("used").text),
                        memory_free=self._parse_memory(fb_memory.find("free").text),
                        memory_utilization_percent=self._parse_percent(
                            utilization.find("memory_util").text,
                        ),
                        gpu_utilization_percent=self._parse_percent(
                            utilization.find("gpu_util").text,
                        ),
                        temperature_celsius=float(
                            temperature.find("gpu_temp").text.replace(" C", ""),
                        ),
                        power_draw_watts=self._parse_power(
                            power.find("power_draw").text,
                        ),
                        power_limit_watts=self._parse_power(
                            power.find("power_limit").text,
                        ),
                        sm_clock=self._parse_clock(clocks.find("sm_clock").text),
                        memory_clock=self._parse_clock(clocks.find("mem_clock").text),
                    ),
                )
            except Exception as e:
                logger.warning(f"Failed to parse GPU {i}: {e}")

        return metrics

    def _parse_memory(self, s: str) -> int:
        """Parse memory string like '16384 MiB' to bytes."""
        parts = s.strip().split()
        value = float(parts[0])
        unit = parts[1] if len(parts) > 1 else "MiB"

        if unit == "MiB":
            return int(value * 1024 * 1024)
        if unit == "GiB":
            return int(value * 1024 * 1024 * 1024)
        return int(value)

    def _parse_percent(self, s: str) -> float:
        """Parse percentage string like '45 %' to float."""
        return float(s.strip().replace(" %", "").replace("%", ""))

    def _parse_power(self, s: str) -> float:
        """Parse power string like '125.00 W' to float."""
        return float(s.strip().replace(" W", "").replace("W", ""))

    def _parse_clock(self, s: str) -> int:
        """Parse clock string like '1530 MHz' to int."""
        return int(s.strip().replace(" MHz", "").replace("MHz", ""))

    def _update_prometheus_metrics(self, metrics: list[GPUMetrics]) -> None:
        """Update Prometheus metrics."""
        for m in metrics:
            labels = {"gpu_id": str(m.gpu_id), "gpu_name": m.name}
            GPU_MEMORY_USED.labels(**labels).set(m.memory_used)
            GPU_MEMORY_TOTAL.labels(**labels).set(m.memory_total)
            GPU_UTILIZATION.labels(**labels).set(m.gpu_utilization_percent)
            GPU_TEMPERATURE.labels(**labels).set(m.temperature_celsius)
            GPU_POWER_DRAW.labels(**labels).set(m.power_draw_watts)

    def get_metrics(self, gpu_id: int | None = None) -> list[GPUMetrics]:
        """
        Get latest GPU metrics.

        Args:
            gpu_id: Optional specific GPU ID to get metrics for

        Returns:
            List of GPU metrics
        """
        if gpu_id is not None:
            m = self._latest_metrics.get(gpu_id)
            return [m] if m else []
        return list(self._latest_metrics.values())

    def get_total_memory_used(self) -> int:
        """Get total GPU memory used across all GPUs."""
        return sum(m.memory_used for m in self._latest_metrics.values())

    def get_total_memory_total(self) -> int:
        """Get total GPU memory available across all GPUs."""
        return sum(m.memory_total for m in self._latest_metrics.values())

    def get_avg_utilization(self) -> float:
        """Get average GPU utilization across all GPUs."""
        if not self._latest_metrics:
            return 0.0
        return sum(
            m.gpu_utilization_percent for m in self._latest_metrics.values()
        ) / len(self._latest_metrics)

    def get_max_temperature(self) -> float:
        """Get maximum GPU temperature across all GPUs."""
        if not self._latest_metrics:
            return 0.0
        return max(m.temperature_celsius for m in self._latest_metrics.values())

    def get_total_power_draw(self) -> float:
        """Get total power draw across all GPUs."""
        return sum(m.power_draw_watts for m in self._latest_metrics.values())

    def register_callback(self, callback: Callable) -> None:
        """
        Register callback for metric updates.

        Args:
            callback: Function to call with list of GPUMetrics
        """
        self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable) -> None:
        """
        Unregister a callback.

        Args:
            callback: Callback to remove
        """
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def _notify_callbacks(self, metrics: list[GPUMetrics]) -> None:
        """Notify registered callbacks."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(metrics)
                else:
                    callback(metrics)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def is_running(self) -> bool:
        """Check if monitoring is running."""
        return self._running

    def get_gpu_count(self) -> int:
        """Get number of GPUs being monitored."""
        return len(self._latest_metrics)

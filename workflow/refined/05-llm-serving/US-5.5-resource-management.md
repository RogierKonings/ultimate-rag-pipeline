# US-5.5: Resource Management

> **Story ID:** US-5.5  
> **Epic:** LLM Serving Layer  
> **Priority:** High  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-5.1 (vLLM Deployment), US-5.2 (Embedding Service), US-5.3 (Reranker Service)

## User Story

**As a** platform engineer  
**I want** efficient GPU resource usage  
**So that** costs are optimized and resources are allocated effectively

## Context

Resource Management ensures efficient utilization of expensive GPU resources across all LLM serving components. This includes GPU memory monitoring, request batching optimization, auto-scaling based on queue depth and GPU utilization, Kubernetes resource limits, and cost tracking per model. The goal is to maximize throughput while minimizing infrastructure costs.

Key features:
- GPU memory monitoring and alerting
- Request batching optimization
- Horizontal Pod Autoscaler (HPA) configuration
- Resource quotas and limits
- Cost tracking and allocation
- Capacity planning tools

## Technical Requirements

### Directory Structure

```
llm-serving/
└── resource-management/
    ├── __init__.py
    ├── gpu_monitor.py           # GPU monitoring
    ├── batch_optimizer.py       # Batch optimization
    ├── cost_tracker.py          # Cost tracking
    ├── capacity_planner.py      # Capacity planning
    ├── k8s/
    │   ├── resource-quotas.yaml
    │   ├── limit-ranges.yaml
    │   ├── hpa-vllm.yaml
    │   ├── hpa-embedding.yaml
    │   ├── hpa-reranker.yaml
    │   ├── vpa.yaml             # Vertical Pod Autoscaler
    │   └── priority-classes.yaml
    └── dashboards/
        └── resource-usage.json   # Grafana dashboard
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum
from datetime import datetime, timedelta
from uuid import UUID

class GPUMetrics(BaseModel):
    """GPU metrics snapshot."""
    
    gpu_id: int
    name: str
    
    # Memory metrics (bytes)
    memory_total: int
    memory_used: int
    memory_free: int
    memory_utilization_percent: float
    
    # Compute metrics
    gpu_utilization_percent: float
    temperature_celsius: float
    power_draw_watts: float
    power_limit_watts: float
    
    # Clock speeds (MHz)
    sm_clock: int
    memory_clock: int
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    @property
    def memory_utilization(self) -> float:
        return self.memory_used / self.memory_total if self.memory_total > 0 else 0.0

class ServiceResourceMetrics(BaseModel):
    """Resource metrics for a service."""
    
    service_name: str
    pod_name: str
    namespace: str = "llm-serving"
    
    # GPU metrics
    gpu_metrics: Optional[GPUMetrics] = None
    
    # CPU metrics
    cpu_usage_cores: float
    cpu_request_cores: float
    cpu_limit_cores: float
    
    # Memory metrics (bytes)
    memory_usage_bytes: int
    memory_request_bytes: int
    memory_limit_bytes: int
    
    # Request metrics
    pending_requests: int
    active_requests: int
    requests_per_second: float
    
    # Queue metrics
    queue_depth: int
    avg_queue_wait_ms: float
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class BatchingMetrics(BaseModel):
    """Metrics for batch processing optimization."""
    
    service_name: str
    
    # Batch statistics
    avg_batch_size: float
    max_batch_size: int
    min_batch_size: int
    
    # Fill rate (actual vs max batch size)
    batch_fill_rate: float
    
    # Timing
    avg_batch_wait_ms: float
    avg_batch_processing_ms: float
    
    # Throughput
    items_per_second: float
    batches_per_second: float
    
    # Efficiency score (higher is better)
    efficiency_score: float
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class CostRecord(BaseModel):
    """Cost record for a time period."""
    
    id: UUID
    service_name: str
    model_name: str
    
    # Time period
    start_time: datetime
    end_time: datetime
    
    # Usage metrics
    gpu_hours: float
    cpu_hours: float
    memory_gb_hours: float
    
    # Request counts
    total_requests: int
    total_tokens_processed: int
    
    # Costs (in USD or configured currency)
    gpu_cost: float
    cpu_cost: float
    memory_cost: float
    total_cost: float
    
    # Per-unit costs
    cost_per_request: float
    cost_per_1k_tokens: float

class ResourceRecommendation(BaseModel):
    """Resource scaling recommendation."""
    
    service_name: str
    recommendation_type: Literal["scale_up", "scale_down", "optimize", "maintain"]
    
    # Current state
    current_replicas: int
    current_gpu_utilization: float
    current_queue_depth: int
    
    # Recommended state
    recommended_replicas: int
    recommended_batch_size: Optional[int] = None
    
    # Reasoning
    reason: str
    confidence: float  # 0.0 to 1.0
    
    # Expected impact
    expected_cost_change_percent: float
    expected_latency_change_percent: float
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ScalingPolicy(BaseModel):
    """Auto-scaling policy configuration."""
    
    service_name: str
    
    # Replica bounds
    min_replicas: int = 1
    max_replicas: int = 10
    
    # Scale-up thresholds
    scale_up_gpu_utilization: float = 80.0
    scale_up_queue_depth: int = 100
    scale_up_latency_p95_ms: float = 1000.0
    
    # Scale-down thresholds
    scale_down_gpu_utilization: float = 30.0
    scale_down_queue_depth: int = 10
    
    # Cooldown periods
    scale_up_cooldown_seconds: int = 60
    scale_down_cooldown_seconds: int = 300
    
    # Behavior
    scale_up_step: int = 1
    scale_down_step: int = 1
    
    # Cost constraints
    max_hourly_cost: Optional[float] = None
```

### GPU Monitor

```python
import asyncio
from typing import Optional
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class GPUMonitor:
    """
    Monitor GPU metrics using nvidia-smi.
    
    Provides real-time GPU utilization, memory usage,
    temperature, and power consumption metrics.
    """
    
    def __init__(self, poll_interval: float = 5.0):
        self.poll_interval = poll_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._latest_metrics: dict[int, GPUMetrics] = {}
        self._callbacks: list = []
    
    async def start(self):
        """Start GPU monitoring."""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("GPU monitoring started")
    
    async def stop(self):
        """Stop GPU monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                metrics = await self._collect_metrics()
                self._latest_metrics = {m.gpu_id: m for m in metrics}
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
                timeout=10
            )
            return result.stdout
        
        try:
            xml_output = await loop.run_in_executor(None, _run_nvidia_smi)
            return self._parse_nvidia_smi_xml(xml_output)
        except FileNotFoundError:
            logger.warning("nvidia-smi not found")
            return []
        except subprocess.TimeoutExpired:
            logger.warning("nvidia-smi timeout")
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
                
                metrics.append(GPUMetrics(
                    gpu_id=i,
                    name=gpu.find("product_name").text,
                    memory_total=self._parse_memory(fb_memory.find("total").text),
                    memory_used=self._parse_memory(fb_memory.find("used").text),
                    memory_free=self._parse_memory(fb_memory.find("free").text),
                    memory_utilization_percent=self._parse_percent(
                        utilization.find("memory_util").text
                    ),
                    gpu_utilization_percent=self._parse_percent(
                        utilization.find("gpu_util").text
                    ),
                    temperature_celsius=float(
                        temperature.find("gpu_temp").text.replace(" C", "")
                    ),
                    power_draw_watts=self._parse_power(
                        power.find("power_draw").text
                    ),
                    power_limit_watts=self._parse_power(
                        power.find("power_limit").text
                    ),
                    sm_clock=self._parse_clock(clocks.find("sm_clock").text),
                    memory_clock=self._parse_clock(clocks.find("mem_clock").text)
                ))
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
        elif unit == "GiB":
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
    
    def get_metrics(self, gpu_id: Optional[int] = None) -> list[GPUMetrics]:
        """Get latest GPU metrics."""
        if gpu_id is not None:
            m = self._latest_metrics.get(gpu_id)
            return [m] if m else []
        return list(self._latest_metrics.values())
    
    def get_total_memory_used(self) -> int:
        """Get total GPU memory used across all GPUs."""
        return sum(m.memory_used for m in self._latest_metrics.values())
    
    def get_avg_utilization(self) -> float:
        """Get average GPU utilization across all GPUs."""
        if not self._latest_metrics:
            return 0.0
        return sum(m.gpu_utilization_percent for m in self._latest_metrics.values()) / len(self._latest_metrics)
    
    def register_callback(self, callback):
        """Register callback for metric updates."""
        self._callbacks.append(callback)
    
    async def _notify_callbacks(self, metrics: list[GPUMetrics]):
        """Notify registered callbacks."""
        for callback in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(metrics)
                else:
                    callback(metrics)
            except Exception as e:
                logger.error(f"Callback error: {e}")
```

### Batch Optimizer

```python
from dataclasses import dataclass
from typing import Optional
import statistics
import asyncio
import logging

logger = logging.getLogger(__name__)

@dataclass
class BatchStats:
    """Statistics for batch processing."""
    batch_sizes: list[int]
    processing_times_ms: list[float]
    wait_times_ms: list[float]

class BatchOptimizer:
    """
    Optimizes batch processing parameters based on observed metrics.
    
    Monitors batch fill rates, processing times, and throughput
    to recommend optimal batch sizes and timeouts.
    """
    
    def __init__(
        self,
        service_name: str,
        initial_batch_size: int = 32,
        initial_timeout_ms: float = 50.0,
        window_size: int = 100
    ):
        self.service_name = service_name
        self.current_batch_size = initial_batch_size
        self.current_timeout_ms = initial_timeout_ms
        self.window_size = window_size
        
        self._batch_sizes: list[int] = []
        self._processing_times: list[float] = []
        self._wait_times: list[float] = []
        self._throughputs: list[float] = []
    
    def record_batch(
        self,
        batch_size: int,
        processing_time_ms: float,
        wait_time_ms: float
    ):
        """Record a batch processing event."""
        self._batch_sizes.append(batch_size)
        self._processing_times.append(processing_time_ms)
        self._wait_times.append(wait_time_ms)
        
        # Calculate throughput (items per second)
        total_time_s = (processing_time_ms + wait_time_ms) / 1000
        if total_time_s > 0:
            self._throughputs.append(batch_size / total_time_s)
        
        # Trim to window size
        if len(self._batch_sizes) > self.window_size:
            self._batch_sizes = self._batch_sizes[-self.window_size:]
            self._processing_times = self._processing_times[-self.window_size:]
            self._wait_times = self._wait_times[-self.window_size:]
            self._throughputs = self._throughputs[-self.window_size:]
    
    def get_metrics(self) -> BatchingMetrics:
        """Get current batching metrics."""
        if not self._batch_sizes:
            return BatchingMetrics(
                service_name=self.service_name,
                avg_batch_size=0,
                max_batch_size=0,
                min_batch_size=0,
                batch_fill_rate=0,
                avg_batch_wait_ms=0,
                avg_batch_processing_ms=0,
                items_per_second=0,
                batches_per_second=0,
                efficiency_score=0
            )
        
        avg_batch = statistics.mean(self._batch_sizes)
        fill_rate = avg_batch / self.current_batch_size if self.current_batch_size > 0 else 0
        
        return BatchingMetrics(
            service_name=self.service_name,
            avg_batch_size=avg_batch,
            max_batch_size=max(self._batch_sizes),
            min_batch_size=min(self._batch_sizes),
            batch_fill_rate=fill_rate,
            avg_batch_wait_ms=statistics.mean(self._wait_times) if self._wait_times else 0,
            avg_batch_processing_ms=statistics.mean(self._processing_times) if self._processing_times else 0,
            items_per_second=statistics.mean(self._throughputs) if self._throughputs else 0,
            batches_per_second=len(self._batch_sizes) / self.window_size,
            efficiency_score=self._calculate_efficiency()
        )
    
    def _calculate_efficiency(self) -> float:
        """
        Calculate efficiency score (0-1).
        
        Higher is better. Considers:
        - Batch fill rate (want high)
        - Wait time relative to processing (want low)
        - Throughput stability
        """
        if not self._batch_sizes or not self._processing_times:
            return 0.0
        
        # Fill rate component (0-0.4)
        avg_fill = statistics.mean(self._batch_sizes) / self.current_batch_size
        fill_score = min(avg_fill, 1.0) * 0.4
        
        # Wait efficiency component (0-0.3)
        # Lower wait-to-processing ratio is better
        if self._processing_times:
            avg_wait = statistics.mean(self._wait_times) if self._wait_times else 0
            avg_proc = statistics.mean(self._processing_times)
            wait_ratio = avg_wait / (avg_wait + avg_proc) if (avg_wait + avg_proc) > 0 else 0
            wait_score = (1 - wait_ratio) * 0.3
        else:
            wait_score = 0
        
        # Throughput stability component (0-0.3)
        if len(self._throughputs) > 1:
            try:
                cv = statistics.stdev(self._throughputs) / statistics.mean(self._throughputs)
                stability_score = max(0, 1 - cv) * 0.3
            except:
                stability_score = 0
        else:
            stability_score = 0.15
        
        return fill_score + wait_score + stability_score
    
    def recommend_parameters(self) -> dict:
        """
        Recommend optimal batch parameters based on observed data.
        
        Returns:
            Dict with recommended batch_size and timeout_ms
        """
        if len(self._batch_sizes) < 10:
            return {
                "batch_size": self.current_batch_size,
                "timeout_ms": self.current_timeout_ms,
                "confidence": 0.0,
                "reason": "Insufficient data"
            }
        
        metrics = self.get_metrics()
        
        # Low fill rate: decrease batch size or increase timeout
        if metrics.batch_fill_rate < 0.5:
            if metrics.avg_batch_wait_ms < self.current_timeout_ms * 0.8:
                # Timeout rarely reached, increase it
                new_timeout = min(self.current_timeout_ms * 1.5, 500.0)
                return {
                    "batch_size": self.current_batch_size,
                    "timeout_ms": new_timeout,
                    "confidence": 0.7,
                    "reason": f"Low fill rate ({metrics.batch_fill_rate:.2f}), increasing timeout"
                }
            else:
                # Decrease batch size
                new_batch_size = max(int(self.current_batch_size * 0.75), 4)
                return {
                    "batch_size": new_batch_size,
                    "timeout_ms": self.current_timeout_ms,
                    "confidence": 0.8,
                    "reason": f"Low fill rate ({metrics.batch_fill_rate:.2f}), decreasing batch size"
                }
        
        # High fill rate and quick processing: increase batch size
        if metrics.batch_fill_rate > 0.9 and metrics.avg_batch_processing_ms < 100:
            new_batch_size = min(int(self.current_batch_size * 1.25), 128)
            return {
                "batch_size": new_batch_size,
                "timeout_ms": self.current_timeout_ms,
                "confidence": 0.7,
                "reason": f"High fill rate ({metrics.batch_fill_rate:.2f}) with fast processing, increasing batch size"
            }
        
        # Good efficiency, maintain current settings
        return {
            "batch_size": self.current_batch_size,
            "timeout_ms": self.current_timeout_ms,
            "confidence": 0.9,
            "reason": f"Current settings optimal (efficiency: {metrics.efficiency_score:.2f})"
        }
    
    def apply_recommendation(self, recommendation: dict):
        """Apply recommended parameters."""
        self.current_batch_size = recommendation["batch_size"]
        self.current_timeout_ms = recommendation["timeout_ms"]
        logger.info(
            f"Applied batch optimization for {self.service_name}: "
            f"batch_size={self.current_batch_size}, timeout={self.current_timeout_ms}ms"
        )
```

### Cost Tracker

```python
from datetime import datetime, timedelta
from uuid import uuid4
from typing import Optional
import asyncio
import logging

logger = logging.getLogger(__name__)

class CostConfig:
    """Cost configuration per resource type."""
    
    # GPU costs (per hour)
    GPU_COST_PER_HOUR = {
        "NVIDIA-A100-SXM4-40GB": 4.00,
        "NVIDIA-A100-SXM4-80GB": 6.00,
        "NVIDIA-A10": 1.50,
        "NVIDIA-T4": 0.75,
    }
    
    # CPU cost per core-hour
    CPU_COST_PER_CORE_HOUR = 0.05
    
    # Memory cost per GB-hour
    MEMORY_COST_PER_GB_HOUR = 0.01

class CostTracker:
    """
    Track and allocate costs for LLM serving infrastructure.
    
    Monitors GPU, CPU, and memory usage per service/model
    and calculates associated costs.
    """
    
    def __init__(
        self,
        config: Optional[CostConfig] = None,
        aggregation_interval: timedelta = timedelta(hours=1)
    ):
        self.config = config or CostConfig()
        self.aggregation_interval = aggregation_interval
        
        self._current_period_start = datetime.utcnow()
        self._usage_accumulator: dict[str, dict] = {}
        self._cost_records: list[CostRecord] = []
    
    def record_usage(
        self,
        service_name: str,
        model_name: str,
        gpu_name: str,
        gpu_utilization: float,
        cpu_cores: float,
        memory_gb: float,
        requests: int = 0,
        tokens: int = 0,
        duration_seconds: float = 1.0
    ):
        """Record resource usage for cost tracking."""
        key = f"{service_name}:{model_name}"
        
        if key not in self._usage_accumulator:
            self._usage_accumulator[key] = {
                "service_name": service_name,
                "model_name": model_name,
                "gpu_name": gpu_name,
                "gpu_seconds": 0.0,
                "cpu_core_seconds": 0.0,
                "memory_gb_seconds": 0.0,
                "requests": 0,
                "tokens": 0
            }
        
        acc = self._usage_accumulator[key]
        acc["gpu_seconds"] += duration_seconds * (gpu_utilization / 100.0)
        acc["cpu_core_seconds"] += cpu_cores * duration_seconds
        acc["memory_gb_seconds"] += memory_gb * duration_seconds
        acc["requests"] += requests
        acc["tokens"] += tokens
        
        # Check if we should finalize the period
        if datetime.utcnow() - self._current_period_start > self.aggregation_interval:
            self._finalize_period()
    
    def _finalize_period(self):
        """Finalize the current period and create cost records."""
        period_end = datetime.utcnow()
        
        for key, acc in self._usage_accumulator.items():
            gpu_hours = acc["gpu_seconds"] / 3600
            cpu_hours = acc["cpu_core_seconds"] / 3600
            memory_gb_hours = acc["memory_gb_seconds"] / 3600
            
            # Calculate costs
            gpu_cost = gpu_hours * self.config.GPU_COST_PER_HOUR.get(
                acc["gpu_name"], 2.0  # Default rate
            )
            cpu_cost = cpu_hours * self.config.CPU_COST_PER_CORE_HOUR
            memory_cost = memory_gb_hours * self.config.MEMORY_COST_PER_GB_HOUR
            total_cost = gpu_cost + cpu_cost + memory_cost
            
            record = CostRecord(
                id=uuid4(),
                service_name=acc["service_name"],
                model_name=acc["model_name"],
                start_time=self._current_period_start,
                end_time=period_end,
                gpu_hours=gpu_hours,
                cpu_hours=cpu_hours,
                memory_gb_hours=memory_gb_hours,
                total_requests=acc["requests"],
                total_tokens_processed=acc["tokens"],
                gpu_cost=gpu_cost,
                cpu_cost=cpu_cost,
                memory_cost=memory_cost,
                total_cost=total_cost,
                cost_per_request=total_cost / acc["requests"] if acc["requests"] > 0 else 0,
                cost_per_1k_tokens=total_cost / (acc["tokens"] / 1000) if acc["tokens"] > 0 else 0
            )
            
            self._cost_records.append(record)
            logger.info(
                f"Cost record for {acc['service_name']}/{acc['model_name']}: "
                f"${total_cost:.4f} ({acc['requests']} requests, {acc['tokens']} tokens)"
            )
        
        # Reset accumulator
        self._usage_accumulator = {}
        self._current_period_start = period_end
    
    def get_cost_summary(
        self,
        service_name: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> dict:
        """Get cost summary for a time period."""
        records = self._cost_records
        
        if service_name:
            records = [r for r in records if r.service_name == service_name]
        
        if start_time:
            records = [r for r in records if r.start_time >= start_time]
        
        if end_time:
            records = [r for r in records if r.end_time <= end_time]
        
        if not records:
            return {
                "total_cost": 0,
                "gpu_cost": 0,
                "cpu_cost": 0,
                "memory_cost": 0,
                "total_requests": 0,
                "total_tokens": 0,
                "cost_per_request": 0,
                "cost_per_1k_tokens": 0
            }
        
        total_cost = sum(r.total_cost for r in records)
        total_requests = sum(r.total_requests for r in records)
        total_tokens = sum(r.total_tokens_processed for r in records)
        
        return {
            "total_cost": total_cost,
            "gpu_cost": sum(r.gpu_cost for r in records),
            "cpu_cost": sum(r.cpu_cost for r in records),
            "memory_cost": sum(r.memory_cost for r in records),
            "total_requests": total_requests,
            "total_tokens": total_tokens,
            "cost_per_request": total_cost / total_requests if total_requests > 0 else 0,
            "cost_per_1k_tokens": total_cost / (total_tokens / 1000) if total_tokens > 0 else 0,
            "records_count": len(records)
        }
    
    def get_cost_by_model(self) -> dict[str, dict]:
        """Get cost breakdown by model."""
        model_costs: dict[str, dict] = {}
        
        for record in self._cost_records:
            if record.model_name not in model_costs:
                model_costs[record.model_name] = {
                    "total_cost": 0,
                    "total_requests": 0,
                    "total_tokens": 0
                }
            
            model_costs[record.model_name]["total_cost"] += record.total_cost
            model_costs[record.model_name]["total_requests"] += record.total_requests
            model_costs[record.model_name]["total_tokens"] += record.total_tokens_processed
        
        return model_costs
    
    def estimate_monthly_cost(self) -> float:
        """Estimate monthly cost based on recent usage."""
        now = datetime.utcnow()
        day_ago = now - timedelta(days=1)
        
        recent_records = [
            r for r in self._cost_records
            if r.start_time >= day_ago
        ]
        
        if not recent_records:
            return 0.0
        
        daily_cost = sum(r.total_cost for r in recent_records)
        return daily_cost * 30
```

### Kubernetes HPA Configuration

```yaml
# k8s/hpa-vllm.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: vllm-hpa
  namespace: llm-serving
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: vllm-llama
  minReplicas: 1
  maxReplicas: 4
  metrics:
    # Scale based on GPU utilization (custom metric)
    - type: Pods
      pods:
        metric:
          name: gpu_utilization_percent
        target:
          type: AverageValue
          averageValue: "80"
    
    # Scale based on pending requests
    - type: Pods
      pods:
        metric:
          name: vllm_pending_requests
        target:
          type: AverageValue
          averageValue: "50"
    
    # Scale based on queue time
    - type: Pods
      pods:
        metric:
          name: vllm_avg_queue_time_seconds
        target:
          type: AverageValue
          averageValue: "2"
  
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 120
---
# k8s/hpa-embedding.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: embedding-hpa
  namespace: llm-serving
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: embedding-service
  minReplicas: 1
  maxReplicas: 4
  metrics:
    - type: Pods
      pods:
        metric:
          name: embedding_queue_size
        target:
          type: AverageValue
          averageValue: "100"
    
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
        - type: Pods
          value: 1
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 60
---
# k8s/hpa-reranker.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: reranker-hpa
  namespace: llm-serving
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: reranker-service
  minReplicas: 1
  maxReplicas: 3
  metrics:
    - type: Pods
      pods:
        metric:
          name: rerank_queue_size
        target:
          type: AverageValue
          averageValue: "50"
  
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
        - type: Pods
          value: 1
          periodSeconds: 30
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Pods
          value: 1
          periodSeconds: 120
```

### Resource Quotas

```yaml
# k8s/resource-quotas.yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: llm-serving-quota
  namespace: llm-serving
spec:
  hard:
    # GPU limits
    requests.nvidia.com/gpu: "8"
    limits.nvidia.com/gpu: "8"
    
    # CPU limits
    requests.cpu: "64"
    limits.cpu: "128"
    
    # Memory limits
    requests.memory: "256Gi"
    limits.memory: "512Gi"
    
    # Pod limits
    pods: "20"
    
    # Service limits
    services: "10"
    services.loadbalancers: "3"
---
# k8s/limit-ranges.yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: llm-serving-limits
  namespace: llm-serving
spec:
  limits:
    # Default container limits
    - type: Container
      default:
        cpu: "2"
        memory: "4Gi"
      defaultRequest:
        cpu: "500m"
        memory: "1Gi"
      max:
        cpu: "16"
        memory: "64Gi"
        nvidia.com/gpu: "2"
      min:
        cpu: "100m"
        memory: "128Mi"
    
    # Pod limits
    - type: Pod
      max:
        cpu: "32"
        memory: "128Gi"
        nvidia.com/gpu: "4"
---
# k8s/priority-classes.yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: llm-critical
value: 1000000
globalDefault: false
description: "Critical LLM serving workloads"
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: llm-standard
value: 100000
globalDefault: false
description: "Standard LLM serving workloads"
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: llm-batch
value: 10000
globalDefault: false
description: "Batch/background LLM workloads"
```

## Acceptance Criteria

- [ ] GPU memory monitoring implemented
- [ ] GPU utilization tracking working
- [ ] Request batching optimization functional
- [ ] HPA configured for all services
- [ ] Auto-scaling based on queue depth
- [ ] Resource limits configured in Kubernetes
- [ ] Resource quotas enforced
- [ ] Cost tracking per model implemented
- [ ] Cost per request/token calculated
- [ ] Priority classes defined
- [ ] Prometheus metrics for resources
- [ ] Recommendations for scaling generated

## Testing Requirements

```python
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

@pytest.fixture
def gpu_monitor():
    return GPUMonitor(poll_interval=1.0)

@pytest.fixture
def batch_optimizer():
    return BatchOptimizer(
        service_name="test-service",
        initial_batch_size=32,
        initial_timeout_ms=50.0
    )

@pytest.fixture
def cost_tracker():
    return CostTracker(aggregation_interval=timedelta(seconds=1))

def test_gpu_metrics_model():
    """Test GPUMetrics model."""
    metrics = GPUMetrics(
        gpu_id=0,
        name="NVIDIA A100",
        memory_total=40 * 1024 * 1024 * 1024,  # 40GB
        memory_used=20 * 1024 * 1024 * 1024,   # 20GB
        memory_free=20 * 1024 * 1024 * 1024,
        memory_utilization_percent=50.0,
        gpu_utilization_percent=75.0,
        temperature_celsius=65.0,
        power_draw_watts=250.0,
        power_limit_watts=400.0,
        sm_clock=1530,
        memory_clock=1215
    )
    
    assert metrics.memory_utilization == 0.5
    assert metrics.gpu_utilization_percent == 75.0

@pytest.mark.asyncio
async def test_gpu_monitor_start_stop(gpu_monitor):
    """Test GPU monitor lifecycle."""
    await gpu_monitor.start()
    assert gpu_monitor._running
    
    await gpu_monitor.stop()
    assert not gpu_monitor._running

def test_batch_optimizer_record(batch_optimizer):
    """Test recording batch events."""
    batch_optimizer.record_batch(
        batch_size=16,
        processing_time_ms=50.0,
        wait_time_ms=25.0
    )
    
    metrics = batch_optimizer.get_metrics()
    assert metrics.avg_batch_size == 16
    assert metrics.avg_batch_processing_ms == 50.0

def test_batch_optimizer_recommendations(batch_optimizer):
    """Test batch optimization recommendations."""
    # Record low fill rate batches
    for _ in range(20):
        batch_optimizer.record_batch(
            batch_size=8,  # 25% of 32
            processing_time_ms=50.0,
            wait_time_ms=50.0  # Full timeout
        )
    
    recommendation = batch_optimizer.recommend_parameters()
    
    # Should recommend smaller batch size
    assert recommendation["batch_size"] < 32

def test_batch_optimizer_high_efficiency(batch_optimizer):
    """Test recommendations for high efficiency."""
    # Record high fill rate batches
    for _ in range(20):
        batch_optimizer.record_batch(
            batch_size=30,  # 94% of 32
            processing_time_ms=30.0,
            wait_time_ms=10.0
        )
    
    recommendation = batch_optimizer.recommend_parameters()
    
    # Should recommend increasing batch size or maintaining
    assert recommendation["batch_size"] >= 32
    assert recommendation["confidence"] > 0.5

def test_cost_tracker_record(cost_tracker):
    """Test recording usage."""
    cost_tracker.record_usage(
        service_name="vllm",
        model_name="llama-8b",
        gpu_name="NVIDIA-A100-SXM4-40GB",
        gpu_utilization=80.0,
        cpu_cores=4.0,
        memory_gb=24.0,
        requests=100,
        tokens=10000,
        duration_seconds=1.0
    )
    
    # Force finalization
    import time
    time.sleep(1.1)
    cost_tracker.record_usage(
        service_name="vllm",
        model_name="llama-8b",
        gpu_name="NVIDIA-A100-SXM4-40GB",
        gpu_utilization=80.0,
        cpu_cores=4.0,
        memory_gb=24.0
    )
    
    summary = cost_tracker.get_cost_summary()
    assert summary["total_requests"] >= 100

def test_cost_tracker_by_model(cost_tracker):
    """Test cost breakdown by model."""
    # Record usage for different models
    cost_tracker.record_usage(
        service_name="vllm",
        model_name="llama-8b",
        gpu_name="NVIDIA-A100-SXM4-40GB",
        gpu_utilization=80.0,
        cpu_cores=4.0,
        memory_gb=24.0,
        requests=50,
        tokens=5000
    )
    
    cost_tracker.record_usage(
        service_name="embedding",
        model_name="bge-large",
        gpu_name="NVIDIA-T4",
        gpu_utilization=60.0,
        cpu_cores=2.0,
        memory_gb=4.0,
        requests=200,
        tokens=20000
    )
    
    # Force finalization
    cost_tracker._finalize_period()
    
    by_model = cost_tracker.get_cost_by_model()
    assert "llama-8b" in by_model or "bge-large" in by_model

def test_scaling_policy_model():
    """Test ScalingPolicy model."""
    policy = ScalingPolicy(
        service_name="vllm",
        min_replicas=1,
        max_replicas=4,
        scale_up_gpu_utilization=80.0,
        scale_down_gpu_utilization=30.0
    )
    
    assert policy.min_replicas == 1
    assert policy.max_replicas == 4

def test_resource_recommendation_model():
    """Test ResourceRecommendation model."""
    rec = ResourceRecommendation(
        service_name="vllm",
        recommendation_type="scale_up",
        current_replicas=1,
        current_gpu_utilization=90.0,
        current_queue_depth=150,
        recommended_replicas=2,
        reason="High GPU utilization and queue depth",
        confidence=0.85,
        expected_cost_change_percent=100.0,
        expected_latency_change_percent=-40.0
    )
    
    assert rec.recommendation_type == "scale_up"
    assert rec.recommended_replicas == 2
```

## Dependencies

```txt
# requirements.txt
pydantic>=2.5.0
prometheus-client>=0.19.0
kubernetes>=28.0.0
numpy>=1.24.0
```

## Definition of Done

- [ ] GPUMonitor collecting metrics from nvidia-smi
- [ ] BatchOptimizer tracking and recommending parameters
- [ ] CostTracker calculating per-model costs
- [ ] HPA configurations for all services
- [ ] Resource quotas and limits defined
- [ ] Priority classes configured
- [ ] Prometheus metrics exposed
- [ ] Scaling recommendations generated
- [ ] Cost summaries available via API
- [ ] Monthly cost estimates calculated
- [ ] >90% test coverage
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy

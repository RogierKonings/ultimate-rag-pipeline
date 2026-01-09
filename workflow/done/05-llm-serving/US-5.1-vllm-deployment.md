# US-5.1: vLLM Deployment

> **Story ID:** US-5.1  
> **Epic:** LLM Serving Layer  
> **Priority:** Critical  
> **Estimated Effort:** 3-4 days  
> **Dependencies:** Epic 1 (Infrastructure - GPU nodes)

## User Story

**As a** platform engineer  
**I want** vLLM deployed for LLM serving  
**So that** we have high-throughput inference with OpenAI-compatible API

## Context

vLLM is a high-throughput LLM serving engine that uses PagedAttention for efficient memory management. It provides an OpenAI-compatible API server, making it easy to integrate with existing applications. The deployment serves the Llama-3.1-8B-Instruct model with optimized settings for production workloads.

Key features:
- PagedAttention for efficient KV cache management
- Continuous batching for optimal GPU utilization
- OpenAI-compatible API (chat completions, completions)
- Tensor parallelism support for larger models
- Streaming responses for low latency

## Technical Requirements

### Directory Structure

```
llm-serving/
└── vllm/
    ├── Dockerfile
    ├── k8s/
    │   ├── namespace.yaml
    │   ├── configmap.yaml
    │   ├── secret.yaml
    │   ├── deployment.yaml
    │   ├── service.yaml
    │   ├── hpa.yaml
    │   └── pdb.yaml
    ├── scripts/
    │   ├── healthcheck.py
    │   ├── benchmark.py
    │   └── warmup.py
    └── config/
        └── serving_config.yaml
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum

class VLLMConfig(BaseModel):
    """vLLM server configuration."""
    
    # Model settings
    model: str = "meta-llama/Llama-3.1-8B-Instruct"
    tokenizer: Optional[str] = None  # Uses model tokenizer by default
    revision: Optional[str] = None   # Model revision/commit hash
    
    # Serving settings
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Memory settings
    gpu_memory_utilization: float = Field(default=0.90, ge=0.1, le=0.99)
    max_model_len: int = 8192
    
    # Parallelism
    tensor_parallel_size: int = 1
    pipeline_parallel_size: int = 1
    
    # Batching
    max_num_batched_tokens: Optional[int] = None  # Auto-calculated
    max_num_seqs: int = 256  # Maximum concurrent sequences
    
    # KV cache settings
    block_size: int = 16
    swap_space: int = 4  # GB of CPU swap space
    
    # Quantization
    quantization: Optional[Literal["awq", "gptq", "squeezellm"]] = None
    
    # API settings
    api_key: Optional[str] = None  # Optional API key requirement
    served_model_name: Optional[str] = None  # Override model name in API
    
    # Logging
    disable_log_requests: bool = False
    disable_log_stats: bool = False

class ModelInfo(BaseModel):
    """Model information response."""
    id: str
    object: str = "model"
    created: int
    owned_by: str = "vllm"
    
class HealthStatus(BaseModel):
    """Health check response."""
    status: Literal["healthy", "unhealthy", "degraded"]
    model_loaded: bool
    gpu_available: bool
    gpu_memory_used_gb: float
    gpu_memory_total_gb: float
    pending_requests: int
    uptime_seconds: float

class ServerMetrics(BaseModel):
    """Server metrics for monitoring."""
    # Request metrics
    requests_total: int
    requests_active: int
    requests_pending: int
    
    # Throughput
    tokens_per_second: float
    requests_per_second: float
    
    # Latency (milliseconds)
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    
    # GPU metrics
    gpu_utilization_percent: float
    gpu_memory_used_gb: float
    gpu_memory_total_gb: float
    kv_cache_utilization_percent: float
```

### Dockerfile

```dockerfile
# vLLM Production Dockerfile
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

# Set environment variables
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV VLLM_WORKER_MULTIPROC_METHOD=spawn

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create symlinks for python
RUN ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    ln -sf /usr/bin/python3.11 /usr/bin/python

# Install vLLM and dependencies
RUN pip install --no-cache-dir \
    vllm>=0.4.0 \
    ray>=2.9.0 \
    prometheus-client>=0.19.0 \
    pydantic>=2.5.0

# Create non-root user
RUN useradd -m -u 1000 vllm
USER vllm
WORKDIR /app

# Copy scripts
COPY --chown=vllm:vllm scripts/ /app/scripts/
COPY --chown=vllm:vllm config/ /app/config/

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python3 /app/scripts/healthcheck.py || exit 1

# Expose port
EXPOSE 8000

# Default command - will be overridden by Kubernetes
ENTRYPOINT ["python3", "-m", "vllm.entrypoints.openai.api_server"]
CMD ["--model", "meta-llama/Llama-3.1-8B-Instruct", "--port", "8000"]
```

### Kubernetes ConfigMap

```yaml
# k8s/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: vllm-config
  namespace: llm-serving
  labels:
    app: vllm
    component: llm
data:
  MODEL_NAME: "meta-llama/Llama-3.1-8B-Instruct"
  PORT: "8000"
  GPU_MEMORY_UTILIZATION: "0.90"
  MAX_MODEL_LEN: "8192"
  MAX_NUM_SEQS: "256"
  TENSOR_PARALLEL_SIZE: "1"
  BLOCK_SIZE: "16"
  SWAP_SPACE: "4"
  DISABLE_LOG_REQUESTS: "false"
  DISABLE_LOG_STATS: "false"
```

### Kubernetes Deployment

```yaml
# k8s/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-llama
  namespace: llm-serving
  labels:
    app: vllm
    model: llama-3-1-8b
spec:
  replicas: 1
  selector:
    matchLabels:
      app: vllm
      model: llama-3-1-8b
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0
      maxSurge: 1
  template:
    metadata:
      labels:
        app: vllm
        model: llama-3-1-8b
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      serviceAccountName: vllm-sa
      
      # Model download init container
      initContainers:
        - name: model-downloader
          image: python:3.11-slim
          command:
            - python3
            - -c
            - |
              from huggingface_hub import snapshot_download
              import os
              model_name = os.environ.get("MODEL_NAME", "meta-llama/Llama-3.1-8B-Instruct")
              cache_dir = "/models"
              print(f"Downloading {model_name} to {cache_dir}")
              snapshot_download(
                  repo_id=model_name,
                  cache_dir=cache_dir,
                  token=os.environ.get("HF_TOKEN")
              )
              print("Download complete!")
          env:
            - name: MODEL_NAME
              valueFrom:
                configMapKeyRef:
                  name: vllm-config
                  key: MODEL_NAME
            - name: HF_TOKEN
              valueFrom:
                secretKeyRef:
                  name: vllm-secrets
                  key: hf-token
                  optional: true
          volumeMounts:
            - name: model-cache
              mountPath: /models
          resources:
            requests:
              memory: "4Gi"
              cpu: "1"
            limits:
              memory: "8Gi"
              cpu: "2"
      
      containers:
        - name: vllm
          image: llm-serving/vllm:latest
          imagePullPolicy: Always
          ports:
            - name: http
              containerPort: 8000
              protocol: TCP
          
          args:
            - "--model"
            - "$(MODEL_NAME)"
            - "--port"
            - "$(PORT)"
            - "--gpu-memory-utilization"
            - "$(GPU_MEMORY_UTILIZATION)"
            - "--max-model-len"
            - "$(MAX_MODEL_LEN)"
            - "--max-num-seqs"
            - "$(MAX_NUM_SEQS)"
            - "--tensor-parallel-size"
            - "$(TENSOR_PARALLEL_SIZE)"
            - "--block-size"
            - "$(BLOCK_SIZE)"
            - "--swap-space"
            - "$(SWAP_SPACE)"
            - "--download-dir"
            - "/models"
          
          envFrom:
            - configMapRef:
                name: vllm-config
          
          env:
            - name: CUDA_VISIBLE_DEVICES
              value: "0"
            - name: TRANSFORMERS_CACHE
              value: "/models"
            - name: HF_HOME
              value: "/models"
          
          resources:
            requests:
              memory: "24Gi"
              cpu: "4"
              nvidia.com/gpu: "1"
            limits:
              memory: "32Gi"
              cpu: "8"
              nvidia.com/gpu: "1"
          
          volumeMounts:
            - name: model-cache
              mountPath: /models
            - name: shm
              mountPath: /dev/shm
          
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 120
            periodSeconds: 30
            timeoutSeconds: 10
            failureThreshold: 3
          
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 60
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          
          startupProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 10
            timeoutSeconds: 10
            failureThreshold: 30  # Allow up to 5 minutes for startup
      
      volumes:
        - name: model-cache
          persistentVolumeClaim:
            claimName: vllm-model-cache
        - name: shm
          emptyDir:
            medium: Memory
            sizeLimit: "16Gi"
      
      nodeSelector:
        nvidia.com/gpu.product: "NVIDIA-A100-SXM4-40GB"
      
      tolerations:
        - key: "nvidia.com/gpu"
          operator: "Exists"
          effect: "NoSchedule"
      
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                labelSelector:
                  matchLabels:
                    app: vllm
                topologyKey: kubernetes.io/hostname
```

### Kubernetes Service

```yaml
# k8s/service.yaml
apiVersion: v1
kind: Service
metadata:
  name: vllm-llama
  namespace: llm-serving
  labels:
    app: vllm
    model: llama-3-1-8b
spec:
  type: ClusterIP
  selector:
    app: vllm
    model: llama-3-1-8b
  ports:
    - name: http
      port: 8000
      targetPort: 8000
      protocol: TCP
---
# External access via LoadBalancer (optional)
apiVersion: v1
kind: Service
metadata:
  name: vllm-llama-external
  namespace: llm-serving
  labels:
    app: vllm
    model: llama-3-1-8b
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-internal: "true"
spec:
  type: LoadBalancer
  selector:
    app: vllm
    model: llama-3-1-8b
  ports:
    - name: http
      port: 80
      targetPort: 8000
      protocol: TCP
```

### PersistentVolumeClaim

```yaml
# k8s/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: vllm-model-cache
  namespace: llm-serving
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: fast-ssd
  resources:
    requests:
      storage: 50Gi
```

### Health Check Script

```python
#!/usr/bin/env python3
"""
Health check script for vLLM server.
Used by Kubernetes probes and monitoring.
"""

import sys
import httpx
from datetime import datetime

VLLM_URL = "http://localhost:8000"
TIMEOUT = 5.0

def check_health() -> bool:
    """
    Check vLLM server health.
    
    Returns:
        True if healthy, False otherwise
    """
    try:
        # Check /health endpoint
        response = httpx.get(f"{VLLM_URL}/health", timeout=TIMEOUT)
        
        if response.status_code != 200:
            print(f"Health check failed: HTTP {response.status_code}")
            return False
        
        # Optionally check model is loaded via /v1/models
        models_response = httpx.get(f"{VLLM_URL}/v1/models", timeout=TIMEOUT)
        
        if models_response.status_code == 200:
            models = models_response.json()
            if models.get("data"):
                print(f"Health check passed: {len(models['data'])} model(s) loaded")
                return True
            else:
                print("Health check failed: No models loaded")
                return False
        
        print("Health check passed (basic)")
        return True
        
    except httpx.ConnectError as e:
        print(f"Health check failed: Connection error - {e}")
        return False
    except httpx.TimeoutException:
        print("Health check failed: Timeout")
        return False
    except Exception as e:
        print(f"Health check failed: {e}")
        return False

if __name__ == "__main__":
    is_healthy = check_health()
    sys.exit(0 if is_healthy else 1)
```

### Warmup Script

```python
#!/usr/bin/env python3
"""
Warmup script for vLLM server.
Runs initial requests to warm up the model and KV cache.
"""

import asyncio
import httpx
import time
from typing import Optional

VLLM_URL = "http://localhost:8000"

async def warmup_request(
    client: httpx.AsyncClient,
    prompt: str,
    max_tokens: int = 10
) -> Optional[float]:
    """
    Send a warmup request.
    
    Returns:
        Latency in milliseconds, or None if failed
    """
    start = time.time()
    
    try:
        response = await client.post(
            f"{VLLM_URL}/v1/chat/completions",
            json={
                "model": "meta-llama/Llama-3.1-8B-Instruct",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.0
            },
            timeout=30.0
        )
        
        if response.status_code == 200:
            latency_ms = (time.time() - start) * 1000
            return latency_ms
        else:
            print(f"Warmup request failed: HTTP {response.status_code}")
            return None
            
    except Exception as e:
        print(f"Warmup request failed: {e}")
        return None

async def run_warmup(
    num_requests: int = 10,
    concurrent: int = 2
) -> dict:
    """
    Run warmup sequence.
    
    Args:
        num_requests: Total number of warmup requests
        concurrent: Number of concurrent requests
    
    Returns:
        Warmup statistics
    """
    prompts = [
        "Hello, how are you?",
        "What is the capital of France?",
        "Explain quantum computing briefly.",
        "Write a haiku about technology.",
        "What is 2 + 2?",
    ]
    
    async with httpx.AsyncClient() as client:
        # Wait for server to be ready
        print("Waiting for server to be ready...")
        for _ in range(60):
            try:
                response = await client.get(f"{VLLM_URL}/health", timeout=2.0)
                if response.status_code == 200:
                    print("Server is ready!")
                    break
            except:
                pass
            await asyncio.sleep(1)
        else:
            print("Server not ready after 60 seconds")
            return {"success": False}
        
        # Run warmup requests
        print(f"Running {num_requests} warmup requests...")
        
        start_time = time.time()
        latencies = []
        
        semaphore = asyncio.Semaphore(concurrent)
        
        async def bounded_request(prompt: str):
            async with semaphore:
                return await warmup_request(client, prompt)
        
        tasks = [
            bounded_request(prompts[i % len(prompts)])
            for i in range(num_requests)
        ]
        
        results = await asyncio.gather(*tasks)
        latencies = [r for r in results if r is not None]
        
        total_time = time.time() - start_time
        
        stats = {
            "success": True,
            "total_requests": num_requests,
            "successful_requests": len(latencies),
            "failed_requests": num_requests - len(latencies),
            "total_time_seconds": total_time,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
            "min_latency_ms": min(latencies) if latencies else 0,
            "max_latency_ms": max(latencies) if latencies else 0,
        }
        
        print(f"Warmup complete: {stats['successful_requests']}/{num_requests} successful")
        print(f"Average latency: {stats['avg_latency_ms']:.2f}ms")
        
        return stats

if __name__ == "__main__":
    asyncio.run(run_warmup())
```

### Benchmark Script

```python
#!/usr/bin/env python3
"""
Benchmark script for vLLM performance testing.
"""

import asyncio
import httpx
import time
import statistics
from dataclasses import dataclass
from typing import Optional
import argparse

VLLM_URL = "http://localhost:8000"

@dataclass
class BenchmarkResult:
    """Benchmark results."""
    total_requests: int
    successful_requests: int
    failed_requests: int
    total_time_seconds: float
    requests_per_second: float
    tokens_per_second: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    total_tokens_generated: int

async def benchmark_request(
    client: httpx.AsyncClient,
    prompt: str,
    max_tokens: int,
    model: str
) -> tuple[Optional[float], int]:
    """
    Send a benchmark request.
    
    Returns:
        Tuple of (latency_ms, tokens_generated)
    """
    start = time.time()
    
    try:
        response = await client.post(
            f"{VLLM_URL}/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.7
            },
            timeout=120.0
        )
        
        if response.status_code == 200:
            latency_ms = (time.time() - start) * 1000
            data = response.json()
            tokens = data.get("usage", {}).get("completion_tokens", 0)
            return latency_ms, tokens
        else:
            return None, 0
            
    except Exception as e:
        print(f"Request failed: {e}")
        return None, 0

async def run_benchmark(
    num_requests: int = 100,
    concurrent: int = 10,
    max_tokens: int = 100,
    model: str = "meta-llama/Llama-3.1-8B-Instruct"
) -> BenchmarkResult:
    """
    Run performance benchmark.
    """
    prompts = [
        "Write a detailed explanation of how neural networks work.",
        "Describe the process of photosynthesis in plants.",
        "Explain the theory of relativity in simple terms.",
        "What are the main causes of climate change?",
        "How does a computer processor execute instructions?",
    ]
    
    print(f"Running benchmark: {num_requests} requests, {concurrent} concurrent")
    print(f"Model: {model}, Max tokens: {max_tokens}")
    
    async with httpx.AsyncClient() as client:
        start_time = time.time()
        
        semaphore = asyncio.Semaphore(concurrent)
        latencies = []
        total_tokens = 0
        
        async def bounded_request(prompt: str):
            async with semaphore:
                return await benchmark_request(client, prompt, max_tokens, model)
        
        tasks = [
            bounded_request(prompts[i % len(prompts)])
            for i in range(num_requests)
        ]
        
        results = await asyncio.gather(*tasks)
        
        for latency, tokens in results:
            if latency is not None:
                latencies.append(latency)
                total_tokens += tokens
        
        total_time = time.time() - start_time
        
        if not latencies:
            print("All requests failed!")
            return BenchmarkResult(
                total_requests=num_requests,
                successful_requests=0,
                failed_requests=num_requests,
                total_time_seconds=total_time,
                requests_per_second=0,
                tokens_per_second=0,
                avg_latency_ms=0,
                p50_latency_ms=0,
                p95_latency_ms=0,
                p99_latency_ms=0,
                total_tokens_generated=0
            )
        
        sorted_latencies = sorted(latencies)
        
        result = BenchmarkResult(
            total_requests=num_requests,
            successful_requests=len(latencies),
            failed_requests=num_requests - len(latencies),
            total_time_seconds=total_time,
            requests_per_second=len(latencies) / total_time,
            tokens_per_second=total_tokens / total_time,
            avg_latency_ms=statistics.mean(latencies),
            p50_latency_ms=sorted_latencies[int(len(sorted_latencies) * 0.5)],
            p95_latency_ms=sorted_latencies[int(len(sorted_latencies) * 0.95)],
            p99_latency_ms=sorted_latencies[int(len(sorted_latencies) * 0.99)],
            total_tokens_generated=total_tokens
        )
        
        print("\n=== Benchmark Results ===")
        print(f"Total requests:     {result.total_requests}")
        print(f"Successful:         {result.successful_requests}")
        print(f"Failed:             {result.failed_requests}")
        print(f"Total time:         {result.total_time_seconds:.2f}s")
        print(f"Requests/sec:       {result.requests_per_second:.2f}")
        print(f"Tokens/sec:         {result.tokens_per_second:.2f}")
        print(f"Avg latency:        {result.avg_latency_ms:.2f}ms")
        print(f"P50 latency:        {result.p50_latency_ms:.2f}ms")
        print(f"P95 latency:        {result.p95_latency_ms:.2f}ms")
        print(f"P99 latency:        {result.p99_latency_ms:.2f}ms")
        print(f"Total tokens:       {result.total_tokens_generated}")
        
        return result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="vLLM Benchmark")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--concurrent", type=int, default=10)
    parser.add_argument("--max-tokens", type=int, default=100)
    parser.add_argument("--model", type=str, default="meta-llama/Llama-3.1-8B-Instruct")
    
    args = parser.parse_args()
    
    asyncio.run(run_benchmark(
        num_requests=args.requests,
        concurrent=args.concurrent,
        max_tokens=args.max_tokens,
        model=args.model
    ))
```

### OpenAI-Compatible API Examples

```python
"""
Example usage of vLLM OpenAI-compatible API.
"""

import httpx
from typing import AsyncIterator

VLLM_URL = "http://vllm-llama.llm-serving.svc.cluster.local:8000"

async def chat_completion(
    messages: list[dict],
    model: str = "meta-llama/Llama-3.1-8B-Instruct",
    temperature: float = 0.7,
    max_tokens: int = 1024,
    stream: bool = False
) -> dict:
    """
    Send a chat completion request to vLLM.
    
    Args:
        messages: List of message dicts with role and content
        model: Model name
        temperature: Sampling temperature
        max_tokens: Maximum tokens to generate
        stream: Whether to stream the response
    
    Returns:
        Chat completion response
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{VLLM_URL}/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": stream
            },
            timeout=60.0
        )
        response.raise_for_status()
        return response.json()

async def chat_completion_stream(
    messages: list[dict],
    model: str = "meta-llama/Llama-3.1-8B-Instruct",
    temperature: float = 0.7,
    max_tokens: int = 1024
) -> AsyncIterator[str]:
    """
    Stream chat completion from vLLM.
    
    Yields:
        Generated text chunks
    """
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{VLLM_URL}/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True
            },
            timeout=60.0
        ) as response:
            response.raise_for_status()
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]  # Remove "data: " prefix
                    if data == "[DONE]":
                        break
                    
                    import json
                    chunk = json.loads(data)
                    
                    if chunk["choices"][0]["delta"].get("content"):
                        yield chunk["choices"][0]["delta"]["content"]

async def list_models() -> list[dict]:
    """List available models."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{VLLM_URL}/v1/models", timeout=10.0)
        response.raise_for_status()
        return response.json()["data"]

# Usage example
async def example():
    # Non-streaming
    response = await chat_completion(
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is the meaning of life?"}
        ]
    )
    print(response["choices"][0]["message"]["content"])
    
    # Streaming
    print("\nStreaming response:")
    async for chunk in chat_completion_stream(
        messages=[
            {"role": "user", "content": "Count from 1 to 10."}
        ]
    ):
        print(chunk, end="", flush=True)
    print()
```

## Acceptance Criteria

- [ ] vLLM deployed on Kubernetes GPU node
- [ ] Llama-3.1-8B-Instruct model loaded successfully
- [ ] OpenAI-compatible `/v1/chat/completions` endpoint working
- [ ] OpenAI-compatible `/v1/completions` endpoint working
- [ ] `/v1/models` endpoint returns loaded model
- [ ] `/health` endpoint returns healthy status
- [ ] Streaming responses working correctly
- [ ] Max model length set to 8192 tokens
- [ ] GPU memory utilization at 90%
- [ ] Tensor parallelism configurable
- [ ] KV cache properly managed
- [ ] Prometheus metrics exposed at `/metrics`
- [ ] Health check probes configured
- [ ] PersistentVolumeClaim for model cache
- [ ] Init container downloads model from HuggingFace
- [ ] Pod anti-affinity for HA deployments

## Testing Requirements

```python
import pytest
import httpx
from unittest.mock import AsyncMock, patch, MagicMock

VLLM_URL = "http://localhost:8000"

@pytest.fixture
def mock_client():
    """Mock httpx client for unit tests."""
    return AsyncMock(spec=httpx.AsyncClient)

@pytest.mark.asyncio
async def test_chat_completion_returns_response():
    """Test basic chat completion."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{VLLM_URL}/v1/chat/completions",
            json={
                "model": "meta-llama/Llama-3.1-8B-Instruct",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 10
            },
            timeout=30.0
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "choices" in data
        assert len(data["choices"]) > 0
        assert "message" in data["choices"][0]
        assert data["choices"][0]["message"]["role"] == "assistant"

@pytest.mark.asyncio
async def test_chat_completion_streaming():
    """Test streaming chat completion."""
    chunks = []
    
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{VLLM_URL}/v1/chat/completions",
            json={
                "model": "meta-llama/Llama-3.1-8B-Instruct",
                "messages": [{"role": "user", "content": "Say hi"}],
                "max_tokens": 5,
                "stream": True
            },
            timeout=30.0
        ) as response:
            assert response.status_code == 200
            
            async for line in response.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunks.append(line)
    
    assert len(chunks) > 0

@pytest.mark.asyncio
async def test_list_models():
    """Test listing models."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{VLLM_URL}/v1/models", timeout=10.0)
        
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert len(data["data"]) > 0

@pytest.mark.asyncio
async def test_health_endpoint():
    """Test health check endpoint."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{VLLM_URL}/health", timeout=10.0)
        
        assert response.status_code == 200

@pytest.mark.asyncio
async def test_max_tokens_limit():
    """Test max tokens is respected."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{VLLM_URL}/v1/chat/completions",
            json={
                "model": "meta-llama/Llama-3.1-8B-Instruct",
                "messages": [{"role": "user", "content": "Write a long essay"}],
                "max_tokens": 10
            },
            timeout=30.0
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["usage"]["completion_tokens"] <= 10

@pytest.mark.asyncio
async def test_temperature_affects_output():
    """Test temperature parameter."""
    async with httpx.AsyncClient() as client:
        # Temperature 0 should be deterministic
        responses_temp_0 = []
        for _ in range(3):
            response = await client.post(
                f"{VLLM_URL}/v1/chat/completions",
                json={
                    "model": "meta-llama/Llama-3.1-8B-Instruct",
                    "messages": [{"role": "user", "content": "Say hello"}],
                    "max_tokens": 5,
                    "temperature": 0.0
                },
                timeout=30.0
            )
            data = response.json()
            responses_temp_0.append(data["choices"][0]["message"]["content"])
        
        # All responses should be identical with temp 0
        assert all(r == responses_temp_0[0] for r in responses_temp_0)

@pytest.mark.asyncio
async def test_invalid_model_returns_error():
    """Test error handling for invalid model."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{VLLM_URL}/v1/chat/completions",
            json={
                "model": "nonexistent-model",
                "messages": [{"role": "user", "content": "Hello"}]
            },
            timeout=10.0
        )
        
        # vLLM should return 400 or 404 for invalid model
        assert response.status_code in [400, 404]

def test_healthcheck_script():
    """Test the health check script."""
    # Import and test the health check function
    from scripts.healthcheck import check_health
    
    # Mock the httpx.get call
    with patch("httpx.get") as mock_get:
        # Simulate healthy response
        mock_get.return_value = MagicMock(status_code=200)
        assert check_health() == True
        
        # Simulate unhealthy response
        mock_get.return_value = MagicMock(status_code=500)
        assert check_health() == False

def test_vllm_config_validation():
    """Test VLLMConfig validation."""
    # Valid config
    config = VLLMConfig(
        model="meta-llama/Llama-3.1-8B-Instruct",
        gpu_memory_utilization=0.9,
        max_model_len=8192
    )
    assert config.model == "meta-llama/Llama-3.1-8B-Instruct"
    
    # Invalid GPU memory utilization
    with pytest.raises(ValueError):
        VLLMConfig(gpu_memory_utilization=1.5)
    
    with pytest.raises(ValueError):
        VLLMConfig(gpu_memory_utilization=0.05)
```

## Integration Tests

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_vllm_end_to_end():
    """End-to-end test with real vLLM server."""
    async with httpx.AsyncClient(base_url=VLLM_URL) as client:
        # Check health
        health = await client.get("/health")
        assert health.status_code == 200
        
        # List models
        models = await client.get("/v1/models")
        assert models.status_code == 200
        model_list = models.json()["data"]
        assert len(model_list) > 0
        
        # Chat completion
        chat = await client.post(
            "/v1/chat/completions",
            json={
                "model": model_list[0]["id"],
                "messages": [
                    {"role": "system", "content": "Be concise."},
                    {"role": "user", "content": "What is 2+2?"}
                ],
                "max_tokens": 20
            }
        )
        assert chat.status_code == 200
        assert "4" in chat.json()["choices"][0]["message"]["content"]

@pytest.mark.integration
@pytest.mark.asyncio
async def test_vllm_concurrent_requests():
    """Test concurrent request handling."""
    import asyncio
    
    async def make_request(client: httpx.AsyncClient, i: int):
        response = await client.post(
            f"{VLLM_URL}/v1/chat/completions",
            json={
                "model": "meta-llama/Llama-3.1-8B-Instruct",
                "messages": [{"role": "user", "content": f"Count to {i}"}],
                "max_tokens": 50
            },
            timeout=60.0
        )
        return response.status_code
    
    async with httpx.AsyncClient() as client:
        tasks = [make_request(client, i) for i in range(1, 11)]
        results = await asyncio.gather(*tasks)
        
        # All requests should succeed
        assert all(status == 200 for status in results)

@pytest.mark.integration
@pytest.mark.asyncio  
async def test_vllm_long_context():
    """Test handling of long context."""
    # Create a long prompt
    long_prompt = "Hello. " * 1000  # ~3000 tokens
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{VLLM_URL}/v1/chat/completions",
            json={
                "model": "meta-llama/Llama-3.1-8B-Instruct",
                "messages": [{"role": "user", "content": long_prompt}],
                "max_tokens": 100
            },
            timeout=120.0
        )
        
        assert response.status_code == 200
```

## Deployment Commands

```bash
# Create namespace
kubectl create namespace llm-serving

# Apply configurations
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/pvc.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

# Check deployment status
kubectl -n llm-serving get pods -w

# View logs
kubectl -n llm-serving logs -f deployment/vllm-llama

# Port forward for local testing
kubectl -n llm-serving port-forward svc/vllm-llama 8000:8000

# Run benchmark
python scripts/benchmark.py --requests 100 --concurrent 10
```

## Dependencies

- `vllm>=0.4.0`
- `torch>=2.1.0`
- `transformers>=4.37.0`
- `ray>=2.9.0`
- `httpx>=0.25.0`
- `pydantic>=2.5.0`
- `prometheus-client>=0.19.0`

## Performance Targets

| Metric | Target |
|--------|--------|
| Throughput | >100 tokens/sec |
| Time to First Token (TTFT) | <500ms |
| Inter-token Latency | <50ms |
| P99 Latency (100 tokens) | <5s |
| Concurrent Requests | 256 |
| GPU Memory Utilization | 90% |

## Definition of Done

- [ ] vLLM container built and pushed to registry
- [ ] Kubernetes manifests applied successfully
- [ ] Model downloaded and loaded
- [ ] `/v1/chat/completions` endpoint responding
- [ ] `/v1/completions` endpoint responding
- [ ] `/v1/models` endpoint listing model
- [ ] `/health` endpoint returning healthy
- [ ] Streaming responses working
- [ ] Prometheus metrics available at `/metrics`
- [ ] Health probes passing
- [ ] Warmup script executed successfully
- [ ] Benchmark meets performance targets
- [ ] Pod anti-affinity configured
- [ ] Resource limits set appropriately
- [ ] Documentation complete
- [ ] >90% test coverage
- [ ] Docstrings on all functions

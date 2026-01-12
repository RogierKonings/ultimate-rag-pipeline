#!/usr/bin/env python3
"""
Benchmark script for vLLM performance testing.
"""

import argparse
import asyncio
import os
import statistics
import time
from dataclasses import dataclass

import httpx

VLLM_URL = os.environ.get("VLLM_URL", "http://localhost:8000")


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
    model: str,
) -> tuple[float | None, int]:
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
                "temperature": 0.7,
            },
            timeout=120.0,
        )

        if response.status_code == 200:
            latency_ms = (time.time() - start) * 1000
            data = response.json()
            tokens = data.get("usage", {}).get("completion_tokens", 0)
            return latency_ms, tokens
        return None, 0

    except Exception as e:
        print(f"Request failed: {e}")
        return None, 0


async def run_benchmark(
    num_requests: int = 100,
    concurrent: int = 10,
    max_tokens: int = 100,
    model: str = "Qwen/Qwen2.5-7B-Instruct",
) -> BenchmarkResult:
    """Run performance benchmark."""
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
        latencies: list[float] = []
        total_tokens = 0

        async def bounded_request(prompt: str) -> tuple[float | None, int]:
            async with semaphore:
                return await benchmark_request(client, prompt, max_tokens, model)

        tasks = [bounded_request(prompts[i % len(prompts)]) for i in range(num_requests)]

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
                total_tokens_generated=0,
            )

        sorted_latencies = sorted(latencies)
        n = len(sorted_latencies)

        result = BenchmarkResult(
            total_requests=num_requests,
            successful_requests=len(latencies),
            failed_requests=num_requests - len(latencies),
            total_time_seconds=total_time,
            requests_per_second=len(latencies) / total_time,
            tokens_per_second=total_tokens / total_time,
            avg_latency_ms=statistics.mean(latencies),
            p50_latency_ms=sorted_latencies[int(n * 0.5)] if n > 0 else 0,
            p95_latency_ms=sorted_latencies[min(int(n * 0.95), n - 1)] if n > 0 else 0,
            p99_latency_ms=sorted_latencies[min(int(n * 0.99), n - 1)] if n > 0 else 0,
            total_tokens_generated=total_tokens,
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
    parser.add_argument("--model", type=str, default="Qwen/Qwen2.5-7B-Instruct")

    args = parser.parse_args()

    asyncio.run(
        run_benchmark(
            num_requests=args.requests,
            concurrent=args.concurrent,
            max_tokens=args.max_tokens,
            model=args.model,
        ),
    )

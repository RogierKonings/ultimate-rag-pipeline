#!/usr/bin/env python3
"""
Warmup script for vLLM server.
Runs initial requests to warm up the model and KV cache.
"""

import asyncio
import os
import time

import httpx

VLLM_URL = os.environ.get("VLLM_URL", "http://localhost:8000")
MODEL_NAME = os.environ.get("MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct")


async def warmup_request(
    client: httpx.AsyncClient,
    prompt: str,
    max_tokens: int = 10,
) -> float | None:
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
                "model": MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.0,
            },
            timeout=30.0,
        )

        if response.status_code == 200:
            return (time.time() - start) * 1000
        print(f"Warmup request failed: HTTP {response.status_code}")
        return None

    except Exception as e:
        print(f"Warmup request failed: {e}")
        return None


async def run_warmup(
    num_requests: int = 10,
    concurrent: int = 2,
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
        for _attempt in range(60):
            try:
                response = await client.get(f"{VLLM_URL}/health", timeout=2.0)
                if response.status_code == 200:
                    print("Server is ready!")
                    break
            except Exception:
                pass
            await asyncio.sleep(1)
        else:
            print("Server not ready after 60 seconds")
            return {"success": False}

        # Run warmup requests
        print(f"Running {num_requests} warmup requests...")

        start_time = time.time()
        latencies: list[float] = []

        semaphore = asyncio.Semaphore(concurrent)

        async def bounded_request(prompt: str) -> float | None:
            async with semaphore:
                return await warmup_request(client, prompt)

        tasks = [bounded_request(prompts[i % len(prompts)]) for i in range(num_requests)]

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

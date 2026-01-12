#!/usr/bin/env python3
"""
Health check script for vLLM server.
Used by Kubernetes probes and monitoring.
"""

import os
import sys

import httpx

VLLM_URL = os.environ.get("VLLM_URL", "http://localhost:8000")
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

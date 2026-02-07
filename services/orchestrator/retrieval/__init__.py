"""Retrieval client module for the Orchestrator Service.

This module provides a high-level client for the retrieval service
that wraps the shared HTTP client with structured search and health
check methods.

Example:
    ```python
    from retrieval import RetrievalClient

    client = RetrievalClient()
    result = await client.search("What is Python?", tenant_id="t-123")
    documents = result["documents"]
    ```
"""

from .client import RetrievalClient

__all__ = [
    "RetrievalClient",
]

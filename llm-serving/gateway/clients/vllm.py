"""
vLLM service client.

Handles communication with the vLLM service for chat completions.
"""

import asyncio
import json
import logging
import time
from typing import Any, AsyncIterator, Optional

import httpx

from ..models import (
    ChatCompletionChoice,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ChatMessageRole,
    DeltaMessage,
    Usage,
)

logger = logging.getLogger(__name__)


class VLLMClient:
    """Client for vLLM service."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        timeout: float = 60.0,
        default_model: str = "Qwen/Qwen2.5-7B-Instruct",
    ):
        """
        Initialize vLLM client.

        Args:
            base_url: Base URL of the vLLM service
            timeout: Request timeout in seconds
            default_model: Default model to use
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.default_model = default_model
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def health_check(self) -> bool:
        """Check if vLLM service is healthy."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"vLLM health check failed: {e}")
            return False

    async def list_models(self) -> list[dict]:
        """List available models."""
        try:
            client = await self._get_client()
            response = await client.get("/v1/models")
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
        context_headers: Optional[dict[str, str]] = None,
    ) -> ChatCompletionResponse:
        """
        Create a chat completion (non-streaming).

        Args:
            request: Chat completion request
            context_headers: Additional headers to pass (e.g., auth context)

        Returns:
            Chat completion response
        """
        client = await self._get_client()
        start_time = time.time()

        # Build request payload
        payload = {
            "model": request.model or self.default_model,
            "messages": [
                {"role": msg.role.value, "content": msg.content}
                for msg in request.messages
            ],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "n": request.n,
            "stream": False,
        }

        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        if request.stop:
            payload["stop"] = request.stop
        if request.presence_penalty:
            payload["presence_penalty"] = request.presence_penalty
        if request.frequency_penalty:
            payload["frequency_penalty"] = request.frequency_penalty
        if request.seed is not None:
            payload["seed"] = request.seed

        headers = {"Content-Type": "application/json"}
        if context_headers:
            headers.update(context_headers)

        try:
            response = await client.post(
                "/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            # Parse response
            choices = []
            for i, choice in enumerate(data.get("choices", [])):
                msg = choice.get("message", {})
                choices.append(
                    ChatCompletionChoice(
                        index=i,
                        message=ChatMessage(
                            role=ChatMessageRole(msg.get("role", "assistant")),
                            content=msg.get("content"),
                        ),
                        finish_reason=choice.get("finish_reason"),
                    )
                )

            usage_data = data.get("usage", {})
            usage = Usage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )

            latency_ms = (time.time() - start_time) * 1000
            logger.debug(f"Chat completion completed in {latency_ms:.1f}ms")

            return ChatCompletionResponse(
                id=data.get("id", f"chatcmpl-{id(data)}"),
                model=data.get("model", request.model or self.default_model),
                choices=choices,
                usage=usage,
                created=data.get("created", int(time.time())),
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"vLLM request failed: {e.response.status_code} - {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"vLLM request error: {e}")
            raise

    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest,
        context_headers: Optional[dict[str, str]] = None,
    ) -> AsyncIterator[ChatCompletionChunk]:
        """
        Create a streaming chat completion.

        Args:
            request: Chat completion request
            context_headers: Additional headers to pass

        Yields:
            Chat completion chunks
        """
        client = await self._get_client()

        # Build request payload
        payload = {
            "model": request.model or self.default_model,
            "messages": [
                {"role": msg.role.value, "content": msg.content}
                for msg in request.messages
            ],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "n": request.n,
            "stream": True,
        }

        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        if request.stop:
            payload["stop"] = request.stop
        if request.presence_penalty:
            payload["presence_penalty"] = request.presence_penalty
        if request.frequency_penalty:
            payload["frequency_penalty"] = request.frequency_penalty

        headers = {"Content-Type": "application/json"}
        if context_headers:
            headers.update(context_headers)

        chunk_id = f"chatcmpl-{id(request)}"
        created = int(time.time())

        try:
            async with client.stream(
                "POST",
                "/v1/chat/completions",
                json=payload,
                headers=headers,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break

                        try:
                            data = json.loads(data_str)
                            choices = []
                            for choice in data.get("choices", []):
                                delta = choice.get("delta", {})
                                choices.append({
                                    "index": choice.get("index", 0),
                                    "delta": {
                                        "role": delta.get("role"),
                                        "content": delta.get("content"),
                                    },
                                    "finish_reason": choice.get("finish_reason"),
                                })

                            yield ChatCompletionChunk(
                                id=data.get("id", chunk_id),
                                created=data.get("created", created),
                                model=data.get("model", request.model or self.default_model),
                                choices=choices,
                            )
                        except json.JSONDecodeError:
                            logger.warning(f"Failed to parse chunk: {data_str}")
                            continue

        except httpx.HTTPStatusError as e:
            logger.error(f"vLLM stream failed: {e.response.status_code}")
            raise
        except Exception as e:
            logger.error(f"vLLM stream error: {e}")
            raise

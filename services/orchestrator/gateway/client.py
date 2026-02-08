"""Model Gateway client implementation.

This module provides the ModelGateway class for unified LLM access,
supporting multiple providers with retry logic, streaming, and health checks.

Implementation details are split across submodules:
- request_builder: HTTP payload and header construction
- response_parser: API response parsing
- retry: Retry logic, backoff, and fallback
- health: Health check logic
- streaming: SSE stream parsing (pre-existing)
"""

import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import structlog

from config import OrchestratorConfig

from .exceptions import (
    ModelError,
    ModelTimeoutError,
    StreamingNotSupportedError,
)
from .health import check_model_health
from .models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    GatewayConfig,
    HealthStatus,
    ModelConfig,
    StreamChunk,
)
from .request_builder import build_chat_payload, build_headers
from .response_parser import parse_completion_response, parse_stream_chunk
from .retry import (
    build_fallback_request,
    is_retryable_http_error,
    map_http_error,
    should_fallback,
    sleep_with_backoff,
)
from .streaming import parse_sse_stream

logger = structlog.get_logger(__name__)


class ModelGateway:
    """Unified gateway for LLM access.

    This class provides a unified interface for interacting with LLM providers,
    supporting multiple models with retry logic, streaming, and health checks.

    Features:
        - OpenAI-compatible API interface
        - Multiple model/provider support
        - Retry with exponential backoff and jitter
        - Streaming support
        - Health check endpoint
        - Configurable timeout per request

    Example:
        ```python
        config = OrchestratorConfig()
        gateway = ModelGateway(config)

        request = ChatCompletionRequest(
            model="meta-llama/Llama-3.1-8B-Instruct",
            messages=[ChatMessage(role="user", content="Hello!")],
        )

        response = await gateway.chat_completion(request)
        print(response.choices[0].message.content)

        await gateway.close()
        ```
    """

    def __init__(self, config: OrchestratorConfig) -> None:
        """Initialize the model gateway.

        Args:
            config: Orchestrator configuration containing LLM settings.
        """
        self.config = config
        self._gateway_config = self._create_gateway_config(config)
        self._client: httpx.AsyncClient | None = None
        self._initialized = False

    def _create_gateway_config(self, config: OrchestratorConfig) -> GatewayConfig:
        """Create gateway config from orchestrator config.

        Args:
            config: The orchestrator configuration.

        Returns:
            A GatewayConfig instance.
        """
        # Create model configs for default and fallback models
        models = {
            config.default_model: ModelConfig(
                name=config.default_model,
                base_url=f"{config.llm_gateway_url}/v1",
                timeout=config.stream_timeout,
                max_tokens=config.max_tokens,
            ),
        }

        # Add fallback model if different from default
        if config.fallback_model and config.fallback_model != config.default_model:
            models[config.fallback_model] = ModelConfig(
                name=config.fallback_model,
                base_url=f"{config.llm_gateway_url}/v1",
                timeout=config.stream_timeout,
                max_tokens=config.max_tokens,
            )

        return GatewayConfig(
            default_model=config.default_model,
            fallback_model=config.fallback_model,
            models=models,
            fallback_on_timeout=True,
            fallback_on_rate_limit=True,
        )

    async def _ensure_client(self) -> httpx.AsyncClient:
        """Ensure HTTP client is initialized.

        Returns:
            The initialized HTTP client.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.stream_timeout),
                limits=httpx.Limits(
                    max_connections=self._gateway_config.max_connections,
                    max_keepalive_connections=20,
                ),
            )
            self._initialized = True
        return self._client

    def _get_model_config(self, model: str) -> ModelConfig:
        """Get configuration for a model.

        Args:
            model: The model identifier.

        Returns:
            The model configuration.
        """
        if model in self._gateway_config.models:
            return self._gateway_config.models[model]

        # Create default config for unknown model
        return ModelConfig(
            name=model,
            base_url=f"{self.config.llm_gateway_url}/v1",
            timeout=self.config.stream_timeout,
            max_tokens=self.config.max_tokens,
        )

    # Keep _get_headers and _map_http_error as thin delegates for backward compat
    def _get_headers(self, model_config: ModelConfig) -> dict[str, str]:
        """Get headers for API requests.

        Args:
            model_config: The model configuration.

        Returns:
            Dictionary of HTTP headers.
        """
        return build_headers(model_config)

    def _map_http_error(self, error: httpx.HTTPStatusError) -> Exception:
        """Map HTTP errors to gateway exceptions.

        Args:
            error: The HTTP error.

        Returns:
            The appropriate gateway exception.
        """
        return map_http_error(error)

    async def chat_completion(
        self,
        request: ChatCompletionRequest,
    ) -> ChatCompletionResponse:
        """Execute a chat completion request.

        This method sends a chat completion request to the LLM provider
        with automatic retry on transient failures.

        Args:
            request: The completion request.

        Returns:
            Chat completion response with generated text.

        Raises:
            ModelNotFoundError: If model is not configured.
            RateLimitError: If rate limit exceeded.
            ModelTimeoutError: If request times out.
            ModelError: For other API errors.

        Example:
            ```python
            request = ChatCompletionRequest(
                model="meta-llama/Llama-3.1-8B-Instruct",
                messages=[ChatMessage(role="user", content="Hello!")],
                temperature=0.7,
                max_tokens=100,
            )
            response = await gateway.chat_completion(request)
            ```
        """
        model = request.model or self._gateway_config.default_model
        model_config = self._get_model_config(model)
        client = await self._ensure_client()

        start_time = time.perf_counter()

        payload = build_chat_payload(
            request=request,
            model=model,
            max_tokens_default=self.config.max_tokens,
            stream=False,
        )

        last_error: Exception | None = None

        for attempt in range(model_config.max_retries + 1):
            try:
                response = await client.post(
                    f"{model_config.base_url}/chat/completions",
                    json=payload,
                    headers=build_headers(model_config),
                    timeout=model_config.timeout,
                )
                response.raise_for_status()

                data = response.json()
                latency_ms = (time.perf_counter() - start_time) * 1000

                result = parse_completion_response(data)
                result.latency_ms = latency_ms
                result.request_id = request.request_id

                return result

            except httpx.HTTPStatusError as e:
                last_error = map_http_error(e)
                if not is_retryable_http_error(e):
                    raise last_error from None

            except httpx.TimeoutException as e:
                last_error = ModelTimeoutError(str(e))

            except httpx.ConnectError as e:
                last_error = ModelError(f"Connection failed: {e}")

            # If we get here, we should retry (unless it's the last attempt)
            if attempt < model_config.max_retries:
                await sleep_with_backoff(
                    attempt=attempt,
                    base_delay=model_config.retry_base_delay,
                    max_delay=model_config.retry_max_delay,
                )
            else:
                break

        # All retries exhausted, try fallback or raise
        if should_fallback(last_error, self._gateway_config):
            return await self._execute_fallback(request, last_error)
        if last_error:
            raise last_error
        raise ModelError("Request failed after retries")

    def _parse_completion_response(
        self,
        data: dict[str, Any],
    ) -> ChatCompletionResponse:
        """Parse raw API response into ChatCompletionResponse.

        Args:
            data: The raw JSON response.

        Returns:
            Parsed ChatCompletionResponse.
        """
        return parse_completion_response(data)

    async def chat_completion_stream(
        self,
        request: ChatCompletionRequest,
    ) -> AsyncGenerator[str, None]:
        """Execute streaming chat completion.

        This method streams the response token by token, yielding
        content as it's generated.

        Args:
            request: The completion request (stream=True is set automatically).

        Yields:
            String tokens as they are generated.

        Raises:
            StreamingNotSupportedError: If model doesn't support streaming.
            ModelGatewayError: For API errors.

        Example:
            ```python
            request = ChatCompletionRequest(
                model="meta-llama/Llama-3.1-8B-Instruct",
                messages=[ChatMessage(role="user", content="Hello!")],
            )
            async for token in gateway.chat_completion_stream(request):
                print(token, end="", flush=True)
            ```
        """
        model = request.model or self._gateway_config.default_model
        model_config = self._get_model_config(model)

        if not model_config.supports_streaming:
            raise StreamingNotSupportedError(model)

        client = await self._ensure_client()

        payload = build_chat_payload(
            request=request,
            model=model,
            max_tokens_default=self.config.max_tokens,
            stream=True,
        )

        try:
            async with client.stream(
                "POST",
                f"{model_config.base_url}/chat/completions",
                json=payload,
                headers=build_headers(model_config),
                timeout=model_config.timeout,
            ) as response:
                response.raise_for_status()

                async for chunk in parse_sse_stream(response):
                    # Extract content from chunk
                    if "choices" in chunk and chunk["choices"]:
                        choice = chunk["choices"][0]
                        delta = choice.get("delta", {})
                        content = delta.get("content")

                        if content:
                            yield content

                        # Check for finish reason
                        if choice.get("finish_reason"):
                            return

        except httpx.HTTPStatusError as e:
            raise map_http_error(e) from None
        except httpx.TimeoutException as e:
            raise ModelTimeoutError(str(e)) from None
        except httpx.ConnectError as e:
            raise ModelError(f"Connection failed: {e}") from None

    async def chat_completion_stream_chunks(
        self,
        request: ChatCompletionRequest,
    ) -> AsyncGenerator[StreamChunk, None]:
        """Execute streaming chat completion yielding full chunks.

        Similar to chat_completion_stream but yields full StreamChunk objects
        instead of just content strings.

        Args:
            request: The completion request.

        Yields:
            StreamChunk objects with full chunk data.
        """
        model = request.model or self._gateway_config.default_model
        model_config = self._get_model_config(model)

        if not model_config.supports_streaming:
            raise StreamingNotSupportedError(model)

        client = await self._ensure_client()

        payload = build_chat_payload(
            request=request,
            model=model,
            max_tokens_default=self.config.max_tokens,
            stream=True,
        )

        try:
            async with client.stream(
                "POST",
                f"{model_config.base_url}/chat/completions",
                json=payload,
                headers=build_headers(model_config),
                timeout=model_config.timeout,
            ) as response:
                response.raise_for_status()

                async for chunk_data in parse_sse_stream(response):
                    chunk = parse_stream_chunk(chunk_data)
                    yield chunk

        except httpx.HTTPStatusError as e:
            raise map_http_error(e) from None
        except httpx.TimeoutException as e:
            raise ModelTimeoutError(str(e)) from None

    def _parse_stream_chunk(self, data: dict[str, Any]) -> StreamChunk:
        """Parse raw chunk data into StreamChunk.

        Args:
            data: The raw chunk data.

        Returns:
            Parsed StreamChunk object.
        """
        return parse_stream_chunk(data)

    def _should_fallback(self, error: Exception | None) -> bool:
        """Check if should try fallback model.

        Args:
            error: The error that occurred.

        Returns:
            True if fallback should be attempted.
        """
        return should_fallback(error, self._gateway_config)

    async def _execute_fallback(
        self,
        request: ChatCompletionRequest,
        original_error: Exception | None,
    ) -> ChatCompletionResponse:
        """Execute request with fallback model.

        Args:
            request: The original request.
            original_error: The error that triggered fallback.

        Returns:
            Response from fallback model.

        Raises:
            The original error if fallback fails.
        """
        if not self._gateway_config.fallback_model:
            if original_error:
                raise original_error
            raise ModelError("No fallback model configured")

        fallback_request = build_fallback_request(
            original_request=request,
            fallback_model=self._gateway_config.fallback_model,
        )

        try:
            return await self.chat_completion(fallback_request)
        except Exception:
            # If fallback fails, raise original error
            if original_error:
                raise original_error from None
            raise

    async def health_check(self) -> dict[str, HealthStatus]:
        """Check health of all configured model endpoints.

        Returns:
            Dictionary mapping model names to their health status.

        Example:
            ```python
            health = await gateway.health_check()
            for model, status in health.items():
                print(f"{model}: {status.status}")
            ```
        """
        client = await self._ensure_client()
        gateway_base = self.config.llm_gateway_url.rstrip("/")
        return await check_model_health(client, self._gateway_config, gateway_base)

    async def close(self) -> None:
        """Close the HTTP client and release resources.

        This should be called when the gateway is no longer needed.
        """
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._initialized = False

    def get_model_info(self, model: str) -> dict[str, Any]:
        """Get information about a configured model.

        Args:
            model: The model identifier.

        Returns:
            Dictionary with model information.
        """
        config = self._get_model_config(model)
        return {
            "name": config.name,
            "provider": config.provider.value,
            "max_tokens": config.max_tokens,
            "context_window": config.context_window,
            "supports_streaming": config.supports_streaming,
            "supports_function_calling": config.supports_function_calling,
        }

    def list_models(self) -> list[str]:
        """List all configured models.

        Returns:
            List of model identifiers.
        """
        return list(self._gateway_config.models.keys())

    @property
    def default_model(self) -> str:
        """Get the default model name.

        Returns:
            The default model identifier.
        """
        return self._gateway_config.default_model

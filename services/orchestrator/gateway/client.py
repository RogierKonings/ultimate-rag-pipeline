"""Model Gateway client implementation.

This module provides the ModelGateway class for unified LLM access,
supporting multiple providers with retry logic, streaming, and health checks.
"""

import asyncio
import logging
import random
import time
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from config import OrchestratorConfig

from .exceptions import (
    AuthenticationError,
    ModelError,
    ModelGatewayError,
    ModelNotFoundError,
    ModelTimeoutError,
    RateLimitError,
    StreamingNotSupportedError,
)
from .models import (
    ChatChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    GatewayConfig,
    HealthStatus,
    ModelConfig,
    StreamChoice,
    StreamChunk,
    StreamDelta,
    UsageStats,
)
from .streaming import parse_sse_stream

logger = logging.getLogger(__name__)


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

    def _get_headers(self, model_config: ModelConfig) -> dict[str, str]:
        """Get headers for API requests.

        Args:
            model_config: The model configuration.

        Returns:
            Dictionary of HTTP headers.
        """
        headers = {"Content-Type": "application/json"}
        if model_config.api_key:
            headers["Authorization"] = f"Bearer {model_config.api_key}"
        return headers

    def _map_http_error(self, error: httpx.HTTPStatusError) -> ModelGatewayError:
        """Map HTTP errors to gateway exceptions.

        Args:
            error: The HTTP error.

        Returns:
            The appropriate gateway exception.
        """
        status = error.response.status_code

        if status == 429:
            return RateLimitError("Rate limit exceeded")
        if status == 401:
            return AuthenticationError("Invalid API key")
        if status == 404:
            return ModelNotFoundError("Model not found")
        if status >= 500:
            return ModelError(f"Server error: {status}")
        return ModelError(f"Request failed: {status}")

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

        # Prepare request payload
        payload = {
            "model": model,
            "messages": [msg.model_dump() for msg in request.messages],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": False,
        }

        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        elif self.config.max_tokens:
            payload["max_tokens"] = self.config.max_tokens

        if request.stop:
            payload["stop"] = request.stop
        if request.frequency_penalty != 0.0:
            payload["frequency_penalty"] = request.frequency_penalty
        if request.presence_penalty != 0.0:
            payload["presence_penalty"] = request.presence_penalty

        last_error: Exception | None = None

        for attempt in range(model_config.max_retries + 1):
            try:
                response = await client.post(
                    f"{model_config.base_url}/chat/completions",
                    json=payload,
                    headers=self._get_headers(model_config),
                    timeout=model_config.timeout,
                )
                response.raise_for_status()

                data = response.json()
                latency_ms = (time.perf_counter() - start_time) * 1000

                # Parse response
                result = self._parse_completion_response(data)
                result.latency_ms = latency_ms
                result.request_id = request.request_id

                return result

            except httpx.HTTPStatusError as e:
                last_error = self._map_http_error(e)
                # Don't retry on client errors (4xx) except rate limit (429)
                if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                    raise last_error from None
                # For 429 and 5xx, continue to retry logic below

            except httpx.TimeoutException as e:
                last_error = ModelTimeoutError(str(e))

            except httpx.ConnectError as e:
                last_error = ModelError(f"Connection failed: {e}")

            # If we get here, we should retry (unless it's the last attempt)
            if attempt < model_config.max_retries:
                # Calculate backoff with jitter
                delay = min(
                    model_config.retry_base_delay * (2**attempt),
                    model_config.retry_max_delay,
                )
                # Add jitter (0.5 to 1.5 of the delay)
                delay *= 0.5 + random.random()  # noqa: S311
                await asyncio.sleep(delay)
            else:
                # All retries exhausted
                break

        # All retries exhausted, try fallback or raise
        if self._should_fallback(last_error):
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
        choices = []
        for choice_data in data.get("choices", []):
            message_data = choice_data.get("message", {})
            message = ChatMessage(
                role=message_data.get("role", "assistant"),
                content=message_data.get("content", ""),
                name=message_data.get("name"),
            )
            choices.append(
                ChatChoice(
                    index=choice_data.get("index", 0),
                    message=message,
                    finish_reason=choice_data.get("finish_reason"),
                ),
            )

        usage_data = data.get("usage", {})
        usage = UsageStats(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return ChatCompletionResponse(
            id=data.get("id", ""),
            object=data.get("object", "chat.completion"),
            created=data.get("created", int(time.time())),
            model=data.get("model", ""),
            choices=choices,
            usage=usage,
        )

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

        # Prepare request payload with stream=True
        payload = {
            "model": model,
            "messages": [msg.model_dump() for msg in request.messages],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": True,
        }

        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        elif self.config.max_tokens:
            payload["max_tokens"] = self.config.max_tokens

        if request.stop:
            payload["stop"] = request.stop
        if request.frequency_penalty != 0.0:
            payload["frequency_penalty"] = request.frequency_penalty
        if request.presence_penalty != 0.0:
            payload["presence_penalty"] = request.presence_penalty

        try:
            async with client.stream(
                "POST",
                f"{model_config.base_url}/chat/completions",
                json=payload,
                headers=self._get_headers(model_config),
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
            raise self._map_http_error(e) from None
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

        # Prepare request payload with stream=True
        payload = {
            "model": model,
            "messages": [msg.model_dump() for msg in request.messages],
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": True,
        }

        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        elif self.config.max_tokens:
            payload["max_tokens"] = self.config.max_tokens

        try:
            async with client.stream(
                "POST",
                f"{model_config.base_url}/chat/completions",
                json=payload,
                headers=self._get_headers(model_config),
                timeout=model_config.timeout,
            ) as response:
                response.raise_for_status()

                async for chunk_data in parse_sse_stream(response):
                    chunk = self._parse_stream_chunk(chunk_data)
                    yield chunk

        except httpx.HTTPStatusError as e:
            raise self._map_http_error(e) from None
        except httpx.TimeoutException as e:
            raise ModelTimeoutError(str(e)) from None

    def _parse_stream_chunk(self, data: dict[str, Any]) -> StreamChunk:
        """Parse raw chunk data into StreamChunk.

        Args:
            data: The raw chunk data.

        Returns:
            Parsed StreamChunk object.
        """
        choices = []
        for choice_data in data.get("choices", []):
            delta_data = choice_data.get("delta", {})
            delta = StreamDelta(
                role=delta_data.get("role"),
                content=delta_data.get("content"),
            )
            choices.append(
                StreamChoice(
                    index=choice_data.get("index", 0),
                    delta=delta,
                    finish_reason=choice_data.get("finish_reason"),
                ),
            )

        return StreamChunk(
            id=data.get("id", ""),
            object=data.get("object", "chat.completion.chunk"),
            created=data.get("created", int(time.time())),
            model=data.get("model", ""),
            choices=choices,
        )

    def _should_fallback(self, error: Exception | None) -> bool:
        """Check if should try fallback model.

        Args:
            error: The error that occurred.

        Returns:
            True if fallback should be attempted.
        """
        if not self._gateway_config.fallback_model:
            return False

        if error is None:
            return False

        if isinstance(error, RateLimitError) and self._gateway_config.fallback_on_rate_limit:
            return True

        return bool(
            isinstance(error, ModelTimeoutError) and self._gateway_config.fallback_on_timeout,
        )

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

        # Create new request with fallback model
        fallback_request = ChatCompletionRequest(
            model=self._gateway_config.fallback_model,
            messages=request.messages,
            temperature=request.temperature,
            top_p=request.top_p,
            max_tokens=request.max_tokens,
            stop=request.stop,
            stream=request.stream,
            frequency_penalty=request.frequency_penalty,
            presence_penalty=request.presence_penalty,
            request_id=request.request_id,
            user_id=request.user_id,
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
        results: dict[str, HealthStatus] = {}

        # Extract base URL without /v1 suffix for root health checks
        gateway_base = self.config.llm_gateway_url.rstrip("/")

        for model_name, model_config in self._gateway_config.models.items():
            try:
                start_time = time.perf_counter()

                # Try multiple health endpoints (vLLM uses /v1/health, Ollama uses /)
                health_endpoints = [
                    f"{model_config.base_url}/health",  # vLLM style
                    gateway_base,  # Ollama root endpoint
                ]

                response = None
                for endpoint in health_endpoints:
                    try:
                        response = await client.get(endpoint, timeout=5.0)
                        if response.is_success:
                            break
                    except Exception as e:
                        logger.debug("Health check failed for endpoint %s: %s", endpoint, e)
                        continue

                latency_ms = (time.perf_counter() - start_time) * 1000

                if response is not None and response.is_success:
                    results[model_name] = HealthStatus(
                        status="healthy",
                        latency_ms=latency_ms,
                    )
                else:
                    status_code = response.status_code if response else "N/A"
                    results[model_name] = HealthStatus(
                        status="unhealthy",
                        latency_ms=latency_ms,
                        message=f"HTTP {status_code}",
                    )
            except httpx.TimeoutException:
                results[model_name] = HealthStatus(
                    status="error",
                    message="Health check timed out",
                )
            except Exception as e:
                results[model_name] = HealthStatus(
                    status="error",
                    message=str(e),
                )

        return results

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

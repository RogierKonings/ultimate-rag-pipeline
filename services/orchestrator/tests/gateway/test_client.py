"""Unit tests for the ModelGateway client."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from gateway import (
    AuthenticationError,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ModelError,
    ModelGateway,
    ModelTimeoutError,
    StreamingNotSupportedError,
)

from config import OrchestratorConfig

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def gateway_config():
    """Create a test configuration."""
    return OrchestratorConfig(
        service_name="orchestrator-test",
        llm_gateway_url="http://test-llm:8004",
        default_model="test-model",
        fallback_model="fallback-model",
        max_tokens=1024,
        temperature=0.7,
        stream_timeout=30.0,
    )


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    """Speed up tests by making asyncio.sleep a no-op."""
    async def fast_sleep(delay):
        pass  # Skip the delay in tests
    monkeypatch.setattr("gateway.client.asyncio.sleep", fast_sleep)


@pytest.fixture
def gateway(gateway_config):
    """Create a gateway instance."""
    return ModelGateway(gateway_config)


@pytest.fixture
def chat_request():
    """Create a test chat request."""
    return ChatCompletionRequest(
        model="test-model",
        messages=[
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="Hello!"),
        ],
        temperature=0.7,
        max_tokens=100,
    )


@pytest.fixture
def mock_response_data():
    """Create mock LLM response data."""
    return {
        "id": "chatcmpl-test123",
        "object": "chat.completion",
        "created": int(datetime.now(tz=UTC).timestamp()),
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello! How can I help you today?",
                },
                "finish_reason": "stop",
            },
        ],
        "usage": {
            "prompt_tokens": 15,
            "completion_tokens": 8,
            "total_tokens": 23,
        },
    }


# ============================================================================
# Chat Completion Tests
# ============================================================================


@pytest.mark.asyncio
async def test_chat_completion_success(gateway, chat_request, mock_response_data):
    """Test successful chat completion."""
    mock_response = MagicMock()
    mock_response.json.return_value = mock_response_data
    mock_response.raise_for_status = MagicMock()
    mock_response.status_code = 200

    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ensure.return_value = mock_client

        response = await gateway.chat_completion(chat_request)

    assert isinstance(response, ChatCompletionResponse)
    assert response.id == "chatcmpl-test123"
    assert len(response.choices) == 1
    assert response.choices[0].message.content == "Hello! How can I help you today?"
    assert response.choices[0].message.role == "assistant"
    assert response.choices[0].finish_reason == "stop"
    assert response.usage.prompt_tokens == 15
    assert response.usage.completion_tokens == 8
    assert response.usage.total_tokens == 23
    assert response.latency_ms is not None
    assert response.request_id == chat_request.request_id


@pytest.mark.asyncio
async def test_chat_completion_with_default_model(gateway, mock_response_data):
    """Test chat completion uses default model when not specified."""
    request = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello!")],
    )

    mock_response = MagicMock()
    mock_response.json.return_value = mock_response_data
    mock_response.raise_for_status = MagicMock()

    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ensure.return_value = mock_client

        response = await gateway.chat_completion(request)

    assert response is not None
    mock_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_chat_completion_includes_optional_params(gateway, mock_response_data):
    """Test that optional parameters are included in request."""
    request = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello!")],
        temperature=0.5,
        top_p=0.9,
        max_tokens=200,
        stop=["STOP"],
        frequency_penalty=0.5,
        presence_penalty=0.3,
    )

    mock_response = MagicMock()
    mock_response.json.return_value = mock_response_data
    mock_response.raise_for_status = MagicMock()

    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_ensure.return_value = mock_client

        await gateway.chat_completion(request)

    # Verify the call was made with correct payload
    call_args = mock_client.post.call_args
    payload = call_args.kwargs["json"]
    assert payload["temperature"] == 0.5
    assert payload["top_p"] == 0.9
    assert payload["max_tokens"] == 200
    assert payload["stop"] == ["STOP"]
    assert payload["frequency_penalty"] == 0.5
    assert payload["presence_penalty"] == 0.3


# ============================================================================
# Error Handling Tests
# ============================================================================


@pytest.mark.asyncio
async def test_chat_completion_server_error_retries(gateway, chat_request, mock_response_data):
    """Test retry behavior on 5xx server errors."""
    # Create a mock that fails first two times, then succeeds
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            error_response = MagicMock()
            error_response.status_code = 500
            raise httpx.HTTPStatusError(
                "Server Error",
                request=MagicMock(),
                response=error_response,
            )
        response = MagicMock()
        response.json.return_value = mock_response_data
        response.raise_for_status = MagicMock()
        return response

    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_ensure.return_value = mock_client

        response = await gateway.chat_completion(chat_request)

    assert call_count == 3
    assert response is not None


@pytest.mark.asyncio
async def test_chat_completion_client_error_no_retry(gateway, chat_request):
    """Test no retry on 4xx client errors (except 429)."""
    error_response = MagicMock()
    error_response.status_code = 400

    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Bad Request",
                request=MagicMock(),
                response=error_response,
            ),
        )
        mock_ensure.return_value = mock_client

        with pytest.raises(ModelError):
            await gateway.chat_completion(chat_request)

    # Should only be called once (no retry)
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_chat_completion_rate_limit_retries(gateway, chat_request, mock_response_data):
    """Test retry on rate limit (429) errors."""
    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            error_response = MagicMock()
            error_response.status_code = 429
            raise httpx.HTTPStatusError(
                "Rate Limited",
                request=MagicMock(),
                response=error_response,
            )
        response = MagicMock()
        response.json.return_value = mock_response_data
        response.raise_for_status = MagicMock()
        return response

    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_ensure.return_value = mock_client

        response = await gateway.chat_completion(chat_request)

    assert call_count == 2
    assert response is not None


@pytest.mark.asyncio
async def test_chat_completion_auth_error(gateway, chat_request):
    """Test authentication error handling."""
    error_response = MagicMock()
    error_response.status_code = 401

    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Unauthorized",
                request=MagicMock(),
                response=error_response,
            ),
        )
        mock_ensure.return_value = mock_client

        with pytest.raises(AuthenticationError):
            await gateway.chat_completion(chat_request)


@pytest.mark.asyncio
async def test_chat_completion_timeout(gateway, chat_request):
    """Test timeout error handling."""
    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.TimeoutException("Request timed out"),
        )
        mock_ensure.return_value = mock_client

        # Should try fallback after retries exhausted
        with pytest.raises(ModelTimeoutError):
            await gateway.chat_completion(chat_request)


@pytest.mark.asyncio
async def test_chat_completion_fallback_on_timeout(gateway_config, chat_request, mock_response_data):
    """Test fallback to secondary model on timeout."""
    gateway = ModelGateway(gateway_config)
    call_count = 0

    async def mock_post(url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Primary model times out
        if "test-model" in str(url) or call_count <= 4:  # 4 retries for primary
            raise httpx.TimeoutException("Timeout")
        # Fallback succeeds
        response = MagicMock()
        response.json.return_value = mock_response_data
        response.raise_for_status = MagicMock()
        return response

    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_ensure.return_value = mock_client

        # Fallback should work after primary fails
        response = await gateway.chat_completion(chat_request)

    assert response is not None


# ============================================================================
# Streaming Tests
# ============================================================================


@pytest.mark.asyncio
async def test_chat_completion_stream_success(gateway, chat_request):
    """Test successful streaming chat completion."""
    # Create mock SSE response
    sse_data = [
        'data: {"id": "test", "choices": [{"delta": {"content": "Hello"}}]}\n\n',
        'data: {"id": "test", "choices": [{"delta": {"content": " world"}}]}\n\n',
        'data: {"id": "test", "choices": [{"delta": {}, "finish_reason": "stop"}]}\n\n',
        "data: [DONE]\n\n",
    ]

    async def mock_aiter_text():
        for chunk in sse_data:
            yield chunk

    mock_response = MagicMock()
    mock_response.aiter_text = mock_aiter_text
    mock_response.raise_for_status = MagicMock()
    mock_response.is_success = True

    mock_stream_context = MagicMock()
    mock_stream_context.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_context.__aexit__ = AsyncMock(return_value=None)

    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.stream = MagicMock(return_value=mock_stream_context)
        mock_ensure.return_value = mock_client

        tokens = []
        async for token in gateway.chat_completion_stream(chat_request):
            tokens.append(token)

    assert tokens == ["Hello", " world"]


@pytest.mark.asyncio
async def test_streaming_not_supported_error(gateway_config):
    """Test error when model doesn't support streaming."""
    # Modify config to have a model that doesn't support streaming
    gateway = ModelGateway(gateway_config)

    # Manually set supports_streaming to False for the model
    model_config = gateway._get_model_config("test-model")
    model_config.supports_streaming = False
    gateway._gateway_config.models["test-model"] = model_config

    request = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hello!")],
    )

    with pytest.raises(StreamingNotSupportedError):
        async for _ in gateway.chat_completion_stream(request):
            pass


# ============================================================================
# Health Check Tests
# ============================================================================


@pytest.mark.asyncio
async def test_health_check_healthy(gateway):
    """Test health check with healthy endpoint."""
    mock_response = MagicMock()
    mock_response.is_success = True

    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_ensure.return_value = mock_client

        results = await gateway.health_check()

    assert "test-model" in results
    assert results["test-model"].status == "healthy"
    assert results["test-model"].latency_ms is not None


@pytest.mark.asyncio
async def test_health_check_unhealthy(gateway):
    """Test health check with unhealthy endpoint."""
    mock_response = MagicMock()
    mock_response.is_success = False
    mock_response.status_code = 503

    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_ensure.return_value = mock_client

        results = await gateway.health_check()

    assert "test-model" in results
    assert results["test-model"].status == "unhealthy"


@pytest.mark.asyncio
async def test_health_check_timeout(gateway):
    """Test health check with timeout."""
    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
        mock_ensure.return_value = mock_client

        results = await gateway.health_check()

    assert "test-model" in results
    assert results["test-model"].status == "error"
    assert "timed out" in results["test-model"].message.lower()


@pytest.mark.asyncio
async def test_health_check_connection_error(gateway):
    """Test health check with connection error."""
    with patch.object(gateway, "_ensure_client") as mock_ensure:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_ensure.return_value = mock_client

        results = await gateway.health_check()

    assert "test-model" in results
    assert results["test-model"].status == "error"
    assert results["test-model"].message is not None


# ============================================================================
# Client Lifecycle Tests
# ============================================================================


@pytest.mark.asyncio
async def test_close_client(gateway):
    """Test closing the gateway client."""
    # First ensure client is created
    with patch("httpx.AsyncClient") as mock_async_client:
        mock_client = AsyncMock()
        mock_async_client.return_value = mock_client

        await gateway._ensure_client()
        assert gateway._client is not None

    # Now close it
    gateway._client = mock_client
    await gateway.close()

    mock_client.aclose.assert_called_once()
    assert gateway._client is None


@pytest.mark.asyncio
async def test_close_without_init(gateway):
    """Test closing when client was never initialized."""
    # Should not raise any errors
    await gateway.close()
    assert gateway._client is None


# ============================================================================
# Model Info Tests
# ============================================================================


def test_get_model_info(gateway):
    """Test getting model information."""
    info = gateway.get_model_info("test-model")

    assert info["name"] == "test-model"
    assert "max_tokens" in info
    assert "context_window" in info
    assert "supports_streaming" in info
    assert "supports_function_calling" in info


def test_get_model_info_unknown_model(gateway):
    """Test getting info for unknown model creates default config."""
    info = gateway.get_model_info("unknown-model")

    assert info["name"] == "unknown-model"
    assert info["supports_streaming"] is True  # Default value


def test_list_models(gateway):
    """Test listing configured models."""
    models = gateway.list_models()

    assert isinstance(models, list)
    assert "test-model" in models
    assert "fallback-model" in models


def test_default_model_property(gateway):
    """Test default model property."""
    assert gateway.default_model == "test-model"


# ============================================================================
# Request Validation Tests
# ============================================================================


def test_chat_request_empty_messages_fails():
    """Test that empty messages list raises validation error."""
    with pytest.raises(ValueError):
        ChatCompletionRequest(
            model="test-model",
            messages=[],
        )


def test_chat_request_temperature_bounds():
    """Test temperature validation bounds."""
    # Valid temperature
    request = ChatCompletionRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Hi")],
        temperature=1.5,
    )
    assert request.temperature == 1.5

    # Invalid temperature
    with pytest.raises(ValueError):
        ChatCompletionRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hi")],
            temperature=2.5,  # > 2.0
        )


def test_chat_message_roles():
    """Test that all valid message roles work."""
    roles = ["system", "user", "assistant", "function"]

    for role in roles:
        msg = ChatMessage(role=role, content="Test")
        assert msg.role == role

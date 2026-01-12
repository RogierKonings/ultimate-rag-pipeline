"""Tests for fallback handlers."""

import pytest
from resilience.config import FallbackConfig
from resilience.fallbacks import (
    FallbackError,
    FallbackHandlers,
    create_fallback_response,
)


class TestFallbackHandlersConfiguration:
    """Tests for FallbackHandlers configuration."""

    def setup_method(self):
        """Reset configuration before each test."""
        FallbackHandlers._config = FallbackConfig()
        FallbackHandlers.clear_cache()

    def test_default_configuration(self):
        """Test default configuration values."""
        config = FallbackHandlers._config

        assert config.enable_cache_fallback is True
        assert config.enable_default_response is True
        assert "apologize" in config.default_response.lower()

    def test_configure_handlers(self):
        """Test configuring fallback handlers."""
        custom_config = FallbackConfig(
            enable_cache_fallback=False,
            enable_default_response=True,
            default_response="Custom default response",
        )

        FallbackHandlers.configure(custom_config)

        assert FallbackHandlers._config.enable_cache_fallback is False
        assert FallbackHandlers._config.default_response == "Custom default response"


class TestFallbackCache:
    """Tests for fallback cache operations."""

    def setup_method(self):
        """Clear cache before each test."""
        FallbackHandlers.clear_cache()

    def test_set_and_get_cached_response(self):
        """Test setting and getting cached responses."""
        FallbackHandlers.set_cached_response("test_key", "test_value")

        result = FallbackHandlers.get_cached_response("test_key")

        assert result == "test_value"

    def test_get_nonexistent_key_returns_none(self):
        """Test getting nonexistent key returns None."""
        result = FallbackHandlers.get_cached_response("nonexistent")

        assert result is None

    def test_clear_cache(self):
        """Test clearing the cache."""
        FallbackHandlers.set_cached_response("key1", "value1")
        FallbackHandlers.set_cached_response("key2", "value2")

        FallbackHandlers.clear_cache()

        assert FallbackHandlers.get_cached_response("key1") is None
        assert FallbackHandlers.get_cached_response("key2") is None


class TestLLMFallback:
    """Tests for LLM fallback handler."""

    def setup_method(self):
        """Reset configuration before each test."""
        FallbackHandlers._config = FallbackConfig()
        FallbackHandlers.clear_cache()

    @pytest.mark.asyncio
    async def test_returns_cached_response(self):
        """Test LLM fallback returns cached response when available."""
        FallbackHandlers.set_cached_response("query_123", "Cached answer")

        result = await FallbackHandlers.llm_fallback(
            "prompt",
            cache_key="query_123",
        )

        assert result == "Cached answer"

    @pytest.mark.asyncio
    async def test_returns_default_when_no_cache(self):
        """Test LLM fallback returns default when no cache available."""
        result = await FallbackHandlers.llm_fallback("prompt")

        assert "apologize" in result.lower()

    @pytest.mark.asyncio
    async def test_returns_custom_default_response(self):
        """Test LLM fallback returns custom default response."""
        custom_config = FallbackConfig(default_response="Service unavailable")
        FallbackHandlers.configure(custom_config)

        result = await FallbackHandlers.llm_fallback("prompt")

        assert result == "Service unavailable"

    @pytest.mark.asyncio
    async def test_raises_when_all_fallbacks_disabled(self):
        """Test LLM fallback raises when all options disabled."""
        custom_config = FallbackConfig(
            enable_cache_fallback=False,
            enable_default_response=False,
        )
        FallbackHandlers.configure(custom_config)

        with pytest.raises(FallbackError) as exc_info:
            await FallbackHandlers.llm_fallback("prompt")

        assert exc_info.value.service == "llm"
        assert "No fallback option available" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_includes_error_in_fallback(self):
        """Test LLM fallback accepts original error."""
        original_error = Exception("LLM timeout")

        # Should not raise, just log
        result = await FallbackHandlers.llm_fallback("prompt", error=original_error)

        assert "apologize" in result.lower()


class TestRetrievalFallback:
    """Tests for retrieval fallback handler."""

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        """Test retrieval fallback returns empty list."""
        result = await FallbackHandlers.retrieval_fallback("query")

        assert result == []
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_returns_empty_list_with_error(self):
        """Test retrieval fallback returns empty list even with error."""
        error = Exception("Retrieval service unavailable")

        result = await FallbackHandlers.retrieval_fallback("query", error=error)

        assert result == []


class TestEmbeddingFallback:
    """Tests for embedding fallback handler."""

    def setup_method(self):
        """Reset configuration before each test."""
        FallbackHandlers._config = FallbackConfig()
        FallbackHandlers.clear_cache()

    @pytest.mark.asyncio
    async def test_returns_cached_embedding(self):
        """Test embedding fallback returns cached embedding."""
        cached_embedding = [0.1, 0.2, 0.3, 0.4, 0.5]
        FallbackHandlers.set_cached_response("text_hash_123", cached_embedding)

        result = await FallbackHandlers.embedding_fallback(
            "text",
            cache_key="text_hash_123",
        )

        assert result == cached_embedding

    @pytest.mark.asyncio
    async def test_raises_without_cached_embedding(self):
        """Test embedding fallback raises when no cache available."""
        with pytest.raises(FallbackError) as exc_info:
            await FallbackHandlers.embedding_fallback("text", cache_key="nonexistent")

        assert exc_info.value.service == "embedding"
        assert "No cached embedding" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_raises_without_cache_key(self):
        """Test embedding fallback raises without cache key."""
        with pytest.raises(FallbackError) as exc_info:
            await FallbackHandlers.embedding_fallback("text")

        assert exc_info.value.service == "embedding"

    @pytest.mark.asyncio
    async def test_includes_original_error(self):
        """Test embedding fallback includes original error."""
        original_error = Exception("Embedding service timeout")

        with pytest.raises(FallbackError) as exc_info:
            await FallbackHandlers.embedding_fallback("text", error=original_error)

        assert exc_info.value.original_error == original_error


class TestGuardrailsFallback:
    """Tests for guardrails fallback handler."""

    @pytest.mark.asyncio
    async def test_permissive_mode_allows_content(self):
        """Test guardrails fallback in permissive mode allows content."""
        result = await FallbackHandlers.guardrails_fallback("content", strict_mode=False)

        assert result["passed"] is True
        assert "unavailable" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_strict_mode_blocks_content(self):
        """Test guardrails fallback in strict mode blocks content."""
        result = await FallbackHandlers.guardrails_fallback("content", strict_mode=True)

        assert result["passed"] is False
        assert "strict" in result["reason"].lower()

    @pytest.mark.asyncio
    async def test_default_is_permissive(self):
        """Test guardrails fallback defaults to permissive mode."""
        result = await FallbackHandlers.guardrails_fallback("content")

        assert result["passed"] is True


class TestCreateFallbackResponse:
    """Tests for create_fallback_response factory."""

    @pytest.mark.asyncio
    async def test_creates_fallback_with_default_value(self):
        """Test creating a fallback that returns default value."""
        fallback = create_fallback_response(
            service_name="custom_service",
            default_value={"status": "fallback"},
        )

        result = await fallback("arg1", kwarg1="value1")

        assert result == {"status": "fallback"}

    @pytest.mark.asyncio
    async def test_created_fallback_accepts_error(self):
        """Test created fallback accepts error parameter."""
        fallback = create_fallback_response(
            service_name="custom_service",
            default_value="default",
        )

        error = Exception("Service error")
        result = await fallback(error=error)

        assert result == "default"

    @pytest.mark.asyncio
    async def test_creates_fallback_with_different_types(self):
        """Test creating fallbacks with different return types."""
        # List fallback
        list_fallback = create_fallback_response("list_service", [1, 2, 3])
        assert await list_fallback() == [1, 2, 3]

        # Dict fallback
        dict_fallback = create_fallback_response("dict_service", {"key": "value"})
        assert await dict_fallback() == {"key": "value"}

        # None fallback
        none_fallback = create_fallback_response("none_service", None)
        assert await none_fallback() is None


class TestFallbackError:
    """Tests for FallbackError exception."""

    def test_error_message(self):
        """Test FallbackError message format."""
        error = FallbackError("test_service", "Cache miss")

        assert error.service == "test_service"
        assert "test_service" in str(error)
        assert "Cache miss" in str(error)

    def test_includes_original_error(self):
        """Test FallbackError includes original error."""
        original = ValueError("Original error")
        error = FallbackError("test_service", "Cache miss", original_error=original)

        assert error.original_error == original

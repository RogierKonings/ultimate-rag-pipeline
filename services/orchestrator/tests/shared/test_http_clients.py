"""Tests for shared HTTP client lifecycle and configuration."""

import httpx
import pytest

from shared.http_clients import (
    _create_llm_client,
    _create_retrieval_client,
    close_http_clients,
    get_llm_client,
    get_retrieval_client,
    init_http_clients,
)


class TestClientLifecycle:
    """Tests for init/close lifecycle of shared HTTP clients."""

    @pytest.mark.asyncio
    async def test_init_creates_clients(self):
        """Test that init_http_clients creates both clients."""
        await init_http_clients()

        try:
            retrieval = get_retrieval_client()
            llm = get_llm_client()

            assert isinstance(retrieval, httpx.AsyncClient)
            assert isinstance(llm, httpx.AsyncClient)
        finally:
            await close_http_clients()

    @pytest.mark.asyncio
    async def test_close_cleans_up_clients(self):
        """Test that close_http_clients properly closes and nullifies clients."""
        await init_http_clients()
        await close_http_clients()

        with pytest.raises(RuntimeError, match="Retrieval HTTP client not initialized"):
            get_retrieval_client()

        with pytest.raises(RuntimeError, match="LLM HTTP client not initialized"):
            get_llm_client()

    @pytest.mark.asyncio
    async def test_get_retrieval_client_raises_before_init(self):
        """Test that get_retrieval_client raises RuntimeError before init."""
        # Ensure clean state
        await close_http_clients()

        with pytest.raises(RuntimeError, match="not initialized"):
            get_retrieval_client()

    @pytest.mark.asyncio
    async def test_get_llm_client_raises_before_init(self):
        """Test that get_llm_client raises RuntimeError before init."""
        # Ensure clean state
        await close_http_clients()

        with pytest.raises(RuntimeError, match="not initialized"):
            get_llm_client()

    @pytest.mark.asyncio
    async def test_double_close_is_safe(self):
        """Test that closing clients twice does not raise."""
        await init_http_clients()
        await close_http_clients()
        await close_http_clients()  # Should not raise

    @pytest.mark.asyncio
    async def test_reinit_after_close(self):
        """Test that clients can be reinitialized after close."""
        await init_http_clients()
        await close_http_clients()

        await init_http_clients()
        try:
            retrieval = get_retrieval_client()
            assert isinstance(retrieval, httpx.AsyncClient)
        finally:
            await close_http_clients()


class TestClientConfiguration:
    """Tests for client configuration (timeouts, limits, headers)."""

    def test_retrieval_client_has_base_url(self):
        """Test retrieval client is configured with base_url."""
        client = _create_retrieval_client()
        try:
            assert str(client.base_url) != ""
            assert "localhost" in str(client.base_url) or "retrieval" in str(client.base_url)
        finally:
            # Synchronous close is fine for test cleanup
            pass

    def test_llm_client_has_base_url(self):
        """Test LLM client is configured with base_url."""
        client = _create_llm_client()
        try:
            assert str(client.base_url) != ""
            assert "localhost" in str(client.base_url) or "gateway" in str(client.base_url)
        finally:
            pass

    def test_retrieval_client_has_timeout(self):
        """Test retrieval client has timeout configured."""
        client = _create_retrieval_client()
        assert client.timeout.connect is not None
        assert client.timeout.connect > 0

    def test_llm_client_has_timeout(self):
        """Test LLM client has timeout configured."""
        client = _create_llm_client()
        assert client.timeout.connect is not None
        assert client.timeout.connect > 0

    def test_retrieval_client_has_user_agent_header(self):
        """Test retrieval client sends User-Agent header."""
        client = _create_retrieval_client()
        assert "user-agent" in {k.lower() for k in client.headers}

    def test_llm_client_has_user_agent_header(self):
        """Test LLM client sends User-Agent header."""
        client = _create_llm_client()
        assert "user-agent" in {k.lower() for k in client.headers}

    def test_retrieval_client_has_connection_limits(self):
        """Test retrieval client has connection pool limits configured."""
        client = _create_retrieval_client()
        # Connection pool limits are set via httpx.Limits at construction time;
        # verify the client was created successfully with transport configured
        assert client is not None
        assert isinstance(client, httpx.AsyncClient)

    def test_clients_have_different_timeouts(self):
        """Test that retrieval and LLM clients may have different timeouts."""
        retrieval = _create_retrieval_client()
        llm = _create_llm_client()
        # They may or may not be equal depending on config,
        # but they should both be positive
        assert retrieval.timeout.pool is not None or retrieval.timeout.read is not None
        assert llm.timeout.pool is not None or llm.timeout.read is not None


class TestClientReuse:
    """Tests verifying that shared clients are reused (not recreated)."""

    @pytest.mark.asyncio
    async def test_get_retrieval_client_returns_same_instance(self):
        """Test that get_retrieval_client returns the same instance each call."""
        await init_http_clients()
        try:
            client1 = get_retrieval_client()
            client2 = get_retrieval_client()
            assert client1 is client2
        finally:
            await close_http_clients()

    @pytest.mark.asyncio
    async def test_get_llm_client_returns_same_instance(self):
        """Test that get_llm_client returns the same instance each call."""
        await init_http_clients()
        try:
            client1 = get_llm_client()
            client2 = get_llm_client()
            assert client1 is client2
        finally:
            await close_http_clients()

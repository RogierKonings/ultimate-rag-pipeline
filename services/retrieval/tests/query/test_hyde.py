"""Tests for HyDE and multi-query generation."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from query.hyde import HyDEGenerator, MultiQueryGenerator


class TestHyDEGenerator:
    """Tests for HyDEGenerator."""

    @pytest.fixture
    def hyde(self):
        """Create HyDE generator."""
        return HyDEGenerator()

    def test_build_prompt(self, hyde):
        """Test prompt building."""
        query = "What is machine learning?"
        prompt = hyde._build_prompt(query)

        assert query in prompt
        assert "document passage" in prompt.lower()
        assert "Query:" in prompt

    @pytest.mark.asyncio
    async def test_generate_success(self, hyde):
        """Test successful HyDE generation."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"text": "Machine learning is a subset of AI..."}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(hyde._http_client, "post", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response

            result = await hyde.generate("What is machine learning?")

            assert "Machine learning" in result
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_strips_whitespace(self, hyde):
        """Test that generated document is stripped."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"text": "  Document content  \n"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(hyde._http_client, "post", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response

            result = await hyde.generate("test query")

            assert result == "Document content"

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        async with HyDEGenerator() as hyde:
            assert hyde is not None

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method."""
        hyde = HyDEGenerator()
        await hyde.close()
        # Should not raise


class TestMultiQueryGenerator:
    """Tests for MultiQueryGenerator."""

    @pytest.fixture
    def generator(self):
        """Create multi-query generator."""
        return MultiQueryGenerator()

    @pytest.mark.asyncio
    async def test_generate_includes_original(self, generator):
        """Test that original query is always included."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"text": "Alternative query 1\nAlternative query 2"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(generator._http_client, "post", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response

            result = await generator.generate("original query")

            assert "original query" in result
            assert result[0] == "original query"  # Original is first

    @pytest.mark.asyncio
    async def test_generate_respects_max_queries(self, generator):
        """Test that max_queries is respected."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"text": "Alt 1\nAlt 2\nAlt 3\nAlt 4\nAlt 5"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(generator._http_client, "post", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response

            result = await generator.generate("test query")

            # max_queries is 3, plus original = 4
            assert len(result) <= 4

    @pytest.mark.asyncio
    async def test_generate_cleans_numbering(self, generator):
        """Test that numbering is removed from generated queries."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"text": "1. First query\n2) Second query\n3- Third query"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(generator._http_client, "post", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response

            result = await generator.generate("original query")

            # Check that numbering is stripped
            for query in result[1:]:  # Skip original
                assert not query.startswith("1")
                assert not query.startswith("2")
                assert not query.startswith("3")

    @pytest.mark.asyncio
    async def test_generate_excludes_duplicates(self, generator):
        """Test that duplicate of original is excluded."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"text": "original query\nAlternative query"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(generator._http_client, "post", new_callable=AsyncMock) as mock:
            mock.return_value = mock_response

            result = await generator.generate("original query")

            # Original should only appear once
            assert result.count("original query") == 1

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test async context manager."""
        async with MultiQueryGenerator() as generator:
            assert generator is not None

    @pytest.mark.asyncio
    async def test_close(self):
        """Test close method."""
        generator = MultiQueryGenerator()
        await generator.close()
        # Should not raise

    def test_custom_max_queries(self):
        """Test custom max_queries."""
        generator = MultiQueryGenerator(max_queries=5)
        assert generator.max_queries == 5

    def test_custom_model(self):
        """Test custom model."""
        generator = MultiQueryGenerator(model="custom-model")
        assert generator.model == "custom-model"

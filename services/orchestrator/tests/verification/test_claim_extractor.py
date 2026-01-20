"""Tests for ClaimExtractor."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from workflow.verification import ClaimExtractor


@pytest.fixture
def mock_gateway():
    """Create a mock ModelGateway."""
    gateway = MagicMock()
    gateway.default_model = "test-model"
    gateway.chat_completion = AsyncMock()
    return gateway


class TestClaimExtractor:
    """Tests for ClaimExtractor."""

    @pytest.mark.asyncio
    async def test_extracts_claims_from_valid_response(self, mock_gateway):
        """Test extraction of claims from a valid JSON response."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='[{"text": "Python was released in 1991", "claim_type": "temporal"}]'
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        extractor = ClaimExtractor(mock_gateway, max_claims=5)
        result = await extractor.extract("Python was released in 1991.")

        assert len(result.claims) == 1
        assert result.claims[0].text == "Python was released in 1991"
        assert result.claims[0].claim_type == "temporal"
        assert result.extraction_time_ms > 0

    @pytest.mark.asyncio
    async def test_extracts_multiple_claims(self, mock_gateway):
        """Test extraction of multiple claims."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content="""[
                        {"text": "Python is interpreted", "claim_type": "factual"},
                        {"text": "Python was created in 1991", "claim_type": "temporal"},
                        {"text": "Guido van Rossum created Python", "claim_type": "attribution"}
                    ]"""
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        extractor = ClaimExtractor(mock_gateway, max_claims=5)
        result = await extractor.extract("Python is interpreted...")

        assert len(result.claims) == 3
        assert result.claims[0].claim_type == "factual"
        assert result.claims[1].claim_type == "temporal"
        assert result.claims[2].claim_type == "attribution"

    @pytest.mark.asyncio
    async def test_limits_claims_to_max(self, mock_gateway):
        """Test that claims are limited to max_claims."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content="""[
                        {"text": "Claim 1", "claim_type": "factual"},
                        {"text": "Claim 2", "claim_type": "factual"},
                        {"text": "Claim 3", "claim_type": "factual"},
                        {"text": "Claim 4", "claim_type": "factual"},
                        {"text": "Claim 5", "claim_type": "factual"}
                    ]"""
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        extractor = ClaimExtractor(mock_gateway, max_claims=3)
        result = await extractor.extract("Many claims...")

        assert len(result.claims) == 3

    @pytest.mark.asyncio
    async def test_handles_empty_response(self, mock_gateway):
        """Test handling of empty response."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="[]"))]
        mock_gateway.chat_completion.return_value = mock_response

        extractor = ClaimExtractor(mock_gateway, max_claims=5)
        result = await extractor.extract("No claims here.")

        assert len(result.claims) == 0

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self, mock_gateway):
        """Test handling of invalid JSON response."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="This is not JSON"))
        ]
        mock_gateway.chat_completion.return_value = mock_response

        extractor = ClaimExtractor(mock_gateway, max_claims=5)
        result = await extractor.extract("Some answer.")

        assert len(result.claims) == 0

    @pytest.mark.asyncio
    async def test_handles_markdown_code_block(self, mock_gateway):
        """Test handling of JSON wrapped in markdown code block."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='```json\n[{"text": "Python is great", "claim_type": "factual"}]\n```'
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        extractor = ClaimExtractor(mock_gateway, max_claims=5)
        result = await extractor.extract("Python is great.")

        assert len(result.claims) == 1
        assert result.claims[0].text == "Python is great"

    @pytest.mark.asyncio
    async def test_handles_missing_claim_type(self, mock_gateway):
        """Test handling of claims without claim_type."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content='[{"text": "A claim without type"}]'))
        ]
        mock_gateway.chat_completion.return_value = mock_response

        extractor = ClaimExtractor(mock_gateway, max_claims=5)
        result = await extractor.extract("Some text.")

        assert len(result.claims) == 1
        assert result.claims[0].claim_type == "factual"  # Default

    @pytest.mark.asyncio
    async def test_handles_invalid_claim_type(self, mock_gateway):
        """Test handling of invalid claim type."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='[{"text": "A claim", "claim_type": "invalid_type"}]'
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        extractor = ClaimExtractor(mock_gateway, max_claims=5)
        result = await extractor.extract("Some text.")

        assert len(result.claims) == 1
        assert result.claims[0].claim_type == "factual"  # Falls back to factual

    @pytest.mark.asyncio
    async def test_handles_gateway_exception(self, mock_gateway):
        """Test handling of gateway exception."""
        mock_gateway.chat_completion.side_effect = Exception("Gateway error")

        extractor = ClaimExtractor(mock_gateway, max_claims=5)
        result = await extractor.extract("Some text.")

        assert len(result.claims) == 0
        assert result.extraction_time_ms > 0

    @pytest.mark.asyncio
    async def test_handles_empty_choices(self, mock_gateway):
        """Test handling of response with no choices."""
        mock_response = MagicMock()
        mock_response.choices = []
        mock_gateway.chat_completion.return_value = mock_response

        extractor = ClaimExtractor(mock_gateway, max_claims=5)
        result = await extractor.extract("Some text.")

        assert len(result.claims) == 0

"""Tests for the verification workflow node."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from workflow.nodes.verification import verification_node
from workflow.state import create_initial_state


@pytest.fixture
def base_state():
    """Create a base state with response and documents."""
    state = create_initial_state(
        request_id=str(uuid4()),
        query="What is Python?",
        options={"enable_verification": True},
    )
    state["response"] = "Python is a programming language released in 1991."
    state["documents"] = [
        {"content": "Python is a high-level programming language created in 1991."},
        {"content": "Python supports multiple programming paradigms."},
    ]
    return state


@pytest.fixture
def mock_gateway():
    """Create a mock ModelGateway."""
    gateway = MagicMock()
    gateway.default_model = "test-model"
    gateway.chat_completion = AsyncMock()
    gateway.close = AsyncMock()
    return gateway


class TestVerificationNode:
    """Tests for verification_node."""

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        """Test verification skips when disabled."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
            options={"enable_verification": False},
        )
        state["response"] = "Some response"
        state["documents"] = [{"content": "Some context"}]

        result = await verification_node(state)

        assert result["verification_result"]["skipped"] is True
        assert result["verification_result"]["skip_reason"] == "verification_disabled"
        assert "verification" in result["timing"]

    @pytest.mark.asyncio
    async def test_skips_when_no_response(self):
        """Test verification skips when there's no response."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
            options={"enable_verification": True},
        )
        state["response"] = None
        state["documents"] = [{"content": "Some context"}]

        result = await verification_node(state)

        assert result["verification_result"]["skipped"] is True
        assert result["verification_result"]["skip_reason"] == "no_response"

    @pytest.mark.asyncio
    async def test_skips_when_no_documents(self):
        """Test verification skips when there are no documents."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
            options={"enable_verification": True},
        )
        state["response"] = "Some response"
        state["documents"] = []

        result = await verification_node(state)

        assert result["verification_result"]["skipped"] is True
        assert result["verification_result"]["skip_reason"] == "no_context"

    @pytest.mark.asyncio
    @patch("workflow.nodes.verification.ModelGateway")
    async def test_skips_when_no_claims_extracted(self, MockGateway, base_state, mock_gateway):
        """Test verification skips when no claims are extracted."""
        MockGateway.return_value = mock_gateway

        # Mock extraction returning empty claims
        extraction_response = MagicMock()
        extraction_response.choices = [MagicMock(message=MagicMock(content="[]"))]
        mock_gateway.chat_completion.return_value = extraction_response

        result = await verification_node(base_state)

        assert result["verification_result"]["skipped"] is True
        assert result["verification_result"]["skip_reason"] == "no_claims_extracted"

    @pytest.mark.asyncio
    @patch("workflow.nodes.verification.ModelGateway")
    async def test_verifies_claims_successfully(self, MockGateway, base_state, mock_gateway):
        """Test successful claim verification."""
        MockGateway.return_value = mock_gateway

        # Mock extraction
        extraction_response = MagicMock()
        extraction_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='[{"text": "Python released in 1991", "claim_type": "temporal"}]'
                )
            )
        ]

        # Mock verification
        verification_response = MagicMock()
        verification_response.choices = [
            MagicMock(
                message=MagicMock(content='{"status": "supported", "evidence": "created in 1991"}')
            )
        ]

        mock_gateway.chat_completion.side_effect = [
            extraction_response,
            verification_response,
        ]

        result = await verification_node(base_state)

        assert result["verification_result"]["skipped"] is False
        assert result["verification_result"]["score"] == 1.0
        assert result["verification_result"]["label"] == "supported"
        assert result["verification_result"]["claims_total"] == 1
        assert result["verification_result"]["claims_supported"] == 1
        assert "verification" in result["timing"]

    @pytest.mark.asyncio
    @patch("workflow.nodes.verification.ModelGateway")
    async def test_calculates_partial_score(self, MockGateway, base_state, mock_gateway):
        """Test partial score calculation."""
        MockGateway.return_value = mock_gateway

        # Mock extraction with 2 claims
        extraction_response = MagicMock()
        extraction_response.choices = [
            MagicMock(
                message=MagicMock(
                    content="""[
                        {"text": "Claim 1", "claim_type": "factual"},
                        {"text": "Claim 2", "claim_type": "factual"}
                    ]"""
                )
            )
        ]

        # Mock verifications: one supported, one partially supported
        verification_responses = [
            MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(content='{"status": "supported", "evidence": "test"}')
                    )
                ]
            ),
            MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"status": "partially_supported", "evidence": "partial"}'
                        )
                    )
                ]
            ),
        ]

        mock_gateway.chat_completion.side_effect = [
            extraction_response,
            *verification_responses,
        ]

        result = await verification_node(base_state)

        # Score: (1 * 1.0 + 1 * 0.5) / 2 = 0.75
        assert result["verification_result"]["score"] == 0.75
        assert result["verification_result"]["label"] == "partial"
        assert result["verification_result"]["claims_supported"] == 1
        assert result["verification_result"]["claims_partial"] == 1

    @pytest.mark.asyncio
    @patch("workflow.nodes.verification.ModelGateway")
    @patch("workflow.nodes.verification.get_config")
    async def test_adds_disclaimer_on_low_confidence(
        self, mock_get_config, MockGateway, base_state, mock_gateway
    ):
        """Test disclaimer is added for low confidence responses."""
        MockGateway.return_value = mock_gateway

        # Configure threshold
        mock_config = MagicMock()
        mock_config.verification_enabled = True
        mock_config.verification_max_claims = 5
        mock_config.verification_confidence_threshold = 0.7
        mock_config.verification_add_disclaimer = True
        mock_get_config.return_value = mock_config

        # Mock extraction
        extraction_response = MagicMock()
        extraction_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='[{"text": "Unsupported claim", "claim_type": "factual"}]'
                )
            )
        ]

        # Mock unsupported verification
        verification_response = MagicMock()
        verification_response.choices = [
            MagicMock(message=MagicMock(content='{"status": "unsupported", "evidence": null}'))
        ]

        mock_gateway.chat_completion.side_effect = [
            extraction_response,
            verification_response,
        ]

        original_response = base_state["response"]
        result = await verification_node(base_state)

        assert result["verification_result"]["score"] == 0.0
        assert result["verification_result"]["label"] == "unsupported"
        assert "could not be fully verified" in result["response"]
        assert original_response in result["response"]

    @pytest.mark.asyncio
    @patch("workflow.nodes.verification.ModelGateway")
    @patch("workflow.nodes.verification.get_config")
    async def test_no_disclaimer_when_disabled(
        self, mock_get_config, MockGateway, base_state, mock_gateway
    ):
        """Test no disclaimer when add_disclaimer is disabled."""
        MockGateway.return_value = mock_gateway

        # Configure with disclaimer disabled
        mock_config = MagicMock()
        mock_config.verification_enabled = True
        mock_config.verification_max_claims = 5
        mock_config.verification_confidence_threshold = 0.7
        mock_config.verification_add_disclaimer = False
        mock_get_config.return_value = mock_config

        # Mock extraction
        extraction_response = MagicMock()
        extraction_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='[{"text": "Unsupported claim", "claim_type": "factual"}]'
                )
            )
        ]

        # Mock unsupported verification
        verification_response = MagicMock()
        verification_response.choices = [
            MagicMock(message=MagicMock(content='{"status": "unsupported", "evidence": null}'))
        ]

        mock_gateway.chat_completion.side_effect = [
            extraction_response,
            verification_response,
        ]

        original_response = base_state["response"]
        result = await verification_node(base_state)

        assert result["response"] == original_response  # No disclaimer added

    @pytest.mark.asyncio
    @patch("workflow.nodes.verification.ModelGateway")
    async def test_handles_exception_gracefully(self, MockGateway, base_state, mock_gateway):
        """Test graceful handling of exceptions.

        When claim extraction fails, it returns empty claims rather than
        raising an exception, which results in a 'no_claims_extracted' skip.
        This is the expected graceful degradation behavior.
        """
        MockGateway.return_value = mock_gateway
        mock_gateway.chat_completion.side_effect = Exception("Gateway error")

        result = await verification_node(base_state)

        assert result["verification_result"]["skipped"] is True
        # Extraction failure returns empty claims, triggering no_claims_extracted
        assert result["verification_result"]["skip_reason"] == "no_claims_extracted"
        # Response should be unchanged
        assert result["response"] == base_state["response"]

    @pytest.mark.asyncio
    async def test_uses_config_default_when_option_not_set(self):
        """Test that config default is used when option not specified."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
            options={},  # No enable_verification set
        )
        state["response"] = "Some response"
        state["documents"] = [{"content": "Some context"}]

        with patch("workflow.nodes.verification.get_config") as mock_get_config:
            mock_config = MagicMock()
            mock_config.verification_enabled = False  # Config default is disabled
            mock_get_config.return_value = mock_config

            result = await verification_node(state)

            assert result["verification_result"]["skipped"] is True
            assert result["verification_result"]["skip_reason"] == "verification_disabled"

    @pytest.mark.asyncio
    async def test_records_timing(self):
        """Test that verification timing is recorded."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
            options={"enable_verification": False},
        )
        state["response"] = "Some response"
        state["documents"] = [{"content": "Some context"}]

        result = await verification_node(state)

        assert "verification" in result["timing"]
        assert result["timing"]["verification"] >= 0

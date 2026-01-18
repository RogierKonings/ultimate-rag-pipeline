"""Tests for ClaimVerifier."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from workflow.verification import (
    Claim,
    ClaimVerifier,
    VerificationStatus,
)


@pytest.fixture
def mock_gateway():
    """Create a mock ModelGateway."""
    gateway = MagicMock()
    gateway.default_model = "test-model"
    gateway.chat_completion = AsyncMock()
    return gateway


@pytest.fixture
def sample_claim():
    """Create a sample claim."""
    return Claim(text="Python was released in 1991", claim_type="temporal")


@pytest.fixture
def sample_context():
    """Create sample context."""
    return """
    [1] Python is a high-level programming language created by Guido van Rossum.
    It was first released in 1991 and has since become one of the most popular
    programming languages in the world.
    """


class TestClaimVerifier:
    """Tests for ClaimVerifier."""

    @pytest.mark.asyncio
    async def test_verifies_supported_claim(
        self, mock_gateway, sample_claim, sample_context
    ):
        """Test verification of a supported claim."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"status": "supported", "evidence": "released in 1991", "reasoning": "Context confirms"}'
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        verifier = ClaimVerifier(mock_gateway)
        result = await verifier.verify(sample_claim, sample_context)

        assert result.status == VerificationStatus.SUPPORTED
        assert result.supporting_evidence == "released in 1991"
        assert result.claim_text == sample_claim.text

    @pytest.mark.asyncio
    async def test_verifies_partially_supported_claim(
        self, mock_gateway, sample_claim, sample_context
    ):
        """Test verification of a partially supported claim."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"status": "partially_supported", "evidence": "some evidence", "reasoning": "Partial match"}'
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        verifier = ClaimVerifier(mock_gateway)
        result = await verifier.verify(sample_claim, sample_context)

        assert result.status == VerificationStatus.PARTIALLY_SUPPORTED

    @pytest.mark.asyncio
    async def test_verifies_unsupported_claim(self, mock_gateway, sample_context):
        """Test verification of an unsupported claim."""
        unsupported_claim = Claim(
            text="Python was released in 2000", claim_type="temporal"
        )
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"status": "unsupported", "evidence": null, "reasoning": "Context says 1991, not 2000"}'
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        verifier = ClaimVerifier(mock_gateway)
        result = await verifier.verify(unsupported_claim, sample_context)

        assert result.status == VerificationStatus.UNSUPPORTED
        assert result.supporting_evidence is None

    @pytest.mark.asyncio
    async def test_handles_unverifiable_claim(self, mock_gateway, sample_context):
        """Test verification of an unverifiable claim."""
        claim = Claim(text="Python is the best language", claim_type="factual")
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"status": "unverifiable", "evidence": null, "reasoning": "Subjective claim"}'
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        verifier = ClaimVerifier(mock_gateway)
        result = await verifier.verify(claim, sample_context)

        assert result.status == VerificationStatus.UNVERIFIABLE

    @pytest.mark.asyncio
    async def test_handles_invalid_json(
        self, mock_gateway, sample_claim, sample_context
    ):
        """Test handling of invalid JSON response."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(message=MagicMock(content="Not valid JSON"))
        ]
        mock_gateway.chat_completion.return_value = mock_response

        verifier = ClaimVerifier(mock_gateway)
        result = await verifier.verify(sample_claim, sample_context)

        assert result.status == VerificationStatus.UNVERIFIABLE

    @pytest.mark.asyncio
    async def test_handles_invalid_status(
        self, mock_gateway, sample_claim, sample_context
    ):
        """Test handling of invalid status in response."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"status": "invalid_status", "evidence": null}'
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        verifier = ClaimVerifier(mock_gateway)
        result = await verifier.verify(sample_claim, sample_context)

        assert result.status == VerificationStatus.UNVERIFIABLE

    @pytest.mark.asyncio
    async def test_handles_gateway_exception(
        self, mock_gateway, sample_claim, sample_context
    ):
        """Test handling of gateway exception."""
        mock_gateway.chat_completion.side_effect = Exception("Gateway error")

        verifier = ClaimVerifier(mock_gateway)
        result = await verifier.verify(sample_claim, sample_context)

        assert result.status == VerificationStatus.UNVERIFIABLE

    @pytest.mark.asyncio
    async def test_handles_markdown_code_block(
        self, mock_gateway, sample_claim, sample_context
    ):
        """Test handling of JSON wrapped in markdown."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='```json\n{"status": "supported", "evidence": "test"}\n```'
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        verifier = ClaimVerifier(mock_gateway)
        result = await verifier.verify(sample_claim, sample_context)

        assert result.status == VerificationStatus.SUPPORTED

    @pytest.mark.asyncio
    async def test_handles_null_string_evidence(
        self, mock_gateway, sample_claim, sample_context
    ):
        """Test handling of 'null' string as evidence."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"status": "unsupported", "evidence": "null"}'
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        verifier = ClaimVerifier(mock_gateway)
        result = await verifier.verify(sample_claim, sample_context)

        assert result.supporting_evidence is None


class TestClaimVerifierVerifyAll:
    """Tests for ClaimVerifier.verify_all method."""

    @pytest.mark.asyncio
    async def test_verifies_all_claims_in_parallel(self, mock_gateway, sample_context):
        """Test that all claims are verified."""
        claims = [
            Claim(text="Claim 1", claim_type="factual"),
            Claim(text="Claim 2", claim_type="factual"),
            Claim(text="Claim 3", claim_type="factual"),
        ]

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content='{"status": "supported", "evidence": "test"}'
                )
            )
        ]
        mock_gateway.chat_completion.return_value = mock_response

        verifier = ClaimVerifier(mock_gateway)
        results = await verifier.verify_all(claims, sample_context)

        assert len(results) == 3
        assert all(r.status == VerificationStatus.SUPPORTED for r in results)

    @pytest.mark.asyncio
    async def test_handles_empty_claims_list(self, mock_gateway, sample_context):
        """Test handling of empty claims list."""
        verifier = ClaimVerifier(mock_gateway)
        results = await verifier.verify_all([], sample_context)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_handles_mixed_results(self, mock_gateway, sample_context):
        """Test handling of mixed verification results."""
        claims = [
            Claim(text="Supported claim", claim_type="factual"),
            Claim(text="Unsupported claim", claim_type="factual"),
        ]

        responses = [
            MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"status": "supported", "evidence": "test"}'
                        )
                    )
                ]
            ),
            MagicMock(
                choices=[
                    MagicMock(
                        message=MagicMock(
                            content='{"status": "unsupported", "evidence": null}'
                        )
                    )
                ]
            ),
        ]
        mock_gateway.chat_completion.side_effect = responses

        verifier = ClaimVerifier(mock_gateway)
        results = await verifier.verify_all(claims, sample_context)

        assert len(results) == 2
        assert results[0].status == VerificationStatus.SUPPORTED
        assert results[1].status == VerificationStatus.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_handles_exceptions_in_parallel(self, mock_gateway, sample_context):
        """Test handling of exceptions during parallel verification."""
        claims = [
            Claim(text="Good claim", claim_type="factual"),
            Claim(text="Bad claim", claim_type="factual"),
        ]

        def side_effect(*args, **kwargs):
            # First call succeeds, second fails
            if mock_gateway.chat_completion.call_count == 1:
                response = MagicMock()
                response.choices = [
                    MagicMock(
                        message=MagicMock(
                            content='{"status": "supported", "evidence": "test"}'
                        )
                    )
                ]
                return response
            else:
                raise Exception("Gateway error")

        mock_gateway.chat_completion.side_effect = side_effect

        verifier = ClaimVerifier(mock_gateway)
        results = await verifier.verify_all(claims, sample_context)

        assert len(results) == 2
        # One should be supported, the other unverifiable due to error
        statuses = {r.status for r in results}
        assert VerificationStatus.UNVERIFIABLE in statuses

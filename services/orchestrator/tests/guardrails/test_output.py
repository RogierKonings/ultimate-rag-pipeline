"""Tests for output guardrails."""

import pytest
from guardrails.models import GuardrailConfig, ViolationType
from guardrails.output import OutputGuardrail


class TestOutputGuardrail:
    """Tests for the OutputGuardrail class."""

    @pytest.fixture
    def guardrail(self):
        """Create an OutputGuardrail with default config."""
        return OutputGuardrail()

    @pytest.fixture
    def strict_guardrail(self):
        """Create an OutputGuardrail that blocks on harmful content."""
        config = GuardrailConfig(
            block_on_harmful_content=True,
        )
        return OutputGuardrail(config)

    @pytest.mark.asyncio
    async def test_valid_output_passes(self, guardrail):
        """Test that valid output passes all checks."""
        text = "The capital of France is Paris."
        result = await guardrail.check(text)

        assert result.passed is True
        assert len(result.violations) == 0
        assert result.processing_time_ms > 0

    @pytest.mark.asyncio
    async def test_length_violation(self, guardrail):
        """Test that overly long output is flagged but not blocked."""
        config = GuardrailConfig(max_output_length=50)
        guardrail = OutputGuardrail(config)

        text = "a" * 100
        result = await guardrail.check(text)

        # Length violations don't block, just truncate
        assert result.passed is True
        assert len(result.violations) == 1
        assert result.violations[0].type == ViolationType.CONTENT_TOO_LONG
        assert result.sanitized_content == "a" * 50

    @pytest.mark.asyncio
    async def test_harmful_content_detected(self, strict_guardrail):
        """Test that harmful content is detected and blocked."""
        text = "Here's how to kill yourself: first..."
        result = await strict_guardrail.check(text)

        assert result.passed is False
        assert len(result.violations) >= 1

        harmful_violation = next(
            (v for v in result.violations if v.type == ViolationType.HARMFUL_CONTENT),
            None,
        )
        assert harmful_violation is not None
        assert harmful_violation.severity in ["high", "critical"]

    @pytest.mark.asyncio
    async def test_harmful_content_not_blocked_when_disabled(self):
        """Test that harmful content is not detected when filter is disabled."""
        config = GuardrailConfig(enable_harmful_content_filter=False)
        guardrail = OutputGuardrail(config)

        text = "Here's how to kill yourself."
        result = await guardrail.check(text)

        harmful_violations = [
            v for v in result.violations if v.type == ViolationType.HARMFUL_CONTENT
        ]
        assert len(harmful_violations) == 0

    @pytest.mark.asyncio
    async def test_violence_content_detected(self, strict_guardrail):
        """Test that violence-related content is detected."""
        text = "I want to kill you!"
        result = await strict_guardrail.check(text)

        assert result.passed is False
        harmful_violation = next(
            (v for v in result.violations if v.type == ViolationType.HARMFUL_CONTENT),
            None,
        )
        assert harmful_violation is not None
        assert (
            "violence" in harmful_violation.description.lower()
            or harmful_violation.severity in ["high", "critical"]
        )

    @pytest.mark.asyncio
    async def test_processing_time_recorded(self, guardrail):
        """Test that processing time is recorded."""
        text = "This is a normal response."
        result = await guardrail.check(text)

        assert result.processing_time_ms > 0

    @pytest.mark.asyncio
    async def test_violation_location(self, strict_guardrail):
        """Test that violation location is recorded."""
        text = "Some text before. I want to kill you. Some text after."
        result = await strict_guardrail.check(text)

        harmful_violation = next(
            (v for v in result.violations if v.type == ViolationType.HARMFUL_CONTENT),
            None,
        )
        if harmful_violation:
            assert harmful_violation.location is not None
            # Location should be in format "start-end"
            assert "-" in harmful_violation.location


class TestOutputGuardrailSanitize:
    """Tests for the OutputGuardrail sanitize methods."""

    @pytest.fixture
    def guardrail(self):
        """Create an OutputGuardrail with default config."""
        return OutputGuardrail()

    def test_sanitize_harmful_content(self, guardrail):
        """Test sanitizing harmful content."""
        text = "Normal text. I want to kill you. More normal text."
        sanitized = guardrail.sanitize_harmful_content(text)

        assert "kill you" not in sanitized
        assert "[CONTENT_REMOVED]" in sanitized
        assert "Normal text" in sanitized

    def test_sanitize_no_harmful_content(self, guardrail):
        """Test sanitizing text without harmful content."""
        text = "This is a perfectly normal response."
        sanitized = guardrail.sanitize_harmful_content(text)

        assert sanitized == text

    def test_sanitize_empty_text(self, guardrail):
        """Test sanitizing empty text."""
        text = ""
        sanitized = guardrail.sanitize_harmful_content(text)

        assert sanitized == ""


class TestOutputGuardrailTruncate:
    """Tests for the OutputGuardrail truncate method."""

    def test_truncate_long_text(self):
        """Test truncating text that exceeds limit."""
        config = GuardrailConfig(max_output_length=50)
        guardrail = OutputGuardrail(config)

        text = "a" * 100
        truncated = guardrail.truncate(text)

        assert len(truncated) == 50

    def test_truncate_short_text(self):
        """Test truncating text that's within limit."""
        config = GuardrailConfig(max_output_length=100)
        guardrail = OutputGuardrail(config)

        text = "a" * 50
        truncated = guardrail.truncate(text)

        assert truncated == text

    def test_truncate_exact_limit(self):
        """Test truncating text that's exactly at limit."""
        config = GuardrailConfig(max_output_length=50)
        guardrail = OutputGuardrail(config)

        text = "a" * 50
        truncated = guardrail.truncate(text)

        assert truncated == text

    def test_truncate_empty_text(self):
        """Test truncating empty text."""
        guardrail = OutputGuardrail()

        text = ""
        truncated = guardrail.truncate(text)

        assert truncated == ""

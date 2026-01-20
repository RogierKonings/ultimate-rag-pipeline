"""Output guardrails for validating LLM responses."""

import time

from .detection import detect_harmful_content
from .models import GuardrailConfig, GuardrailResult, Violation, ViolationType


class OutputGuardrail:
    """Guardrail for validating LLM output.

    This class provides output validation including:
    - Response length limits
    - Harmful content filtering (basic keyword detection)
    """

    def __init__(self, config: GuardrailConfig | None = None):
        """Initialize the output guardrail.

        Args:
            config: Configuration for the guardrail. Uses defaults if not provided.
        """
        self.config = config or GuardrailConfig()

    async def check(self, text: str | None) -> GuardrailResult:
        """Check output text against all enabled guardrails.

        Args:
            text: The output text to validate. Can be None if LLM returned no response.

        Returns:
            GuardrailResult with pass/fail status and any violations found.
        """
        start_time = time.perf_counter()
        violations: list[Violation] = []
        sanitized_content: str | None = None

        # Handle None text - treat as empty response
        if text is None:
            text = ""

        # Check length
        if len(text) > self.config.max_output_length:
            violations.append(
                Violation(
                    type=ViolationType.CONTENT_TOO_LONG,
                    severity=self.config.length_severity,
                    description=f"Output exceeds maximum length of {self.config.max_output_length} characters",
                    location=f"0-{len(text)}",
                ),
            )
            # Truncate the content
            sanitized_content = text[: self.config.max_output_length]

        # Check for harmful content
        if self.config.enable_harmful_content_filter:
            harmful_matches = detect_harmful_content(text)
            for match in harmful_matches:
                category = match.details.get("category", "unknown") if match.details else "unknown"
                severity = (
                    match.details.get("severity", self.config.harmful_content_severity)
                    if match.details
                    else self.config.harmful_content_severity
                )
                violations.append(
                    Violation(
                        type=ViolationType.HARMFUL_CONTENT,
                        severity=severity,
                        description=f"Harmful content detected ({category}): '{match.matched_text}'",
                        location=f"{match.start}-{match.end}",
                    ),
                )

        # Determine if check passed based on config
        passed = self._determine_pass_status(violations)

        processing_time_ms = (time.perf_counter() - start_time) * 1000

        return GuardrailResult(
            passed=passed,
            violations=violations,
            sanitized_content=sanitized_content,
            processing_time_ms=processing_time_ms,
        )

    def _determine_pass_status(self, violations: list[Violation]) -> bool:
        """Determine if the guardrail check passed based on violations and config.

        Args:
            violations: List of violations found.

        Returns:
            True if the check passed, False otherwise.
        """
        if not violations:
            return True

        for violation in violations:
            # Length violations are warnings (content can be truncated)
            if violation.type == ViolationType.CONTENT_TOO_LONG:
                continue  # Don't fail on length, just truncate

            # Check harmful content blocking
            if (
                violation.type == ViolationType.HARMFUL_CONTENT
                and self.config.block_on_harmful_content
            ):
                return False

        return True

    def sanitize_harmful_content(self, text: str) -> str:
        """Sanitize harmful content from text by replacing with placeholders.

        Args:
            text: The text to sanitize.

        Returns:
            Text with harmful content replaced by placeholders.
        """
        harmful_matches = detect_harmful_content(text)

        # Sort matches by position in reverse order to replace from end to start
        sorted_matches = sorted(harmful_matches, key=lambda m: m.start, reverse=True)

        sanitized = text
        for match in sorted_matches:
            placeholder = "[CONTENT_REMOVED]"
            sanitized = sanitized[: match.start] + placeholder + sanitized[match.end :]

        return sanitized

    def truncate(self, text: str) -> str:
        """Truncate text to maximum output length.

        Args:
            text: The text to truncate.

        Returns:
            Truncated text if necessary, otherwise original text.
        """
        if len(text) > self.config.max_output_length:
            return text[: self.config.max_output_length]
        return text

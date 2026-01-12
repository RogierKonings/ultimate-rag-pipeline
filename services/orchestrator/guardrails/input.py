"""Input guardrails for validating user input."""

import time

from .detection import detect_injection, detect_pii
from .models import GuardrailConfig, GuardrailResult, Violation, ViolationType


class InputGuardrail:
    """Guardrail for validating user input.

    This class provides input validation including:
    - Length validation (configurable max)
    - Prompt injection detection
    - PII detection (email, phone, SSN patterns)
    """

    def __init__(self, config: GuardrailConfig | None = None):
        """Initialize the input guardrail.

        Args:
            config: Configuration for the guardrail. Uses defaults if not provided.
        """
        self.config = config or GuardrailConfig()

    async def check(self, text: str) -> GuardrailResult:
        """Check input text against all enabled guardrails.

        Args:
            text: The input text to validate.

        Returns:
            GuardrailResult with pass/fail status and any violations found.
        """
        start_time = time.perf_counter()
        violations: list[Violation] = []

        # Check length
        if len(text) > self.config.max_input_length:
            violations.append(
                Violation(
                    type=ViolationType.CONTENT_TOO_LONG,
                    severity=self.config.length_severity,
                    description=f"Input exceeds maximum length of {self.config.max_input_length} characters",
                    location=f"0-{len(text)}",
                ),
            )

        # Check for prompt injection
        if self.config.enable_injection_detection:
            injection_matches = detect_injection(text)
            for match in injection_matches:
                violations.append(
                    Violation(
                        type=ViolationType.INJECTION_ATTEMPT,
                        severity=self.config.injection_severity,
                        description=f"Potential prompt injection detected: '{match.matched_text}'",
                        location=f"{match.start}-{match.end}",
                    ),
                )

        # Check for PII
        if self.config.enable_pii_detection:
            pii_matches = detect_pii(text)
            for match in pii_matches:
                pii_type = match.details.get("pii_type", "unknown") if match.details else "unknown"
                violations.append(
                    Violation(
                        type=ViolationType.PII_DETECTED,
                        severity=self.config.pii_severity,
                        description=f"PII detected ({pii_type}): '{match.matched_text}'",
                        location=f"{match.start}-{match.end}",
                    ),
                )

        # Determine if check passed based on config
        passed = self._determine_pass_status(violations)

        processing_time_ms = (time.perf_counter() - start_time) * 1000

        return GuardrailResult(
            passed=passed,
            violations=violations,
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
            # Length violations always fail (can't proceed with truncated input safely)
            if violation.type == ViolationType.CONTENT_TOO_LONG:
                return False

            # Check injection blocking
            if violation.type == ViolationType.INJECTION_ATTEMPT and self.config.block_on_injection:
                return False

            # Check PII blocking
            if violation.type == ViolationType.PII_DETECTED and self.config.block_on_pii:
                return False

        return True

    def sanitize_pii(self, text: str) -> str:
        """Sanitize PII from text by replacing with placeholders.

        Args:
            text: The text to sanitize.

        Returns:
            Text with PII replaced by placeholders.
        """
        pii_matches = detect_pii(text)

        # Sort matches by position in reverse order to replace from end to start
        sorted_matches = sorted(pii_matches, key=lambda m: m.start, reverse=True)

        sanitized = text
        for match in sorted_matches:
            pii_type = match.details.get("pii_type", "PII") if match.details else "PII"
            placeholder = f"[{pii_type.upper()}_REDACTED]"
            sanitized = sanitized[: match.start] + placeholder + sanitized[match.end :]

        return sanitized

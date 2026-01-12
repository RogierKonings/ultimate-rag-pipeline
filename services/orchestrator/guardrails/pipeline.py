"""Guardrail pipeline combining input and output guardrails."""


from .input import InputGuardrail
from .models import GuardrailConfig, GuardrailResult
from .output import OutputGuardrail


class GuardrailPipeline:
    """Pipeline combining input and output guardrails.

    This class provides a unified interface for checking both input and output
    through their respective guardrails.
    """

    def __init__(self, config: GuardrailConfig | None = None):
        """Initialize the guardrail pipeline.

        Args:
            config: Configuration for all guardrails. Uses defaults if not provided.
        """
        self.config = config or GuardrailConfig()
        self.input_guardrail = InputGuardrail(self.config)
        self.output_guardrail = OutputGuardrail(self.config)

    async def check_input(self, text: str) -> GuardrailResult:
        """Check input text through input guardrails.

        This method validates user input for:
        - Length limits
        - Prompt injection attempts
        - PII detection

        Args:
            text: The input text to validate.

        Returns:
            GuardrailResult with pass/fail status and any violations found.
        """
        return await self.input_guardrail.check(text)

    async def check_output(self, text: str) -> GuardrailResult:
        """Check output text through output guardrails.

        This method validates LLM output for:
        - Response length limits
        - Harmful content

        Args:
            text: The output text to validate.

        Returns:
            GuardrailResult with pass/fail status and any violations found.
        """
        return await self.output_guardrail.check(text)

    def sanitize_input(self, text: str) -> str:
        """Sanitize PII from input text.

        Args:
            text: The input text to sanitize.

        Returns:
            Text with PII replaced by placeholders.
        """
        return self.input_guardrail.sanitize_pii(text)

    def sanitize_output(self, text: str) -> str:
        """Sanitize harmful content from output text.

        Args:
            text: The output text to sanitize.

        Returns:
            Text with harmful content replaced by placeholders.
        """
        return self.output_guardrail.sanitize_harmful_content(text)

    def truncate_output(self, text: str) -> str:
        """Truncate output text to maximum length.

        Args:
            text: The output text to truncate.

        Returns:
            Truncated text if necessary, otherwise original text.
        """
        return self.output_guardrail.truncate(text)

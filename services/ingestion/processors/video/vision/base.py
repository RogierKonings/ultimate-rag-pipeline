"""Base classes for Vision LLM providers.

This module defines the abstract base class and data models for vision
LLM integrations.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class VisionAnalysisResult:
    """Result of vision analysis on a frame.

    Attributes:
        success: Whether analysis succeeded.
        description: Generated scene description.
        objects: Key objects detected.
        actions: Actions or events detected.
        scene_type: Type of scene (presentation, outdoor, etc.).
        confidence: Confidence score (0-1).
        tokens_used: Number of tokens used.
        latency_ms: Processing latency in milliseconds.
        error: Error message if failed.
        raw_response: Raw response from the model.
    """

    success: bool
    description: str = ""
    objects: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    scene_type: str = ""
    confidence: float = 1.0
    tokens_used: int = 0
    latency_ms: float = 0.0
    error: str | None = None
    raw_response: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "description": self.description,
            "objects": self.objects,
            "actions": self.actions,
            "scene_type": self.scene_type,
            "confidence": self.confidence,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


# Default prompt for scene analysis
DEFAULT_SCENE_ANALYSIS_PROMPT = """Analyze this video frame and provide:
1. A concise description of the scene (2-3 sentences)
2. Key objects visible
3. Any actions or events occurring
4. The type of scene (presentation, outdoor, interview, etc.)

Focus on details useful for search and retrieval.
Respond in JSON format with keys: description, objects, actions, scene_type"""


class VisionLLMProvider(ABC):
    """Abstract base class for Vision LLM providers.

    Defines the interface for vision model integrations used to
    analyze video keyframes.

    Example:
        provider = OpenAIVisionProvider(api_key="...")
        result = await provider.analyze_image(
            image_path="/path/to/frame.jpg",
            prompt="Describe this scene",
        )
    """

    @abstractmethod
    async def analyze_image(
        self,
        image_path: str | Path,
        prompt: str | None = None,
    ) -> VisionAnalysisResult:
        """Analyze a single image.

        Args:
            image_path: Path to the image file.
            prompt: Optional custom prompt.

        Returns:
            VisionAnalysisResult with analysis.
        """

    @abstractmethod
    async def analyze_batch(
        self,
        image_paths: list[Path],
        prompt: str | None = None,
        max_concurrent: int = 5,
    ) -> list[VisionAnalysisResult]:
        """Analyze multiple images.

        Args:
            image_paths: List of image paths.
            prompt: Optional custom prompt.
            max_concurrent: Maximum concurrent requests.

        Returns:
            List of VisionAnalysisResult.
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Get the provider name."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Get the model name."""

    async def close(self) -> None:  # noqa: B027
        """Close any open connections.

        Override in subclasses that need cleanup.
        Default implementation does nothing.
        """

    def _encode_image_base64(self, image_path: Path) -> str:
        """Encode image to base64.

        Args:
            image_path: Path to image file.

        Returns:
            Base64 encoded string.
        """
        import base64

        with image_path.open("rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _get_image_mime_type(self, image_path: Path) -> str:
        """Get MIME type for image.

        Args:
            image_path: Path to image file.

        Returns:
            MIME type string.
        """
        suffix = image_path.suffix.lower()
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        return mime_types.get(suffix, "image/jpeg")

    def _parse_json_response(self, text: str) -> dict:
        """Parse JSON from response text.

        Args:
            text: Response text potentially containing JSON.

        Returns:
            Parsed dictionary or empty dict.
        """
        import json
        import re

        # Try to extract JSON from markdown code block
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if json_match:
            text = json_match.group(1)

        # Try direct JSON parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in text
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

        return {}

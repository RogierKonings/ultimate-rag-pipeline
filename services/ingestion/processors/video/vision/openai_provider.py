"""OpenAI Vision LLM provider.

This module provides the OpenAI GPT-4V/GPT-4o integration for
video frame analysis.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from processors.video.vision.base import (
    DEFAULT_SCENE_ANALYSIS_PROMPT,
    VisionAnalysisResult,
    VisionLLMProvider,
)

logger = logging.getLogger(__name__)


@dataclass
class OpenAIVisionConfig:
    """Configuration for OpenAI Vision provider.

    Attributes:
        api_key: OpenAI API key.
        model: Model to use (gpt-4o, gpt-4-vision-preview).
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.
        timeout_seconds: Request timeout.
        rpm_limit: Requests per minute limit.
    """

    api_key: str = ""
    model: str = "gpt-4o"
    max_tokens: int = 300
    temperature: float = 0.3
    timeout_seconds: float = 30.0
    rpm_limit: int = 60


class OpenAIVisionProvider(VisionLLMProvider):
    """OpenAI Vision LLM provider.

    Supports GPT-4V and GPT-4o for image analysis.

    Example:
        provider = OpenAIVisionProvider(
            config=OpenAIVisionConfig(api_key="sk-...")
        )
        result = await provider.analyze_image(
            image_path="/path/to/frame.jpg"
        )
    """

    def __init__(self, config: OpenAIVisionConfig | None = None):
        """Initialize OpenAI Vision provider.

        Args:
            config: Provider configuration.
        """
        self.config = config or OpenAIVisionConfig()
        self._client = None
        self._last_request_time = 0.0
        self._request_interval = 60.0 / max(self.config.rpm_limit, 1)

    async def _get_client(self):
        """Get or create OpenAI client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as e:
                raise ImportError(
                    "openai package not installed. Install with: pip install openai"
                ) from e

            api_key = self.config.api_key
            if not api_key:
                import os

                api_key = os.getenv("OPENAI_API_KEY", "")

            if not api_key:
                raise ValueError("OpenAI API key not configured")

            self._client = AsyncOpenAI(api_key=api_key)

        return self._client

    async def _rate_limit(self) -> None:
        """Apply rate limiting between requests."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._request_interval:
            await asyncio.sleep(self._request_interval - elapsed)
        self._last_request_time = time.time()

    async def analyze_image(
        self,
        image_path: str | Path,
        prompt: str | None = None,
    ) -> VisionAnalysisResult:
        """Analyze a single image using OpenAI Vision.

        Args:
            image_path: Path to the image file.
            prompt: Optional custom prompt.

        Returns:
            VisionAnalysisResult with analysis.
        """
        image_path = Path(image_path)

        if not image_path.exists():
            return VisionAnalysisResult(
                success=False,
                error=f"Image not found: {image_path}",
            )

        prompt = prompt or DEFAULT_SCENE_ANALYSIS_PROMPT
        start_time = time.time()

        try:
            await self._rate_limit()
            client = await self._get_client()

            # Encode image
            base64_image = self._encode_image_base64(image_path)
            mime_type = self._get_image_mime_type(image_path)

            # Build message
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{base64_image}",
                                "detail": "low",  # Use low detail for faster processing
                            },
                        },
                    ],
                }
            ]

            # Call API
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature,
                ),
                timeout=self.config.timeout_seconds,
            )

            latency_ms = (time.time() - start_time) * 1000
            content = response.choices[0].message.content or ""
            tokens_used = response.usage.total_tokens if response.usage else 0

            # Parse response
            parsed = self._parse_json_response(content)

            return VisionAnalysisResult(
                success=True,
                description=parsed.get("description", content),
                objects=parsed.get("objects", []),
                actions=parsed.get("actions", []),
                scene_type=parsed.get("scene_type", ""),
                tokens_used=tokens_used,
                latency_ms=latency_ms,
                raw_response={"content": content},
            )

        except TimeoutError:
            return VisionAnalysisResult(
                success=False,
                error="Request timed out",
                latency_ms=(time.time() - start_time) * 1000,
            )
        except Exception as e:
            logger.warning("OpenAI vision analysis failed: %s", e)
            return VisionAnalysisResult(
                success=False,
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000,
            )

    async def analyze_batch(
        self,
        image_paths: list[Path],
        prompt: str | None = None,
        max_concurrent: int = 5,
    ) -> list[VisionAnalysisResult]:
        """Analyze multiple images with concurrency control.

        Args:
            image_paths: List of image paths.
            prompt: Optional custom prompt.
            max_concurrent: Maximum concurrent requests.

        Returns:
            List of VisionAnalysisResult.
        """
        semaphore = asyncio.Semaphore(max_concurrent)

        async def analyze_with_semaphore(path: Path) -> VisionAnalysisResult:
            async with semaphore:
                return await self.analyze_image(path, prompt)

        tasks = [analyze_with_semaphore(path) for path in image_paths]
        results = await asyncio.gather(*tasks)

        return list(results)

    @property
    def provider_name(self) -> str:
        """Get the provider name."""
        return "openai"

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self.config.model

    async def close(self) -> None:
        """Close the client."""
        if self._client is not None:
            await self._client.close()
            self._client = None

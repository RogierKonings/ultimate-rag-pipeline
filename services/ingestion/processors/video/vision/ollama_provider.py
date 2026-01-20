"""Ollama Vision LLM provider.

This module provides the Ollama integration for local vision model
inference (LLaVA, Qwen-VL, etc.).
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
class OllamaVisionConfig:
    """Configuration for Ollama Vision provider.

    Attributes:
        base_url: Ollama API base URL.
        model: Model to use (llava, qwen-vl, etc.).
        timeout_seconds: Request timeout.
        num_ctx: Context window size.
        temperature: Sampling temperature.
    """

    base_url: str = "http://localhost:11434"
    model: str = "llava"
    timeout_seconds: float = 60.0
    num_ctx: int = 4096
    temperature: float = 0.3


class OllamaVisionProvider(VisionLLMProvider):
    """Ollama Vision LLM provider.

    Supports local vision models like LLaVA and Qwen-VL.

    Example:
        provider = OllamaVisionProvider(
            config=OllamaVisionConfig(model="llava")
        )
        result = await provider.analyze_image(
            image_path="/path/to/frame.jpg"
        )
    """

    def __init__(self, config: OllamaVisionConfig | None = None):
        """Initialize Ollama Vision provider.

        Args:
            config: Provider configuration.
        """
        self.config = config or OllamaVisionConfig()
        self._session = None

    async def _get_session(self):
        """Get or create HTTP session."""
        if self._session is None:
            import aiohttp

            self._session = aiohttp.ClientSession()
        return self._session

    async def analyze_image(
        self,
        image_path: str | Path,
        prompt: str | None = None,
    ) -> VisionAnalysisResult:
        """Analyze a single image using Ollama.

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
            session = await self._get_session()

            # Encode image
            base64_image = self._encode_image_base64(image_path)

            # Build request
            url = f"{self.config.base_url}/api/generate"
            payload = {
                "model": self.config.model,
                "prompt": prompt,
                "images": [base64_image],
                "stream": False,
                "options": {
                    "num_ctx": self.config.num_ctx,
                    "temperature": self.config.temperature,
                },
            }

            # Call API
            async with session.post(
                url,
                json=payload,
                timeout=self.config.timeout_seconds,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return VisionAnalysisResult(
                        success=False,
                        error=f"Ollama API error: {response.status} - {error_text}",
                        latency_ms=(time.time() - start_time) * 1000,
                    )

                data = await response.json()

            latency_ms = (time.time() - start_time) * 1000
            content = data.get("response", "")

            # Parse response
            parsed = self._parse_json_response(content)

            return VisionAnalysisResult(
                success=True,
                description=parsed.get("description", content),
                objects=parsed.get("objects", []),
                actions=parsed.get("actions", []),
                scene_type=parsed.get("scene_type", ""),
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
            logger.warning("Ollama vision analysis failed: %s", e)
            return VisionAnalysisResult(
                success=False,
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000,
            )

    async def analyze_batch(
        self,
        image_paths: list[Path],
        prompt: str | None = None,
        max_concurrent: int = 2,  # Lower default for local inference
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
        return "ollama"

    @property
    def model_name(self) -> str:
        """Get the model name."""
        return self.config.model

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session is not None:
            await self._session.close()
            self._session = None

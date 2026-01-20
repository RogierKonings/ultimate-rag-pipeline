"""Vision analyzer service for video keyframe analysis.

This module provides the VisionAnalyzer class that orchestrates
batch analysis of video keyframes using Vision LLM providers.
"""

import asyncio
import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from processors.video.exceptions import VisionAnalysisError
from processors.video.keyframe_extractor import ExtractedKeyframe
from processors.video.vision.base import VisionAnalysisResult, VisionLLMProvider
from processors.video.vision.ollama_provider import OllamaVisionConfig, OllamaVisionProvider
from processors.video.vision.openai_provider import OpenAIVisionConfig, OpenAIVisionProvider

logger = logging.getLogger(__name__)

# Progress callback type
ProgressCallback = Callable[[int, int, str], None]


@dataclass
class VisionAnalyzerConfig:
    """Configuration for vision analyzer.

    Attributes:
        provider: Vision provider name (openai, ollama).
        max_concurrent: Maximum concurrent analysis requests.
        retry_count: Number of retries for failed requests.
        retry_delay_seconds: Delay between retries.
        cache_enabled: Enable response caching.
        cache_ttl_hours: Cache TTL in hours.
    """

    provider: str = "openai"
    max_concurrent: int = 5
    retry_count: int = 3
    retry_delay_seconds: float = 2.0
    cache_enabled: bool = True
    cache_ttl_hours: int = 24

    # Provider-specific configs
    openai_config: OpenAIVisionConfig = field(default_factory=OpenAIVisionConfig)
    ollama_config: OllamaVisionConfig = field(default_factory=OllamaVisionConfig)


@dataclass
class KeyframeAnalysis:
    """Analysis result for a keyframe.

    Attributes:
        keyframe: The analyzed keyframe.
        result: Vision analysis result.
        from_cache: Whether result was from cache.
    """

    keyframe: ExtractedKeyframe
    result: VisionAnalysisResult
    from_cache: bool = False


class VisionAnalyzer:
    """Orchestrates batch analysis of video keyframes.

    Manages provider selection, rate limiting, retries, and caching
    for efficient keyframe analysis.

    Example:
        analyzer = VisionAnalyzer(
            config=VisionAnalyzerConfig(provider="openai")
        )
        results = await analyzer.analyze_keyframes(
            keyframes=extracted_keyframes,
            progress_callback=update_progress,
        )
    """

    def __init__(
        self,
        config: VisionAnalyzerConfig | None = None,
        cache_client=None,
    ):
        """Initialize vision analyzer.

        Args:
            config: Analyzer configuration.
            cache_client: Optional Redis client for caching.
        """
        self.config = config or VisionAnalyzerConfig()
        self._provider: VisionLLMProvider | None = None
        self._cache_client = cache_client

    def _get_provider(self) -> VisionLLMProvider:
        """Get or create the vision provider."""
        if self._provider is None:
            if self.config.provider == "openai":
                self._provider = OpenAIVisionProvider(self.config.openai_config)
            elif self.config.provider == "ollama":
                self._provider = OllamaVisionProvider(self.config.ollama_config)
            else:
                raise VisionAnalysisError(f"Unknown provider: {self.config.provider}")
        return self._provider

    async def analyze_keyframes(
        self,
        keyframes: list[ExtractedKeyframe],
        prompt: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> list[KeyframeAnalysis]:
        """Analyze a list of keyframes.

        Args:
            keyframes: List of extracted keyframes.
            prompt: Optional custom analysis prompt.
            progress_callback: Optional progress callback (current, total, message).

        Returns:
            List of KeyframeAnalysis results.
        """
        if not keyframes:
            return []

        total = len(keyframes)
        logger.info("Analyzing %d keyframes with provider=%s", total, self.config.provider)

        provider = self._get_provider()
        semaphore = asyncio.Semaphore(self.config.max_concurrent)
        results: list[KeyframeAnalysis] = []
        completed = 0

        async def analyze_single(keyframe: ExtractedKeyframe) -> KeyframeAnalysis:
            nonlocal completed

            async with semaphore:
                # Check cache first
                if self.config.cache_enabled and self._cache_client:
                    cached = await self._get_cached_result(keyframe.image_path)
                    if cached:
                        completed += 1
                        if progress_callback:
                            progress_callback(
                                completed, total, f"Analyzing frame {completed}/{total} (cached)"
                            )
                        return KeyframeAnalysis(
                            keyframe=keyframe,
                            result=cached,
                            from_cache=True,
                        )

                # Analyze with retry
                result = await self._analyze_with_retry(
                    provider=provider,
                    image_path=keyframe.image_path,
                    prompt=prompt,
                )

                # Cache successful results
                if result.success and self.config.cache_enabled and self._cache_client:
                    await self._cache_result(keyframe.image_path, result)

                completed += 1
                if progress_callback:
                    progress_callback(completed, total, f"Analyzing frame {completed}/{total}")

                return KeyframeAnalysis(
                    keyframe=keyframe,
                    result=result,
                    from_cache=False,
                )

        # Process all keyframes
        tasks = [analyze_single(kf) for kf in keyframes]
        results = await asyncio.gather(*tasks)

        # Log summary
        success_count = sum(1 for r in results if r.result.success)
        cache_count = sum(1 for r in results if r.from_cache)
        logger.info(
            "Vision analysis complete: %d/%d successful, %d from cache",
            success_count,
            total,
            cache_count,
        )

        return list(results)

    async def _analyze_with_retry(
        self,
        provider: VisionLLMProvider,
        image_path: Path,
        prompt: str | None,
    ) -> VisionAnalysisResult:
        """Analyze image with retry logic.

        Args:
            provider: Vision provider.
            image_path: Path to image.
            prompt: Analysis prompt.

        Returns:
            VisionAnalysisResult.
        """
        last_error = None

        for attempt in range(self.config.retry_count):
            result = await provider.analyze_image(image_path, prompt)

            if result.success:
                return result

            last_error = result.error
            logger.warning(
                "Vision analysis attempt %d failed: %s",
                attempt + 1,
                last_error,
            )

            if attempt < self.config.retry_count - 1:
                delay = self.config.retry_delay_seconds * (2**attempt)
                await asyncio.sleep(delay)

        return VisionAnalysisResult(
            success=False,
            error=f"Failed after {self.config.retry_count} attempts: {last_error}",
        )

    def _compute_image_hash(self, image_path: Path) -> str:
        """Compute hash for cache key.

        Args:
            image_path: Path to image.

        Returns:
            SHA-256 hash string.
        """
        with image_path.open("rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    async def _get_cached_result(self, image_path: Path) -> VisionAnalysisResult | None:
        """Get cached analysis result.

        Args:
            image_path: Path to image.

        Returns:
            Cached result or None.
        """
        if not self._cache_client:
            return None

        try:
            import json

            image_hash = self._compute_image_hash(image_path)
            cache_key = f"vision:analysis:{image_hash}"

            cached = await self._cache_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                return VisionAnalysisResult(
                    success=data.get("success", True),
                    description=data.get("description", ""),
                    objects=data.get("objects", []),
                    actions=data.get("actions", []),
                    scene_type=data.get("scene_type", ""),
                )
        except Exception as e:
            logger.debug("Cache read failed: %s", e)

        return None

    async def _cache_result(
        self,
        image_path: Path,
        result: VisionAnalysisResult,
    ) -> None:
        """Cache analysis result.

        Args:
            image_path: Path to image.
            result: Analysis result to cache.
        """
        if not self._cache_client:
            return

        try:
            import json

            image_hash = self._compute_image_hash(image_path)
            cache_key = f"vision:analysis:{image_hash}"

            data = {
                "success": result.success,
                "description": result.description,
                "objects": result.objects,
                "actions": result.actions,
                "scene_type": result.scene_type,
            }

            ttl_seconds = self.config.cache_ttl_hours * 3600
            await self._cache_client.setex(cache_key, ttl_seconds, json.dumps(data))
        except Exception as e:
            logger.debug("Cache write failed: %s", e)

    async def analyze_for_video(
        self,
        keyframes: list[ExtractedKeyframe],
        video_id: UUID,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[int, str]:
        """Analyze keyframes and return descriptions by frame index.

        Args:
            keyframes: List of extracted keyframes.
            video_id: Video identifier for logging.
            progress_callback: Optional progress callback.

        Returns:
            Dict mapping frame_index to description.
        """
        results = await self.analyze_keyframes(
            keyframes=keyframes,
            progress_callback=progress_callback,
        )

        descriptions = {}
        for analysis in results:
            if analysis.result.success:
                descriptions[analysis.keyframe.frame_index] = analysis.result.description

        logger.info(
            "Generated %d scene descriptions for video_id=%s",
            len(descriptions),
            video_id,
        )

        return descriptions

    async def close(self) -> None:
        """Close provider connections."""
        if self._provider is not None:
            await self._provider.close()
            self._provider = None

# US-9.4: Visual Scene Understanding

> **Story ID:** US-9.4
> **Epic:** Video RAG Pipeline
> **Priority:** High
> **Estimated Effort:** 3 days
> **Dependencies:** US-9.3 (Keyframe Extraction)

## User Story

**As a** system
**I want** to generate descriptions of visual content
**So that** visual events are searchable by text

## Context

This story implements vision-based content understanding using Vision LLMs (GPT-4V, Claude Vision, LLaVA, Qwen-VL). Each keyframe is analyzed to generate descriptive text about the visual content—objects, actions, settings, text overlays, and events. These descriptions become part of the searchable content, enabling users to find video moments based on what's visually happening.

## Technical Requirements

### Vision LLM Service

```python
# processors/video/vision_llm.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol
from abc import ABC, abstractmethod
import base64
import logging
import asyncio

logger = logging.getLogger(__name__)

@dataclass
class VisionAnalysisResult:
    success: bool
    description: str = ""
    objects: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    scene_type: str = ""
    error: str | None = None
    tokens_used: int = 0

@dataclass
class VisionLLMConfig:
    provider: Literal["openai", "anthropic", "ollama"] = "openai"
    model: str = "gpt-4-vision-preview"
    max_tokens: int = 300
    temperature: float = 0.1
    timeout_seconds: int = 30
    max_retries: int = 3
    retry_delay_seconds: float = 1.0

    # Rate limiting
    requests_per_minute: int = 20
    batch_size: int = 5

class VisionLLMProvider(ABC):
    """Abstract base for Vision LLM providers."""

    @abstractmethod
    async def analyze_image(
        self,
        image_path: Path,
        prompt: str
    ) -> VisionAnalysisResult:
        pass

class OpenAIVisionProvider(VisionLLMProvider):
    """OpenAI GPT-4 Vision implementation."""

    def __init__(self, config: VisionLLMConfig, api_key: str):
        self.config = config
        self.api_key = api_key
        self._client = None

    async def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=self.api_key)
        return self._client

    async def analyze_image(
        self,
        image_path: Path,
        prompt: str
    ) -> VisionAnalysisResult:
        client = await self._get_client()

        # Encode image
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_data}",
                                        "detail": "low"
                                    }
                                }
                            ]
                        }
                    ],
                    max_tokens=self.config.max_tokens,
                    temperature=self.config.temperature
                ),
                timeout=self.config.timeout_seconds
            )

            content = response.choices[0].message.content
            return self._parse_response(content, response.usage.total_tokens)

        except asyncio.TimeoutError:
            return VisionAnalysisResult(success=False, error="Request timed out")
        except Exception as e:
            return VisionAnalysisResult(success=False, error=str(e))

    def _parse_response(self, content: str, tokens: int) -> VisionAnalysisResult:
        """Parse structured response from LLM."""
        # Simple extraction - could use structured output for better parsing
        objects = []
        actions = []
        scene_type = ""

        lines = content.split("\n")
        for line in lines:
            line_lower = line.lower()
            if "objects:" in line_lower or "visible:" in line_lower:
                objects = [o.strip() for o in line.split(":", 1)[1].split(",")]
            elif "actions:" in line_lower or "happening:" in line_lower:
                actions = [a.strip() for a in line.split(":", 1)[1].split(",")]
            elif "scene:" in line_lower or "setting:" in line_lower:
                scene_type = line.split(":", 1)[1].strip()

        return VisionAnalysisResult(
            success=True,
            description=content,
            objects=objects,
            actions=actions,
            scene_type=scene_type,
            tokens_used=tokens
        )

class AnthropicVisionProvider(VisionLLMProvider):
    """Anthropic Claude Vision implementation."""

    def __init__(self, config: VisionLLMConfig, api_key: str):
        self.config = config
        self.api_key = api_key
        self._client = None

    async def _get_client(self):
        if self._client is None:
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(api_key=self.api_key)
        return self._client

    async def analyze_image(
        self,
        image_path: Path,
        prompt: str
    ) -> VisionAnalysisResult:
        client = await self._get_client()

        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        try:
            response = await asyncio.wait_for(
                client.messages.create(
                    model=self.config.model or "claude-3-sonnet-20240229",
                    max_tokens=self.config.max_tokens,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/jpeg",
                                        "data": image_data
                                    }
                                },
                                {"type": "text", "text": prompt}
                            ]
                        }
                    ]
                ),
                timeout=self.config.timeout_seconds
            )

            content = response.content[0].text
            return VisionAnalysisResult(
                success=True,
                description=content,
                tokens_used=response.usage.input_tokens + response.usage.output_tokens
            )

        except Exception as e:
            return VisionAnalysisResult(success=False, error=str(e))

class OllamaVisionProvider(VisionLLMProvider):
    """Local Ollama Vision model implementation."""

    def __init__(self, config: VisionLLMConfig, base_url: str = "http://localhost:11434"):
        self.config = config
        self.base_url = base_url

    async def analyze_image(
        self,
        image_path: Path,
        prompt: str
    ) -> VisionAnalysisResult:
        import httpx

        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode()

        try:
            async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.config.model or "llava",
                        "prompt": prompt,
                        "images": [image_data],
                        "stream": False
                    }
                )
                response.raise_for_status()
                data = response.json()

                return VisionAnalysisResult(
                    success=True,
                    description=data["response"]
                )

        except Exception as e:
            return VisionAnalysisResult(success=False, error=str(e))
```

### Vision Analysis Service

```python
# processors/video/vision_analyzer.py
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
import asyncio
import logging
from typing import Callable

logger = logging.getLogger(__name__)

SCENE_ANALYSIS_PROMPT = """Analyze this video frame and describe what you see.

Provide a concise description (2-3 sentences) covering:
1. Main subjects/objects visible
2. Actions or events happening
3. Setting/environment
4. Any visible text or graphics

Format your response as:
Description: [your description]
Objects: [comma-separated list of main objects]
Actions: [comma-separated list of actions if any]
Scene: [brief scene type, e.g., "outdoor park", "office meeting", "sports event"]

Be factual and specific. Focus on what's clearly visible."""

@dataclass
class BatchAnalysisResult:
    successful: int
    failed: int
    results: dict[int, VisionAnalysisResult]  # frame_index -> result
    total_tokens: int

class VisionAnalyzer:
    """Orchestrates vision analysis across multiple keyframes."""

    def __init__(
        self,
        provider: VisionLLMProvider,
        config: VisionLLMConfig
    ):
        self.provider = provider
        self.config = config
        self._semaphore = asyncio.Semaphore(config.batch_size)
        self._rate_limiter = asyncio.Semaphore(config.requests_per_minute)

    async def analyze_keyframes(
        self,
        keyframes: list[tuple[int, Path]],  # (frame_index, image_path)
        progress_callback: Callable[[int, int], None] | None = None
    ) -> BatchAnalysisResult:
        """
        Analyze multiple keyframes with rate limiting.

        Args:
            keyframes: List of (frame_index, image_path) tuples
            progress_callback: Called with (completed, total) counts

        Returns:
            BatchAnalysisResult with results keyed by frame index
        """
        results = {}
        total_tokens = 0
        completed = 0

        async def analyze_one(frame_index: int, image_path: Path):
            nonlocal completed, total_tokens

            async with self._semaphore:
                async with self._rate_limiter:
                    result = await self._analyze_with_retry(image_path)
                    results[frame_index] = result
                    total_tokens += result.tokens_used

                    completed += 1
                    if progress_callback:
                        progress_callback(completed, len(keyframes))

                    # Rate limiting delay
                    await asyncio.sleep(60 / self.config.requests_per_minute)

        # Process all keyframes
        tasks = [
            analyze_one(idx, path)
            for idx, path in keyframes
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

        successful = sum(1 for r in results.values() if r.success)
        failed = len(keyframes) - successful

        logger.info(f"Vision analysis complete: {successful} succeeded, {failed} failed")

        return BatchAnalysisResult(
            successful=successful,
            failed=failed,
            results=results,
            total_tokens=total_tokens
        )

    async def _analyze_with_retry(self, image_path: Path) -> VisionAnalysisResult:
        """Analyze with exponential backoff retry."""
        last_error = None

        for attempt in range(self.config.max_retries):
            result = await self.provider.analyze_image(
                image_path,
                SCENE_ANALYSIS_PROMPT
            )

            if result.success:
                return result

            last_error = result.error
            delay = self.config.retry_delay_seconds * (2 ** attempt)
            logger.warning(f"Vision analysis failed (attempt {attempt + 1}): {last_error}")
            await asyncio.sleep(delay)

        return VisionAnalysisResult(
            success=False,
            error=f"Failed after {self.config.max_retries} attempts: {last_error}"
        )
```

### Scene Description Storage

```python
# processors/video/scene_storage.py
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update

class SceneDescriptionStorage:
    """Updates keyframe records with scene descriptions."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def store_descriptions(
        self,
        video_id: UUID,
        descriptions: dict[int, "VisionAnalysisResult"]
    ) -> int:
        """Store scene descriptions for keyframes."""
        updated = 0

        for frame_index, result in descriptions.items():
            if not result.success:
                continue

            await self.session.execute(
                update(VideoKeyframe)
                .where(VideoKeyframe.video_id == video_id)
                .where(VideoKeyframe.frame_index == frame_index)
                .values(
                    scene_description=result.description,
                    scene_objects=result.objects,
                    scene_actions=result.actions,
                    scene_type=result.scene_type
                )
            )
            updated += 1

        await self.session.commit()
        return updated
```

### Extended Database Schema

```sql
-- Add columns to video_keyframes table
ALTER TABLE video_keyframes ADD COLUMN scene_description TEXT;
ALTER TABLE video_keyframes ADD COLUMN scene_objects TEXT[];
ALTER TABLE video_keyframes ADD COLUMN scene_actions TEXT[];
ALTER TABLE video_keyframes ADD COLUMN scene_type VARCHAR(100);
ALTER TABLE video_keyframes ADD COLUMN vision_analysis_status VARCHAR(50);
ALTER TABLE video_keyframes ADD COLUMN vision_tokens_used INTEGER;
```

### Pipeline Integration

```python
# In VideoProcessingPipeline

async def _run_visual_analysis_stage(
    self,
    keyframes: list["ExtractedKeyframe"]
) -> dict[int, VisionAnalysisResult]:
    """Analyze keyframes with Vision LLM."""
    if not self.options.get("extract_scenes", True):
        logger.info("Visual analysis disabled, skipping")
        return {}

    await self._update_progress("analyzing_visuals", 0)

    # Prepare keyframes for analysis
    keyframe_inputs = [
        (kf.frame_index, kf.image_path)
        for kf in keyframes
    ]

    # Create provider based on config
    provider = self._create_vision_provider()
    analyzer = VisionAnalyzer(provider, self.vision_config)

    # Analyze with progress updates
    result = await analyzer.analyze_keyframes(
        keyframe_inputs,
        progress_callback=lambda done, total: self._update_progress(
            "analyzing_visuals",
            int(done / total * 100)
        )
    )

    # Store descriptions
    await self.scene_storage.store_descriptions(
        self.video_id,
        result.results
    )

    await self._update_progress("analyzing_visuals", 100)

    return result.results

def _create_vision_provider(self) -> VisionLLMProvider:
    """Factory for vision providers."""
    provider_type = self.vision_config.provider

    if provider_type == "openai":
        return OpenAIVisionProvider(self.vision_config, self.openai_api_key)
    elif provider_type == "anthropic":
        return AnthropicVisionProvider(self.vision_config, self.anthropic_api_key)
    elif provider_type == "ollama":
        return OllamaVisionProvider(self.vision_config, self.ollama_url)
    else:
        raise ValueError(f"Unknown vision provider: {provider_type}")
```

### Caching

```python
# processors/video/vision_cache.py
from pathlib import Path
import hashlib
import json

class VisionResponseCache:
    """Caches vision LLM responses to avoid re-processing."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_key(self, image_path: Path) -> str:
        """Generate cache key from image content hash."""
        with open(image_path, "rb") as f:
            content_hash = hashlib.md5(f.read()).hexdigest()
        return content_hash

    async def get(self, image_path: Path) -> VisionAnalysisResult | None:
        """Get cached result if available."""
        cache_key = self._get_cache_key(image_path)
        cache_file = self.cache_dir / f"{cache_key}.json"

        if cache_file.exists():
            with open(cache_file) as f:
                data = json.load(f)
                return VisionAnalysisResult(**data)
        return None

    async def set(self, image_path: Path, result: VisionAnalysisResult):
        """Cache a result."""
        cache_key = self._get_cache_key(image_path)
        cache_file = self.cache_dir / f"{cache_key}.json"

        with open(cache_file, "w") as f:
            json.dump({
                "success": result.success,
                "description": result.description,
                "objects": result.objects,
                "actions": result.actions,
                "scene_type": result.scene_type,
                "tokens_used": result.tokens_used
            }, f)
```

## Configuration

```python
class VisionConfig(BaseSettings):
    vision_provider: str = "openai"
    vision_model: str = "gpt-4-vision-preview"
    vision_max_tokens: int = 300
    vision_requests_per_minute: int = 20
    vision_batch_size: int = 5
    vision_timeout_seconds: int = 30

    class Config:
        env_prefix = "VISION_"
```

## Cost Considerations

| Provider | Model | Cost per Image | Notes |
|----------|-------|----------------|-------|
| OpenAI | gpt-4-vision-preview | ~$0.01-0.03 | Low detail mode |
| OpenAI | gpt-4o | ~$0.005-0.02 | More efficient |
| Anthropic | claude-3-sonnet | ~$0.01-0.02 | Good balance |
| Ollama | llava | Free (local) | Requires GPU |

For a 30-minute video with ~360 keyframes:
- OpenAI GPT-4V: ~$3.60-10.80
- Local LLaVA: $0 (compute cost only)

## Acceptance Criteria

- [ ] Send keyframes to Vision LLM (GPT-4V, LLaVA, or Qwen-VL)
- [ ] Generate descriptive text for each scene segment
- [ ] Identify key actions, objects, and events
- [ ] Handle Vision LLM rate limits and errors
- [ ] Support configurable Vision LLM provider
- [ ] Cache Vision LLM responses

## Testing Requirements

```python
class TestVisionAnalyzer:
    @pytest.mark.asyncio
    async def test_analyzes_single_image(self, sample_keyframe):
        provider = MockVisionProvider()
        analyzer = VisionAnalyzer(provider, VisionLLMConfig())

        results = await analyzer.analyze_keyframes([(0, sample_keyframe)])

        assert results.successful == 1
        assert 0 in results.results
        assert results.results[0].description

    @pytest.mark.asyncio
    async def test_handles_rate_limiting(self, keyframes_batch):
        config = VisionLLMConfig(requests_per_minute=10, batch_size=2)
        provider = MockVisionProvider()
        analyzer = VisionAnalyzer(provider, config)

        start = time.time()
        results = await analyzer.analyze_keyframes(keyframes_batch)
        duration = time.time() - start

        # Should take at least 6 seconds for 10 images at 10/min
        assert duration >= 5

    @pytest.mark.asyncio
    async def test_retries_on_failure(self, sample_keyframe):
        provider = FailingThenSucceedingProvider(fail_count=2)
        config = VisionLLMConfig(max_retries=3)
        analyzer = VisionAnalyzer(provider, config)

        results = await analyzer.analyze_keyframes([(0, sample_keyframe)])

        assert results.successful == 1

    @pytest.mark.asyncio
    async def test_caches_responses(self, sample_keyframe, tmp_path):
        cache = VisionResponseCache(tmp_path)
        provider = MockVisionProvider()

        # First call - should hit provider
        result1 = await provider.analyze_image(sample_keyframe, "test")
        await cache.set(sample_keyframe, result1)

        # Second call - should hit cache
        cached = await cache.get(sample_keyframe)
        assert cached is not None
        assert cached.description == result1.description

class TestOpenAIProvider:
    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_openai_analysis(self, sample_keyframe, openai_api_key):
        config = VisionLLMConfig(provider="openai")
        provider = OpenAIVisionProvider(config, openai_api_key)

        result = await provider.analyze_image(sample_keyframe, SCENE_ANALYSIS_PROMPT)

        assert result.success
        assert len(result.description) > 50
```

## Dependencies

```
openai>=1.0.0
anthropic>=0.18.0
httpx>=0.25.0
```

## Definition of Done

- [ ] OpenAI GPT-4V integration working
- [ ] Anthropic Claude Vision integration working
- [ ] Ollama local model integration working
- [ ] Rate limiting preventing API throttling
- [ ] Retry logic handling transient failures
- [ ] Response caching reducing costs
- [ ] Scene descriptions stored in database
- [ ] >90% test coverage

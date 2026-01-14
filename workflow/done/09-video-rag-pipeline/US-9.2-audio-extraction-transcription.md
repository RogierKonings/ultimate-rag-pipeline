# US-9.2: Audio Extraction and Transcription

> **Story ID:** US-9.2
> **Epic:** Video RAG Pipeline
> **Priority:** Critical
> **Estimated Effort:** 3 days
> **Dependencies:** US-9.1 (Video Upload)

## User Story

**As a** system
**I want** to extract and transcribe audio from videos
**So that** spoken content is searchable

## Context

This story implements the speech-to-text pipeline for video content. Audio is extracted using FFmpeg and transcribed using Whisper (or faster-whisper for better performance). The transcription produces word-level or segment-level timestamps that align with video timecodes, enabling precise retrieval of spoken content.

## Technical Requirements

### Audio Extractor

```python
# processors/video/audio_extractor.py
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
import asyncio
import logging

logger = logging.getLogger(__name__)

@dataclass
class AudioExtractionConfig:
    output_format: str = "wav"
    sample_rate: int = 16000  # Whisper's expected rate
    channels: int = 1  # Mono
    codec: str = "pcm_s16le"

@dataclass
class AudioExtractionResult:
    success: bool
    audio_path: Path | None = None
    duration_seconds: float | None = None
    error: str | None = None

class AudioExtractor:
    """Extracts audio track from video files using FFmpeg."""

    def __init__(self, config: AudioExtractionConfig = None):
        self.config = config or AudioExtractionConfig()

    async def extract(
        self,
        video_path: Path,
        output_path: Path
    ) -> AudioExtractionResult:
        """
        Extract audio from video file.

        Args:
            video_path: Path to source video
            output_path: Path for output audio file

        Returns:
            AudioExtractionResult with status and path
        """
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vn",  # No video
            "-acodec", self.config.codec,
            "-ar", str(self.config.sample_rate),
            "-ac", str(self.config.channels),
            "-y",  # Overwrite
            str(output_path)
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await proc.communicate()

            if proc.returncode != 0:
                return AudioExtractionResult(
                    success=False,
                    error=f"FFmpeg failed: {stderr.decode()}"
                )

            # Get duration
            duration = await self._get_duration(output_path)

            logger.info(f"Extracted audio: {output_path} ({duration:.1f}s)")

            return AudioExtractionResult(
                success=True,
                audio_path=output_path,
                duration_seconds=duration
            )

        except Exception as e:
            logger.error(f"Audio extraction failed: {e}")
            return AudioExtractionResult(success=False, error=str(e))

    async def _get_duration(self, audio_path: Path) -> float:
        """Get audio duration using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip())

    async def check_has_audio(self, video_path: Path) -> bool:
        """Check if video has an audio stream."""
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(video_path)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return bool(stdout.decode().strip())
```

### Whisper Transcription Service

```python
# processors/video/transcription.py
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
import logging

logger = logging.getLogger(__name__)

@dataclass
class TranscriptSegment:
    """A segment of transcribed speech."""
    start_ms: int
    end_ms: int
    text: str
    confidence: float = 1.0
    words: list[dict] = field(default_factory=list)  # Word-level timestamps

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

@dataclass
class TranscriptionResult:
    success: bool
    segments: list[TranscriptSegment] = field(default_factory=list)
    full_text: str = ""
    language: str | None = None
    language_confidence: float = 0.0
    error: str | None = None
    processing_time_seconds: float = 0.0

@dataclass
class TranscriptionConfig:
    model: Literal["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"] = "base"
    device: Literal["cpu", "cuda"] = "cuda"
    compute_type: Literal["float16", "float32", "int8"] = "float16"
    language: str | None = None  # None = auto-detect
    word_timestamps: bool = True
    vad_filter: bool = True  # Voice activity detection
    vad_parameters: dict = field(default_factory=lambda: {
        "threshold": 0.5,
        "min_speech_duration_ms": 250,
        "min_silence_duration_ms": 100
    })

class WhisperTranscriber:
    """Transcribes audio using faster-whisper."""

    def __init__(self, config: TranscriptionConfig = None):
        self.config = config or TranscriptionConfig()
        self._model = None

    async def initialize(self):
        """Load the Whisper model."""
        from faster_whisper import WhisperModel

        logger.info(f"Loading Whisper model: {self.config.model}")
        self._model = WhisperModel(
            self.config.model,
            device=self.config.device,
            compute_type=self.config.compute_type
        )
        logger.info("Whisper model loaded")

    async def transcribe(self, audio_path: Path) -> TranscriptionResult:
        """
        Transcribe audio file to text with timestamps.

        Args:
            audio_path: Path to audio file (WAV recommended)

        Returns:
            TranscriptionResult with segments and timestamps
        """
        import time

        if self._model is None:
            await self.initialize()

        start_time = time.time()

        try:
            segments_iter, info = self._model.transcribe(
                str(audio_path),
                language=self.config.language,
                word_timestamps=self.config.word_timestamps,
                vad_filter=self.config.vad_filter,
                vad_parameters=self.config.vad_parameters if self.config.vad_filter else None
            )

            segments = []
            full_text_parts = []

            for segment in segments_iter:
                words = []
                if self.config.word_timestamps and segment.words:
                    words = [
                        {
                            "word": w.word,
                            "start_ms": int(w.start * 1000),
                            "end_ms": int(w.end * 1000),
                            "probability": w.probability
                        }
                        for w in segment.words
                    ]

                transcript_segment = TranscriptSegment(
                    start_ms=int(segment.start * 1000),
                    end_ms=int(segment.end * 1000),
                    text=segment.text.strip(),
                    confidence=segment.avg_logprob if hasattr(segment, 'avg_logprob') else 1.0,
                    words=words
                )
                segments.append(transcript_segment)
                full_text_parts.append(segment.text)

            processing_time = time.time() - start_time

            logger.info(
                f"Transcription complete: {len(segments)} segments, "
                f"language={info.language} ({info.language_probability:.2f}), "
                f"took {processing_time:.1f}s"
            )

            return TranscriptionResult(
                success=True,
                segments=segments,
                full_text=" ".join(full_text_parts).strip(),
                language=info.language,
                language_confidence=info.language_probability,
                processing_time_seconds=processing_time
            )

        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            return TranscriptionResult(success=False, error=str(e))

    async def close(self):
        """Release model resources."""
        self._model = None
```

### Transcript Storage

```python
# processors/video/transcript_storage.py
from dataclasses import dataclass
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

@dataclass
class TranscriptSegmentRecord:
    video_id: UUID
    segment_index: int
    start_ms: int
    end_ms: int
    text: str
    words_json: list[dict]
    confidence: float

class TranscriptStorage:
    """Stores transcript segments in database."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def store_transcript(
        self,
        video_id: UUID,
        segments: list["TranscriptSegment"]
    ) -> int:
        """Store transcript segments for a video."""
        records = [
            {
                "video_id": video_id,
                "segment_index": i,
                "start_ms": seg.start_ms,
                "end_ms": seg.end_ms,
                "text": seg.text,
                "words_json": seg.words,
                "confidence": seg.confidence
            }
            for i, seg in enumerate(segments)
        ]

        if records:
            stmt = insert(TranscriptSegment).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["video_id", "segment_index"],
                set_={"text": stmt.excluded.text, "words_json": stmt.excluded.words_json}
            )
            await self.session.execute(stmt)
            await self.session.commit()

        return len(records)

    async def get_transcript(self, video_id: UUID) -> list[dict]:
        """Retrieve all transcript segments for a video."""
        from sqlalchemy import select

        result = await self.session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.video_id == video_id)
            .order_by(TranscriptSegment.segment_index)
        )
        return [
            {
                "start_ms": r.start_ms,
                "end_ms": r.end_ms,
                "text": r.text,
                "words": r.words_json
            }
            for r in result.scalars()
        ]
```

### Database Schema for Transcripts

```sql
CREATE TABLE video_transcripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id UUID NOT NULL REFERENCES source_videos(id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL,
    words_json JSONB,
    confidence DECIMAL(4, 3),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(video_id, segment_index)
);

CREATE INDEX idx_video_transcripts_video ON video_transcripts(video_id);
CREATE INDEX idx_video_transcripts_time ON video_transcripts(video_id, start_ms);
```

### Pipeline Integration

```python
# processors/video/pipeline.py (transcription stage)

class VideoProcessingPipeline:
    async def _run_transcription_stage(self) -> list[TranscriptSegment]:
        """Extract audio and transcribe."""
        await self._update_progress("extracting_audio", 0)

        # Check if video has audio
        has_audio = await self.audio_extractor.check_has_audio(self.video_path)
        if not has_audio:
            logger.warning(f"Video {self.video_id} has no audio track")
            return []

        # Extract audio
        audio_path = self.temp_dir / f"{self.video_id}.wav"
        result = await self.audio_extractor.extract(self.video_path, audio_path)

        if not result.success:
            raise ProcessingError(f"Audio extraction failed: {result.error}")

        await self._update_progress("extracting_audio", 100)
        await self._update_progress("transcribing", 0)

        # Transcribe
        transcription = await self.transcriber.transcribe(audio_path)

        if not transcription.success:
            raise ProcessingError(f"Transcription failed: {transcription.error}")

        # Store transcript
        await self.transcript_storage.store_transcript(
            self.video_id,
            transcription.segments
        )

        # Update video with detected language
        if transcription.language:
            await self.video_service.update_language(
                self.video_id,
                transcription.language
            )

        await self._update_progress("transcribing", 100)

        return transcription.segments
```

### Configuration

```python
# config.py (transcription settings)
class TranscriptionConfig(BaseSettings):
    whisper_model: str = "base"
    whisper_device: str = "cuda"
    whisper_compute_type: str = "float16"
    whisper_language: str | None = None  # Auto-detect
    whisper_word_timestamps: bool = True
    whisper_vad_filter: bool = True

    class Config:
        env_prefix = "TRANSCRIPTION_"
```

## Sequence Diagram

```
┌──────────┐     ┌──────────┐     ┌─────────┐     ┌────────┐
│ Pipeline │     │ FFmpeg   │     │ Whisper │     │   DB   │
└────┬─────┘     └────┬─────┘     └────┬────┘     └───┬────┘
     │                │                │              │
     │ check_has_audio│                │              │
     │───────────────>│                │              │
     │     bool       │                │              │
     │<───────────────│                │              │
     │                │                │              │
     │ extract(video) │                │              │
     │───────────────>│                │              │
     │                │                │              │
     │   audio.wav    │                │              │
     │<───────────────│                │              │
     │                │                │              │
     │ transcribe(audio)               │              │
     │────────────────────────────────>│              │
     │                │                │              │
     │         TranscriptionResult     │              │
     │<────────────────────────────────│              │
     │                │                │              │
     │ store_transcript(segments)      │              │
     │────────────────────────────────────────────────>
     │                │                │              │
```

## Error Handling

| Error | Handling | Recovery |
|-------|----------|----------|
| No audio track | Skip transcription stage | Continue with visual-only content |
| FFmpeg extraction failed | Retry once with different codec | Mark stage failed |
| Whisper OOM | Retry with smaller model | Use chunked processing |
| Language detection failed | Default to English | Allow manual override |
| Corrupt audio | Log and skip | Continue pipeline |

## Performance Considerations

- **faster-whisper** is 4x faster than OpenAI Whisper with same accuracy
- Use VAD filter to skip silence (reduces processing time ~30%)
- GPU acceleration required for production workloads
- Batch multiple short videos when possible
- Consider word-level timestamps only when needed (slight overhead)

### Processing Time Estimates

| Model | Real-time Factor (GPU) | VRAM Required |
|-------|----------------------|---------------|
| tiny | 32x | 1 GB |
| base | 16x | 1 GB |
| small | 6x | 2 GB |
| medium | 2x | 5 GB |
| large-v3 | 1x | 10 GB |

## Acceptance Criteria

- [ ] Extract audio track using FFmpeg
- [ ] Transcribe using Whisper (or faster-whisper)
- [ ] Produce word-level or segment-level timestamps
- [ ] Handle videos with no audio track gracefully
- [ ] Support multiple languages (language detection)
- [ ] Store transcript segments with timing metadata

## Testing Requirements

```python
class TestAudioExtractor:
    @pytest.mark.asyncio
    async def test_extracts_audio_from_video(self, sample_video):
        extractor = AudioExtractor()
        result = await extractor.extract(sample_video, Path("/tmp/audio.wav"))
        assert result.success
        assert result.audio_path.exists()

    @pytest.mark.asyncio
    async def test_handles_video_without_audio(self, silent_video):
        extractor = AudioExtractor()
        has_audio = await extractor.check_has_audio(silent_video)
        assert not has_audio

class TestWhisperTranscriber:
    @pytest.mark.asyncio
    async def test_transcribes_english_audio(self, english_audio):
        transcriber = WhisperTranscriber(TranscriptionConfig(model="tiny"))
        await transcriber.initialize()
        result = await transcriber.transcribe(english_audio)

        assert result.success
        assert len(result.segments) > 0
        assert result.language == "en"

    @pytest.mark.asyncio
    async def test_detects_language(self, spanish_audio):
        transcriber = WhisperTranscriber()
        await transcriber.initialize()
        result = await transcriber.transcribe(spanish_audio)

        assert result.language == "es"
        assert result.language_confidence > 0.8

    @pytest.mark.asyncio
    async def test_produces_word_timestamps(self, audio_file):
        transcriber = WhisperTranscriber(TranscriptionConfig(word_timestamps=True))
        await transcriber.initialize()
        result = await transcriber.transcribe(audio_file)

        assert result.segments[0].words
        assert "start_ms" in result.segments[0].words[0]

    @pytest.mark.asyncio
    async def test_handles_empty_audio(self, silent_audio):
        transcriber = WhisperTranscriber()
        await transcriber.initialize()
        result = await transcriber.transcribe(silent_audio)

        assert result.success
        assert len(result.segments) == 0
```

## Dependencies

```
faster-whisper>=0.10.0
ffmpeg-python>=0.2.0
```

## System Requirements

```dockerfile
RUN apt-get update && apt-get install -y ffmpeg
```

For GPU acceleration:
```dockerfile
# CUDA 11.x or 12.x required for faster-whisper
```

## Definition of Done

- [ ] Audio extraction working with FFmpeg
- [ ] Whisper transcription producing accurate text
- [ ] Word-level timestamps available
- [ ] Language auto-detection working
- [ ] Silent videos handled gracefully
- [ ] Transcripts stored in database
- [ ] Processing time within estimates
- [ ] >90% test coverage

"""
Video processing module for the Video RAG Pipeline.

This module provides video processing capabilities including:
- Video validation and metadata extraction
- Audio extraction and transcription
- Scene detection and keyframe extraction
- Vision analysis and OCR
- Content fusion for embedding
"""

from processors.video.audio import (
    AudioExtractionConfig,
    AudioExtractionResult,
    AudioExtractor,
)
from processors.video.exceptions import (
    AudioExtractionError,
    KeyframeExtractionError,
    SceneDetectionError,
    TranscriptionError,
    VideoProcessingError,
    VideoStorageError,
    VideoValidationError,
)
from processors.video.keyframe_extractor import (
    ExtractedKeyframe,
    KeyframeExtractionConfig,
    KeyframeExtractionResult,
    KeyframeExtractor,
)
from processors.video.metadata import ValidationConfig, VideoMetadata
from processors.video.pipeline import (
    PipelineConfig,
    PipelineProgress,
    PipelineResult,
    PipelineStage,
    VideoProcessingPipeline,
)
from processors.video.scene_detection import (
    SceneBoundary,
    SceneDetectionConfig,
    SceneDetectionResult,
    SceneDetector,
)
from processors.video.storage import VideoStorage, VideoStorageConfig
from processors.video.transcriber import (
    TranscriptionConfig,
    TranscriptionResult,
    TranscriptSegment,
    WhisperTranscriber,
)
from processors.video.transcript_storage import TranscriptStorage, TranscriptStorageConfig
from processors.video.validator import VideoValidator

# Wave 2: Content Analysis
from processors.video.content_fusion import (
    ContentFusionService,
    FusionConfig,
    KeyframeContent,
    VideoChunk,
    VideoChunkStorage,
)
from processors.video.ocr import OCREngine, OCRResult, TesseractOCR, TesseractOCRConfig, TextRegion
from processors.video.ocr_processor import KeyframeOCR, OCRBatchProcessor, OCRProcessorConfig
from processors.video.vision import (
    OllamaVisionProvider,
    OpenAIVisionProvider,
    VisionAnalysisResult,
    VisionLLMProvider,
)
from processors.video.vision_analyzer import (
    KeyframeAnalysis,
    VisionAnalyzer,
    VisionAnalyzerConfig,
)

# Wave 3: Indexing
from processors.video.embedding import (
    ChunkEmbedding,
    EmbeddingBatchResult,
    VideoChunkEmbedder,
    VideoChunkEmbedderConfig,
)
from processors.video.opensearch_indexer import (
    OpenSearchIndexerConfig,
    OpenSearchVideoIndexer,
)
from processors.video.qdrant_indexer import (
    QdrantIndexerConfig,
    QdrantVideoIndexer,
)

__all__ = [
    # Metadata
    "VideoMetadata",
    "ValidationConfig",
    # Validator
    "VideoValidator",
    # Storage
    "VideoStorage",
    "VideoStorageConfig",
    # Audio extraction
    "AudioExtractor",
    "AudioExtractionConfig",
    "AudioExtractionResult",
    # Transcription
    "WhisperTranscriber",
    "TranscriptionConfig",
    "TranscriptionResult",
    "TranscriptSegment",
    "TranscriptStorage",
    "TranscriptStorageConfig",
    # Scene detection
    "SceneDetector",
    "SceneDetectionConfig",
    "SceneDetectionResult",
    "SceneBoundary",
    # Keyframe extraction
    "KeyframeExtractor",
    "KeyframeExtractionConfig",
    "KeyframeExtractionResult",
    "ExtractedKeyframe",
    # Pipeline
    "VideoProcessingPipeline",
    "PipelineConfig",
    "PipelineProgress",
    "PipelineResult",
    "PipelineStage",
    # Exceptions
    "VideoProcessingError",
    "VideoValidationError",
    "VideoStorageError",
    "AudioExtractionError",
    "TranscriptionError",
    "SceneDetectionError",
    "KeyframeExtractionError",
    # Wave 2: Content Analysis
    "ContentFusionService",
    "FusionConfig",
    "VideoChunk",
    "VideoChunkStorage",
    "KeyframeContent",
    "VisionLLMProvider",
    "VisionAnalysisResult",
    "OpenAIVisionProvider",
    "OllamaVisionProvider",
    "VisionAnalyzer",
    "VisionAnalyzerConfig",
    "KeyframeAnalysis",
    "OCREngine",
    "OCRResult",
    "TextRegion",
    "TesseractOCR",
    "TesseractOCRConfig",
    "OCRBatchProcessor",
    "OCRProcessorConfig",
    "KeyframeOCR",
    # Wave 3: Indexing
    "VideoChunkEmbedder",
    "VideoChunkEmbedderConfig",
    "ChunkEmbedding",
    "EmbeddingBatchResult",
    "QdrantVideoIndexer",
    "QdrantIndexerConfig",
    "OpenSearchVideoIndexer",
    "OpenSearchIndexerConfig",
]

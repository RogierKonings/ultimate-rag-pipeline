"""
Configuration data models for LLM Serving Layer.

Provides Pydantic models for model endpoints, generation parameters,
A/B test configuration, and version tracking.
"""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ModelType(str, Enum):
    """Type of model endpoint."""

    LLM = "llm"
    EMBEDDING = "embedding"
    RERANKER = "reranker"


class RoutingStrategy(str, Enum):
    """A/B test routing strategy."""

    SINGLE = "single"  # Always use primary model
    RANDOM = "random"  # Random selection with weights
    ROUND_ROBIN = "round_robin"  # Alternate between models
    HEADER_BASED = "header_based"  # Based on request header
    USER_BASED = "user_based"  # Based on user ID hash


class LLMGenerationConfig(BaseModel):
    """Generation parameters for LLM inference."""

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    top_k: int = Field(default=50, ge=1)
    max_tokens: int = Field(default=1024, ge=1, le=32768)

    # Penalty settings
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0)
    repetition_penalty: float = Field(default=1.0, ge=0.0, le=2.0)

    # Stop sequences
    stop_sequences: list[str] = Field(default_factory=list)

    # Streaming
    stream: bool = True

    def to_vllm_params(self) -> dict:
        """Convert to vLLM SamplingParams format."""
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "max_tokens": self.max_tokens,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "repetition_penalty": self.repetition_penalty,
            "stop": self.stop_sequences if self.stop_sequences else None,
        }


class EmbeddingConfig(BaseModel):
    """Configuration for embedding model."""

    normalize: bool = True
    batch_size: int = Field(default=32, ge=1, le=256)
    max_sequence_length: int = Field(default=512, ge=1, le=8192)
    use_fp16: bool = True
    prefix_query: str = "query: "
    prefix_passage: str = "passage: "


class RerankerConfig(BaseModel):
    """Configuration for reranker model."""

    max_pairs_per_request: int = Field(default=100, ge=1, le=1000)
    max_sequence_length: int = Field(default=512, ge=1, le=2048)
    batch_size: int = Field(default=32, ge=1, le=128)
    normalize_scores: bool = False
    use_fp16: bool = True


class ModelEndpoint(BaseModel):
    """Configuration for a model endpoint."""

    name: str
    type: ModelType
    model_id: str  # HuggingFace model ID or path
    endpoint_url: str

    # Version tracking
    version: str = "1.0.0"
    revision: Optional[str] = None  # Git commit or model revision

    # Enabled state
    enabled: bool = True

    # Type-specific configuration
    llm_config: Optional[LLMGenerationConfig] = None
    embedding_config: Optional[EmbeddingConfig] = None
    reranker_config: Optional[RerankerConfig] = None

    # Performance settings
    timeout_seconds: float = 60.0
    max_retries: int = 3

    # Metadata
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class ABTestConfig(BaseModel):
    """A/B test configuration for model experiments."""

    id: UUID = Field(default_factory=uuid4)
    name: str
    description: Optional[str] = None

    # Models in the test
    model_a: str  # Model endpoint name
    model_b: str  # Model endpoint name

    # Traffic split (0.0 to 1.0 for model_a, rest goes to model_b)
    traffic_split: float = Field(default=0.5, ge=0.0, le=1.0)

    # Routing strategy
    strategy: RoutingStrategy = RoutingStrategy.RANDOM

    # User segments for USER_BASED strategy
    model_a_user_segments: list[str] = Field(default_factory=list)

    # Header name for HEADER_BASED strategy
    routing_header: str = "X-Model-Version"

    # Time bounds
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    # Status
    active: bool = True

    def is_active(self) -> bool:
        """Check if test is currently active."""
        if not self.active:
            return False

        now = datetime.utcnow()
        if self.start_time and now < self.start_time:
            return False
        if self.end_time and now > self.end_time:
            return False

        return True


class ConfigVersion(BaseModel):
    """Versioned configuration snapshot."""

    id: UUID = Field(default_factory=uuid4)
    version: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Configuration content
    endpoints: dict[str, ModelEndpoint]
    ab_tests: list[ABTestConfig] = Field(default_factory=list)

    # Metadata
    description: Optional[str] = None
    created_by: Optional[str] = None

    # Rollback reference
    previous_version_id: Optional[UUID] = None


class ModelConfigurationState(BaseModel):
    """Current state of model configuration."""

    # Current version
    current_version: int = 1

    # Model endpoints
    endpoints: dict[str, ModelEndpoint] = Field(default_factory=dict)

    # Active A/B tests
    ab_tests: list[ABTestConfig] = Field(default_factory=list)

    # Version history
    version_history: list[ConfigVersion] = Field(default_factory=list)
    max_history_versions: int = 10

    def get_endpoint(self, name: str) -> Optional[ModelEndpoint]:
        """Get endpoint by name."""
        return self.endpoints.get(name)

    def get_active_tests(self) -> list[ABTestConfig]:
        """Get currently active A/B tests."""
        return [t for t in self.ab_tests if t.is_active()]

"""
Phoenix Configuration.

Provides configuration for Phoenix LLM observability.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PhoenixConfig:
    """
    Configuration for Phoenix integration.

    Attributes:
        phoenix_url: Phoenix server URL
        project_name: Project name for grouping traces
        enabled: Whether Phoenix tracing is enabled
        log_prompts: Whether to log full prompts
        log_responses: Whether to log full responses
        sample_rate: Fraction of traces to sample (0.0-1.0)
        batch_size: Batch size for sending spans
        flush_interval: Flush interval in seconds
        max_queue_size: Maximum queue size before dropping
        postgres_url: PostgreSQL URL for feedback storage
    """

    phoenix_url: str = "http://localhost:6006"
    project_name: str = "rag-pipeline"
    enabled: bool = True

    log_prompts: bool = True
    log_responses: bool = True
    sample_rate: float = 1.0

    batch_size: int = 100
    flush_interval: float = 5.0
    max_queue_size: int = 10000

    postgres_url: Optional[str] = None

    # Token counting
    count_tokens: bool = True
    tokenizer_model: str = "cl100k_base"  # OpenAI tokenizer

    # Embedding tracking
    track_embeddings: bool = True
    embedding_sample_rate: float = 0.1  # Sample 10% of embeddings

    @classmethod
    def from_env(cls) -> "PhoenixConfig":
        """
        Create configuration from environment variables.

        Environment variables:
            PHOENIX_URL: Phoenix server URL
            PHOENIX_PROJECT: Project name
            PHOENIX_ENABLED: Enable Phoenix tracing
            PHOENIX_LOG_PROMPTS: Log full prompts
            PHOENIX_LOG_RESPONSES: Log full responses
            PHOENIX_SAMPLE_RATE: Trace sample rate
            PHOENIX_BATCH_SIZE: Batch size for sending
            PHOENIX_FLUSH_INTERVAL: Flush interval seconds
            DATABASE_URL: PostgreSQL URL for feedback

        Returns:
            PhoenixConfig instance
        """
        return cls(
            phoenix_url=os.getenv("PHOENIX_URL", "http://localhost:6006"),
            project_name=os.getenv("PHOENIX_PROJECT", "rag-pipeline"),
            enabled=os.getenv("PHOENIX_ENABLED", "true").lower() == "true",
            log_prompts=os.getenv("PHOENIX_LOG_PROMPTS", "true").lower() == "true",
            log_responses=os.getenv("PHOENIX_LOG_RESPONSES", "true").lower() == "true",
            sample_rate=float(os.getenv("PHOENIX_SAMPLE_RATE", "1.0")),
            batch_size=int(os.getenv("PHOENIX_BATCH_SIZE", "100")),
            flush_interval=float(os.getenv("PHOENIX_FLUSH_INTERVAL", "5.0")),
            max_queue_size=int(os.getenv("PHOENIX_MAX_QUEUE_SIZE", "10000")),
            postgres_url=os.getenv("DATABASE_URL"),
            count_tokens=os.getenv("PHOENIX_COUNT_TOKENS", "true").lower() == "true",
            track_embeddings=os.getenv("PHOENIX_TRACK_EMBEDDINGS", "true").lower() == "true",
            embedding_sample_rate=float(os.getenv("PHOENIX_EMBEDDING_SAMPLE_RATE", "0.1")),
        )

    def validate(self) -> list[str]:
        """
        Validate configuration.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if self.sample_rate < 0 or self.sample_rate > 1:
            errors.append("sample_rate must be between 0 and 1")

        if self.embedding_sample_rate < 0 or self.embedding_sample_rate > 1:
            errors.append("embedding_sample_rate must be between 0 and 1")

        if self.batch_size < 1:
            errors.append("batch_size must be at least 1")

        if self.flush_interval < 0.1:
            errors.append("flush_interval must be at least 0.1 seconds")

        return errors

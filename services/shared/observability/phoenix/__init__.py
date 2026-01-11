"""
Phoenix LLM Observability Module.

Provides integration with Arize Phoenix for LLM observability:
- LLM call tracing with token usage
- Prompt/response logging
- Feedback collection
- Experiment tracking
- Performance analysis

Usage:
    from shared.observability.phoenix import (
        PhoenixTracer,
        LangChainCallback,
        FeedbackCollector,
    )

    # Initialize tracer
    tracer = PhoenixTracer()

    # Use with LangChain
    callback = LangChainCallback(tracer)
    llm = ChatOpenAI(callbacks=[callback])

    # Collect feedback
    collector = FeedbackCollector(tracer)
    await collector.record_feedback(
        trace_id="...",
        score=0.9,
        feedback_type="thumbs_up",
    )
"""

from .config import PhoenixConfig
from .tracer import PhoenixTracer, LLMSpan
from .callbacks import LangChainCallback, LlamaIndexCallback
from .feedback import FeedbackCollector, Feedback, FeedbackType
from .experiments import ExperimentTracker, Experiment, ExperimentRun

__all__ = [
    # Configuration
    "PhoenixConfig",
    # Tracer
    "PhoenixTracer",
    "LLMSpan",
    # Callbacks
    "LangChainCallback",
    "LlamaIndexCallback",
    # Feedback
    "FeedbackCollector",
    "Feedback",
    "FeedbackType",
    # Experiments
    "ExperimentTracker",
    "Experiment",
    "ExperimentRun",
]

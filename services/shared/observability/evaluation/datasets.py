"""
Evaluation Dataset Management.

Provides classes for loading, saving, and managing evaluation datasets.
"""

import hashlib
import json
import logging
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import SamplingStrategy

logger = logging.getLogger(__name__)


@dataclass
class EvaluationSample:
    """
    A single evaluation sample.

    Attributes:
        id: Unique identifier
        question: The question/query
        contexts: Retrieved or expected contexts
        answer: Generated or expected answer
        ground_truth: Ground truth answer (optional)
        metadata: Additional metadata (source, category, etc.)
    """

    question: str
    contexts: list[str]
    answer: str = ""
    ground_truth: str | None = None
    id: str = field(default_factory=lambda: str(uuid4()))
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Ensure contexts is a list."""
        if isinstance(self.contexts, str):
            self.contexts = [self.contexts]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "question": self.question,
            "contexts": self.contexts,
            "answer": self.answer,
            "ground_truth": self.ground_truth,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationSample":
        """Create from dictionary."""
        return cls(
            id=data.get("id", str(uuid4())),
            question=data["question"],
            contexts=data.get("contexts", []),
            answer=data.get("answer", ""),
            ground_truth=data.get("ground_truth"),
            metadata=data.get("metadata", {}),
        )

    def content_hash(self) -> str:
        """Generate hash of question + contexts for deduplication."""
        content = f"{self.question}{''.join(sorted(self.contexts))}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class EvaluationDataset:
    """
    Collection of evaluation samples.

    Supports loading from JSON, HuggingFace datasets, and manual creation.
    """

    name: str
    samples: list[EvaluationSample] = field(default_factory=list)
    version: str = "1.0.0"
    description: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        """Return number of samples."""
        return len(self.samples)

    def __iter__(self) -> Iterator[EvaluationSample]:
        """Iterate over samples."""
        return iter(self.samples)

    def __getitem__(self, index: int) -> EvaluationSample:
        """Get sample by index."""
        return self.samples[index]

    def add_sample(self, sample: EvaluationSample) -> None:
        """Add a sample to the dataset."""
        self.samples.append(sample)

    def add_samples(self, samples: list[EvaluationSample]) -> None:
        """Add multiple samples."""
        self.samples.extend(samples)

    def remove_duplicates(self) -> int:
        """
        Remove duplicate samples based on content hash.

        Returns:
            Number of duplicates removed
        """
        seen_hashes = set()
        unique_samples = []

        for sample in self.samples:
            hash_ = sample.content_hash()
            if hash_ not in seen_hashes:
                seen_hashes.add(hash_)
                unique_samples.append(sample)

        removed = len(self.samples) - len(unique_samples)
        self.samples = unique_samples
        return removed

    def sample(
        self,
        n: int | None = None,
        strategy: SamplingStrategy = SamplingStrategy.RANDOM,
        seed: int = 42,
        stratify_by: str | None = None,
    ) -> "EvaluationDataset":
        """
        Sample from the dataset.

        Args:
            n: Number of samples (None = all)
            strategy: Sampling strategy
            seed: Random seed
            stratify_by: Metadata field to stratify by (for STRATIFIED strategy)

        Returns:
            New dataset with sampled data
        """
        if n is None or n >= len(self.samples):
            return EvaluationDataset(
                name=f"{self.name}_sampled",
                samples=self.samples.copy(),
                version=self.version,
                description=f"Sampled from {self.name}",
                metadata={**self.metadata, "parent_dataset": self.name},
            )

        random.seed(seed)

        if strategy == SamplingStrategy.SEQUENTIAL:
            selected = self.samples[:n]

        elif strategy == SamplingStrategy.RANDOM:
            selected = random.sample(self.samples, n)

        elif strategy == SamplingStrategy.STRATIFIED:
            if not stratify_by:
                # Fall back to random
                selected = random.sample(self.samples, n)
            else:
                # Group by stratification field
                groups: dict[str, list[EvaluationSample]] = {}
                for sample in self.samples:
                    key = str(sample.metadata.get(stratify_by, "default"))
                    if key not in groups:
                        groups[key] = []
                    groups[key].append(sample)

                # Sample proportionally from each group
                selected = []
                total = len(self.samples)
                for _key, group_samples in groups.items():
                    group_n = max(1, int(n * len(group_samples) / total))
                    group_n = min(group_n, len(group_samples))
                    selected.extend(random.sample(group_samples, group_n))

                # If we have too few, add more randomly
                if len(selected) < n:
                    remaining = [s for s in self.samples if s not in selected]
                    selected.extend(random.sample(remaining, n - len(selected)))

                # If we have too many, remove randomly
                if len(selected) > n:
                    selected = random.sample(selected, n)

        else:  # ALL
            selected = self.samples.copy()

        return EvaluationDataset(
            name=f"{self.name}_sampled",
            samples=selected,
            version=self.version,
            description=f"Sampled {len(selected)} from {self.name}",
            metadata={
                **self.metadata,
                "parent_dataset": self.name,
                "sampling_strategy": strategy.value,
                "sample_size": len(selected),
            },
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
            "samples": [s.to_dict() for s in self.samples],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationDataset":
        """Create from dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif created_at is None:
            created_at = datetime.now(tz=UTC)

        return cls(
            name=data["name"],
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            created_at=created_at,
            metadata=data.get("metadata", {}),
            samples=[
                EvaluationSample.from_dict(s)
                for s in data.get("samples", [])
            ],
        )

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_json(cls, json_str: str) -> "EvaluationDataset":
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def save(self, path: str | Path) -> None:
        """Save dataset to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            f.write(self.to_json())
        logger.info(f"Saved dataset to {path}")

    @classmethod
    def load(cls, path: str | Path) -> "EvaluationDataset":
        """Load dataset from JSON file."""
        path = Path(path)
        with open(path) as f:
            return cls.from_json(f.read())

    @classmethod
    def from_huggingface(
        cls,
        dataset_name: str,
        split: str = "test",
        name: str | None = None,
        question_column: str = "question",
        contexts_column: str = "contexts",
        answer_column: str = "answer",
        ground_truth_column: str = "ground_truth",
        max_samples: int | None = None,
    ) -> "EvaluationDataset":
        """
        Load dataset from HuggingFace datasets.

        Args:
            dataset_name: HuggingFace dataset name
            split: Dataset split to use
            name: Name for the dataset
            question_column: Column name for questions
            contexts_column: Column name for contexts
            answer_column: Column name for answers
            ground_truth_column: Column name for ground truth
            max_samples: Maximum samples to load

        Returns:
            EvaluationDataset instance
        """
        try:
            from datasets import load_dataset

            hf_dataset = load_dataset(dataset_name, split=split)

            if max_samples:
                hf_dataset = hf_dataset.select(range(min(max_samples, len(hf_dataset))))

            samples = []
            for row in hf_dataset:
                sample = EvaluationSample(
                    question=row.get(question_column, ""),
                    contexts=row.get(contexts_column, []),
                    answer=row.get(answer_column, ""),
                    ground_truth=row.get(ground_truth_column),
                    metadata={"source": dataset_name, "split": split},
                )
                samples.append(sample)

            return cls(
                name=name or dataset_name.replace("/", "_"),
                samples=samples,
                description=f"Loaded from HuggingFace: {dataset_name}",
                metadata={
                    "source": "huggingface",
                    "dataset_name": dataset_name,
                    "split": split,
                },
            )

        except ImportError:
            logger.error("datasets library not installed")
            raise

    def get_by_category(self, category: str) -> "EvaluationDataset":
        """
        Get samples by category metadata.

        Args:
            category: Category value to filter by

        Returns:
            New dataset with filtered samples
        """
        filtered = [
            s for s in self.samples
            if s.metadata.get("category") == category
        ]
        return EvaluationDataset(
            name=f"{self.name}_{category}",
            samples=filtered,
            version=self.version,
            metadata={**self.metadata, "filtered_by": f"category={category}"},
        )

    def statistics(self) -> dict[str, Any]:
        """
        Compute dataset statistics.

        Returns:
            Dictionary with statistics
        """
        if not self.samples:
            return {"total_samples": 0}

        context_counts = [len(s.contexts) for s in self.samples]
        question_lengths = [len(s.question) for s in self.samples]
        has_ground_truth = sum(1 for s in self.samples if s.ground_truth)

        categories = {}
        for s in self.samples:
            cat = s.metadata.get("category", "uncategorized")
            categories[cat] = categories.get(cat, 0) + 1

        return {
            "total_samples": len(self.samples),
            "samples_with_ground_truth": has_ground_truth,
            "avg_contexts_per_sample": sum(context_counts) / len(context_counts),
            "min_contexts": min(context_counts),
            "max_contexts": max(context_counts),
            "avg_question_length": sum(question_lengths) / len(question_lengths),
            "categories": categories,
        }

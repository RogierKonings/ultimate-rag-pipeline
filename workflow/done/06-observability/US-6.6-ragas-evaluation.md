# US-6.6: Ragas Evaluation

> **Story ID:** US-6.6  
> **Epic:** Observability Stack  
> **Priority:** High  
> **Estimated Effort:** 3-4 days  
> **Dependencies:** Epic 3 (Retrieval Service), Epic 5 (LLM Serving)

## User Story

**As a** ML engineer  
**I want** automated RAG quality evaluation  
**So that** I can measure and improve system quality

## Context

Ragas (RAG Assessment) is a framework for evaluating the quality of RAG pipelines. It provides metrics for:

- **Context Precision**: How much of the retrieved context is relevant
- **Context Recall**: How much of the ground truth is covered by retrieved context
- **Faithfulness**: How much of the answer is grounded in the context
- **Answer Relevancy**: How relevant the answer is to the question

Automated evaluation enables continuous quality monitoring, regression detection, and data-driven improvements to the RAG pipeline.

## Technical Requirements

### Directory Structure

```
observability/
├── evaluation/
│   ├── __init__.py
│   ├── config.py              # Evaluation configuration
│   ├── ragas_evaluator.py     # Ragas integration
│   ├── datasets.py            # Evaluation dataset management
│   ├── metrics.py             # Custom RAG metrics
│   ├── pipeline.py            # Evaluation pipeline
│   ├── reporters.py           # Result reporters
│   └── schedulers/
│       ├── __init__.py
│       ├── celery_tasks.py    # Celery scheduled tasks
│       └── airflow_dag.py     # Airflow DAG (alternative)
├── datasets/
│   ├── evaluation_golden.json # Golden test set
│   └── evaluation_samples.json # Sample queries
└── k8s/
    └── evaluation-cronjob.yaml # Kubernetes CronJob
```

### Evaluation Configuration

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum
import os


class EvaluatorLLM(str, Enum):
    """LLM to use for evaluation."""
    OPENAI_GPT4 = "openai/gpt-4"
    OPENAI_GPT4_TURBO = "openai/gpt-4-turbo"
    OPENAI_GPT35_TURBO = "openai/gpt-3.5-turbo"
    ANTHROPIC_CLAUDE = "anthropic/claude-3-sonnet"
    LOCAL_VLLM = "local/vllm"


class EvaluationMetric(str, Enum):
    """Available evaluation metrics."""
    CONTEXT_PRECISION = "context_precision"
    CONTEXT_RECALL = "context_recall"
    FAITHFULNESS = "faithfulness"
    ANSWER_RELEVANCY = "answer_relevancy"
    CONTEXT_RELEVANCY = "context_relevancy"
    ANSWER_SIMILARITY = "answer_similarity"
    ANSWER_CORRECTNESS = "answer_correctness"


class EvaluationConfig(BaseModel):
    """
    Configuration for RAG evaluation.
    
    Supports both Ragas metrics and custom metrics.
    """
    # LLM for evaluation
    evaluator_llm: EvaluatorLLM = EvaluatorLLM.OPENAI_GPT4_TURBO
    evaluator_api_key: Optional[str] = None
    
    # Embedding model for metrics that need it
    embedding_model: str = "text-embedding-3-small"
    
    # Metrics to compute
    metrics: List[EvaluationMetric] = Field(
        default_factory=lambda: [
            EvaluationMetric.CONTEXT_PRECISION,
            EvaluationMetric.CONTEXT_RECALL,
            EvaluationMetric.FAITHFULNESS,
            EvaluationMetric.ANSWER_RELEVANCY,
        ]
    )
    
    # Batch settings
    batch_size: int = 10
    max_concurrent: int = 5
    
    # Retry settings
    max_retries: int = 3
    retry_delay: float = 1.0
    
    # Timeout per evaluation
    timeout_seconds: int = 120
    
    # Storage
    results_storage: str = "postgresql"  # postgresql, s3, local
    results_table: str = "rag_evaluations"
    
    # Prometheus metrics
    export_to_prometheus: bool = True
    
    # Thresholds for alerts
    min_context_precision: float = 0.7
    min_faithfulness: float = 0.8
    min_answer_relevancy: float = 0.7
    
    @classmethod
    def from_env(cls) -> "EvaluationConfig":
        """Create config from environment variables."""
        return cls(
            evaluator_llm=EvaluatorLLM(os.getenv(
                "RAGAS_EVALUATOR_LLM",
                "openai/gpt-4-turbo"
            )),
            evaluator_api_key=os.getenv("RAGAS_API_KEY"),
            embedding_model=os.getenv("RAGAS_EMBEDDING_MODEL", "text-embedding-3-small"),
        )
```

### Ragas Evaluator

```python
from ragas import evaluate
from ragas.metrics import (
    context_precision,
    context_recall,
    faithfulness,
    answer_relevancy,
    context_relevancy,
    answer_similarity,
    answer_correctness,
)
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from datasets import Dataset
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import asyncio
from uuid import uuid4


@dataclass
class EvaluationSample:
    """
    A single evaluation sample.
    
    Contains the inputs and outputs needed for RAG evaluation.
    """
    id: str
    question: str
    answer: str
    contexts: List[str]
    ground_truth: Optional[str] = None  # For context recall
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Ragas."""
        return {
            "question": self.question,
            "answer": self.answer,
            "contexts": self.contexts,
            "ground_truth": self.ground_truth or "",
        }


@dataclass
class EvaluationResult:
    """
    Result of evaluating a sample.
    """
    sample_id: str
    question: str
    timestamp: datetime
    metrics: Dict[str, float]
    metadata: Optional[Dict[str, Any]] = None


class RagasEvaluator:
    """
    Ragas-based RAG quality evaluator.
    
    Computes standard Ragas metrics:
    - context_precision: Relevance of retrieved context
    - context_recall: Coverage of ground truth in context
    - faithfulness: Answer grounding in context
    - answer_relevancy: Answer relevance to question
    
    Example:
        evaluator = RagasEvaluator(config)
        samples = [EvaluationSample(...), ...]
        results = await evaluator.evaluate(samples)
    """
    
    METRIC_MAP = {
        EvaluationMetric.CONTEXT_PRECISION: context_precision,
        EvaluationMetric.CONTEXT_RECALL: context_recall,
        EvaluationMetric.FAITHFULNESS: faithfulness,
        EvaluationMetric.ANSWER_RELEVANCY: answer_relevancy,
        EvaluationMetric.CONTEXT_RELEVANCY: context_relevancy,
        EvaluationMetric.ANSWER_SIMILARITY: answer_similarity,
        EvaluationMetric.ANSWER_CORRECTNESS: answer_correctness,
    }
    
    def __init__(self, config: EvaluationConfig):
        self.config = config
        self._setup_llm()
        self._setup_embeddings()
        self._setup_metrics()
    
    def _setup_llm(self) -> None:
        """Set up the evaluator LLM."""
        if self.config.evaluator_llm.value.startswith("openai/"):
            model_name = self.config.evaluator_llm.value.replace("openai/", "")
            llm = ChatOpenAI(
                model=model_name,
                api_key=self.config.evaluator_api_key,
                temperature=0,
            )
            self.llm = LangchainLLMWrapper(llm)
        elif self.config.evaluator_llm.value.startswith("anthropic/"):
            from langchain_anthropic import ChatAnthropic
            model_name = self.config.evaluator_llm.value.replace("anthropic/", "")
            llm = ChatAnthropic(
                model=model_name,
                api_key=self.config.evaluator_api_key,
            )
            self.llm = LangchainLLMWrapper(llm)
        else:
            raise ValueError(f"Unsupported LLM: {self.config.evaluator_llm}")
    
    def _setup_embeddings(self) -> None:
        """Set up embeddings for metrics that need them."""
        embeddings = OpenAIEmbeddings(
            model=self.config.embedding_model,
            api_key=self.config.evaluator_api_key,
        )
        self.embeddings = LangchainEmbeddingsWrapper(embeddings)
    
    def _setup_metrics(self) -> None:
        """Set up Ragas metrics."""
        self.metrics = []
        for metric_type in self.config.metrics:
            metric = self.METRIC_MAP[metric_type]
            self.metrics.append(metric)
    
    async def evaluate(
        self,
        samples: List[EvaluationSample],
    ) -> List[EvaluationResult]:
        """
        Evaluate a list of samples.
        
        Args:
            samples: List of evaluation samples
        
        Returns:
            List of evaluation results with metrics
        """
        # Convert samples to Ragas dataset format
        data = {
            "question": [s.question for s in samples],
            "answer": [s.answer for s in samples],
            "contexts": [s.contexts for s in samples],
            "ground_truth": [s.ground_truth or "" for s in samples],
        }
        dataset = Dataset.from_dict(data)
        
        # Run evaluation
        try:
            result = evaluate(
                dataset=dataset,
                metrics=self.metrics,
                llm=self.llm,
                embeddings=self.embeddings,
            )
        except Exception as e:
            # Log error and return empty results
            import logging
            logging.error(f"Ragas evaluation failed: {e}")
            raise
        
        # Convert to EvaluationResult objects
        results = []
        result_df = result.to_pandas()
        
        for idx, sample in enumerate(samples):
            metrics = {}
            for metric_type in self.config.metrics:
                metric_name = metric_type.value
                if metric_name in result_df.columns:
                    metrics[metric_name] = float(result_df.iloc[idx][metric_name])
            
            results.append(EvaluationResult(
                sample_id=sample.id,
                question=sample.question,
                timestamp=datetime.utcnow(),
                metrics=metrics,
            ))
        
        return results
    
    async def evaluate_single(
        self,
        sample: EvaluationSample,
    ) -> EvaluationResult:
        """Evaluate a single sample."""
        results = await self.evaluate([sample])
        return results[0]
    
    def compute_aggregates(
        self,
        results: List[EvaluationResult],
    ) -> Dict[str, Dict[str, float]]:
        """
        Compute aggregate statistics over results.
        
        Returns:
            Dict with mean, min, max, std for each metric
        """
        import numpy as np
        
        aggregates = {}
        
        for metric_type in self.config.metrics:
            metric_name = metric_type.value
            values = [r.metrics.get(metric_name) for r in results if metric_name in r.metrics]
            
            if values:
                aggregates[metric_name] = {
                    "mean": float(np.mean(values)),
                    "min": float(np.min(values)),
                    "max": float(np.max(values)),
                    "std": float(np.std(values)),
                    "count": len(values),
                }
        
        return aggregates
```

### Evaluation Dataset Management

```python
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from datetime import datetime
import json
from pathlib import Path


@dataclass
class EvaluationDataset:
    """
    A collection of evaluation samples.
    
    Supports:
    - Loading from JSON files
    - Storing in PostgreSQL
    - Versioning and metadata
    """
    name: str
    version: str
    samples: List[EvaluationSample] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    @classmethod
    def from_json(cls, path: Path) -> "EvaluationDataset":
        """Load dataset from JSON file."""
        with open(path) as f:
            data = json.load(f)
        
        samples = [
            EvaluationSample(
                id=s.get("id", str(uuid4())),
                question=s["question"],
                answer=s["answer"],
                contexts=s["contexts"],
                ground_truth=s.get("ground_truth"),
            )
            for s in data["samples"]
        ]
        
        return cls(
            name=data.get("name", path.stem),
            version=data.get("version", "1.0.0"),
            samples=samples,
            metadata=data.get("metadata", {}),
        )
    
    def to_json(self, path: Path) -> None:
        """Save dataset to JSON file."""
        data = {
            "name": self.name,
            "version": self.version,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "samples": [s.to_dict() | {"id": s.id} for s in self.samples],
        }
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    
    def add_sample(self, sample: EvaluationSample) -> None:
        """Add a sample to the dataset."""
        self.samples.append(sample)
    
    def sample_subset(self, n: int) -> List[EvaluationSample]:
        """Get a random subset of samples."""
        import random
        return random.sample(self.samples, min(n, len(self.samples)))


class DatasetStore:
    """
    Store and manage evaluation datasets.
    """
    
    def __init__(self, db_url: str):
        self.db_url = db_url
        self._engine = None
    
    async def save_dataset(self, dataset: EvaluationDataset) -> None:
        """Save dataset to database."""
        # Implementation depends on database choice
        pass
    
    async def load_dataset(self, name: str, version: str = None) -> EvaluationDataset:
        """Load dataset from database."""
        pass
    
    async def list_datasets(self) -> List[Dict[str, Any]]:
        """List available datasets."""
        pass
```

### Evaluation Pipeline

```python
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
import asyncio
import logging


@dataclass
class PipelineResult:
    """Result of running the evaluation pipeline."""
    run_id: str
    dataset_name: str
    dataset_version: str
    started_at: datetime
    completed_at: datetime
    sample_count: int
    results: List[EvaluationResult]
    aggregates: Dict[str, Dict[str, float]]
    passed: bool
    failures: List[Dict[str, Any]]


class EvaluationPipeline:
    """
    Orchestrates the full evaluation workflow.
    
    Pipeline stages:
    1. Load evaluation dataset
    2. Run RAG pipeline on questions
    3. Evaluate with Ragas
    4. Store results
    5. Export metrics
    6. Check thresholds and alert
    """
    
    def __init__(
        self,
        config: EvaluationConfig,
        rag_client,  # Client to call RAG API
        dataset_store: Optional[DatasetStore] = None,
    ):
        self.config = config
        self.rag_client = rag_client
        self.dataset_store = dataset_store
        self.evaluator = RagasEvaluator(config)
        self.logger = logging.getLogger(__name__)
    
    async def run(
        self,
        dataset: EvaluationDataset,
        run_rag: bool = True,
    ) -> PipelineResult:
        """
        Run the evaluation pipeline.
        
        Args:
            dataset: Evaluation dataset
            run_rag: Whether to run RAG pipeline (False if samples already have answers)
        
        Returns:
            Pipeline result with metrics and pass/fail status
        """
        run_id = str(uuid4())
        started_at = datetime.utcnow()
        
        self.logger.info(f"Starting evaluation run {run_id} with {len(dataset.samples)} samples")
        
        # Step 1: Run RAG pipeline if needed
        if run_rag:
            samples = await self._run_rag_pipeline(dataset.samples)
        else:
            samples = dataset.samples
        
        # Step 2: Evaluate with Ragas
        self.logger.info("Running Ragas evaluation")
        results = await self.evaluator.evaluate(samples)
        
        # Step 3: Compute aggregates
        aggregates = self.evaluator.compute_aggregates(results)
        
        # Step 4: Check thresholds
        failures = self._check_thresholds(aggregates)
        passed = len(failures) == 0
        
        # Step 5: Store results
        if self.config.results_storage:
            await self._store_results(run_id, results, aggregates)
        
        # Step 6: Export to Prometheus
        if self.config.export_to_prometheus:
            self._export_to_prometheus(aggregates)
        
        completed_at = datetime.utcnow()
        
        return PipelineResult(
            run_id=run_id,
            dataset_name=dataset.name,
            dataset_version=dataset.version,
            started_at=started_at,
            completed_at=completed_at,
            sample_count=len(samples),
            results=results,
            aggregates=aggregates,
            passed=passed,
            failures=failures,
        )
    
    async def _run_rag_pipeline(
        self,
        samples: List[EvaluationSample],
    ) -> List[EvaluationSample]:
        """Run RAG pipeline to get answers and contexts."""
        updated_samples = []
        
        for sample in samples:
            try:
                # Call RAG API
                response = await self.rag_client.query(
                    question=sample.question,
                    return_contexts=True,
                )
                
                updated_samples.append(EvaluationSample(
                    id=sample.id,
                    question=sample.question,
                    answer=response.answer,
                    contexts=[c.text for c in response.contexts],
                    ground_truth=sample.ground_truth,
                ))
            except Exception as e:
                self.logger.error(f"RAG pipeline failed for sample {sample.id}: {e}")
                # Keep original sample
                updated_samples.append(sample)
        
        return updated_samples
    
    def _check_thresholds(
        self,
        aggregates: Dict[str, Dict[str, float]],
    ) -> List[Dict[str, Any]]:
        """Check if metrics meet minimum thresholds."""
        failures = []
        
        threshold_map = {
            "context_precision": self.config.min_context_precision,
            "faithfulness": self.config.min_faithfulness,
            "answer_relevancy": self.config.min_answer_relevancy,
        }
        
        for metric_name, threshold in threshold_map.items():
            if metric_name in aggregates:
                mean_value = aggregates[metric_name]["mean"]
                if mean_value < threshold:
                    failures.append({
                        "metric": metric_name,
                        "expected": threshold,
                        "actual": mean_value,
                    })
        
        return failures
    
    async def _store_results(
        self,
        run_id: str,
        results: List[EvaluationResult],
        aggregates: Dict[str, Dict[str, float]],
    ) -> None:
        """Store evaluation results."""
        # Implementation depends on storage choice
        self.logger.info(f"Storing {len(results)} results for run {run_id}")
    
    def _export_to_prometheus(
        self,
        aggregates: Dict[str, Dict[str, float]],
    ) -> None:
        """Export metrics to Prometheus."""
        from prometheus_client import Gauge
        
        for metric_name, stats in aggregates.items():
            # Create or get gauge
            gauge = Gauge(
                f"rag_evaluation_{metric_name}",
                f"RAG evaluation {metric_name} score",
                ["stat"],
            )
            
            for stat_name, value in stats.items():
                if stat_name != "count":
                    gauge.labels(stat=stat_name).set(value)
```

### Scheduled Evaluation (Celery)

```python
from celery import Celery
from celery.schedules import crontab
from datetime import datetime


app = Celery('evaluation')
app.config_from_object('celeryconfig')


@app.task(bind=True, max_retries=3)
def run_scheduled_evaluation(self, dataset_name: str, dataset_version: str = None):
    """
    Celery task for scheduled RAG evaluation.
    
    Runs weekly by default, configurable via Celery beat.
    """
    import asyncio
    
    config = EvaluationConfig.from_env()
    
    # Load dataset
    if dataset_version:
        dataset = EvaluationDataset.from_json(
            Path(f"datasets/{dataset_name}_{dataset_version}.json")
        )
    else:
        dataset = EvaluationDataset.from_json(
            Path(f"datasets/{dataset_name}.json")
        )
    
    # Create pipeline
    from rag_client import RAGClient
    rag_client = RAGClient()
    
    pipeline = EvaluationPipeline(
        config=config,
        rag_client=rag_client,
    )
    
    # Run evaluation
    try:
        result = asyncio.run(pipeline.run(dataset))
        
        # Log results
        logger = get_logger("evaluation")
        logger.info(
            "Evaluation completed",
            extra={
                "run_id": result.run_id,
                "passed": result.passed,
                "aggregates": result.aggregates,
            }
        )
        
        # Send alert if failed
        if not result.passed:
            send_evaluation_alert(result)
        
        return result.run_id
    
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        self.retry(exc=e, countdown=60 * 5)  # Retry in 5 minutes


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    """Configure periodic evaluation tasks."""
    # Weekly evaluation on Sunday at 2am
    sender.add_periodic_task(
        crontab(hour=2, minute=0, day_of_week=0),
        run_scheduled_evaluation.s("evaluation_golden"),
        name="weekly-rag-evaluation",
    )
    
    # Daily sample evaluation
    sender.add_periodic_task(
        crontab(hour=3, minute=0),
        run_scheduled_evaluation.s("evaluation_samples"),
        name="daily-rag-sample-evaluation",
    )


def send_evaluation_alert(result: PipelineResult) -> None:
    """Send alert when evaluation fails thresholds."""
    import requests
    
    slack_webhook = os.getenv("SLACK_WEBHOOK_URL")
    if not slack_webhook:
        return
    
    message = {
        "text": f"⚠️ RAG Evaluation Failed",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*RAG Evaluation Failed*\n"
                           f"Run ID: `{result.run_id}`\n"
                           f"Dataset: {result.dataset_name} v{result.dataset_version}",
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Failed Metrics:*\n" + "\n".join([
                        f"• {f['metric']}: {f['actual']:.3f} (min: {f['expected']:.3f})"
                        for f in result.failures
                    ]),
                }
            },
        ],
    }
    
    requests.post(slack_webhook, json=message)
```

### Result Reporters

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any
import json
from datetime import datetime


class ResultReporter(ABC):
    """Base class for result reporters."""
    
    @abstractmethod
    async def report(self, result: PipelineResult) -> None:
        """Report evaluation results."""
        pass


class JSONFileReporter(ResultReporter):
    """Report results to JSON file."""
    
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    async def report(self, result: PipelineResult) -> None:
        filename = f"evaluation_{result.run_id}_{result.completed_at.strftime('%Y%m%d_%H%M%S')}.json"
        output_path = self.output_dir / filename
        
        data = {
            "run_id": result.run_id,
            "dataset": {
                "name": result.dataset_name,
                "version": result.dataset_version,
            },
            "timing": {
                "started_at": result.started_at.isoformat(),
                "completed_at": result.completed_at.isoformat(),
                "duration_seconds": (result.completed_at - result.started_at).total_seconds(),
            },
            "sample_count": result.sample_count,
            "passed": result.passed,
            "aggregates": result.aggregates,
            "failures": result.failures,
            "results": [
                {
                    "sample_id": r.sample_id,
                    "question": r.question,
                    "metrics": r.metrics,
                }
                for r in result.results
            ],
        }
        
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)


class PostgreSQLReporter(ResultReporter):
    """Report results to PostgreSQL."""
    
    def __init__(self, db_url: str):
        self.db_url = db_url
    
    async def report(self, result: PipelineResult) -> None:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        
        engine = create_async_engine(self.db_url)
        
        async with engine.begin() as conn:
            # Insert run summary
            await conn.execute(
                text("""
                    INSERT INTO evaluation_runs 
                    (run_id, dataset_name, dataset_version, started_at, completed_at, 
                     sample_count, passed, aggregates)
                    VALUES (:run_id, :dataset_name, :dataset_version, :started_at, 
                            :completed_at, :sample_count, :passed, :aggregates)
                """),
                {
                    "run_id": result.run_id,
                    "dataset_name": result.dataset_name,
                    "dataset_version": result.dataset_version,
                    "started_at": result.started_at,
                    "completed_at": result.completed_at,
                    "sample_count": result.sample_count,
                    "passed": result.passed,
                    "aggregates": json.dumps(result.aggregates),
                }
            )
            
            # Insert individual results
            for r in result.results:
                await conn.execute(
                    text("""
                        INSERT INTO evaluation_results
                        (run_id, sample_id, question, metrics, evaluated_at)
                        VALUES (:run_id, :sample_id, :question, :metrics, :evaluated_at)
                    """),
                    {
                        "run_id": result.run_id,
                        "sample_id": r.sample_id,
                        "question": r.question,
                        "metrics": json.dumps(r.metrics),
                        "evaluated_at": r.timestamp,
                    }
                )


class GrafanaAnnotationReporter(ResultReporter):
    """Add Grafana annotations for evaluation runs."""
    
    def __init__(self, grafana_url: str, api_key: str):
        self.grafana_url = grafana_url
        self.api_key = api_key
    
    async def report(self, result: PipelineResult) -> None:
        import httpx
        
        status = "✅ Passed" if result.passed else "❌ Failed"
        
        annotation = {
            "dashboardUID": "rag-overview",
            "time": int(result.completed_at.timestamp() * 1000),
            "tags": ["evaluation", result.dataset_name],
            "text": f"RAG Evaluation {status}\n\n"
                   f"Dataset: {result.dataset_name} v{result.dataset_version}\n"
                   f"Samples: {result.sample_count}\n"
                   f"Aggregates: {json.dumps(result.aggregates, indent=2)}",
        }
        
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{self.grafana_url}/api/annotations",
                json=annotation,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
```

### Sample Evaluation Dataset

```json
{
  "name": "evaluation_golden",
  "version": "1.0.0",
  "metadata": {
    "description": "Golden test set for RAG evaluation",
    "created_by": "ml-team",
    "created_at": "2024-01-15"
  },
  "samples": [
    {
      "id": "sample-001",
      "question": "What is the company's return policy for electronics?",
      "ground_truth": "Electronics can be returned within 30 days of purchase with original receipt. Items must be in original packaging and unopened. Opened items may be subject to a 15% restocking fee.",
      "answer": "",
      "contexts": []
    },
    {
      "id": "sample-002", 
      "question": "How do I reset my password?",
      "ground_truth": "To reset your password: 1) Go to login page, 2) Click 'Forgot Password', 3) Enter your email, 4) Check email for reset link, 5) Create new password meeting security requirements.",
      "answer": "",
      "contexts": []
    }
  ]
}
```

### Kubernetes CronJob

```yaml
# evaluation-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: rag-evaluation
  namespace: rag-pipeline
spec:
  schedule: "0 2 * * 0"  # Weekly on Sunday at 2am
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: evaluation
              image: rag-evaluation:latest
              command: ["python", "-m", "evaluation.run"]
              args:
                - "--dataset=evaluation_golden"
                - "--run-rag=true"
              env:
                - name: RAGAS_API_KEY
                  valueFrom:
                    secretKeyRef:
                      name: evaluation-secrets
                      key: openai-api-key
                - name: RAG_API_URL
                  value: "http://orchestrator:8000"
                - name: DATABASE_URL
                  valueFrom:
                    secretKeyRef:
                      name: db-secrets
                      key: url
              resources:
                requests:
                  memory: 512Mi
                  cpu: 500m
                limits:
                  memory: 1Gi
                  cpu: 1000m
```

## Unit Tests

```python
import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime


@pytest.fixture
def evaluation_config():
    """Create test evaluation configuration."""
    return EvaluationConfig(
        evaluator_llm=EvaluatorLLM.OPENAI_GPT4_TURBO,
        evaluator_api_key="test-key",
        metrics=[
            EvaluationMetric.CONTEXT_PRECISION,
            EvaluationMetric.FAITHFULNESS,
        ],
    )


@pytest.fixture
def sample_dataset():
    """Create test dataset."""
    return EvaluationDataset(
        name="test",
        version="1.0.0",
        samples=[
            EvaluationSample(
                id="s1",
                question="What is X?",
                answer="X is Y.",
                contexts=["X is defined as Y in the documentation."],
                ground_truth="X is Y.",
            ),
            EvaluationSample(
                id="s2",
                question="How does Z work?",
                answer="Z works by doing A and B.",
                contexts=["Z operates through process A.", "Z also uses B."],
                ground_truth="Z works through A and B processes.",
            ),
        ],
    )


def test_evaluation_sample_to_dict():
    """Test EvaluationSample conversion to dict."""
    sample = EvaluationSample(
        id="test-1",
        question="Test question?",
        answer="Test answer.",
        contexts=["Context 1", "Context 2"],
        ground_truth="Ground truth.",
    )
    
    d = sample.to_dict()
    
    assert d["question"] == "Test question?"
    assert d["answer"] == "Test answer."
    assert len(d["contexts"]) == 2


def test_evaluation_dataset_from_json(tmp_path):
    """Test loading dataset from JSON."""
    json_data = {
        "name": "test-dataset",
        "version": "1.0.0",
        "samples": [
            {
                "id": "s1",
                "question": "Q1",
                "answer": "A1",
                "contexts": ["C1"],
                "ground_truth": "GT1",
            }
        ],
    }
    
    json_path = tmp_path / "test.json"
    with open(json_path, "w") as f:
        json.dump(json_data, f)
    
    dataset = EvaluationDataset.from_json(json_path)
    
    assert dataset.name == "test-dataset"
    assert len(dataset.samples) == 1


def test_evaluation_dataset_sample_subset(sample_dataset):
    """Test getting random subset of samples."""
    subset = sample_dataset.sample_subset(1)
    
    assert len(subset) == 1
    assert subset[0] in sample_dataset.samples


@pytest.mark.asyncio
async def test_ragas_evaluator(evaluation_config):
    """Test Ragas evaluator with mocked LLM."""
    with patch('ragas.evaluate') as mock_evaluate:
        # Mock Ragas response
        mock_result = Mock()
        mock_result.to_pandas.return_value = pd.DataFrame({
            "context_precision": [0.85, 0.90],
            "faithfulness": [0.75, 0.80],
        })
        mock_evaluate.return_value = mock_result
        
        evaluator = RagasEvaluator(evaluation_config)
        
        samples = [
            EvaluationSample(
                id="s1",
                question="Q1",
                answer="A1",
                contexts=["C1"],
            ),
            EvaluationSample(
                id="s2",
                question="Q2",
                answer="A2",
                contexts=["C2"],
            ),
        ]
        
        results = await evaluator.evaluate(samples)
        
        assert len(results) == 2
        assert results[0].metrics["context_precision"] == 0.85


def test_compute_aggregates(evaluation_config):
    """Test aggregate computation."""
    evaluator = RagasEvaluator.__new__(RagasEvaluator)
    evaluator.config = evaluation_config
    
    results = [
        EvaluationResult(
            sample_id="s1",
            question="Q1",
            timestamp=datetime.utcnow(),
            metrics={"context_precision": 0.8, "faithfulness": 0.7},
        ),
        EvaluationResult(
            sample_id="s2",
            question="Q2",
            timestamp=datetime.utcnow(),
            metrics={"context_precision": 0.9, "faithfulness": 0.8},
        ),
    ]
    
    aggregates = evaluator.compute_aggregates(results)
    
    assert aggregates["context_precision"]["mean"] == 0.85
    assert aggregates["faithfulness"]["mean"] == 0.75


@pytest.mark.asyncio
async def test_pipeline_threshold_check():
    """Test pipeline threshold checking."""
    config = EvaluationConfig(
        min_context_precision=0.7,
        min_faithfulness=0.8,
    )
    
    pipeline = EvaluationPipeline.__new__(EvaluationPipeline)
    pipeline.config = config
    
    # Failing aggregates
    aggregates = {
        "context_precision": {"mean": 0.65},
        "faithfulness": {"mean": 0.85},
    }
    
    failures = pipeline._check_thresholds(aggregates)
    
    assert len(failures) == 1
    assert failures[0]["metric"] == "context_precision"


@pytest.mark.asyncio
async def test_json_reporter(tmp_path):
    """Test JSON file reporter."""
    reporter = JSONFileReporter(str(tmp_path))
    
    result = PipelineResult(
        run_id="test-run",
        dataset_name="test",
        dataset_version="1.0.0",
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        sample_count=10,
        results=[],
        aggregates={"context_precision": {"mean": 0.85}},
        passed=True,
        failures=[],
    )
    
    await reporter.report(result)
    
    files = list(tmp_path.glob("evaluation_*.json"))
    assert len(files) == 1
```

## Integration Tests

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_evaluation_pipeline():
    """Test full evaluation pipeline with real RAG."""
    config = EvaluationConfig.from_env()
    
    # Create mock RAG client
    class MockRAGClient:
        async def query(self, question: str, return_contexts: bool = False):
            return Mock(
                answer="This is the answer.",
                contexts=[Mock(text="Context 1"), Mock(text="Context 2")],
            )
    
    dataset = EvaluationDataset(
        name="integration-test",
        version="1.0.0",
        samples=[
            EvaluationSample(
                id="s1",
                question="Test question?",
                answer="",
                contexts=[],
                ground_truth="Expected answer.",
            ),
        ],
    )
    
    pipeline = EvaluationPipeline(
        config=config,
        rag_client=MockRAGClient(),
    )
    
    result = await pipeline.run(dataset)
    
    assert result.sample_count == 1
    assert "context_precision" in result.aggregates


@pytest.mark.integration
def test_prometheus_metrics_export():
    """Test Prometheus metrics are exported."""
    from prometheus_client import REGISTRY
    
    aggregates = {
        "context_precision": {"mean": 0.85, "std": 0.05},
        "faithfulness": {"mean": 0.75, "std": 0.10},
    }
    
    pipeline = EvaluationPipeline.__new__(EvaluationPipeline)
    pipeline.config = EvaluationConfig()
    pipeline._export_to_prometheus(aggregates)
    
    # Check metrics exist
    sample = REGISTRY.get_sample_value(
        "rag_evaluation_context_precision",
        {"stat": "mean"},
    )
    assert sample == 0.85
```

## Dependencies

```
ragas>=0.1.0
langchain-openai>=0.0.5
langchain-anthropic>=0.0.1  # Optional
datasets>=2.14.0
pandas>=2.0.0
celery>=5.3.0  # For scheduling
```

## Definition of Done

- [ ] EvaluationConfig with LLM and metric selection
- [ ] RagasEvaluator with all standard metrics
- [ ] EvaluationSample and EvaluationDataset models
- [ ] Dataset loading from JSON
- [ ] Dataset storage in PostgreSQL
- [ ] EvaluationPipeline with full workflow
- [ ] RAG pipeline integration for live evaluation
- [ ] Aggregate statistics computation
- [ ] Threshold checking with failures
- [ ] Results stored to PostgreSQL
- [ ] Prometheus metrics exported
- [ ] Celery scheduled tasks configured
- [ ] Weekly and daily evaluation schedules
- [ ] Slack alerting on failures
- [ ] Grafana annotation reporter
- [ ] JSON file reporter
- [ ] Kubernetes CronJob manifest
- [ ] Golden test dataset created
- [ ] >90% test coverage
- [ ] Documentation complete

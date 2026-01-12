"""
Evaluation Data Persistence.

Provides comprehensive persistence for evaluation datasets, runs, and results.
"""

import json
import logging
from typing import Any
from uuid import uuid4

from .datasets import EvaluationDataset, EvaluationSample
from .ragas_evaluator import AggregatedResults

logger = logging.getLogger(__name__)


class EvaluationRepository:
    """
    Repository for evaluation data persistence.

    Provides CRUD operations for:
    - Datasets
    - Examples
    - Runs
    - Metrics
    """

    def __init__(self, connection_url: str, table_prefix: str = "eval_"):
        """
        Initialize repository.

        Args:
            connection_url: PostgreSQL connection URL
            table_prefix: Prefix for table names
        """
        self.connection_url = connection_url
        self.table_prefix = table_prefix
        self._pool = None

    async def _get_pool(self):
        """Get or create connection pool."""
        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                self.connection_url,
                min_size=2,
                max_size=10,
            )
        return self._pool

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    # =========================================================================
    # Dataset Operations
    # =========================================================================

    async def create_dataset(
        self,
        name: str,
        description: str = "",
        version: str = "1.0.0",
        config: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Create a new evaluation dataset.

        Args:
            name: Dataset name (unique)
            description: Dataset description
            version: Dataset version
            config: Configuration options
            metadata: Additional metadata

        Returns:
            Dataset ID
        """
        pool = await self._get_pool()
        dataset_id = str(uuid4())

        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.table_prefix}datasets
                (id, name, description, version, config, metadata, example_count)
                VALUES ($1, $2, $3, $4, $5, $6, 0)
                """,
                dataset_id,
                name,
                description,
                version,
                json.dumps(config or {}),
                json.dumps(metadata or {}),
            )

        logger.info(f"Created dataset {dataset_id}: {name}")
        return dataset_id

    async def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        """Get a dataset by ID."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.table_prefix}datasets WHERE id = $1",
                dataset_id,
            )

            if row:
                return dict(row)
            return None

    async def get_dataset_by_name(self, name: str) -> dict[str, Any] | None:
        """Get a dataset by name."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.table_prefix}datasets WHERE name = $1",
                name,
            )

            if row:
                return dict(row)
            return None

    async def list_datasets(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List all datasets."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM {self.table_prefix}datasets
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )

            return [dict(row) for row in rows]

    async def delete_dataset(self, dataset_id: str) -> bool:
        """Delete a dataset and its examples."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            result = await conn.execute(
                f"DELETE FROM {self.table_prefix}datasets WHERE id = $1",
                dataset_id,
            )

            return result == "DELETE 1"

    # =========================================================================
    # Example Operations
    # =========================================================================

    async def add_example(
        self,
        dataset_id: str,
        question: str,
        contexts: list[str],
        answer: str = "",
        ground_truth: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Add an example to a dataset.

        Args:
            dataset_id: Dataset ID
            question: The question
            contexts: Retrieved/expected contexts
            answer: Generated answer
            ground_truth: Ground truth answer
            metadata: Additional metadata

        Returns:
            Example ID
        """
        import hashlib

        pool = await self._get_pool()
        example_id = str(uuid4())

        # Generate content hash for deduplication
        content = f"{question}{''.join(sorted(contexts))}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                f"""
                INSERT INTO {self.table_prefix}examples
                (id, dataset_id, question, contexts, answer, ground_truth, metadata, content_hash)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                example_id,
                dataset_id,
                question,
                json.dumps(contexts),
                answer,
                ground_truth,
                json.dumps(metadata or {}),
                content_hash,
            )

            # Update example count
            await conn.execute(
                f"""
                UPDATE {self.table_prefix}datasets
                SET example_count = example_count + 1, updated_at = NOW()
                WHERE id = $1
                """,
                dataset_id,
            )

        return example_id

    async def add_examples_bulk(
        self,
        dataset_id: str,
        examples: list[EvaluationSample],
    ) -> int:
        """
        Add multiple examples to a dataset.

        Args:
            dataset_id: Dataset ID
            examples: List of examples

        Returns:
            Number of examples added
        """
        import hashlib

        pool = await self._get_pool()
        count = 0

        async with pool.acquire() as conn, conn.transaction():
            for sample in examples:
                example_id = sample.id or str(uuid4())
                content = f"{sample.question}{''.join(sorted(sample.contexts))}"
                content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

                await conn.execute(
                    f"""
                    INSERT INTO {self.table_prefix}examples
                    (id, dataset_id, question, contexts, answer, ground_truth, metadata, content_hash)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    example_id,
                    dataset_id,
                    sample.question,
                    json.dumps(sample.contexts),
                    sample.answer,
                    sample.ground_truth,
                    json.dumps(sample.metadata),
                    content_hash,
                )
                count += 1

            # Update example count
            await conn.execute(
                f"""
                UPDATE {self.table_prefix}datasets
                SET example_count = (
                    SELECT COUNT(*) FROM {self.table_prefix}examples WHERE dataset_id = $1
                ), updated_at = NOW()
                WHERE id = $1
                """,
                dataset_id,
            )

        logger.info(f"Added {count} examples to dataset {dataset_id}")
        return count

    async def get_examples(
        self,
        dataset_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get examples for a dataset."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM {self.table_prefix}examples
                WHERE dataset_id = $1
                ORDER BY created_at
                LIMIT $2 OFFSET $3
                """,
                dataset_id,
                limit,
                offset,
            )

            return [dict(row) for row in rows]

    async def load_dataset(self, dataset_id: str) -> EvaluationDataset | None:
        """
        Load a full dataset with examples.

        Args:
            dataset_id: Dataset ID

        Returns:
            EvaluationDataset or None
        """
        dataset = await self.get_dataset(dataset_id)
        if not dataset:
            return None

        examples = await self.get_examples(dataset_id, limit=10000)

        samples = [
            EvaluationSample(
                id=str(ex["id"]),
                question=ex["question"],
                contexts=ex["contexts"]
                if isinstance(ex["contexts"], list)
                else json.loads(ex["contexts"]),
                answer=ex.get("answer", ""),
                ground_truth=ex.get("ground_truth"),
                metadata=ex.get("metadata", {}),
            )
            for ex in examples
        ]

        return EvaluationDataset(
            name=dataset["name"],
            samples=samples,
            version=dataset.get("version", "1.0.0"),
            description=dataset.get("description", ""),
            metadata=dataset.get("metadata", {}),
        )

    async def save_dataset(self, dataset: EvaluationDataset) -> str:
        """
        Save a dataset to the database.

        Args:
            dataset: Dataset to save

        Returns:
            Dataset ID
        """
        # Check if dataset exists
        existing = await self.get_dataset_by_name(dataset.name)

        if existing:
            dataset_id = str(existing["id"])
            # Update metadata
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    f"""
                    UPDATE {self.table_prefix}datasets
                    SET version = $1, description = $2, metadata = $3, updated_at = NOW()
                    WHERE id = $4
                    """,
                    dataset.version,
                    dataset.description,
                    json.dumps(dataset.metadata),
                    dataset_id,
                )
        else:
            dataset_id = await self.create_dataset(
                name=dataset.name,
                description=dataset.description,
                version=dataset.version,
                metadata=dataset.metadata,
            )

        # Add examples
        await self.add_examples_bulk(dataset_id, dataset.samples)

        return dataset_id

    # =========================================================================
    # Run Operations
    # =========================================================================

    async def create_run(
        self,
        name: str,
        dataset_id: str | None = None,
        dataset_name: str | None = None,
        config: dict[str, Any] | None = None,
        pipeline_version: str | None = None,
        model_version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Create a new evaluation run.

        Args:
            name: Run name
            dataset_id: Dataset ID
            dataset_name: Dataset name (if ID not available)
            config: Run configuration
            pipeline_version: Pipeline version
            model_version: Model version
            metadata: Additional metadata

        Returns:
            Run ID
        """
        pool = await self._get_pool()
        run_id = str(uuid4())

        async with pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO {self.table_prefix}runs
                (id, name, dataset_id, dataset_name, status, config,
                 pipeline_version, model_version, metadata)
                VALUES ($1, $2, $3, $4, 'running', $5, $6, $7, $8)
                """,
                run_id,
                name,
                dataset_id,
                dataset_name,
                json.dumps(config or {}),
                pipeline_version,
                model_version,
                json.dumps(metadata or {}),
            )

        logger.info(f"Created run {run_id}: {name}")
        return run_id

    async def update_run_status(
        self,
        run_id: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update run status."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            if status in ["completed", "failed"]:
                await conn.execute(
                    f"""
                    UPDATE {self.table_prefix}runs
                    SET status = $1, completed_at = NOW(), error_message = $2
                    WHERE id = $3
                    """,
                    status,
                    error_message,
                    run_id,
                )
            else:
                await conn.execute(
                    f"""
                    UPDATE {self.table_prefix}runs
                    SET status = $1
                    WHERE id = $2
                    """,
                    status,
                    run_id,
                )

    async def save_run_results(
        self,
        run_id: str,
        results: AggregatedResults,
    ) -> None:
        """
        Save run results.

        Args:
            run_id: Run ID
            results: Aggregated results
        """
        pool = await self._get_pool()

        async with pool.acquire() as conn, conn.transaction():
            # Update run with summary
            await conn.execute(
                f"""
                    UPDATE {self.table_prefix}runs
                    SET status = 'completed',
                        completed_at = NOW(),
                        total_samples = $1,
                        successful_samples = $2,
                        failed_samples = $3,
                        aggregated_scores = $4,
                        metadata = metadata || $5
                    WHERE id = $6
                    """,
                results.total_samples,
                results.successful_samples,
                results.failed_samples,
                json.dumps(results.aggregated_metrics),
                json.dumps(results.metadata),
                run_id,
            )

            # Insert individual metrics
            for metric_name, stats in results.aggregated_metrics.items():
                await conn.execute(
                    f"""
                        INSERT INTO {self.table_prefix}metrics
                        (run_id, metric_name, mean, std, min, max, median)
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (run_id, metric_name) DO UPDATE SET
                            mean = EXCLUDED.mean,
                            std = EXCLUDED.std,
                            min = EXCLUDED.min,
                            max = EXCLUDED.max,
                            median = EXCLUDED.median
                        """,
                    run_id,
                    metric_name,
                    stats["mean"],
                    stats["std"],
                    stats["min"],
                    stats["max"],
                    stats["median"],
                )

        logger.info(f"Saved results for run {run_id}")

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Get a run by ID."""
        pool = await self._get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                f"SELECT * FROM {self.table_prefix}runs WHERE id = $1",
                run_id,
            )

            if row:
                result = dict(row)

                # Get metrics
                metrics = await conn.fetch(
                    f"SELECT * FROM {self.table_prefix}metrics WHERE run_id = $1",
                    run_id,
                )
                result["metrics"] = [dict(m) for m in metrics]

                return result
            return None

    async def list_runs(
        self,
        dataset_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List runs with optional filters."""
        pool = await self._get_pool()

        query = f"SELECT * FROM {self.table_prefix}runs WHERE 1=1"
        params = []

        if dataset_id:
            params.append(dataset_id)
            query += f" AND dataset_id = ${len(params)}"

        if status:
            params.append(status)
            query += f" AND status = ${len(params)}"

        params.append(limit)
        query += f" ORDER BY started_at DESC LIMIT ${len(params)}"

        params.append(offset)
        query += f" OFFSET ${len(params)}"

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def get_metric_trend(
        self,
        metric_name: str,
        dataset_id: str | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """Get metric values over time."""
        pool = await self._get_pool()

        query = f"""
            SELECT r.started_at, m.mean, m.std, r.name as run_name
            FROM {self.table_prefix}metrics m
            JOIN {self.table_prefix}runs r ON m.run_id = r.id
            WHERE m.metric_name = $1 AND r.status = 'completed'
        """
        params = [metric_name]

        if dataset_id:
            params.append(dataset_id)
            query += f" AND r.dataset_id = ${len(params)}"

        params.append(limit)
        query += f" ORDER BY r.started_at DESC LIMIT ${len(params)}"

        async with pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [dict(row) for row in rows]

    async def compare_runs(
        self,
        run_id_1: str,
        run_id_2: str,
    ) -> dict[str, Any]:
        """Compare metrics between two runs."""
        run1 = await self.get_run(run_id_1)
        run2 = await self.get_run(run_id_2)

        if not run1 or not run2:
            return {"error": "One or both runs not found"}

        comparison = {
            "run1": {
                "id": run_id_1,
                "name": run1["name"],
                "started_at": run1["started_at"].isoformat() if run1["started_at"] else None,
            },
            "run2": {
                "id": run_id_2,
                "name": run2["name"],
                "started_at": run2["started_at"].isoformat() if run2["started_at"] else None,
            },
            "metrics": {},
        }

        # Build metric lookup
        metrics1 = {m["metric_name"]: m for m in run1.get("metrics", [])}
        metrics2 = {m["metric_name"]: m for m in run2.get("metrics", [])}

        all_metrics = set(metrics1.keys()) | set(metrics2.keys())

        for metric_name in all_metrics:
            m1 = metrics1.get(metric_name, {})
            m2 = metrics2.get(metric_name, {})

            mean1 = m1.get("mean", 0)
            mean2 = m2.get("mean", 0)
            delta = mean2 - mean1

            comparison["metrics"][metric_name] = {
                "run1": mean1,
                "run2": mean2,
                "delta": delta,
                "percent_change": (delta / mean1 * 100) if mean1 != 0 else 0,
            }

        return comparison

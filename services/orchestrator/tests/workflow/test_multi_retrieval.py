"""Tests for multi-retrieval node (US-10.4.4)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from workflow.nodes.multi_retrieval import (
    SubQueryResult,
    _aggregate_results,
    _format_multi_hop_context,
    multi_retrieval_node,
)
from workflow.state import create_initial_state


class TestSubQueryResult:
    """Tests for SubQueryResult dataclass."""

    def test_creates_result(self):
        """Test creating a sub-query result."""
        result = SubQueryResult(
            sub_question="What is Python?",
            documents=[{"chunk_id": "abc", "content": "Python is..."}],
            latency_ms=50.0,
        )

        assert result.sub_question == "What is Python?"
        assert len(result.documents) == 1
        assert result.latency_ms == 50.0


class TestAggregateResults:
    """Tests for _aggregate_results function."""

    def test_aggregates_single_result(self):
        """Test aggregation with single sub-question result."""
        results = [
            SubQueryResult(
                sub_question="q1",
                documents=[
                    {"chunk_id": "a", "content": "doc a", "score": 0.9},
                    {"chunk_id": "b", "content": "doc b", "score": 0.8},
                ],
                latency_ms=100,
            )
        ]

        aggregated = _aggregate_results(results)

        assert len(aggregated.documents) == 2
        assert aggregated.total_retrieved == 2
        assert aggregated.deduplicated_count == 2
        assert "a" in aggregated.sub_question_mapping
        assert aggregated.sub_question_mapping["a"] == ["q1"]

    def test_deduplicates_across_sub_questions(self):
        """Test that same chunk from multiple sub-questions is deduplicated."""
        results = [
            SubQueryResult(
                sub_question="q1",
                documents=[{"chunk_id": "a", "content": "doc a", "score": 0.9}],
                latency_ms=100,
            ),
            SubQueryResult(
                sub_question="q2",
                documents=[{"chunk_id": "a", "content": "doc a", "score": 0.8}],
                latency_ms=100,
            ),
        ]

        aggregated = _aggregate_results(results)

        assert len(aggregated.documents) == 1
        assert aggregated.total_retrieved == 2
        assert aggregated.deduplicated_count == 1
        assert aggregated.sub_question_mapping["a"] == ["q1", "q2"]

    def test_boosts_score_for_multi_relevant_documents(self):
        """Test score boosting for documents relevant to multiple sub-questions."""
        results = [
            SubQueryResult(
                sub_question="q1",
                documents=[{"chunk_id": "a", "content": "doc a", "score": 0.9}],
                latency_ms=100,
            ),
            SubQueryResult(
                sub_question="q2",
                documents=[{"chunk_id": "a", "content": "doc a", "score": 0.8}],
                latency_ms=100,
            ),
        ]

        aggregated = _aggregate_results(results)

        # Score should be boosted: 0.9 + (0.8 * 0.5) = 1.3
        assert aggregated.documents[0]["score"] > 0.9

    def test_respects_max_documents_limit(self):
        """Test that results are limited to max_documents."""
        results = [
            SubQueryResult(
                sub_question="q1",
                documents=[
                    {"chunk_id": f"doc{i}", "content": f"content {i}", "score": 1.0 - i * 0.1}
                    for i in range(10)
                ],
                latency_ms=100,
            )
        ]

        aggregated = _aggregate_results(results, max_documents=5)

        assert len(aggregated.documents) == 5
        assert aggregated.deduplicated_count == 5

    def test_sorts_by_score_descending(self):
        """Test that results are sorted by score in descending order."""
        results = [
            SubQueryResult(
                sub_question="q1",
                documents=[
                    {"chunk_id": "low", "content": "low", "score": 0.3},
                    {"chunk_id": "high", "content": "high", "score": 0.9},
                    {"chunk_id": "mid", "content": "mid", "score": 0.6},
                ],
                latency_ms=100,
            )
        ]

        aggregated = _aggregate_results(results)

        assert aggregated.documents[0]["chunk_id"] == "high"
        assert aggregated.documents[1]["chunk_id"] == "mid"
        assert aggregated.documents[2]["chunk_id"] == "low"

    def test_handles_empty_results(self):
        """Test handling of empty results."""
        results = [
            SubQueryResult(sub_question="q1", documents=[], latency_ms=50),
            SubQueryResult(sub_question="q2", documents=[], latency_ms=50),
        ]

        aggregated = _aggregate_results(results)

        assert len(aggregated.documents) == 0
        assert aggregated.total_retrieved == 0
        assert aggregated.deduplicated_count == 0

    def test_handles_missing_chunk_id(self):
        """Test that documents without chunk_id are skipped."""
        results = [
            SubQueryResult(
                sub_question="q1",
                documents=[
                    {"chunk_id": "a", "content": "doc a", "score": 0.9},
                    {"content": "no id", "score": 0.8},  # Missing chunk_id
                ],
                latency_ms=100,
            )
        ]

        aggregated = _aggregate_results(results)

        assert len(aggregated.documents) == 1
        assert aggregated.documents[0]["chunk_id"] == "a"


class TestFormatMultiHopContext:
    """Tests for _format_multi_hop_context function."""

    def test_formats_single_query_simply(self):
        """Test simple formatting for single query (no sub-questions)."""
        documents = [
            {"chunk_id": "a", "content": "Content A", "source": "source1.pdf"},
            {"chunk_id": "b", "content": "Content B", "source": "source2.pdf"},
        ]
        mapping = {"a": ["What is X?"], "b": ["What is X?"]}

        context = _format_multi_hop_context(documents, mapping, ["What is X?"])

        assert "[Document 1: source1.pdf]" in context
        assert "Content A" in context
        assert "Sub-question" not in context

    def test_formats_multi_hop_with_sections(self):
        """Test multi-hop formatting groups by sub-question."""
        documents = [
            {"chunk_id": "a", "content": "Content A", "source": "source1.pdf"},
            {"chunk_id": "b", "content": "Content B", "source": "source2.pdf"},
        ]
        mapping = {"a": ["What is X?"], "b": ["What is Y?"]}

        context = _format_multi_hop_context(documents, mapping, ["What is X?", "What is Y?"])

        assert "Sub-question 1: What is X?" in context
        assert "Sub-question 2: What is Y?" in context
        assert "Content A" in context
        assert "Content B" in context

    def test_handles_empty_documents(self):
        """Test handling of empty documents list."""
        context = _format_multi_hop_context([], {}, ["q1"])

        assert context == ""


class TestMultiRetrievalNode:
    """Tests for multi_retrieval_node."""

    @pytest.mark.asyncio
    async def test_falls_back_to_original_query_without_sub_questions(self):
        """Test that original query is used when no sub-questions present."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="What is Python?",
        )

        with patch("workflow.nodes.multi_retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            # Use MagicMock for response (not async) - only post() is async
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "results": [{"chunk_id": "a", "content": "Python is...", "score": 0.9}]
            }
            mock_response.raise_for_status.return_value = None
            mock_instance.post.return_value = mock_response
            mock_get_client.return_value = mock_instance

            result = await multi_retrieval_node(state)

        # Should have called retrieval once (for original query)
        assert mock_instance.post.call_count == 1
        assert len(result["documents"]) == 1
        assert result["retrieval_stats"]["sub_questions"] == 1

    @pytest.mark.asyncio
    async def test_retrieves_for_multiple_sub_questions(self):
        """Test retrieval for multiple sub-questions."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Compare Python and Java",
        )
        state["sub_questions"] = ["What is Python?", "What is Java?"]

        with patch("workflow.nodes.multi_retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "results": [{"chunk_id": "a", "content": "content", "score": 0.9}]
            }
            mock_response.raise_for_status.return_value = None
            mock_instance.post.return_value = mock_response
            mock_get_client.return_value = mock_instance

            result = await multi_retrieval_node(state)

        # Should have called retrieval twice (once per sub-question)
        assert mock_instance.post.call_count == 2
        assert result["retrieval_stats"]["sub_questions"] == 2

    @pytest.mark.asyncio
    async def test_parallel_execution_is_faster_than_sequential(self):
        """Test that parallel retrieval is faster than sequential would be."""
        import time

        state = create_initial_state(
            request_id=str(uuid4()),
            query="Multi-part question",
        )
        state["sub_questions"] = ["q1", "q2", "q3"]

        async def slow_response(*args, **kwargs):
            await asyncio.sleep(0.1)  # 100ms delay
            mock_resp = AsyncMock()
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            return mock_resp

        with patch("workflow.nodes.multi_retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = slow_response
            mock_get_client.return_value = mock_instance

            start = time.time()
            await multi_retrieval_node(state)
            duration = time.time() - start

        # Parallel: should take ~100ms, not 300ms
        # Allow 200ms to account for overhead
        assert duration < 0.25, f"Expected parallel execution, but took {duration}s"

    @pytest.mark.asyncio
    async def test_handles_retrieval_errors_gracefully(self):
        """Test that errors for individual sub-questions don't fail the whole node."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Multi-part question",
        )
        state["sub_questions"] = ["q1", "q2"]

        call_count = 0

        async def mixed_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise httpx.ConnectError("Connection failed")
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "results": [{"chunk_id": "a", "content": "content", "score": 0.9}]
            }
            mock_resp.raise_for_status.return_value = None
            return mock_resp

        with patch("workflow.nodes.multi_retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = mixed_response
            mock_get_client.return_value = mock_instance

            result = await multi_retrieval_node(state)

        # Should still return results from successful sub-question
        assert len(result["documents"]) == 1
        assert "multi_retrieval" in result["timing"]

    @pytest.mark.asyncio
    async def test_deduplicates_results_from_multiple_sub_questions(self):
        """Test that same document from multiple sub-questions is deduplicated."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Multi-part question",
        )
        state["sub_questions"] = ["q1", "q2"]

        with patch("workflow.nodes.multi_retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_response = MagicMock()
            # Both sub-questions return the same document
            mock_response.json.return_value = {
                "results": [{"chunk_id": "same", "content": "same content", "score": 0.9}]
            }
            mock_response.raise_for_status.return_value = None
            mock_instance.post.return_value = mock_response
            mock_get_client.return_value = mock_instance

            result = await multi_retrieval_node(state)

        # Should deduplicate to single document
        assert len(result["documents"]) == 1
        assert result["retrieval_stats"]["total_retrieved"] == 2
        assert result["retrieval_stats"]["after_dedup"] == 1
        # Should track which sub-questions retrieved this doc
        assert len(result["sub_question_mapping"]["same"]) == 2

    @pytest.mark.asyncio
    async def test_records_timing(self):
        """Test that timing is recorded."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
        )

        with patch("workflow.nodes.multi_retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"results": []}
            mock_response.raise_for_status.return_value = None
            mock_instance.post.return_value = mock_response
            mock_get_client.return_value = mock_instance

            result = await multi_retrieval_node(state)

        assert "multi_retrieval" in result["timing"]
        assert result["timing"]["multi_retrieval"] >= 0

    @pytest.mark.asyncio
    async def test_preserves_existing_state(self):
        """Test that existing state fields are preserved."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
            session_id=str(uuid4()),
        )
        state["strategy"] = "complex"
        state["timing"] = {"routing": 5.0}

        with patch("workflow.nodes.multi_retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"results": []}
            mock_response.raise_for_status.return_value = None
            mock_instance.post.return_value = mock_response
            mock_get_client.return_value = mock_instance

            result = await multi_retrieval_node(state)

        assert result["session_id"] == state["session_id"]
        assert result["strategy"] == "complex"
        assert result["timing"]["routing"] == 5.0

    @pytest.mark.asyncio
    async def test_uses_tenant_filter(self):
        """Test that tenant_id is passed to retrieval."""
        tenant_id = "test-tenant"
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
            tenant_id=tenant_id,
        )

        with patch("workflow.nodes.multi_retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"results": []}
            mock_response.raise_for_status.return_value = None
            mock_instance.post.return_value = mock_response
            mock_get_client.return_value = mock_instance

            await multi_retrieval_node(state)

        # Check that tenant_id was included in the request
        call_args = mock_instance.post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload.get("filters", {}).get("tenant_id") == tenant_id

    @pytest.mark.asyncio
    async def test_respects_options_for_top_k(self):
        """Test that options control retrieval parameters."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Test query",
            options={"sub_question_top_k": 5, "max_total_documents": 10},
        )

        with patch("workflow.nodes.multi_retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"results": []}
            mock_response.raise_for_status.return_value = None
            mock_instance.post.return_value = mock_response
            mock_get_client.return_value = mock_instance

            await multi_retrieval_node(state)

        # Check that top_k was set from options
        call_args = mock_instance.post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload.get("top_k") == 5

    @pytest.mark.asyncio
    async def test_enables_rerank_for_comparison_strategy(self):
        """Comparison strategy should enable reranking by default."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Compare Python and Java",
        )
        state["strategy"] = "comparison"
        state["intent"] = "ANALYTICAL"

        with patch("workflow.nodes.multi_retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"results": []}
            mock_response.raise_for_status.return_value = None
            mock_instance.post.return_value = mock_response
            mock_get_client.return_value = mock_instance

            await multi_retrieval_node(state)

        call_args = mock_instance.post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload.get("rerank") is True

    @pytest.mark.asyncio
    async def test_respects_rerank_override(self):
        """Explicit rerank option should override strategy-based defaults."""
        state = create_initial_state(
            request_id=str(uuid4()),
            query="Compare Python and Java",
            options={"rerank": False},
        )
        state["strategy"] = "comparison"
        state["intent"] = "ANALYTICAL"

        with patch("workflow.nodes.multi_retrieval.get_retrieval_client") as mock_get_client:
            mock_instance = AsyncMock()
            mock_response = MagicMock()
            mock_response.json.return_value = {"results": []}
            mock_response.raise_for_status.return_value = None
            mock_instance.post.return_value = mock_response
            mock_get_client.return_value = mock_instance

            await multi_retrieval_node(state)

        call_args = mock_instance.post.call_args
        payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
        assert payload.get("rerank") is False

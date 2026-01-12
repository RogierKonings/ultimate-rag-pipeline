"""
Unit tests for Gateway Models (US-5.7).

Tests OpenAI-compatible request/response models.
"""

import pytest
from gateway.models import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ChatMessageRole,
    EmbeddingData,
    EmbeddingRequest,
    EmbeddingResponse,
    ErrorResponse,
    ModelInfo,
    ModelListResponse,
    RerankRequest,
    RerankResponse,
    RerankResult,
    Usage,
)


class TestChatModels:
    """Tests for chat completion models."""

    def test_chat_message_creation(self):
        """Test creating a chat message."""
        msg = ChatMessage(
            role=ChatMessageRole.USER,
            content="Hello, how are you?",
        )

        assert msg.role == ChatMessageRole.USER
        assert msg.content == "Hello, how are you?"
        assert msg.name is None

    def test_chat_message_with_name(self):
        """Test chat message with function name."""
        msg = ChatMessage(
            role=ChatMessageRole.FUNCTION,
            content='{"result": 42}',
            name="calculate",
        )

        assert msg.role == ChatMessageRole.FUNCTION
        assert msg.name == "calculate"

    def test_chat_completion_request_minimal(self):
        """Test minimal chat completion request."""
        request = ChatCompletionRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role=ChatMessageRole.USER, content="Hello"),
            ],
        )

        assert request.model == "gpt-4"
        assert len(request.messages) == 1
        assert request.temperature == 0.7  # default
        assert request.stream is False  # default

    def test_chat_completion_request_full(self):
        """Test chat completion request with all parameters."""
        request = ChatCompletionRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role=ChatMessageRole.SYSTEM, content="You are helpful"),
                ChatMessage(role=ChatMessageRole.USER, content="Hello"),
            ],
            temperature=0.5,
            top_p=0.9,
            n=2,
            max_tokens=100,
            stop=["###"],
            presence_penalty=0.5,
            frequency_penalty=0.5,
            stream=True,
            seed=42,
        )

        assert request.temperature == 0.5
        assert request.n == 2
        assert request.stream is True
        assert request.seed == 42

    def test_chat_completion_request_validation(self):
        """Test validation of chat completion parameters."""
        # Valid temperature
        ChatCompletionRequest(
            model="test",
            messages=[ChatMessage(role=ChatMessageRole.USER, content="Hi")],
            temperature=0.0,
        )
        ChatCompletionRequest(
            model="test",
            messages=[ChatMessage(role=ChatMessageRole.USER, content="Hi")],
            temperature=2.0,
        )

        # Invalid temperature
        with pytest.raises(ValueError):
            ChatCompletionRequest(
                model="test",
                messages=[ChatMessage(role=ChatMessageRole.USER, content="Hi")],
                temperature=2.5,
            )

    def test_chat_completion_response(self):
        """Test chat completion response creation."""
        response = ChatCompletionResponse(
            model="gpt-4",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(
                        role=ChatMessageRole.ASSISTANT,
                        content="Hello! I'm doing well.",
                    ),
                    finish_reason="stop",
                ),
            ],
            usage=Usage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )

        assert response.object == "chat.completion"
        assert response.model == "gpt-4"
        assert len(response.choices) == 1
        assert response.choices[0].finish_reason == "stop"
        assert response.usage.total_tokens == 30
        assert response.id.startswith("chatcmpl-")


class TestEmbeddingModels:
    """Tests for embedding models."""

    def test_embedding_request_single(self):
        """Test embedding request with single input."""
        request = EmbeddingRequest(
            model="text-embedding-ada-002",
            input="Hello, world!",
        )

        assert request.model == "text-embedding-ada-002"
        assert request.input == "Hello, world!"
        assert request.encoding_format == "float"

    def test_embedding_request_batch(self):
        """Test embedding request with batch input."""
        request = EmbeddingRequest(
            model="text-embedding-ada-002",
            input=["Hello", "World", "Test"],
        )

        assert len(request.input) == 3

    def test_embedding_request_base64(self):
        """Test embedding request with base64 encoding."""
        request = EmbeddingRequest(
            model="test",
            input="Hello",
            encoding_format="base64",
        )

        assert request.encoding_format == "base64"

    def test_embedding_data(self):
        """Test embedding data creation."""
        data = EmbeddingData(
            index=0,
            embedding=[0.1, 0.2, 0.3, 0.4],
        )

        assert data.object == "embedding"
        assert data.index == 0
        assert len(data.embedding) == 4

    def test_embedding_response(self):
        """Test embedding response creation."""
        response = EmbeddingResponse(
            data=[
                EmbeddingData(index=0, embedding=[0.1, 0.2]),
                EmbeddingData(index=1, embedding=[0.3, 0.4]),
            ],
            model="text-embedding-ada-002",
            usage=Usage(prompt_tokens=10, total_tokens=10),
        )

        assert response.object == "list"
        assert len(response.data) == 2
        assert response.model == "text-embedding-ada-002"


class TestRerankModels:
    """Tests for rerank models."""

    def test_rerank_request_strings(self):
        """Test rerank request with string documents."""
        request = RerankRequest(
            model="rerank-v1",
            query="What is machine learning?",
            documents=["ML is a subset of AI", "Python is a language"],
        )

        assert request.model == "rerank-v1"
        assert len(request.documents) == 2
        assert request.top_n is None
        assert request.return_documents is False

    def test_rerank_request_dicts(self):
        """Test rerank request with dict documents."""
        request = RerankRequest(
            model="rerank-v1",
            query="Test query",
            documents=[
                {"text": "Document 1", "id": "doc1"},
                {"text": "Document 2", "id": "doc2"},
            ],
            top_n=5,
            return_documents=True,
        )

        assert request.top_n == 5
        assert request.return_documents is True

    def test_rerank_result(self):
        """Test rerank result creation."""
        result = RerankResult(
            index=0,
            relevance_score=0.95,
        )

        assert result.index == 0
        assert result.relevance_score == 0.95
        assert result.document is None

    def test_rerank_result_with_document(self):
        """Test rerank result with document."""
        result = RerankResult(
            index=1,
            relevance_score=0.85,
            document="This is the document text",
        )

        assert result.document == "This is the document text"

    def test_rerank_response(self):
        """Test rerank response creation."""
        response = RerankResponse(
            results=[
                RerankResult(index=1, relevance_score=0.95),
                RerankResult(index=0, relevance_score=0.75),
            ],
            model="rerank-v1",
        )

        assert len(response.results) == 2
        assert response.results[0].relevance_score > response.results[1].relevance_score
        assert response.id.startswith("rerank-")


class TestCommonModels:
    """Tests for common models."""

    def test_usage(self):
        """Test usage model."""
        usage = Usage(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )

        assert usage.prompt_tokens == 100
        assert usage.completion_tokens == 50
        assert usage.total_tokens == 150

    def test_usage_defaults(self):
        """Test usage model defaults."""
        usage = Usage()

        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0

    def test_error_response_create(self):
        """Test creating error response."""
        error = ErrorResponse.create(
            message="Invalid model",
            error_type="invalid_request_error",
            code="model_not_found",
            param="model",
        )

        assert error.error["message"] == "Invalid model"
        assert error.error["type"] == "invalid_request_error"
        assert error.error["code"] == "model_not_found"
        assert error.error["param"] == "model"

    def test_error_response_minimal(self):
        """Test minimal error response."""
        error = ErrorResponse.create("Something went wrong")

        assert error.error["message"] == "Something went wrong"
        assert error.error["type"] == "invalid_request_error"
        assert "code" not in error.error

    def test_model_info(self):
        """Test model info creation."""
        info = ModelInfo(
            id="gpt-4",
            owned_by="openai",
        )

        assert info.id == "gpt-4"
        assert info.object == "model"
        assert info.owned_by == "openai"

    def test_model_list_response(self):
        """Test model list response."""
        response = ModelListResponse(
            data=[
                ModelInfo(id="gpt-4", owned_by="openai"),
                ModelInfo(id="gpt-3.5-turbo", owned_by="openai"),
            ],
        )

        assert response.object == "list"
        assert len(response.data) == 2

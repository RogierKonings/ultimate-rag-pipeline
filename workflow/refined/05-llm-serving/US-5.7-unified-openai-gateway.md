# US-5.7: Unified OpenAI Gateway (Chat/Embeddings/Rerank)

## Goal
Expose a single OpenAI-compatible gateway covering chat completions, embeddings, and rerank endpoints for orchestrator/retrieval.

## Requirements
- Implement routes: `/v1/chat/completions`, `/v1/embeddings`, `/v1/rerank` (or `/v1/rerankings`) with OpenAI-like request/response shapes.
- Route requests to vLLM (chat), embedding service, and reranker service; support streaming for chat.
- Surface model configs and limits from configuration; include model names per architecture defaults.
- Include health and readiness endpoints; OpenAPI docs published.

## Acceptance Criteria
- OpenAI SDK can call chat and embeddings without code changes; rerank endpoint documented and tested.
- Responses include model, usage tokens (where applicable), and match expected schemas.
- Gateway handles batch embedding/rerank; returns proper errors for unsupported models.
- Tested integration with orchestrator and retrieval services.

## Verification
- `pytest tests/api/test_gateway_openai_contract.py`
- `openai api chat.completions.create …` against gateway succeeds; embeddings and rerank cURL tests pass.

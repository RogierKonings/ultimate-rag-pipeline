# Orchestrator Model and Retrieval Policy

This document describes the latest orchestrator capabilities for stage-aware model selection, retrieval optimization, and cache-key consistency.

## Scope

These capabilities are implemented in the orchestrator service and used by:

- Sync workflow generation (`workflow/nodes/generation.py`)
- Streaming query path (`api/routes/query.py`)
- Query decomposition (`workflow/nodes/decomposition.py`)
- Answer verification (`workflow/nodes/verification.py`)
- Retrieval and multi-retrieval nodes (`workflow/nodes/retrieval.py`, `workflow/nodes/multi_retrieval.py`)
- Answer cache hashing (`workflow/nodes/cache_check.py`, `cache/answer_cache.py`)

## 1. Centralized Stage-Aware Model Policy

Model decisions are centralized in `services/orchestrator/model_policy.py` so all LLM stages use consistent routing logic.

### Stage routing

- `select_generation_model(...)`:
  - Used by sync generation and streaming
  - Inputs: `tenant_tier`, `strategy`, `intent`, optional token/model overrides
- `select_decomposition_model(...)`:
  - Defaults decomposition to small tier for cost/latency efficiency
- `select_verification_model(...)`:
  - Uses generation policy baseline
  - Caps large-tier selections to medium for verification cost control

### Routing signals used by policy

The workflow routing node writes these state fields:

- `strategy`
- `intent`
- `complexity_score`

These signals are then reused for model and retrieval decisions across stages.

### Request-level model overrides

Supported overrides:

- Global model override:
  - `options.model`
- Per-stage overrides:
  - `options.stage_models.generation`
  - `options.stage_models.streaming`
  - `options.stage_models.decomposition`
  - `options.stage_models.verification`

If a stage override is set, it takes precedence for that stage.

## 2. Policy-Based Retrieval Tuning

Retrieval parameter selection is centralized in `services/orchestrator/retrieval/policy.py`.

### Rerank decision logic

`should_enable_rerank(...)` uses this order:

1. Explicit request override (`rerank`) if provided
2. Complex strategies (`complex`, `multi_hop`, `comparison`, `aggregation`)
3. Analytical intent (`ANALYTICAL`)
4. High complexity score fallback (`>= 0.75`)
5. Otherwise disabled

This keeps simple factual requests fast while enabling reranking where quality impact is highest.

### Retrieval option normalization

`get_retrieval_option(...)` supports both new and legacy request formats:

- Preferred nested options:
  - `options.retrieval.mode`
  - `options.retrieval.top_k`
  - `options.retrieval.rerank`
  - `options.retrieval.sub_question_top_k`
  - `options.retrieval.max_total_documents`
- Legacy top-level options (still supported):
  - `options.retrieval_mode`
  - `options.top_k`
  - `options.rerank`
  - `options.sub_question_top_k`
  - `options.max_total_documents`

`coerce_positive_int(...)` guards invalid `top_k` values and falls back safely.

### Where policy is applied

- `workflow/nodes/retrieval.py`
- `workflow/nodes/multi_retrieval.py`
- `api/routes/query.py` (streaming retrieval prefetch)
- `retrieval/client.py` now accepts explicit `rerank`

## 3. Cache-Key Alignment With Retrieval Policy

Answer cache hashing now uses the same effective retrieval settings as runtime retrieval behavior.

### What changed

- `workflow/nodes/cache_check.py` computes config hash using policy-resolved:
  - retrieval mode
  - top-k
  - rerank decision
- Cache check runs before routing, so it infers strategy from query heuristics when routing state is not yet present.
- `cache/answer_cache.py` now defaults `_compute_config_hash(..., rerank=False)` for consistency with simple-query defaults.

### Why it matters

Previously, cache hashes could diverge from actual retrieval behavior (especially rerank defaults), reducing hit quality and predictability. Hashing now reflects effective retrieval policy.

## 4. Observability

Retrieval nodes emit policy-related span attributes:

- `orchestrator.retrieval_mode`
- `orchestrator.retrieval_rerank`
- `orchestrator.retrieval_top_k`

This makes policy decisions visible in traces and easier to debug.

## 5. Request Examples

### Per-stage model override + retrieval override

```json
{
  "query": "Compare Python and Java for backend systems",
  "options": {
    "stage_models": {
      "generation": "llama-3.1-70b",
      "verification": "llama-3.1-13b"
    },
    "retrieval": {
      "mode": "hybrid",
      "top_k": 40,
      "rerank": true
    }
  }
}
```

### Lightweight/fast path override

```json
{
  "query": "What is Python?",
  "options": {
    "model": "qwen2.5-7b",
    "retrieval": {
      "top_k": 8,
      "rerank": false
    }
  }
}
```

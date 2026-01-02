# US-3.10: API Contract & Hybrid Alignment

## Goal
Align retrieval API responses and hybrid flow ordering with architecture (RRF → rerank → ACL) and debug payload.

## Requirements
- Enforce hybrid ordering: RRF fuse top-N semantic/keyword results, rerank top-K, apply ACL filter post-rerank.
- Default weights/top_k consistent with architecture (semantic 0.7, keyword 0.3, RRF top 50, rerank top 10).
- API response includes debug block: counts per stage, latency breakdown, model names, retrieval_id.
- Validate request/response schemas match `docs/architecture.md` Retrieval API example.

## Acceptance Criteria
- Integration test confirms ordering (ACL applied after rerank) and scores reflect weights.
- API returns debug block fields; contract changes documented if diverging.
- Configurable weights/top_k exposed with sane bounds; validation prevents invalid values.
- P95 latency <200ms maintained with instrumentation in debug.

## Verification
- `pytest tests/api/test_retrieve_contract.py`
- `curl -X POST /api/v1/retrieve …` returns debug with latency fields and retrieval_id.

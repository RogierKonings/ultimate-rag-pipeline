# US-3.9: Retrieval Cache (Redis)

## Goal
Implement Redis-based retrieval caching per architecture caching strategy to reduce latency and cost.

## Requirements
- Cache key derived from query + filters (stable json) using SHA-256 prefix; namespace `rag:query:<hash>`.
- TTL configurable (default 3600s); invalidate on ACL-relevant changes or embeddings re-embed jobs if signaled.
- Respect top_k and options in cache key; include user/tenant scoping.
- Metrics: cache hits/misses, TTL, eviction; expose Prometheus counters.

## Acceptance Criteria
- Cache hit returns response under TTL with correct tenant/ACL scoping.
- Cache key includes query, filters, options; collisions avoided.
- Hit rate metric captured; tests assert behavior for different filters/users.
- Feature flag to disable cache per environment.

## Verification
- `pytest tests/retrieval/test_cache.py`
- `curl /metrics | grep rag_cache_hits_total`

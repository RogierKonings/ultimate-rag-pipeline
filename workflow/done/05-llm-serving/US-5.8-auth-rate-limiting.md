# US-5.8: Auth & Rate Limiting for Gateway

## Goal
Enforce JWT validation and rate limiting on the LLM gateway consistent with Security epic policies.

## Requirements
- Validate JWT (RS256) with issuer/audience; extract tenant/user/roles for logging/quotas.
- Apply per-tenant and per-user rate limits (token bucket or sliding window); configurable limits.
- Propagate auth context to downstream services (vLLM/embedding/reranker) via headers.
- Return 401/403/429 as appropriate; structured error payloads.

## Acceptance Criteria
- Requests without valid JWT are rejected; valid tokens pass through and context is logged.
- Rate limits enforced with clear 429 response and retry-after header.
- Downstream requests include tenant/user context headers for auditing.
- Tests cover success, auth failure, rate limit hit.

## Verification
- `pytest tests/security/test_gateway_auth_rate_limit.py`
- Load test demonstrates 429 when exceeding configured RPS for tenant/user.

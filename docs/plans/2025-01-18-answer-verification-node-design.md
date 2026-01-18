# Answer Verification Node Design

> **User Story:** US-10.4.1
> **Date:** 2025-01-18
> **Status:** Approved

## Overview

Add a CRAG-style (Corrective RAG) verification node to the LangGraph workflow that validates generated answers against retrieved context before returning to the user.

## Architecture

### File Structure

```
services/orchestrator/workflow/
├── verification/
│   ├── __init__.py
│   ├── claim_extractor.py    # Extracts claims from answer
│   ├── claim_verifier.py     # Verifies claims against context
│   └── models.py             # Pydantic models for claims/results
├── nodes/
│   └── verification.py       # The workflow node
└── ...
```

### Workflow Position

```
input_validation → routing → retrieval → prompt_building → generation → verification → output_validation
```

The verification node is inserted between `generation` and `output_validation`.

## Data Models

### New Models (`workflow/verification/models.py`)

```python
from enum import Enum
from typing import Literal
from pydantic import BaseModel

class Claim(BaseModel):
    """A factual claim extracted from the answer."""
    text: str
    claim_type: Literal["factual", "numerical", "temporal", "attribution"]

class VerificationStatus(str, Enum):
    """Status of claim verification."""
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    UNVERIFIABLE = "unverifiable"

class ClaimVerificationResult(BaseModel):
    """Result of verifying a single claim."""
    claim_text: str
    status: VerificationStatus
    supporting_evidence: str | None = None

class VerificationResult(BaseModel):
    """Overall verification result for the answer."""
    score: float              # 0-1, proportion of supported claims
    label: str                # "supported", "partial", "unsupported", "skipped"
    claims_total: int
    claims_supported: int
    claims_partial: int
    claims_unsupported: int
    verification_time_ms: float
    skipped: bool = False
    skip_reason: str | None = None
```

### RAGState Additions

```python
# New fields in RAGState TypedDict
verification_result: dict | None   # VerificationResult as dict
```

### Configuration Additions

```python
# New fields in OrchestratorConfig
verification_enabled: bool = False          # Global default (opt-in)
verification_max_claims: int = 5
verification_confidence_threshold: float = 0.7
verification_add_disclaimer: bool = True
```

## Component Design

### ClaimExtractor

Extracts verifiable factual claims from the generated answer.

- Uses LLM with structured prompt requesting JSON array output
- Limits to `max_claims` (default 5) most important claims
- Categorizes claims by type (factual, numerical, temporal, attribution)
- Uses `temperature=0.0` for deterministic extraction
- Returns empty list on parse errors (graceful degradation)

### ClaimVerifier

Verifies each claim against the retrieved context.

- For each claim, asks LLM: "Is this claim supported by the context?"
- Returns status: `supported`, `partially_supported`, `unsupported`, `unverifiable`
- Extracts supporting evidence quote when found
- **Runs all claim verifications in parallel** using `asyncio.gather()`
- Uses `temperature=0.0` for consistency

### Score Calculation

```python
# full support = 1.0, partial = 0.5, unsupported/unverifiable = 0.0
score = (supported + 0.5 * partial) / total_claims

# Label thresholds
if score >= 0.9: label = "supported"
elif score >= 0.5: label = "partial"
else: label = "unsupported"
```

## Verification Node Logic

### Skip Conditions

The node returns early with `skipped=True` when:

| Condition | skip_reason |
|-----------|-------------|
| `enable_verification=False` in options | `"verification_disabled"` |
| No documents retrieved | `"no_context"` |
| No response generated (error state) | `"no_response"` |
| No claims extracted from answer | `"no_claims_extracted"` |

### Low-Confidence Disclaimer

When `score < verification_confidence_threshold` and `verification_add_disclaimer=True`:

```
*Note: Some information in this response could not be fully verified
against the available sources. Please verify important details independently.*
```

Appended to `state["response"]`.

## Graph Changes

```python
# workflow/graph.py

# Add verification node
graph.add_node("verification", verification_node)

# Update edges
graph.add_edge("generation", "verification")
graph.add_edge("verification", "output_validation")
# Remove: graph.add_edge("generation", "output_validation")
```

## LLM Integration

Uses existing `ModelGateway.chat_completion()` for all LLM calls:
- No new HTTP client code
- Inherits retry logic, fallback handling, and error mapping
- Gateway instance passed via dependency injection or created in node

## Implementation Steps

1. Create `workflow/verification/models.py` with Pydantic models
2. Create `workflow/verification/claim_extractor.py`
3. Create `workflow/verification/claim_verifier.py`
4. Create `workflow/verification/__init__.py` with exports
5. Add config fields to `OrchestratorConfig`
6. Add `verification_result` field to `RAGState`
7. Create `workflow/nodes/verification.py` with the node function
8. Update `workflow/graph.py` to include verification node
9. Write unit tests for extractor and verifier
10. Write integration tests for verification in workflow
11. Update API response schema to include verification_result

## Testing Strategy

### Unit Tests
- ClaimExtractor: extraction, JSON parsing, error handling
- ClaimVerifier: verification status mapping, parallel execution
- VerificationResult: score calculation, label thresholds

### Integration Tests
- Verification disabled: should skip
- Verification enabled with good context: should return high score
- Verification enabled with poor context: should add disclaimer
- No documents retrieved: should skip

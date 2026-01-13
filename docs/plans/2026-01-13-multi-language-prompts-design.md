# Multi-Language Prompt Templates Design

**Date:** 2026-01-13
**Status:** Approved

## Overview

Implement language detection and multi-language prompt templates so the LLM responds in the same language as the user's query. Initial support for English and Dutch, with an extensible design for adding more languages.

## Architecture

### Components

1. **Language Detection** (`guardrails/detection.py`)
   - Uses `langdetect` library for lightweight detection
   - Falls back to English for unsupported languages or detection failures
   - Minimum text length threshold (10 chars) before detection

2. **Template Structure** (`prompts/templates.py`)
   - `Language` enum for supported languages
   - Nested `TEMPLATES` dict: `{language: {strategy: template}}`
   - Updated `get_template(name, language)` function

3. **PromptBuilder Integration** (`prompts/builder.py`)
   - Auto-detects language from query
   - Optional `language` parameter for explicit override
   - Passes language through to template selection

## Files to Modify

| File | Changes |
|------|---------|
| `services/orchestrator/guardrails/detection.py` | Add `detect_language()`, `SUPPORTED_LANGUAGES` |
| `services/orchestrator/prompts/templates.py` | Add `Language` enum, Dutch templates, restructure `TEMPLATES` |
| `services/orchestrator/prompts/builder.py` | Add language param to `build()`, `build_with_metadata()`, `_render_system_prompt()` |
| `services/orchestrator/requirements.txt` | Add `langdetect` |

## Implementation Details

### Language Detection

```python
SUPPORTED_LANGUAGES = {"en", "nl"}
DEFAULT_LANGUAGE = "en"

def detect_language(text: str) -> str:
    """Detect language, fallback to English."""
```

### Template Structure

```python
TEMPLATES = {
    "en": {"rag": ..., "no_context": ..., ...},
    "nl": {"rag": ..., "no_context": ..., ...},
}

def get_template(template_name: str, language: str = "en") -> str:
```

### PromptBuilder Changes

- `build()` gains optional `language` parameter
- Auto-detects from query if not provided
- `build_with_metadata()` returns detected language in response

## Dutch Templates

All six templates translated:
- `RAG_SYSTEM_PROMPT_NL`
- `RAG_CITATIONS_PROMPT_NL`
- `NO_CONTEXT_PROMPT_NL`
- `FOLLOW_UP_PROMPT_NL`
- `CLARIFICATION_PROMPT_NL`
- `SUMMARY_PROMPT_NL`

Key Dutch conventions:
- Citation format: `[Bron: titel]`
- "I don't have enough information" → "Ik heb niet genoeg informatie om deze vraag te beantwoorden"

## Extensibility

To add a new language:
1. Add language code to `SUPPORTED_LANGUAGES` in `detection.py`
2. Add translated templates to `TEMPLATES` dict in `templates.py`

## Backward Compatibility

- All existing API calls work unchanged
- English remains the default
- New `language` parameter is optional throughout

## Dependencies

- `langdetect` - Lightweight language detection (~1MB, no GPU)

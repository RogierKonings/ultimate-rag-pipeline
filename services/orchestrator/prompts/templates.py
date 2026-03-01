"""Jinja2 prompt templates for the Orchestrator Service.

This module contains the template strings used for building prompts
for different strategies (RAG, no-context, follow-up).

Supports multiple languages with automatic language detection.
"""

from enum import StrEnum


class Language(StrEnum):
    """Supported languages for prompt templates."""

    ENGLISH = "en"
    DUTCH = "nl"


# =============================================================================
# English Templates
# =============================================================================

# RAG System Prompt - Used when context from retrieval is available
RAG_SYSTEM_PROMPT_EN = """You are a helpful assistant that answers questions based on the provided context.

Context:
{{ context }}

Instructions:
- Answer based ONLY on the provided context
- If the answer isn't in the context, say so
- Cite sources using [Source: title] format
- Be concise and accurate
"""

# No Context Prompt - Used for direct questions without retrieval
NO_CONTEXT_PROMPT_EN = """You are a helpful assistant.

Instructions:
- Answer the user's question directly
- If you're uncertain, acknowledge it
- Be concise and helpful
"""

# Follow-up Prompt - Used when continuing a conversation
FOLLOW_UP_PROMPT_EN = """You are continuing a conversation with the user.

Previous context:
{{ summary }}

Instructions:
- Consider the conversation history
- Maintain consistency with previous responses
- Answer the new question
"""

# RAG with Citations Prompt - Enhanced RAG template with citation instructions
RAG_CITATIONS_PROMPT_EN = """You are a helpful assistant that answers questions based on the provided context.

Context:
{{ context }}

Sources:
{{ citations }}

Instructions:
- Answer based ONLY on the provided context
- If the answer isn't in the context, say "I don't have enough information to answer this question"
- Cite sources using [Source: title] format when referencing information
- Each fact should include its source citation
- Be concise, accurate, and well-structured
"""

# Clarification Prompt - Used when the query needs clarification
CLARIFICATION_PROMPT_EN = """You are a helpful assistant that helps clarify ambiguous questions.

User's question: {{ query }}

Instructions:
- Identify what aspects of the question need clarification
- Ask specific, targeted questions to understand the user's intent
- Keep your clarifying questions brief and focused
"""

# Summary Prompt - Used for summarizing conversation history
SUMMARY_PROMPT_EN = """Summarize the following conversation in a concise manner that captures the key points and context:

{{ conversation }}

Provide a brief summary (2-3 sentences) that captures:
- The main topics discussed
- Key information exchanged
- The current state of the conversation
"""

# =============================================================================
# Dutch Templates
# =============================================================================

# RAG System Prompt - Dutch
RAG_SYSTEM_PROMPT_NL = """Je bent een behulpzame assistent die vragen beantwoordt op basis van de verstrekte context.

Context:
{{ context }}

Instructies:
- Antwoord ALLEEN op basis van de verstrekte context
- Als het antwoord niet in de context staat, zeg dat dan
- Citeer bronnen met [Bron: titel] formaat
- Wees beknopt en nauwkeurig
"""

# No Context Prompt - Dutch
NO_CONTEXT_PROMPT_NL = """Je bent een behulpzame assistent.

Instructies:
- Beantwoord de vraag van de gebruiker direct
- Als je onzeker bent, geef dat aan
- Wees beknopt en behulpzaam
"""

# Follow-up Prompt - Dutch
FOLLOW_UP_PROMPT_NL = """Je vervolgt een gesprek met de gebruiker.

Vorige context:
{{ summary }}

Instructies:
- Houd rekening met de gespreksgeschiedenis
- Blijf consistent met eerdere antwoorden
- Beantwoord de nieuwe vraag
"""

# RAG with Citations Prompt - Dutch
RAG_CITATIONS_PROMPT_NL = """Je bent een behulpzame assistent die vragen beantwoordt op basis van de verstrekte context.

Context:
{{ context }}

Bronnen:
{{ citations }}

Instructies:
- Antwoord ALLEEN op basis van de verstrekte context
- Als het antwoord niet in de context staat, zeg "Ik heb niet genoeg informatie om deze vraag te beantwoorden"
- Citeer bronnen met [Bron: titel] formaat bij het verwijzen naar informatie
- Elk feit moet een bronvermelding bevatten
- Wees beknopt, nauwkeurig en goed gestructureerd
"""

# Clarification Prompt - Dutch
CLARIFICATION_PROMPT_NL = """Je bent een behulpzame assistent die helpt bij het verduidelijken van onduidelijke vragen.

Vraag van de gebruiker: {{ query }}

Instructies:
- Identificeer welke aspecten van de vraag verduidelijking nodig hebben
- Stel specifieke, gerichte vragen om de bedoeling van de gebruiker te begrijpen
- Houd je verduidelijkende vragen kort en gefocust
"""

# Summary Prompt - Dutch
SUMMARY_PROMPT_NL = """Vat het volgende gesprek beknopt samen en leg de belangrijkste punten en context vast:

{{ conversation }}

Geef een korte samenvatting (2-3 zinnen) die het volgende bevat:
- De belangrijkste besproken onderwerpen
- Belangrijke uitgewisselde informatie
- De huidige stand van het gesprek
"""

# =============================================================================
# Template Registry
# =============================================================================

# Templates organized by language code, then by strategy
TEMPLATES = {
    "en": {
        "rag": RAG_SYSTEM_PROMPT_EN,
        "rag_citations": RAG_CITATIONS_PROMPT_EN,
        "no_context": NO_CONTEXT_PROMPT_EN,
        "follow_up": FOLLOW_UP_PROMPT_EN,
        "clarification": CLARIFICATION_PROMPT_EN,
        "summary": SUMMARY_PROMPT_EN,
    },
    "nl": {
        "rag": RAG_SYSTEM_PROMPT_NL,
        "rag_citations": RAG_CITATIONS_PROMPT_NL,
        "no_context": NO_CONTEXT_PROMPT_NL,
        "follow_up": FOLLOW_UP_PROMPT_NL,
        "clarification": CLARIFICATION_PROMPT_NL,
        "summary": SUMMARY_PROMPT_NL,
    },
}

# Default language for fallback
DEFAULT_LANGUAGE = "en"


def get_template(template_name: str, language: str = DEFAULT_LANGUAGE) -> str:
    """Get a template by name and language.

    Args:
        template_name: The name of the template to retrieve
            (e.g., 'rag', 'no_context', 'follow_up').
        language: ISO 639-1 language code (e.g., 'en', 'nl').
            Defaults to English. Falls back to English if the
            requested language is not available.

    Returns:
        The template string for the requested strategy and language.

    Raises:
        KeyError: If the template name is not found.
    """
    # Get templates for requested language, fallback to default
    lang_templates = TEMPLATES.get(language, TEMPLATES[DEFAULT_LANGUAGE])

    if template_name not in lang_templates:
        available = list(TEMPLATES[DEFAULT_LANGUAGE].keys())
        raise KeyError(f"Template '{template_name}' not found. Available: {available}")

    return lang_templates[template_name]


def list_templates() -> list[str]:
    """List all available template names.

    Returns:
        List of template names (same for all languages).
    """
    return list(TEMPLATES[DEFAULT_LANGUAGE].keys())


def list_languages() -> list[str]:
    """List all supported language codes.

    Returns:
        List of ISO 639-1 language codes.
    """
    return list(TEMPLATES.keys())


# =============================================================================
# Backward Compatibility
# =============================================================================
# These aliases maintain backward compatibility with existing code
# that imports template constants directly.

RAG_SYSTEM_PROMPT = RAG_SYSTEM_PROMPT_EN
NO_CONTEXT_PROMPT = NO_CONTEXT_PROMPT_EN
FOLLOW_UP_PROMPT = FOLLOW_UP_PROMPT_EN
RAG_CITATIONS_PROMPT = RAG_CITATIONS_PROMPT_EN
CLARIFICATION_PROMPT = CLARIFICATION_PROMPT_EN
SUMMARY_PROMPT = SUMMARY_PROMPT_EN

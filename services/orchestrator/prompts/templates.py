"""Jinja2 prompt templates for the Orchestrator Service.

This module contains the template strings used for building prompts
for different strategies (RAG, no-context, follow-up).
"""

# RAG System Prompt - Used when context from retrieval is available
RAG_SYSTEM_PROMPT = """You are a helpful assistant that answers questions based on the provided context.

Context:
{{ context }}

Instructions:
- Answer based ONLY on the provided context
- If the answer isn't in the context, say so
- Cite sources using [Source: title] format
- Be concise and accurate
"""

# No Context Prompt - Used for direct questions without retrieval
NO_CONTEXT_PROMPT = """You are a helpful assistant.

Instructions:
- Answer the user's question directly
- If you're uncertain, acknowledge it
- Be concise and helpful
"""

# Follow-up Prompt - Used when continuing a conversation
FOLLOW_UP_PROMPT = """You are continuing a conversation with the user.

Previous context:
{{ summary }}

Instructions:
- Consider the conversation history
- Maintain consistency with previous responses
- Answer the new question
"""

# RAG with Citations Prompt - Enhanced RAG template with citation instructions
RAG_CITATIONS_PROMPT = """You are a helpful assistant that answers questions based on the provided context.

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
CLARIFICATION_PROMPT = """You are a helpful assistant that helps clarify ambiguous questions.

User's question: {{ query }}

Instructions:
- Identify what aspects of the question need clarification
- Ask specific, targeted questions to understand the user's intent
- Keep your clarifying questions brief and focused
"""

# Summary Prompt - Used for summarizing conversation history
SUMMARY_PROMPT = """Summarize the following conversation in a concise manner that captures the key points and context:

{{ conversation }}

Provide a brief summary (2-3 sentences) that captures:
- The main topics discussed
- Key information exchanged
- The current state of the conversation
"""

# Template registry for easy lookup
TEMPLATES = {
    "rag": RAG_SYSTEM_PROMPT,
    "rag_citations": RAG_CITATIONS_PROMPT,
    "no_context": NO_CONTEXT_PROMPT,
    "follow_up": FOLLOW_UP_PROMPT,
    "clarification": CLARIFICATION_PROMPT,
    "summary": SUMMARY_PROMPT,
}


def get_template(template_name: str) -> str:
    """Get a template by name.

    Args:
        template_name: The name of the template to retrieve.

    Returns:
        The template string.

    Raises:
        KeyError: If the template name is not found.
    """
    if template_name not in TEMPLATES:
        raise KeyError(f"Template '{template_name}' not found. Available: {list(TEMPLATES.keys())}")
    return TEMPLATES[template_name]


def list_templates() -> list[str]:
    """List all available template names.

    Returns:
        List of template names.
    """
    return list(TEMPLATES.keys())

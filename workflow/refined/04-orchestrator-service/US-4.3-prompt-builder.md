# US-4.3: Prompt Builder

> **Story ID:** US-4.3  
> **Epic:** Orchestrator Service  
> **Priority:** Critical  
> **Estimated Effort:** 2 days  
> **Dependencies:** US-4.1 (LangGraph Workflow)

## User Story

**As a** developer  
**I want** flexible prompt construction  
**So that** prompts are optimized for different use cases

## Context

The prompt builder constructs optimized prompts for the LLM by combining the user query, retrieved context, conversation history, and system instructions. It uses Jinja2 templates for flexibility and handles token limits to ensure prompts fit within model constraints. Different templates are used for different query strategies and use cases.

## Technical Requirements

### Directory Structure

```
orchestrator-service/
└── prompts/
    ├── __init__.py
    ├── builder.py           # Prompt builder
    ├── templates.py         # Prompt templates
    ├── context.py           # Context formatting
    ├── tokenizer.py         # Token counting
    └── templates/           # Template files
        ├── rag_default.j2
        ├── rag_no_context.j2
        ├── rag_conversational.j2
        └── system_prompts.j2
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal
from enum import Enum

class PromptTemplate(str, Enum):
    RAG_DEFAULT = "rag_default"
    RAG_NO_CONTEXT = "rag_no_context"
    RAG_CONVERSATIONAL = "rag_conversational"
    RAG_MULTI_STEP = "rag_multi_step"
    CLARIFICATION = "clarification"

class PromptConfig(BaseModel):
    """Configuration for prompt builder."""
    # Token limits
    max_prompt_tokens: int = 4096
    max_context_tokens: int = 2048
    max_history_tokens: int = 1024
    reserved_output_tokens: int = 1024
    
    # Model-specific settings
    model: str = "meta-llama/Llama-3.1-8B-Instruct"
    tokenizer_model: str = "meta-llama/Llama-3.1-8B-Instruct"
    
    # Template settings
    default_template: PromptTemplate = PromptTemplate.RAG_DEFAULT
    templates_dir: str = "prompts/templates"
    
    # Context formatting
    include_sources: bool = True
    include_scores: bool = False
    max_context_chunks: int = 5
    context_separator: str = "\n\n---\n\n"
    
    # System prompt
    system_prompt: Optional[str] = None
    
    # Few-shot examples
    include_examples: bool = False
    max_examples: int = 2

class FormattedContext(BaseModel):
    """Formatted context for prompt."""
    content: str
    sources: list[str] = []
    token_count: int = 0
    chunks_used: int = 0
    chunks_truncated: int = 0

class BuiltPrompt(BaseModel):
    """Result of prompt building."""
    prompt: str
    template_used: PromptTemplate
    token_count: int
    context_token_count: int
    history_token_count: int
    truncation_applied: bool = False
```

### Prompt Builder Implementation

```python
from typing import Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape
import tiktoken

class PromptBuilder:
    """
    Builds optimized prompts for RAG queries.
    
    Features:
    - Jinja2 template-based prompt construction
    - Token-aware context truncation
    - Conversation history management
    - Source citation formatting
    - Multiple template support for different strategies
    """
    
    DEFAULT_SYSTEM_PROMPT = """You are a helpful AI assistant that answers questions based on the provided context. 
When answering:
- Use information from the context when available
- Cite sources using [Source: filename] format when referencing specific information
- If the context doesn't contain enough information, say so clearly
- Be concise but thorough
- If asked about topics not in the context, use your general knowledge but indicate this"""
    
    def __init__(self, config: PromptConfig = PromptConfig()):
        self.config = config
        self._tokenizer = TokenCounter(config.tokenizer_model)
        self._env = self._setup_jinja_env()
        self._context_formatter = ContextFormatter(config)
    
    def _setup_jinja_env(self) -> Environment:
        """Set up Jinja2 environment with templates."""
        env = Environment(
            loader=FileSystemLoader(self.config.templates_dir),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True
        )
        
        # Add custom filters
        env.filters['truncate_tokens'] = self._truncate_tokens
        
        return env
    
    async def build(
        self,
        query: str,
        contexts: list,  # list[RetrievedContext]
        history: Optional[list] = None,  # list[Message]
        strategy: Optional[str] = None,
        template: Optional[PromptTemplate] = None
    ) -> str:
        """
        Build a prompt from query, context, and history.
        
        Args:
            query: User's query
            contexts: Retrieved context chunks
            history: Conversation history
            strategy: Query strategy for template selection
            template: Explicit template override
        
        Returns:
            Constructed prompt string
        """
        # Select template
        selected_template = self._select_template(template, strategy, contexts)
        
        # Format context with token management
        formatted_context = self._context_formatter.format(
            contexts,
            max_tokens=self.config.max_context_tokens
        )
        
        # Format history with token management
        formatted_history = self._format_history(
            history or [],
            max_tokens=self.config.max_history_tokens
        )
        
        # Get system prompt
        system_prompt = self.config.system_prompt or self.DEFAULT_SYSTEM_PROMPT
        
        # Render template
        try:
            jinja_template = self._env.get_template(f"{selected_template.value}.j2")
            prompt = jinja_template.render(
                query=query,
                context=formatted_context.content,
                sources=formatted_context.sources,
                history=formatted_history,
                system_prompt=system_prompt
            )
        except Exception:
            # Fallback to inline template
            prompt = self._build_inline(
                query, formatted_context, formatted_history, system_prompt
            )
        
        # Final token check and truncation if needed
        prompt = self._ensure_token_limit(prompt)
        
        return prompt
    
    async def build_with_metadata(
        self,
        query: str,
        contexts: list,
        history: Optional[list] = None,
        strategy: Optional[str] = None,
        template: Optional[PromptTemplate] = None
    ) -> BuiltPrompt:
        """Build prompt and return with metadata."""
        prompt = await self.build(query, contexts, history, strategy, template)
        
        selected_template = self._select_template(template, strategy, contexts)
        formatted_context = self._context_formatter.format(contexts)
        
        return BuiltPrompt(
            prompt=prompt,
            template_used=selected_template,
            token_count=self._tokenizer.count(prompt),
            context_token_count=formatted_context.token_count,
            history_token_count=self._count_history_tokens(history or []),
            truncation_applied=formatted_context.chunks_truncated > 0
        )
    
    def _select_template(
        self,
        template: Optional[PromptTemplate],
        strategy: Optional[str],
        contexts: list
    ) -> PromptTemplate:
        """Select appropriate template based on context."""
        if template:
            return template
        
        # No contexts -> use no_context template
        if not contexts:
            return PromptTemplate.RAG_NO_CONTEXT
        
        # Map strategy to template
        strategy_map = {
            "simple": PromptTemplate.RAG_DEFAULT,
            "complex": PromptTemplate.RAG_MULTI_STEP,
            "no_retrieval": PromptTemplate.RAG_NO_CONTEXT,
            "clarification": PromptTemplate.CLARIFICATION,
        }
        
        return strategy_map.get(strategy, self.config.default_template)
    
    def _format_history(
        self,
        history: list,  # list[Message]
        max_tokens: int
    ) -> str:
        """Format conversation history with token limit."""
        if not history:
            return ""
        
        formatted_messages = []
        total_tokens = 0
        
        # Process from most recent to oldest
        for msg in reversed(history):
            role = msg.role.upper()
            content = msg.content
            msg_text = f"{role}: {content}"
            
            msg_tokens = self._tokenizer.count(msg_text)
            
            if total_tokens + msg_tokens > max_tokens:
                # Truncate this message to fit
                remaining = max_tokens - total_tokens
                if remaining > 50:
                    msg_text = self._truncate_tokens(msg_text, remaining)
                    formatted_messages.insert(0, msg_text)
                break
            
            total_tokens += msg_tokens
            formatted_messages.insert(0, msg_text)
        
        return "\n".join(formatted_messages)
    
    def _count_history_tokens(self, history: list) -> int:
        """Count tokens in history."""
        return sum(
            self._tokenizer.count(f"{m.role}: {m.content}")
            for m in history
        )
    
    def _truncate_tokens(self, text: str, max_tokens: int) -> str:
        """Truncate text to max tokens."""
        return self._tokenizer.truncate(text, max_tokens)
    
    def _ensure_token_limit(self, prompt: str) -> str:
        """Ensure prompt is within token limit."""
        max_tokens = self.config.max_prompt_tokens - self.config.reserved_output_tokens
        
        token_count = self._tokenizer.count(prompt)
        if token_count <= max_tokens:
            return prompt
        
        return self._tokenizer.truncate(prompt, max_tokens)
    
    def _build_inline(
        self,
        query: str,
        context: FormattedContext,
        history: str,
        system_prompt: str
    ) -> str:
        """Build prompt using inline template as fallback."""
        parts = [f"System: {system_prompt}", ""]
        
        if context.content:
            parts.append("Context:")
            parts.append(context.content)
            parts.append("")
        
        if history:
            parts.append("Conversation History:")
            parts.append(history)
            parts.append("")
        
        parts.append(f"User: {query}")
        parts.append("")
        parts.append("Assistant:")
        
        return "\n".join(parts)


class ContextFormatter:
    """
    Formats retrieved contexts for prompt inclusion.
    
    Handles:
    - Token-aware truncation
    - Source citation formatting
    - Score-based prioritization
    """
    
    def __init__(self, config: PromptConfig):
        self.config = config
        self._tokenizer = TokenCounter(config.tokenizer_model)
    
    def format(
        self,
        contexts: list,  # list[RetrievedContext]
        max_tokens: Optional[int] = None
    ) -> FormattedContext:
        """
        Format contexts for prompt inclusion.
        
        Prioritizes higher-scoring contexts and truncates
        to fit within token limit.
        """
        if not contexts:
            return FormattedContext(content="", token_count=0, chunks_used=0)
        
        max_tokens = max_tokens or self.config.max_context_tokens
        max_chunks = self.config.max_context_chunks
        
        # Sort by score descending
        sorted_contexts = sorted(contexts, key=lambda c: c.score, reverse=True)
        
        formatted_chunks = []
        sources = []
        total_tokens = 0
        chunks_used = 0
        
        for ctx in sorted_contexts[:max_chunks]:
            # Format this chunk
            chunk_text = self._format_chunk(ctx)
            chunk_tokens = self._tokenizer.count(chunk_text)
            
            # Check if it fits
            if total_tokens + chunk_tokens > max_tokens:
                # Try to fit partial
                remaining = max_tokens - total_tokens
                if remaining > 100:
                    truncated = self._tokenizer.truncate(chunk_text, remaining)
                    formatted_chunks.append(truncated)
                    chunks_used += 1
                break
            
            formatted_chunks.append(chunk_text)
            total_tokens += chunk_tokens
            chunks_used += 1
            
            if ctx.source:
                sources.append(ctx.source)
        
        content = self.config.context_separator.join(formatted_chunks)
        
        return FormattedContext(
            content=content,
            sources=list(set(sources)),
            token_count=total_tokens,
            chunks_used=chunks_used,
            chunks_truncated=len(contexts) - chunks_used
        )
    
    def _format_chunk(self, ctx) -> str:
        """Format a single context chunk."""
        parts = []
        
        # Add source reference
        if self.config.include_sources and ctx.source:
            parts.append(f"[Source: {ctx.source}]")
        
        if ctx.title:
            parts.append(f"Title: {ctx.title}")
        
        parts.append(ctx.content)
        
        if self.config.include_scores:
            parts.append(f"(Relevance: {ctx.score:.2f})")
        
        return "\n".join(parts)


class TokenCounter:
    """
    Counts and manages tokens using tiktoken.
    """
    
    def __init__(self, model: str = "meta-llama/Llama-3.1-8B-Instruct"):
        # Use cl100k_base encoding as approximation for Llama
        try:
            self._encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            self._encoding = tiktoken.get_encoding("gpt2")
    
    def count(self, text: str) -> int:
        """Count tokens in text."""
        return len(self._encoding.encode(text))
    
    def truncate(self, text: str, max_tokens: int) -> str:
        """Truncate text to max tokens."""
        tokens = self._encoding.encode(text)
        
        if len(tokens) <= max_tokens:
            return text
        
        # Truncate tokens and decode
        truncated_tokens = tokens[:max_tokens]
        truncated_text = self._encoding.decode(truncated_tokens)
        
        # Add ellipsis to indicate truncation
        return truncated_text + "..."
    
    def split_by_tokens(self, text: str, chunk_size: int) -> list[str]:
        """Split text into chunks of approximately chunk_size tokens."""
        tokens = self._encoding.encode(text)
        chunks = []
        
        for i in range(0, len(tokens), chunk_size):
            chunk_tokens = tokens[i:i + chunk_size]
            chunk_text = self._encoding.decode(chunk_tokens)
            chunks.append(chunk_text)
        
        return chunks
```

### Jinja2 Templates

```jinja2
{# templates/rag_default.j2 #}
{{ system_prompt }}

{% if context %}
## Retrieved Context

{{ context }}

{% endif %}
{% if history %}
## Conversation History

{{ history }}

{% endif %}
## Current Question

{{ query }}

## Instructions

Please answer the question based on the context provided above. If the context doesn't contain relevant information, say so and use your general knowledge if appropriate. Cite sources when referencing specific information from the context.

Answer:
```

```jinja2
{# templates/rag_no_context.j2 #}
{{ system_prompt }}

{% if history %}
## Conversation History

{{ history }}

{% endif %}
## Question

{{ query }}

## Instructions

Please answer the question using your general knowledge. Be helpful and accurate.

Answer:
```

```jinja2
{# templates/rag_conversational.j2 #}
{{ system_prompt }}

{% if context %}
## Relevant Information

{{ context }}

{% endif %}
{% if history %}
## Previous Messages

{{ history }}

{% endif %}
User: {{ query }}

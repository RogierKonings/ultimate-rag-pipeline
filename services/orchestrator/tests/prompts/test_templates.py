"""Tests for prompt templates."""

import pytest
from jinja2 import BaseLoader, Environment
from prompts.templates import (
    CLARIFICATION_PROMPT,
    CLARIFICATION_PROMPT_EN,
    CLARIFICATION_PROMPT_NL,
    DEFAULT_LANGUAGE,
    FOLLOW_UP_PROMPT,
    FOLLOW_UP_PROMPT_EN,
    FOLLOW_UP_PROMPT_NL,
    NO_CONTEXT_PROMPT,
    NO_CONTEXT_PROMPT_EN,
    NO_CONTEXT_PROMPT_NL,
    RAG_CITATIONS_PROMPT,
    RAG_CITATIONS_PROMPT_EN,
    RAG_CITATIONS_PROMPT_NL,
    RAG_SYSTEM_PROMPT,
    RAG_SYSTEM_PROMPT_EN,
    RAG_SYSTEM_PROMPT_NL,
    SUMMARY_PROMPT,
    SUMMARY_PROMPT_EN,
    SUMMARY_PROMPT_NL,
    TEMPLATES,
    Language,
    get_template,
    list_languages,
    list_templates,
)


class TestTemplateConstants:
    """Tests for template constant strings."""

    def test_rag_system_prompt_contains_context_placeholder(self):
        """RAG prompt should have context placeholder."""
        assert "{{ context }}" in RAG_SYSTEM_PROMPT

    def test_rag_system_prompt_contains_instructions(self):
        """RAG prompt should contain instruction section."""
        assert "Instructions:" in RAG_SYSTEM_PROMPT
        assert "Answer based ONLY on the provided context" in RAG_SYSTEM_PROMPT
        assert "Cite sources" in RAG_SYSTEM_PROMPT

    def test_no_context_prompt_has_no_context_placeholder(self):
        """No-context prompt should not have context placeholder."""
        assert "{{ context }}" not in NO_CONTEXT_PROMPT

    def test_no_context_prompt_contains_instructions(self):
        """No-context prompt should have helpful assistant instructions."""
        assert "helpful assistant" in NO_CONTEXT_PROMPT
        assert "Instructions:" in NO_CONTEXT_PROMPT

    def test_follow_up_prompt_contains_summary_placeholder(self):
        """Follow-up prompt should have summary placeholder."""
        assert "{{ summary }}" in FOLLOW_UP_PROMPT

    def test_follow_up_prompt_references_conversation(self):
        """Follow-up prompt should reference conversation continuity."""
        assert "conversation" in FOLLOW_UP_PROMPT.lower()

    def test_rag_citations_prompt_has_citations_placeholder(self):
        """RAG citations prompt should have citations placeholder."""
        assert "{{ citations }}" in RAG_CITATIONS_PROMPT
        assert "{{ context }}" in RAG_CITATIONS_PROMPT

    def test_clarification_prompt_has_query_placeholder(self):
        """Clarification prompt should have query placeholder."""
        assert "{{ query }}" in CLARIFICATION_PROMPT

    def test_summary_prompt_has_conversation_placeholder(self):
        """Summary prompt should have conversation placeholder."""
        assert "{{ conversation }}" in SUMMARY_PROMPT


class TestTemplateRegistry:
    """Tests for the TEMPLATES registry."""

    def test_templates_dict_contains_all_languages(self):
        """Templates dict should contain all supported languages."""
        assert "en" in TEMPLATES
        assert "nl" in TEMPLATES

    def test_templates_dict_contains_all_strategies_per_language(self):
        """Templates dict should contain all expected strategies for each language."""
        expected_keys = [
            "rag",
            "rag_citations",
            "no_context",
            "follow_up",
            "clarification",
            "summary",
        ]
        for lang in TEMPLATES:
            for key in expected_keys:
                assert key in TEMPLATES[lang], f"Template {key} missing for language {lang}"

    def test_templates_values_are_strings(self):
        """All template values should be non-empty strings."""
        for lang, lang_templates in TEMPLATES.items():
            for key, value in lang_templates.items():
                assert isinstance(value, str), f"Template {lang}/{key} should be a string"
                assert len(value) > 0, f"Template {lang}/{key} should not be empty"

    def test_english_rag_template_matches_constant(self):
        """TEMPLATES['en']['rag'] should match RAG_SYSTEM_PROMPT_EN."""
        assert TEMPLATES["en"]["rag"] == RAG_SYSTEM_PROMPT_EN

    def test_dutch_rag_template_matches_constant(self):
        """TEMPLATES['nl']['rag'] should match RAG_SYSTEM_PROMPT_NL."""
        assert TEMPLATES["nl"]["rag"] == RAG_SYSTEM_PROMPT_NL

    def test_backward_compatibility_constants(self):
        """Backward compatibility constants should match English templates."""
        assert RAG_SYSTEM_PROMPT == RAG_SYSTEM_PROMPT_EN
        assert NO_CONTEXT_PROMPT == NO_CONTEXT_PROMPT_EN
        assert FOLLOW_UP_PROMPT == FOLLOW_UP_PROMPT_EN
        assert RAG_CITATIONS_PROMPT == RAG_CITATIONS_PROMPT_EN
        assert CLARIFICATION_PROMPT == CLARIFICATION_PROMPT_EN
        assert SUMMARY_PROMPT == SUMMARY_PROMPT_EN


class TestGetTemplate:
    """Tests for the get_template function."""

    def test_get_template_returns_english_rag_by_default(self):
        """get_template('rag') should return English RAG template by default."""
        template = get_template("rag")
        assert template == RAG_SYSTEM_PROMPT_EN

    def test_get_template_returns_english_rag_explicitly(self):
        """get_template('rag', 'en') should return English RAG template."""
        template = get_template("rag", "en")
        assert template == RAG_SYSTEM_PROMPT_EN

    def test_get_template_returns_dutch_rag(self):
        """get_template('rag', 'nl') should return Dutch RAG template."""
        template = get_template("rag", "nl")
        assert template == RAG_SYSTEM_PROMPT_NL

    def test_get_template_returns_no_context(self):
        """get_template('no_context') should return no-context template."""
        template = get_template("no_context")
        assert template == NO_CONTEXT_PROMPT_EN

    def test_get_template_returns_dutch_no_context(self):
        """get_template('no_context', 'nl') should return Dutch no-context template."""
        template = get_template("no_context", "nl")
        assert template == NO_CONTEXT_PROMPT_NL

    def test_get_template_returns_follow_up(self):
        """get_template('follow_up') should return follow-up template."""
        template = get_template("follow_up")
        assert template == FOLLOW_UP_PROMPT_EN

    def test_get_template_raises_for_unknown(self):
        """get_template should raise KeyError for unknown template."""
        with pytest.raises(KeyError) as exc_info:
            get_template("nonexistent")
        assert "nonexistent" in str(exc_info.value)
        assert "Available:" in str(exc_info.value)

    def test_get_template_falls_back_to_english_for_unknown_language(self):
        """get_template should fall back to English for unknown language."""
        template = get_template("rag", "xx")
        assert template == RAG_SYSTEM_PROMPT_EN


class TestListTemplates:
    """Tests for the list_templates function."""

    def test_list_templates_returns_list(self):
        """list_templates should return a list."""
        templates = list_templates()
        assert isinstance(templates, list)

    def test_list_templates_contains_expected_names(self):
        """list_templates should contain all expected template names."""
        templates = list_templates()
        assert "rag" in templates
        assert "no_context" in templates
        assert "follow_up" in templates

    def test_list_templates_matches_default_language_keys(self):
        """list_templates should match default language TEMPLATES keys."""
        templates = list_templates()
        assert set(templates) == set(TEMPLATES[DEFAULT_LANGUAGE].keys())


class TestListLanguages:
    """Tests for the list_languages function."""

    def test_list_languages_returns_list(self):
        """list_languages should return a list."""
        languages = list_languages()
        assert isinstance(languages, list)

    def test_list_languages_contains_expected(self):
        """list_languages should contain expected language codes."""
        languages = list_languages()
        assert "en" in languages
        assert "nl" in languages

    def test_list_languages_matches_templates_keys(self):
        """list_languages should match TEMPLATES top-level keys."""
        languages = list_languages()
        assert set(languages) == set(TEMPLATES.keys())


class TestTemplateRendering:
    """Tests for Jinja2 template rendering."""

    @pytest.fixture
    def jinja_env(self):
        """Create a Jinja2 environment for testing."""
        return Environment(loader=BaseLoader())

    def test_render_rag_template_with_context(self, jinja_env):
        """RAG template should render with context variable."""
        template = jinja_env.from_string(RAG_SYSTEM_PROMPT)
        context_text = "Python is a versatile programming language."
        rendered = template.render(context=context_text)

        assert context_text in rendered
        assert "Instructions:" in rendered

    def test_render_rag_template_empty_context(self, jinja_env):
        """RAG template should handle empty context."""
        template = jinja_env.from_string(RAG_SYSTEM_PROMPT)
        rendered = template.render(context="")

        assert "Context:" in rendered
        assert "Instructions:" in rendered

    def test_render_follow_up_with_summary(self, jinja_env):
        """Follow-up template should render with summary variable."""
        template = jinja_env.from_string(FOLLOW_UP_PROMPT)
        summary_text = "User asked about Python basics. Assistant explained core concepts."
        rendered = template.render(summary=summary_text)

        assert summary_text in rendered

    def test_render_rag_citations_with_both_vars(self, jinja_env):
        """RAG citations template should render with context and citations."""
        template = jinja_env.from_string(RAG_CITATIONS_PROMPT)
        context_text = "Document content here."
        citations_text = "[1] Python Guide\n[2] Code Tutorial"
        rendered = template.render(context=context_text, citations=citations_text)

        assert context_text in rendered
        assert citations_text in rendered
        assert "Sources:" in rendered

    def test_render_clarification_with_query(self, jinja_env):
        """Clarification template should render with query variable."""
        template = jinja_env.from_string(CLARIFICATION_PROMPT)
        query_text = "How do I use it?"
        rendered = template.render(query=query_text)

        assert query_text in rendered

    def test_render_summary_with_conversation(self, jinja_env):
        """Summary template should render with conversation variable."""
        template = jinja_env.from_string(SUMMARY_PROMPT)
        conversation_text = "User: Hello\nAssistant: Hi!"
        rendered = template.render(conversation=conversation_text)

        assert conversation_text in rendered


class TestTemplateStructure:
    """Tests for template structural requirements."""

    def test_all_templates_are_valid_jinja2(self):
        """All templates should be valid Jinja2 templates."""
        env = Environment(loader=BaseLoader())
        for lang, lang_templates in TEMPLATES.items():
            for name, template_str in lang_templates.items():
                try:
                    env.from_string(template_str)
                except Exception as e:
                    pytest.fail(f"Template '{lang}/{name}' is not valid Jinja2: {e}")

    def test_english_rag_templates_have_citation_instructions(self):
        """English RAG templates should have citation instructions."""
        assert "[Source:" in RAG_SYSTEM_PROMPT_EN or "Cite sources" in RAG_SYSTEM_PROMPT_EN
        assert "[Source:" in RAG_CITATIONS_PROMPT_EN or "Cite sources" in RAG_CITATIONS_PROMPT_EN

    def test_dutch_rag_templates_have_citation_instructions(self):
        """Dutch RAG templates should have Dutch citation instructions."""
        assert "[Bron:" in RAG_SYSTEM_PROMPT_NL or "Citeer bronnen" in RAG_SYSTEM_PROMPT_NL
        assert "[Bron:" in RAG_CITATIONS_PROMPT_NL or "Citeer bronnen" in RAG_CITATIONS_PROMPT_NL

    def test_templates_have_reasonable_length(self):
        """Templates should not be excessively long."""
        max_length = 2000  # characters
        for lang, lang_templates in TEMPLATES.items():
            for name, template_str in lang_templates.items():
                assert len(template_str) < max_length, (
                    f"Template '{lang}/{name}' exceeds max length"
                )


class TestLanguageEnum:
    """Tests for the Language enum."""

    def test_language_enum_has_english(self):
        """Language enum should have ENGLISH."""
        assert Language.ENGLISH.value == "en"

    def test_language_enum_has_dutch(self):
        """Language enum should have DUTCH."""
        assert Language.DUTCH.value == "nl"


class TestDutchTemplates:
    """Tests for Dutch template content."""

    def test_dutch_rag_prompt_contains_dutch_text(self):
        """Dutch RAG prompt should contain Dutch instructions."""
        assert "behulpzame assistent" in RAG_SYSTEM_PROMPT_NL
        assert "Instructies:" in RAG_SYSTEM_PROMPT_NL
        assert "verstrekte context" in RAG_SYSTEM_PROMPT_NL

    def test_dutch_no_context_prompt_contains_dutch_text(self):
        """Dutch no-context prompt should contain Dutch instructions."""
        assert "behulpzame assistent" in NO_CONTEXT_PROMPT_NL
        assert "Instructies:" in NO_CONTEXT_PROMPT_NL

    def test_dutch_templates_have_same_placeholders_as_english(self):
        """Dutch templates should have the same Jinja2 placeholders as English."""
        # RAG templates should have {{ context }}
        assert "{{ context }}" in RAG_SYSTEM_PROMPT_EN
        assert "{{ context }}" in RAG_SYSTEM_PROMPT_NL

        # Follow-up templates should have {{ summary }}
        assert "{{ summary }}" in FOLLOW_UP_PROMPT_EN
        assert "{{ summary }}" in FOLLOW_UP_PROMPT_NL

        # RAG citations should have {{ citations }}
        assert "{{ citations }}" in RAG_CITATIONS_PROMPT_EN
        assert "{{ citations }}" in RAG_CITATIONS_PROMPT_NL

        # Clarification should have {{ query }}
        assert "{{ query }}" in CLARIFICATION_PROMPT_EN
        assert "{{ query }}" in CLARIFICATION_PROMPT_NL

        # Summary should have {{ conversation }}
        assert "{{ conversation }}" in SUMMARY_PROMPT_EN
        assert "{{ conversation }}" in SUMMARY_PROMPT_NL

    def test_dutch_citation_format_differs_from_english(self):
        """Dutch templates should use Dutch citation format."""
        assert "[Bron:" in RAG_SYSTEM_PROMPT_NL
        assert "[Source:" in RAG_SYSTEM_PROMPT_EN

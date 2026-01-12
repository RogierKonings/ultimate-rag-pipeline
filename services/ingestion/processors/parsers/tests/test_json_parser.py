"""Tests for JSON document parser."""

import pytest

from ..base import ContentType, ParsedDocument
from ..json_parser import JSONParser


class TestJSONParser:
    """Tests for JSONParser."""

    @pytest.fixture
    def parser(self) -> JSONParser:
        """Return default JSON parser."""
        return JSONParser()

    @pytest.fixture
    def custom_parser(self) -> JSONParser:
        """Return JSON parser with custom field configuration."""
        return JSONParser(
            content_fields=["message", "data"],
            metadata_fields=["name", "timestamp"],
        )

    # Basic object parsing tests

    @pytest.mark.asyncio
    async def test_parse_simple_object(self, parser: JSONParser):
        """Test parsing a simple JSON object with content field."""
        content = b'{"title": "Test", "content": "Hello world", "author": "Jane"}'
        result = await parser.parse(content)

        assert isinstance(result, ParsedDocument)
        assert "Hello world" in result.text
        assert result.title == "Test"
        assert result.metadata.get("author") == "Jane"

    @pytest.mark.asyncio
    async def test_parse_object_with_text_field(self, parser: JSONParser):
        """Test parsing object with 'text' content field."""
        content = b'{"text": "Sample text content"}'
        result = await parser.parse(content)

        assert result.text == "Sample text content"
        assert len(result.blocks) == 1
        assert result.blocks[0].content_type == ContentType.TEXT

    @pytest.mark.asyncio
    async def test_parse_object_with_body_field(self, parser: JSONParser):
        """Test parsing object with 'body' content field."""
        content = b'{"body": "Body content here"}'
        result = await parser.parse(content)

        assert result.text == "Body content here"

    @pytest.mark.asyncio
    async def test_parse_object_with_description_field(self, parser: JSONParser):
        """Test parsing object with 'description' content field."""
        content = b'{"description": "A detailed description"}'
        result = await parser.parse(content)

        assert result.text == "A detailed description"

    @pytest.mark.asyncio
    async def test_parse_object_multiple_content_fields(self, parser: JSONParser):
        """Test parsing object with multiple content fields."""
        content = b'{"content": "First part", "text": "Second part"}'
        result = await parser.parse(content)

        assert "First part" in result.text
        assert "Second part" in result.text
        assert len(result.blocks) == 2

    # Metadata extraction tests

    @pytest.mark.asyncio
    async def test_extracts_all_metadata_fields(self, parser: JSONParser):
        """Test that all configured metadata fields are extracted."""
        content = b"""{
            "title": "Document Title",
            "author": "John Doe",
            "date": "2024-01-15",
            "id": "doc-123",
            "url": "https://example.com/doc",
            "content": "Main content"
        }"""
        result = await parser.parse(content)

        assert result.title == "Document Title"
        assert result.author == "John Doe"
        assert result.metadata.get("date") == "2024-01-15"
        assert result.metadata.get("id") == "doc-123"
        assert result.metadata.get("url") == "https://example.com/doc"

    @pytest.mark.asyncio
    async def test_merge_with_provided_metadata(self, parser: JSONParser):
        """Test that provided metadata is merged with extracted metadata."""
        content = b'{"title": "From JSON", "content": "Text"}'
        provided_metadata = {"source": "api", "custom_field": "value"}
        result = await parser.parse(content, provided_metadata)

        assert result.metadata.get("source") == "api"
        assert result.metadata.get("custom_field") == "value"
        assert result.metadata.get("title") == "From JSON"

    # Nested structure tests

    @pytest.mark.asyncio
    async def test_flatten_nested_object(self, parser: JSONParser):
        """Test flattening of nested objects when no content fields found."""
        content = b"""{
            "user": {
                "name": "Alice",
                "email": "alice@example.com"
            },
            "settings": {
                "theme": "dark"
            }
        }"""
        result = await parser.parse(content)

        assert "user.name: Alice" in result.text
        assert "user.email: alice@example.com" in result.text
        assert "settings.theme: dark" in result.text

    @pytest.mark.asyncio
    async def test_flatten_deeply_nested(self, parser: JSONParser):
        """Test flattening of deeply nested structures."""
        content = b"""{
            "level1": {
                "level2": {
                    "level3": {
                        "value": "deep"
                    }
                }
            }
        }"""
        result = await parser.parse(content)

        assert "level1.level2.level3.value: deep" in result.text

    @pytest.mark.asyncio
    async def test_content_field_with_nested_value(self, parser: JSONParser):
        """Test content field containing nested object is JSON-stringified."""
        content = b'{"content": {"nested": "value", "array": [1, 2, 3]}}'
        result = await parser.parse(content)

        # Should contain formatted JSON
        assert "nested" in result.text
        assert "value" in result.text

    # Array parsing tests

    @pytest.mark.asyncio
    async def test_parse_array_of_objects(self, parser: JSONParser):
        """Test parsing JSON array of objects."""
        content = b'[{"text": "First"}, {"text": "Second"}]'
        result = await parser.parse(content)

        assert "First" in result.text
        assert "Second" in result.text
        assert result.metadata.get("array_length") == 2

    @pytest.mark.asyncio
    async def test_parse_array_extracts_first_title(self, parser: JSONParser):
        """Test that first title in array becomes document title."""
        content = b'[{"title": "First Title", "text": "A"}, {"title": "Second", "text": "B"}]'
        result = await parser.parse(content)

        assert result.title == "First Title"

    @pytest.mark.asyncio
    async def test_parse_array_of_strings(self, parser: JSONParser):
        """Test parsing array of string values."""
        content = b'["Line one", "Line two", "Line three"]'
        result = await parser.parse(content)

        assert "Line one" in result.text
        assert "Line two" in result.text
        assert "Line three" in result.text

    @pytest.mark.asyncio
    async def test_parse_array_of_primitives(self, parser: JSONParser):
        """Test parsing array of mixed primitive values."""
        content = b'[1, 2, "three", true, null]'
        result = await parser.parse(content)

        assert "1" in result.text
        assert "2" in result.text
        assert "three" in result.text
        assert "True" in result.text
        # null values are skipped

    @pytest.mark.asyncio
    async def test_parse_array_with_nested_arrays(self, parser: JSONParser):
        """Test parsing objects with array fields that get flattened."""
        content = b'[{"items": ["a", "b", "c"]}]'
        result = await parser.parse(content)

        assert "items[0]: a" in result.text
        assert "items[1]: b" in result.text
        assert "items[2]: c" in result.text

    @pytest.mark.asyncio
    async def test_parse_empty_array(self, parser: JSONParser):
        """Test parsing empty array."""
        content = b"[]"
        result = await parser.parse(content)

        assert result.text == ""
        assert result.metadata.get("array_length") == 0

    # Primitive value tests

    @pytest.mark.asyncio
    async def test_parse_primitive_string(self, parser: JSONParser):
        """Test parsing a primitive JSON string."""
        content = b'"Just a string"'
        result = await parser.parse(content)

        assert result.text == "Just a string"

    @pytest.mark.asyncio
    async def test_parse_primitive_number(self, parser: JSONParser):
        """Test parsing a primitive JSON number."""
        content = b"42"
        result = await parser.parse(content)

        assert result.text == "42"

    @pytest.mark.asyncio
    async def test_parse_primitive_boolean(self, parser: JSONParser):
        """Test parsing a primitive JSON boolean."""
        content = b"true"
        result = await parser.parse(content)

        assert result.text == "True"

    @pytest.mark.asyncio
    async def test_parse_null(self, parser: JSONParser):
        """Test parsing JSON null."""
        content = b"null"
        result = await parser.parse(content)

        assert result.text == ""

    # Custom field configuration tests

    @pytest.mark.asyncio
    async def test_custom_content_fields(self, custom_parser: JSONParser):
        """Test parser with custom content field configuration."""
        content = b'{"message": "Custom message", "data": "Custom data"}'
        result = await custom_parser.parse(content)

        assert "Custom message" in result.text
        assert "Custom data" in result.text

    @pytest.mark.asyncio
    async def test_custom_metadata_fields(self, custom_parser: JSONParser):
        """Test parser with custom metadata field configuration."""
        content = b'{"name": "Test Name", "timestamp": "2024-01-15T10:00:00Z", "message": "Hi"}'
        result = await custom_parser.parse(content)

        assert result.metadata.get("name") == "Test Name"
        assert result.metadata.get("timestamp") == "2024-01-15T10:00:00Z"

    @pytest.mark.asyncio
    async def test_default_fields_not_used_with_custom(self, custom_parser: JSONParser):
        """Test that default fields are ignored when custom ones specified."""
        content = b'{"content": "Default field", "message": "Custom field"}'
        result = await custom_parser.parse(content)

        # Only "message" should be extracted as content
        assert "Custom field" in result.text
        # "content" should appear in flattened output since it's not a configured field
        # Actually, since "message" is found, we don't flatten
        assert result.text == "Custom field"

    # Error handling tests

    @pytest.mark.asyncio
    async def test_invalid_json_raises_error(self, parser: JSONParser):
        """Test that invalid JSON raises ValueError."""
        content = b"not valid json"
        with pytest.raises(ValueError, match="Invalid JSON"):
            await parser.parse(content)

    @pytest.mark.asyncio
    async def test_malformed_json_raises_error(self, parser: JSONParser):
        """Test that malformed JSON raises ValueError."""
        content = b'{"unclosed": "string'
        with pytest.raises(ValueError, match="Invalid JSON"):
            await parser.parse(content)

    @pytest.mark.asyncio
    async def test_invalid_encoding_raises_error(self, parser: JSONParser):
        """Test that non-UTF-8 content raises ValueError."""
        # Invalid UTF-8 byte sequence
        content = b"\xff\xfe"
        with pytest.raises(ValueError, match="Failed to decode"):
            await parser.parse(content)

    # Edge case tests

    @pytest.mark.asyncio
    async def test_empty_object(self, parser: JSONParser):
        """Test parsing empty JSON object."""
        content = b"{}"
        result = await parser.parse(content)

        assert result.text == ""
        assert result.blocks == []

    @pytest.mark.asyncio
    async def test_object_with_null_values(self, parser: JSONParser):
        """Test that null values are handled gracefully."""
        content = b'{"content": null, "title": null}'
        result = await parser.parse(content)

        # Null values should be skipped
        assert result.text == ""

    @pytest.mark.asyncio
    async def test_unicode_content(self, parser: JSONParser):
        """Test parsing JSON with unicode characters."""
        content = '{"content": "Hello, \u4e16\u754c! \u041f\u0440\u0438\u0432\u0435\u0442!"}'.encode()
        result = await parser.parse(content)

        assert "\u4e16\u754c" in result.text  # Chinese characters
        assert "\u041f\u0440\u0438\u0432\u0435\u0442" in result.text  # Russian characters

    @pytest.mark.asyncio
    async def test_large_nested_structure(self, parser: JSONParser):
        """Test parsing a moderately complex nested structure."""
        content = b"""{
            "document": {
                "header": {
                    "title": "Complex Document"
                },
                "sections": [
                    {"heading": "Section 1", "body": "Content 1"},
                    {"heading": "Section 2", "body": "Content 2"}
                ],
                "footer": {
                    "copyright": "2024"
                }
            }
        }"""
        result = await parser.parse(content)

        # Should flatten since no top-level content fields
        assert "document.header.title: Complex Document" in result.text
        assert "document.sections[0].heading: Section 1" in result.text
        assert "document.footer.copyright: 2024" in result.text

    @pytest.mark.asyncio
    async def test_content_field_with_number_value(self, parser: JSONParser):
        """Test content field with numeric value is stringified."""
        content = b'{"content": 12345}'
        result = await parser.parse(content)

        assert "12345" in result.text

    @pytest.mark.asyncio
    async def test_content_field_with_boolean_value(self, parser: JSONParser):
        """Test content field with boolean value is stringified."""
        content = b'{"content": true}'
        result = await parser.parse(content)

        assert "True" in result.text

    # MIME type and capability tests

    def test_supported_mime_types(self, parser: JSONParser):
        """Test supported MIME types."""
        assert "application/json" in parser.supported_mime_types

    def test_can_parse_json(self, parser: JSONParser):
        """Test can_parse returns True for JSON MIME type."""
        assert parser.can_parse("application/json")

    def test_cannot_parse_other_types(self, parser: JSONParser):
        """Test can_parse returns False for non-JSON MIME types."""
        assert not parser.can_parse("text/plain")
        assert not parser.can_parse("application/xml")

    # Block structure tests

    @pytest.mark.asyncio
    async def test_blocks_have_correct_positions(self, parser: JSONParser):
        """Test that content blocks have sequential positions."""
        content = b'{"content": "First", "text": "Second", "body": "Third"}'
        result = await parser.parse(content)

        positions = [block.position for block in result.blocks]
        assert positions == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_blocks_content_type_is_text(self, parser: JSONParser):
        """Test that all blocks have TEXT content type."""
        content = b'{"content": "Test content"}'
        result = await parser.parse(content)

        for block in result.blocks:
            assert block.content_type == ContentType.TEXT

    # Tables test (JSON parser doesn't extract tables)

    @pytest.mark.asyncio
    async def test_tables_always_empty(self, parser: JSONParser):
        """Test that tables list is always empty for JSON."""
        content = b'{"content": "Data"}'
        result = await parser.parse(content)

        assert result.tables == []


class TestJSONParserRegistry:
    """Tests for JSON parser integration with registry."""

    @pytest.mark.asyncio
    async def test_registry_includes_json_parser(self):
        """Test that default registry includes JSON parser."""
        from ..registry import create_default_registry

        registry = create_default_registry()
        assert registry.has_parser("application/json")

    @pytest.mark.asyncio
    async def test_registry_parses_json(self):
        """Test parsing JSON through registry."""
        from ..registry import create_default_registry

        registry = create_default_registry()
        content = b'{"content": "Test via registry"}'
        result = await registry.parse(content, "application/json")

        assert isinstance(result, ParsedDocument)
        assert "Test via registry" in result.text

    def test_registry_lists_json_type(self):
        """Test that JSON MIME type appears in supported types list."""
        from ..registry import create_default_registry

        registry = create_default_registry()
        types = registry.list_supported_types()
        assert "application/json" in types

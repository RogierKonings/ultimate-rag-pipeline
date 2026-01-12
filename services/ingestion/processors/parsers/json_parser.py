"""JSON document parser for structured data."""

import json
import logging

from .base import BaseParser, ContentBlock, ContentType, ParsedDocument

logger = logging.getLogger(__name__)


class JSONParser(BaseParser):
    """Parser for JSON documents.

    Extracts text content from JSON files by looking for designated
    content fields and/or flattening nested structures to readable text.
    """

    def __init__(
        self,
        content_fields: list[str] | None = None,
        metadata_fields: list[str] | None = None,
    ):
        """Initialize JSON parser.

        Args:
            content_fields: Fields to extract as content. If a field exists,
                its value becomes part of the document text.
                Defaults to ["content", "text", "body", "description"].
            metadata_fields: Fields to extract as metadata. If a field exists,
                it's added to the document metadata.
                Defaults to ["title", "author", "date", "id", "url"].
        """
        self.content_fields = content_fields or [
            "content",
            "text",
            "body",
            "description",
        ]
        self.metadata_fields = metadata_fields or [
            "title",
            "author",
            "date",
            "id",
            "url",
        ]

    @property
    def supported_mime_types(self) -> list[str]:
        """Return list of supported MIME types."""
        return ["application/json", "text/json"]

    async def parse(
        self, content: bytes, metadata: dict | None = None,
    ) -> ParsedDocument:
        """Parse JSON document content.

        Args:
            content: Raw JSON bytes.
            metadata: Optional metadata to include in the result.

        Returns:
            ParsedDocument with extracted text and metadata.

        Raises:
            ValueError: If content is not valid JSON.
        """
        metadata = metadata or {}

        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError as e:
            raise ValueError(f"Failed to decode JSON content as UTF-8: {e}") from e

        try:
            data = json.loads(text_content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e

        # Handle array of objects
        if isinstance(data, list):
            return self._parse_array(data, metadata)

        # Handle single object
        if isinstance(data, dict):
            return self._parse_object(data, metadata)

        # Handle primitive values (string, number, bool, null)
        return self._parse_primitive(data, metadata)

    def _parse_object(self, data: dict, metadata: dict) -> ParsedDocument:
        """Parse a single JSON object.

        Args:
            data: The JSON object to parse.
            metadata: Base metadata to include.

        Returns:
            ParsedDocument with extracted content.
        """
        texts = []
        extracted_metadata = {}

        # Extract content from designated content fields
        for field in self.content_fields:
            if field in data:
                value = data[field]
                if isinstance(value, str):
                    texts.append(value)
                elif isinstance(value, (list, dict)):
                    # Convert complex structures to formatted JSON string
                    texts.append(json.dumps(value, indent=2))
                elif value is not None:
                    # Convert other primitives to string
                    texts.append(str(value))

        # Extract metadata from designated metadata fields
        for field in self.metadata_fields:
            if field in data:
                extracted_metadata[field] = data[field]

        # If no content fields found, flatten the entire object to readable text
        if not texts:
            flattened = self._flatten_to_text(data)
            if flattened:
                texts.append(flattened)

        combined_text = "\n\n".join(texts) if texts else ""

        return ParsedDocument(
            text=combined_text,
            blocks=[
                ContentBlock(
                    content_type=ContentType.TEXT,
                    content=t,
                    position=i,
                )
                for i, t in enumerate(texts)
            ],
            tables=[],
            title=extracted_metadata.get("title"),
            author=extracted_metadata.get("author"),
            metadata={**metadata, **extracted_metadata},
        )

    def _parse_array(self, data: list, metadata: dict) -> ParsedDocument:
        """Parse a JSON array of objects.

        Args:
            data: The JSON array to parse.
            metadata: Base metadata to include.

        Returns:
            ParsedDocument with combined content from all array items.
        """
        all_texts = []
        all_blocks = []
        combined_metadata = dict(metadata)
        title = None
        author = None
        block_position = 0

        for item in data:
            if isinstance(item, dict):
                # Parse each object in the array
                item_texts = []
                item_metadata = {}

                # Extract content fields
                for field in self.content_fields:
                    if field in item:
                        value = item[field]
                        if isinstance(value, str):
                            item_texts.append(value)
                        elif isinstance(value, (list, dict)):
                            item_texts.append(json.dumps(value, indent=2))
                        elif value is not None:
                            item_texts.append(str(value))

                # Extract metadata fields (use first found values)
                for field in self.metadata_fields:
                    if field in item:
                        item_metadata[field] = item[field]
                        # Capture first title/author found
                        if field == "title" and title is None:
                            title = item[field]
                        if field == "author" and author is None:
                            author = item[field]

                # If no content fields, flatten the object
                if not item_texts:
                    flattened = self._flatten_to_text(item)
                    if flattened:
                        item_texts.append(flattened)

                # Add texts to results
                for text in item_texts:
                    all_texts.append(text)
                    all_blocks.append(
                        ContentBlock(
                            content_type=ContentType.TEXT,
                            content=text,
                            position=block_position,
                        ),
                    )
                    block_position += 1

            elif isinstance(item, str):
                # String items in array
                all_texts.append(item)
                all_blocks.append(
                    ContentBlock(
                        content_type=ContentType.TEXT,
                        content=item,
                        position=block_position,
                    ),
                )
                block_position += 1

            elif item is not None:
                # Other primitive values
                text = str(item)
                all_texts.append(text)
                all_blocks.append(
                    ContentBlock(
                        content_type=ContentType.TEXT,
                        content=text,
                        position=block_position,
                    ),
                )
                block_position += 1

        combined_text = "\n\n".join(all_texts) if all_texts else ""
        combined_metadata["array_length"] = len(data)

        return ParsedDocument(
            text=combined_text,
            blocks=all_blocks,
            tables=[],
            title=title,
            author=author,
            metadata=combined_metadata,
        )

    def _parse_primitive(self, data, metadata: dict) -> ParsedDocument:
        """Parse a primitive JSON value (string, number, bool, null).

        Args:
            data: The primitive value.
            metadata: Base metadata to include.

        Returns:
            ParsedDocument with the value as text.
        """
        text = str(data) if data is not None else ""

        return ParsedDocument(
            text=text,
            blocks=[
                ContentBlock(
                    content_type=ContentType.TEXT,
                    content=text,
                    position=0,
                ),
            ]
            if text
            else [],
            tables=[],
            metadata=metadata,
        )

    def _flatten_to_text(self, data: dict, prefix: str = "") -> str:
        """Flatten a nested dictionary to readable key-value text.

        Args:
            data: Dictionary to flatten.
            prefix: Key prefix for nested structures.

        Returns:
            Flattened text representation with format "key: value" per line.
        """
        lines = []

        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key

            if isinstance(value, dict):
                # Recursively flatten nested dicts
                nested = self._flatten_to_text(value, full_key)
                if nested:
                    lines.append(nested)
            elif isinstance(value, list):
                # Handle arrays
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        nested = self._flatten_to_text(item, f"{full_key}[{i}]")
                        if nested:
                            lines.append(nested)
                    elif item is not None:
                        lines.append(f"{full_key}[{i}]: {item}")
            elif value is not None:
                lines.append(f"{full_key}: {value}")

        return "\n".join(lines)

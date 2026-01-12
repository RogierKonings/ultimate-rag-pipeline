"""Markdown document parser."""

import logging
import re

import yaml

from .base import BaseParser, ContentBlock, ContentType, ParsedDocument, TableContent

logger = logging.getLogger(__name__)


class MarkdownParser(BaseParser):
    """Parser for Markdown documents.

    Extracts text, code blocks, and tables from Markdown files.
    """

    @property
    def supported_mime_types(self) -> list[str]:
        """Return list of supported MIME types."""
        return ["text/markdown", "text/x-markdown"]

    async def parse(
        self,
        content: bytes,
        metadata: dict | None = None,
    ) -> ParsedDocument:
        """Parse Markdown document.

        Args:
            content: Raw Markdown bytes.
            metadata: Optional metadata to include.

        Returns:
            ParsedDocument with extracted content.
        """
        metadata = metadata or {}

        # Decode content
        text = content.decode("utf-8", errors="replace")

        # Extract YAML frontmatter
        frontmatter, text = self._extract_frontmatter(text)

        # Merge frontmatter into metadata (frontmatter takes precedence)
        metadata = {**metadata, **frontmatter}

        # Extract title from frontmatter or first H1
        title = frontmatter.get("title") or self._extract_title(text)

        # Extract content blocks
        blocks = self._extract_blocks(text)

        # Extract tables
        tables = self._extract_tables(text)

        # Add table blocks
        for table in tables:
            blocks.append(
                ContentBlock(
                    content_type=ContentType.TABLE,
                    content=self._table_to_text(table),
                    position=len(blocks),
                ),
            )

        return ParsedDocument(
            text=text,
            blocks=blocks,
            tables=tables,
            title=title,
            metadata=metadata,
        )

    def _extract_frontmatter(self, text: str) -> tuple[dict, str]:
        """Extract YAML frontmatter from markdown.

        YAML frontmatter is metadata at the start of a markdown file,
        delimited by `---` markers. Common fields include title, author,
        date, tags, and description.

        Args:
            text: Raw markdown text.

        Returns:
            Tuple of (frontmatter_dict, remaining_text).
            If no valid frontmatter is found, returns ({}, original_text).
        """
        if not text.startswith("---"):
            return {}, text

        # Find closing delimiter (must be on its own line)
        end_match = re.search(r"\n---\s*\n", text[3:])
        if not end_match:
            # Also handle case where frontmatter is at end of file or followed by EOF
            end_match = re.search(r"\n---\s*$", text[3:])
            if not end_match:
                return {}, text

        yaml_content = text[3 : end_match.start() + 3]
        remaining_text = text[end_match.end() + 3 :]

        try:
            frontmatter = yaml.safe_load(yaml_content) or {}
            # Ensure frontmatter is a dict (could be a scalar or list if invalid)
            if not isinstance(frontmatter, dict):
                logger.warning(
                    f"Frontmatter is not a mapping (got {type(frontmatter).__name__}), ignoring",
                )
                return {}, text
            return frontmatter, remaining_text
        except yaml.YAMLError as e:
            logger.warning(f"Failed to parse YAML frontmatter: {e}")
            return {}, text

    def _extract_title(self, text: str) -> str | None:
        """Extract title from first H1 heading.

        Args:
            text: Markdown text.

        Returns:
            Title string or None.
        """
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
            # Also check for setext-style H1
            if lines.index(line.strip()) < len(lines) - 1:
                next_idx = lines.index(line.strip()) + 1
                if next_idx < len(lines) and re.match(r"^=+\s*$", lines[next_idx]):
                    return line.strip()
        return None

    def _extract_blocks(self, text: str) -> list[ContentBlock]:
        """Extract content blocks from Markdown.

        Args:
            text: Markdown text.

        Returns:
            List of ContentBlocks.
        """
        blocks: list[ContentBlock] = []
        position = 0

        # Pattern for fenced code blocks
        code_pattern = re.compile(
            r"```(\w*)\n(.*?)```",
            re.DOTALL | re.MULTILINE,
        )

        # Find all code blocks first
        code_blocks = []
        for match in code_pattern.finditer(text):
            language = match.group(1) or None
            code_content = match.group(2).strip()
            code_blocks.append(
                {
                    "start": match.start(),
                    "end": match.end(),
                    "language": language,
                    "content": code_content,
                },
            )

        # Process text, separating code blocks from other content
        last_end = 0
        for code_block in code_blocks:
            # Process text before this code block
            before_text = text[last_end : code_block["start"]].strip()
            if before_text:
                text_blocks = self._extract_text_blocks(before_text)
                for block in text_blocks:
                    block.position = position
                    position += 1
                blocks.extend(text_blocks)

            # Add code block
            blocks.append(
                ContentBlock(
                    content_type=ContentType.CODE,
                    content=code_block["content"],
                    position=position,
                    metadata={"language": code_block["language"]},
                ),
            )
            position += 1
            last_end = code_block["end"]

        # Process remaining text after last code block
        remaining_text = text[last_end:].strip()
        if remaining_text:
            text_blocks = self._extract_text_blocks(remaining_text)
            for block in text_blocks:
                block.position = position
                position += 1
            blocks.extend(text_blocks)

        return blocks

    def _extract_text_blocks(self, text: str) -> list[ContentBlock]:
        """Extract text blocks from non-code Markdown content.

        Args:
            text: Markdown text without code blocks.

        Returns:
            List of text ContentBlocks.
        """
        blocks: list[ContentBlock] = []

        # Split by double newlines to get paragraphs
        paragraphs = re.split(r"\n\s*\n", text)

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Skip table lines (handled separately)
            if para.startswith("|") or re.match(r"^\s*[-|:]+\s*$", para):
                continue

            # Determine if it's a heading
            block_metadata = {}
            if para.startswith("#"):
                # Count heading level
                level = len(re.match(r"^#+", para).group())
                block_metadata["heading_level"] = level
                para = re.sub(r"^#+\s*", "", para)

            if para:
                blocks.append(
                    ContentBlock(
                        content_type=ContentType.TEXT,
                        content=para,
                        metadata=block_metadata,
                    ),
                )

        return blocks

    def _extract_tables(self, text: str) -> list[TableContent]:
        """Extract tables from Markdown.

        Args:
            text: Markdown text.

        Returns:
            List of TableContent objects.
        """
        tables: list[TableContent] = []

        # Pattern for Markdown tables
        # Header row, separator row, data rows
        table_pattern = re.compile(
            r"^(\|[^\n]+\|)\n"  # Header row
            r"(\|[-:\s|]+\|)\n"  # Separator row
            r"((?:\|[^\n]+\|\n?)+)",  # Data rows
            re.MULTILINE,
        )

        for match in table_pattern.finditer(text):
            header_line = match.group(1)
            data_lines = match.group(3).strip().split("\n")

            # Parse headers
            headers = self._parse_table_row(header_line)

            # Parse data rows
            rows = []
            for line in data_lines:
                row = self._parse_table_row(line)
                if row:
                    rows.append(row)

            if headers:
                tables.append(TableContent(headers=headers, rows=rows))

        return tables

    def _parse_table_row(self, line: str) -> list[str]:
        """Parse a Markdown table row.

        Args:
            line: Table row line.

        Returns:
            List of cell values.
        """
        # Remove leading/trailing pipes and split
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]

        return [cell.strip() for cell in line.split("|")]

    def _table_to_text(self, table: TableContent) -> str:
        """Convert TableContent to plain text.

        Args:
            table: TableContent to convert.

        Returns:
            Plain text representation.
        """
        lines = []

        if table.caption:
            lines.append(table.caption)

        lines.append(" | ".join(table.headers))
        lines.append("-" * len(lines[-1]))

        for row in table.rows:
            lines.append(" | ".join(row))

        return "\n".join(lines)

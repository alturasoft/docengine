"""DocEngine — Application Service: ChunkingService.

Performs 100% local hierarchical/semantic text splitting on Markdown content
using MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter, and a
Table-Aware Contextual Chunking strategy for Markdown tables and sections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.config.settings import EmbeddingConfig
from app.domain.models.chunks import PolicyChunk
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Regular expression to match standard Markdown table delimiter rows (e.g., |---|---|, | :--- | ---: |)
_TABLE_DELIMITER_PATTERN = re.compile(
    r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$"
)

# Regular expression to detect policy number codes within document content (e.g. CAC-SCE0651635, AU-LP00123)
_POLICY_CODE_PATTERN = re.compile(
    r"\b([A-Z]{2,5}\s*-\s*[A-Z0-9]{4,15})\b"
)


@dataclass
class _ContentBlock:
    """Internal representation of a segment within a section."""

    block_type: str  # "text" | "table"
    content: str
    lines: list[str] = field(default_factory=list)


class ChunkingService:
    """Service for local Markdown text chunking with Table-Aware capability.

    Strategy:
    1. Splits Markdown hierarchically by headers (#, ##, ###, ####).
    2. Identifies policy number codes and document context to construct grounding prefixes.
    3. Identifies and isolates Markdown tables from plain narrative text.
    4. Normal text exceeding config.chunk_size_chars is split using
       RecursiveCharacterTextSplitter with config.chunk_overlap_chars.
    5. Markdown tables exceeding config.chunk_size_chars are divided strictly
       by whole rows, repeating contextual prefix, column headers, and delimiter
       rows on every sub-chunk to preserve complete semantic context.
    6. Retains header hierarchy in metadata for all generated chunks.
    """

    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        self._headers_to_split_on = [
            ("#", "Header 1"),
            ("##", "Header 2"),
            ("###", "Header 3"),
            ("####", "Header 4"),
        ]
        self._header_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=self._headers_to_split_on,
            strip_headers=False,
        )
        self._text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self._config.chunk_size_chars,
            chunk_overlap=self._config.chunk_overlap_chars,
            separators=["\n\n", "\n", " ", ""],
        )

    @staticmethod
    def _is_table_delimiter(line: str) -> bool:
        """Check if a line matches Markdown table delimiter row syntax."""
        stripped = line.strip()
        if not stripped or "|" not in stripped:
            return False
        return bool(_TABLE_DELIMITER_PATTERN.match(stripped))

    @staticmethod
    def _is_table_row(line: str) -> bool:
        """Check if a line appears to be part of a Markdown table row."""
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return False
        return "|" in stripped

    @staticmethod
    def _detect_policy_number(markdown: str) -> str | None:
        """Detect the primary policy code (e.g. CAC-SCE0651635) from markdown text."""
        matches = _POLICY_CODE_PATTERN.findall(markdown)
        if matches:
            cleaned = [re.sub(r"\s*-\s*", "-", m).strip() for m in matches]
            # Return the most frequent policy code found
            return max(set(cleaned), key=cleaned.count)
        return None

    @staticmethod
    def _extract_table_title(header_line: str) -> str | None:
        """Extract a descriptive table title if the first column/header contains a title."""
        cells = [c.strip() for c in header_line.split("|") if c.strip()]
        if not cells:
            return None
        clean_cell = re.sub(r"[\*_#]", "", cells[0]).strip()
        if len(clean_cell) >= 3 and not clean_cell.isdigit():
            return clean_cell
        return None

    @staticmethod
    def _build_context_prefix(
        metadata: dict[str, Any],
        file_name: str | None,
        detected_policy_num: str | None = None,
        table_title: str | None = None,
    ) -> str:
        """Build a contextual metadata header for RAG embedding and retrieval grounding."""
        parts: list[str] = []

        if detected_policy_num:
            parts.append(f"Póliza: {detected_policy_num}")

        if file_name:
            clean_name = file_name
            if "." in clean_name:
                clean_name = clean_name.rsplit(".", 1)[0]
            if not detected_policy_num or detected_policy_num not in clean_name:
                parts.append(f"Documento: {clean_name}")

        if table_title:
            parts.append(f"Tabla: {table_title}")

        headers: list[str] = []
        for h_key in ["Header 1", "Header 2", "Header 3", "Header 4"]:
            if h_key in metadata and metadata[h_key]:
                val = str(metadata[h_key]).strip()
                if val and val not in headers:
                    headers.append(val)

        if headers:
            parts.append(f"Sección: {' > '.join(headers)}")

        if parts:
            return f"[{' | '.join(parts)}]\n\n"
        return ""

    def _extract_blocks(self, section_text: str) -> list[_ContentBlock]:
        """Separate section content into ordered plain text and table blocks."""
        lines = section_text.splitlines()
        blocks: list[_ContentBlock] = []
        text_lines_buffer: list[str] = []

        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]

            # Detect table start: current line is header row and next line is delimiter row
            if i + 1 < n and self._is_table_row(line) and self._is_table_delimiter(lines[i + 1]):
                # Flush any pending text before the table
                if text_lines_buffer:
                    text_content = "\n".join(text_lines_buffer).strip()
                    if text_content:
                        blocks.append(_ContentBlock(block_type="text", content=text_content))
                    text_lines_buffer = []

                # Collect all contiguous rows belonging strictly to this table
                table_lines = [line, lines[i + 1]]
                j = i + 2
                while j < n:
                    if not lines[j].strip():
                        # Blank line terminates a markdown table
                        break
                    if not self._is_table_row(lines[j]):
                        # Non-table line terminates the table
                        break
                    if j + 1 < n and self._is_table_delimiter(lines[j + 1]):
                        # Next line is a table delimiter, meaning lines[j] is the header of a new table
                        break
                    table_lines.append(lines[j])
                    j += 1

                table_content = "\n".join(table_lines).strip()
                if table_content:
                    blocks.append(
                        _ContentBlock(
                            block_type="table",
                            content=table_content,
                            lines=table_lines,
                        )
                    )
                i = j
            else:
                text_lines_buffer.append(line)
                i += 1

        # Flush trailing text if any
        if text_lines_buffer:
            text_content = "\n".join(text_lines_buffer).strip()
            if text_content:
                blocks.append(_ContentBlock(block_type="text", content=text_content))

        return blocks

    def _split_table(self, table_lines: list[str], context_prefix: str = "") -> list[str]:
        """Split a Markdown table into sub-chunks if it exceeds chunk_size_chars.

        Guarantees:
        - Document context header, column headers, and delimiter rows are repeated on every sub-chunk.
        - Splits occur strictly across whole rows.
        """
        if not table_lines:
            return []

        header_row = table_lines[0].strip()
        delimiter_row = table_lines[1].strip()
        data_rows = [r.strip() for r in table_lines[2:] if r.strip()]

        raw_header = f"{header_row}\n{delimiter_row}"
        header_prefix = f"{context_prefix}{raw_header}" if context_prefix else raw_header

        if not data_rows:
            raw_tbl = "\n".join(table_lines).strip()
            return [f"{context_prefix}{raw_tbl}" if context_prefix else raw_tbl]

        # Check if full table with context fits in chunk_size_chars
        full_table = header_prefix + "\n" + "\n".join(data_rows)
        if len(full_table) <= self._config.chunk_size_chars:
            return [full_table]

        chunks: list[str] = []
        current_rows: list[str] = []

        for row in data_rows:
            test_rows = current_rows + [row]
            candidate_chunk = header_prefix + "\n" + "\n".join(test_rows)

            if len(candidate_chunk) <= self._config.chunk_size_chars:
                current_rows.append(row)
            else:
                if current_rows:
                    chunks.append(header_prefix + "\n" + "\n".join(current_rows))
                    current_rows = [row]
                else:
                    # Single row exceeds max chunk size by itself; preserve without losing data
                    chunks.append(header_prefix + "\n" + row)
                    current_rows = []

        if current_rows:
            chunks.append(header_prefix + "\n" + "\n".join(current_rows))

        return chunks

    def _split_text_block(self, text: str, context_prefix: str = "") -> list[str]:
        """Split plain narrative text using RecursiveCharacterTextSplitter with context prefix."""
        full_text = f"{context_prefix}{text}" if context_prefix else text
        if len(full_text) > self._config.chunk_size_chars:
            sub_splits = self._text_splitter.split_text(text)
            return [
                f"{context_prefix}{s.strip()}" if context_prefix else s.strip()
                for s in sub_splits
                if s.strip()
            ]
        return [full_text]

    def chunk_markdown(
        self, markdown: str, file_name: str | None = None
    ) -> list[PolicyChunk]:
        """Split a Markdown string into a list of PolicyChunk objects.

        Args:
            markdown: The Markdown content to split.
            file_name: Optional original filename for metadata tracking and contextual grounding.

        Returns:
            List of PolicyChunk instances with indexed order and metadata.
        """
        if not markdown or not markdown.strip():
            logger.warning("Empty markdown provided for chunking", file_name=file_name)
            return []

        # Detect primary policy number from markdown content
        detected_policy_num = self._detect_policy_number(markdown)

        # 1. First pass: Split by Markdown headers
        header_splits = self._header_splitter.split_text(markdown)

        final_chunks: list[PolicyChunk] = []
        chunk_idx = 0

        for doc in header_splits:
            content = doc.page_content.strip()
            if not content:
                continue

            metadata: dict[str, Any] = dict(doc.metadata)
            if file_name:
                metadata["source_file"] = file_name
            if detected_policy_num:
                metadata["policy_number"] = detected_policy_num

            # 2. Second pass: Isolate tables and standard text blocks
            blocks = self._extract_blocks(content)

            for block in blocks:
                if block.block_type == "table":
                    table_title = self._extract_table_title(block.lines[0]) if block.lines else None
                    context_prefix = self._build_context_prefix(
                        metadata=metadata,
                        file_name=file_name,
                        detected_policy_num=detected_policy_num,
                        table_title=table_title,
                    )
                    table_chunks = self._split_table(block.lines, context_prefix=context_prefix)
                    for tbl_chunk in table_chunks:
                        if tbl_chunk.strip():
                            final_chunks.append(
                                PolicyChunk(
                                    chunk_index=chunk_idx,
                                    chunk_content=tbl_chunk.strip(),
                                    metadata_json=dict(metadata),
                                )
                            )
                            chunk_idx += 1
                else:
                    context_prefix = self._build_context_prefix(
                        metadata=metadata,
                        file_name=file_name,
                        detected_policy_num=detected_policy_num,
                    )
                    text_chunks = self._split_text_block(block.content, context_prefix=context_prefix)
                    for txt_chunk in text_chunks:
                        if txt_chunk.strip():
                            final_chunks.append(
                                PolicyChunk(
                                    chunk_index=chunk_idx,
                                    chunk_content=txt_chunk.strip(),
                                    metadata_json=dict(metadata),
                                )
                            )
                            chunk_idx += 1

        logger.info(
            "Local Markdown chunking complete",
            file_name=file_name,
            policy_number=detected_policy_num,
            total_chunks=len(final_chunks),
            avg_chars=(
                sum(len(c.chunk_content) for c in final_chunks) // len(final_chunks)
                if final_chunks
                else 0
            ),
        )

        return final_chunks

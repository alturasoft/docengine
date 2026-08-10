"""DocEngine — Application Service: ChunkingService.

Performs 100% local hierarchical/semantic text splitting on Markdown content
using MarkdownHeaderTextSplitter and RecursiveCharacterTextSplitter.
"""

from __future__ import annotations

from typing import Any

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from app.config.settings import EmbeddingConfig
from app.domain.models.chunks import PolicyChunk
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class ChunkingService:
    """Service for local Markdown text chunking.

    Strategy:
    1. Splits Markdown hierarchically by headers (#, ##, ###, ####).
    2. Any chunk larger than config.chunk_size_chars is further split using
       RecursiveCharacterTextSplitter with config.chunk_overlap_chars.
    3. Retains header hierarchy in metadata.
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

    def chunk_markdown(
        self, markdown: str, file_name: str | None = None
    ) -> list[PolicyChunk]:
        """Split a Markdown string into a list of PolicyChunk objects.

        Args:
            markdown: The Markdown content to split.
            file_name: Optional original filename for metadata tracking.

        Returns:
            List of PolicyChunk instances with indexed order and metadata.
        """
        if not markdown or not markdown.strip():
            logger.warning("Empty markdown provided for chunking", file_name=file_name)
            return []

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

            # 2. Second pass: Recursive character split if content > chunk_size_chars
            if len(content) > self._config.chunk_size_chars:
                sub_splits = self._text_splitter.split_text(content)
                for sub_text in sub_splits:
                    if sub_text.strip():
                        final_chunks.append(
                            PolicyChunk(
                                chunk_index=chunk_idx,
                                chunk_content=sub_text.strip(),
                                metadata_json=dict(metadata),
                            )
                        )
                        chunk_idx += 1
            else:
                final_chunks.append(
                    PolicyChunk(
                        chunk_index=chunk_idx,
                        chunk_content=content,
                        metadata_json=metadata,
                    )
                )
                chunk_idx += 1

        logger.info(
            "Local Markdown chunking complete",
            file_name=file_name,
            total_chunks=len(final_chunks),
            avg_chars=(
                sum(len(c.chunk_content) for c in final_chunks) // len(final_chunks)
                if final_chunks
                else 0
            ),
        )

        return final_chunks

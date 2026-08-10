"""DocEngine — Domain Models: Chunks.

Defines the structure for text chunks generated during local chunking
prior to embedding and PostgreSQL persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PolicyChunk:
    """Represents a text fragment (chunk) extracted from Markdown.

    Attributes:
        chunk_index: Order index of the chunk in the document.
        chunk_content: Markdown content of the chunk.
        metadata_json: Metadata dictionary (headers, page info, etc.).
        embedding: Dense vector representation (1024 float list for bge-m3).
    """

    chunk_index: int
    chunk_content: str
    metadata_json: dict = field(default_factory=dict)
    embedding: list[float] | None = None

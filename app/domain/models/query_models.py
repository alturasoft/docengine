"""DocEngine — Domain Models: RAG Query Response.

Defines the typed output structures for the RAG Query & Retrieval service.
These models are pure dataclasses — they have no dependency on FastAPI
or Pydantic, keeping the domain layer infrastructure-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RetrievedChunk:
    """A single chunk retrieved from the vector store with its similarity score.

    Attributes:
        chunk_id: Primary key of the chunk in policy_chunks table.
        policy_id: UUID of the parent policy document.
        chunk_index: Position of the chunk within the document.
        chunk_content: Raw text content of the chunk.
        metadata_json: Chunk metadata (section headers, page refs, etc.).
        similarity_score: Cosine similarity against the query vector (0.0–1.0).
            Higher is more relevant (1.0 = identical).
    """

    chunk_id: str | None
    policy_id: str
    chunk_index: int
    chunk_content: str
    metadata_json: dict = field(default_factory=dict)
    similarity_score: float = 0.0

    @property
    def document_label(self) -> str:
        """Build a human-readable label for prompt context injection.

        Extracts meaningful metadata fields to construct a citation-friendly
        label such as '[Documento: poliza.pdf | Sección: Coberturas | Pág: 3]'.
        Falls back gracefully if metadata fields are absent.
        """
        parts: list[str] = []

        file_name = (
            self.metadata_json.get("file_name")
            or self.metadata_json.get("filename")
            or self.metadata_json.get("source_file")
        )
        if file_name:
            parts.append(f"Documento: {file_name}")

        section = (
            self.metadata_json.get("section")
            or self.metadata_json.get("header")
            or self.metadata_json.get("Header 2")
            or self.metadata_json.get("Header 1")
            or self.metadata_json.get("Header 3")
        )
        if section:
            parts.append(f"Sección: {section}")

        page = self.metadata_json.get("page") or self.metadata_json.get("page_number")
        if page:
            parts.append(f"Pág: {page}")

        company = self.metadata_json.get("company_sigla")
        if company:
            parts.append(f"Empresa: {company}")

        if not parts:
            parts.append(f"Chunk #{self.chunk_index}")

        return f"[{' | '.join(parts)}]"


@dataclass
class QueryResponse:
    """Structured response returned by RAGQueryService.query().

    Attributes:
        answer: The LLM-generated answer based exclusively on retrieved context.
            Contains the contingency phrase if no relevant context was found.
        sources: Ordered list of chunks used to build the context (most
            relevant first). Empty if no chunks passed the similarity threshold.
        query: The original user question (verbatim).
        chunks_used: Count of chunks included in the prompt context.
        model_used: LLM model identifier used for the completion call.
        no_context_found: True when the retrieval step returned zero relevant
            chunks above the similarity threshold. Used by callers to distinguish
            a genuine "no answer" from an empty answer string.
        created_at: UTC timestamp of the response.
    """

    answer: str
    sources: list[RetrievedChunk]
    query: str
    chunks_used: int
    model_used: str
    no_context_found: bool = False
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def to_dict(self) -> dict:
        """Serialize QueryResponse to a plain dictionary for logging/debugging."""
        return {
            "answer": self.answer,
            "query": self.query,
            "chunks_used": self.chunks_used,
            "model_used": self.model_used,
            "no_context_found": self.no_context_found,
            "created_at": self.created_at.isoformat(),
            "sources": [
                {
                    "chunk_id": s.chunk_id,
                    "policy_id": s.policy_id,
                    "chunk_index": s.chunk_index,
                    "similarity_score": round(s.similarity_score, 4),
                    "label": s.document_label,
                }
                for s in self.sources
            ],
        }

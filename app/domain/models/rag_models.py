"""DocEngine — Domain Models: RAG Processing Report.

Defines the output structure after processing a document through the RAG pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RagProcessingReport:
    """Summary report of RAG processing for a policy document.

    Attributes:
        policy_id: UUID string of the policy record in PostgreSQL.
        file_name: Name of the processed PDF file.
        file_hash: SHA-256 digest of the PDF file.
        company_sigla: Company identifier code (e.g. CRI, LBC).
        chunks_created: Number of chunks created and stored.
        embedding_dim: Dimension of generated embeddings (1024 for bge-m3).
        skipped_duplicate: Whether processing was skipped due to idempotency.
        processing_time_seconds: Elapsed time in seconds for RAG pipeline.
        job_id: Optional UUID string of the async processing job.
        errors: Non-fatal error messages during processing.
        created_at: Completion timestamp.
    """

    policy_id: str | None
    file_name: str
    file_hash: str
    company_sigla: str | None = None
    chunks_created: int = 0
    embedding_dim: int = 1024
    skipped_duplicate: bool = False
    processing_time_seconds: float = 0.0
    job_id: str | None = None
    errors: list[str] = field(default_factory=list)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def to_dict(self) -> dict:
        """Serialize report to a dictionary representation."""
        return {
            "policy_id": self.policy_id,
            "file_name": self.file_name,
            "file_hash": self.file_hash,
            "company_sigla": self.company_sigla,
            "chunks_created": self.chunks_created,
            "embedding_dim": self.embedding_dim,
            "skipped_duplicate": self.skipped_duplicate,
            "processing_time_seconds": round(self.processing_time_seconds, 3),
            "job_id": self.job_id,
            "errors": self.errors,
            "created_at": self.created_at.isoformat(),
        }

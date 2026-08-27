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


@dataclass
class PolicyProcessingStats:
    """Detailed telemetry and processing statistics for a policy document.

    Attributes:
        policy_id: UUID of the policy (PK & FK to policies.id).
        job_id: Optional UUID of the processing job.
        policy_number: Extracted policy identifier or number.
        company_sigla: 3-letter insurer code.
        file_type: PDF document category ('DIGITAL', 'SCANNED', 'HYBRID', 'UNKNOWN').
        ocr_applied: Whether OCR engine was executed.
        scanned_page_ratio: Fraction (0.0 - 1.0) of pages classified as scanned.
        total_pages: Total number of processed pages.
        extraction_time_seconds: Docling PDF extraction wall-clock duration.
        time_per_page_seconds: Average extraction duration per page.
        chunking_time_seconds: Markdown chunking duration.
        embedding_time_seconds: Local dense embedding generation duration.
        openai_time_seconds: LLM structured JSON extraction duration.
        total_pipeline_time_seconds: End-to-end processing duration.
        total_chunks: Count of generated text chunks.
        parent_chunks: Count of parent hierarchy chunks.
        child_chunks: Count of child hierarchy chunks.
        openai_prompt_tokens: Input tokens billed by OpenAI.
        openai_completion_tokens: Output tokens billed by OpenAI.
        openai_total_tokens: Total tokens consumed.
        openai_estimated_cost_usd: Estimated OpenAI cost in USD.
        coberturas_extracted_count: Count of extracted coverage items.
        tables_detected: Count of detected tabular structures.
        memory_peak_mb: Peak RAM usage in megabytes during processing.
        created_at: Creation timestamp.
    """

    policy_id: str
    job_id: str | None = None
    policy_number: str | None = None
    company_sigla: str | None = None
    file_type: str = "UNKNOWN"
    ocr_applied: bool = False
    scanned_page_ratio: float | None = None
    total_pages: int = 0
    extraction_time_seconds: float = 0.0
    time_per_page_seconds: float = 0.0
    chunking_time_seconds: float = 0.0
    embedding_time_seconds: float = 0.0
    openai_time_seconds: float = 0.0
    total_pipeline_time_seconds: float = 0.0
    total_chunks: int = 0
    parent_chunks: int = 0
    child_chunks: int = 0
    openai_prompt_tokens: int = 0
    openai_completion_tokens: int = 0
    openai_total_tokens: int = 0
    openai_estimated_cost_usd: float = 0.0
    coberturas_extracted_count: int = 0
    tables_detected: int = 0
    memory_peak_mb: float | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    def to_dict(self) -> dict:
        """Serialize stats to a JSON-compatible dictionary."""
        return {
            "policy_id": self.policy_id,
            "job_id": self.job_id,
            "policy_number": self.policy_number,
            "company_sigla": self.company_sigla,
            "file_type": self.file_type,
            "ocr_applied": self.ocr_applied,
            "scanned_page_ratio": self.scanned_page_ratio,
            "total_pages": self.total_pages,
            "extraction_time_seconds": round(self.extraction_time_seconds, 3),
            "time_per_page_seconds": round(self.time_per_page_seconds, 3),
            "chunking_time_seconds": round(self.chunking_time_seconds, 3),
            "embedding_time_seconds": round(self.embedding_time_seconds, 3),
            "openai_time_seconds": round(self.openai_time_seconds, 3),
            "total_pipeline_time_seconds": round(self.total_pipeline_time_seconds, 3),
            "total_chunks": self.total_chunks,
            "parent_chunks": self.parent_chunks,
            "child_chunks": self.child_chunks,
            "openai_prompt_tokens": self.openai_prompt_tokens,
            "openai_completion_tokens": self.openai_completion_tokens,
            "openai_total_tokens": self.openai_total_tokens,
            "openai_estimated_cost_usd": round(self.openai_estimated_cost_usd, 5),
            "coberturas_extracted_count": self.coberturas_extracted_count,
            "tables_detected": self.tables_detected,
            "memory_peak_mb": round(self.memory_peak_mb, 2) if self.memory_peak_mb is not None else None,
            "created_at": self.created_at.isoformat(),
        }


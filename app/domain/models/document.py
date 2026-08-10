"""DocEngine — Domain Models: Document.

Defines the core data structures produced by the extraction pipeline.
These models are technology-agnostic: they know nothing about Docling,
FastAPI, or any storage technology.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.models.extraction import ExtractionStatus


@dataclass
class DocumentMetadata:
    """Rich metadata produced for every extracted document.

    Attributes:
        filename: Original filename as provided to the extractor.
        source_path: Absolute path to the source document.
        sha256: SHA-256 digest of the original file content.
        page_count: Total number of pages in the document.
        extraction_time_seconds: Wall-clock time for the full extraction.
        docling_version: Docling library version used for extraction.
        tables_detected: Number of tables detected in the document.
        figures_detected: Number of figures/images detected.
        headers_removed: Count of repeated headers that were removed.
        footers_removed: Count of repeated footers that were removed.
        ocr_used: Whether OCR was activated during extraction.
        has_multi_column: Whether multi-column layout was detected.
        markdown_size_bytes: Size of the produced Markdown in bytes.
        errors: List of non-fatal error messages encountered.
        warnings: List of quality warnings for the extraction result.
        extracted_at: UTC timestamp of extraction completion.
    """

    filename: str
    source_path: Path
    sha256: str
    page_count: int
    extraction_time_seconds: float
    docling_version: str
    tables_detected: int
    figures_detected: int
    headers_removed: int
    footers_removed: int
    ocr_used: bool
    has_multi_column: bool
    markdown_size_bytes: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extracted_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    # Optional: company sigla (e.g. "CRI") for outputs organized by insurer
    company_sigla: str | None = None

    def to_dict(self) -> dict:
        """Serialize metadata to a JSON-compatible dictionary.

        Returns:
            Dictionary representation of all metadata fields.
        """
        return {
            "filename": self.filename,
            "source_path": str(self.source_path),
            "sha256": self.sha256,
            "page_count": self.page_count,
            "extraction_time_seconds": round(self.extraction_time_seconds, 3),
            "docling_version": self.docling_version,
            "tables_detected": self.tables_detected,
            "figures_detected": self.figures_detected,
            "headers_removed": self.headers_removed,
            "footers_removed": self.footers_removed,
            "ocr_used": self.ocr_used,
            "has_multi_column": self.has_multi_column,
            "markdown_size_bytes": self.markdown_size_bytes,
            "errors": self.errors,
            "warnings": self.warnings,
            "extracted_at": self.extracted_at.isoformat(),
            "company_sigla": self.company_sigla,
        }


@dataclass
class ExtractionResult:
    """The complete output of one document extraction operation.

    Every extraction — whether from a file, folder, or URL — produces
    exactly one ExtractionResult per document.

    Attributes:
        document_id: Unique identifier for this extraction (UUID-based).
        status: Final status of the extraction (SUCCESS / PARTIAL / FAILED).
        markdown: The Markdown representation of the document.
        json_data: The full structured representation from Docling.
        metadata: Rich metadata about the extraction process.
        output_paths: Mapping of format name to output file path.
        created_at: UTC timestamp of object creation.
    """

    document_id: str
    status: "ExtractionStatus"
    markdown: str
    json_data: dict
    metadata: DocumentMetadata
    output_paths: dict[str, Path] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    @property
    def is_successful(self) -> bool:
        """Return True if extraction completed without critical errors."""
        from app.domain.models.extraction import ExtractionStatus  # noqa: PLC0415

        return self.status in (ExtractionStatus.SUCCESS, ExtractionStatus.PARTIAL)

    @property
    def markdown_preview(self) -> str:
        """Return the first 500 characters of Markdown for API previews."""
        return self.markdown[:500]

    def to_summary_dict(self) -> dict:
        """Serialize a lightweight summary for API responses.

        Returns:
            Dictionary with key fields, suitable for JSON serialisation.
        """
        return {
            "document_id": self.document_id,
            "status": self.status.value if hasattr(self.status, "value") else str(self.status),
            "markdown_preview": self.markdown_preview,
            "metadata": self.metadata.to_dict(),
            "output_paths": {k: str(v) for k, v in self.output_paths.items()},
            "created_at": self.created_at.isoformat(),
        }


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file, reading in chunks.

    Reads the file in 64 KB chunks to avoid loading large files
    entirely into memory.

    Args:
        file_path: Path to the file to hash.

    Returns:
        Hexadecimal SHA-256 digest string.

    Raises:
        FileNotFoundError: If the file does not exist.
        PermissionError: If the file cannot be read.
    """
    sha256 = hashlib.sha256()
    chunk_size = 65_536  # 64 KB

    with file_path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            sha256.update(chunk)

    return sha256.hexdigest()

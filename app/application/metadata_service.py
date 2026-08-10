"""DocEngine — Application Service: MetadataService.

Extracts and enriches document metadata from extraction results.
All metadata computation logic is centralised here.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.domain.models.document import DocumentMetadata, compute_sha256
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class MetadataService:
    """Computes and enriches DocumentMetadata from raw extraction data.

    Separating metadata logic into its own service ensures that
    metadata computation can be tested and modified independently
    of the extraction pipeline.
    """

    def enrich_metadata(
        self,
        metadata: DocumentMetadata,
        headers_removed: int,
        footers_removed: int,
        processed_markdown: str,
        has_multi_column: bool = False,
    ) -> DocumentMetadata:
        """Enrich metadata with post-processing results.

        Called after MarkdownService.post_process() has run to update
        the metadata fields that depend on post-processing outcomes.

        Args:
            metadata: The metadata object to enrich (modified in-place).
            headers_removed: Number of repeated headers removed.
            footers_removed: Number of repeated footers removed.
            processed_markdown: Final Markdown text after post-processing.
            has_multi_column: Whether multi-column layout was detected.

        Returns:
            The enriched metadata object.
        """
        metadata.headers_removed = headers_removed
        metadata.footers_removed = footers_removed
        metadata.markdown_size_bytes = len(processed_markdown.encode("utf-8"))
        metadata.has_multi_column = has_multi_column

        logger.debug(
            "Metadata enriched",
            filename=metadata.filename,
            headers_removed=headers_removed,
            footers_removed=footers_removed,
            markdown_size_bytes=metadata.markdown_size_bytes,
        )

        return metadata

    def compute_sha256(self, file_path: Path) -> str:
        """Compute SHA-256 hash of a file.

        Args:
            file_path: Path to the file to hash.

        Returns:
            Hexadecimal SHA-256 digest string. Empty string on error.
        """
        try:
            return compute_sha256(file_path)
        except Exception as exc:
            logger.warning(
                "Failed to compute SHA256",
                file=str(file_path),
                error=str(exc),
            )
            return ""

    def estimate_memory_usage_mb(self) -> float:
        """Return the current process memory usage in megabytes.

        Returns:
            Memory in MB, or 0.0 if psutil is unavailable.
        """
        try:
            import psutil  # noqa: PLC0415

            return psutil.Process().memory_info().rss / 1_048_576
        except Exception:
            return 0.0

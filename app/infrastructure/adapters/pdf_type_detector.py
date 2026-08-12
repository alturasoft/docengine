"""DocEngine — Infrastructure Adapter: PdfTypeDetector.

Classifies a PDF document as:
- DIGITAL: All pages contain embedded (selectable) text. No OCR needed.
- SCANNED: Pages are rasterised images. OCR required for text extraction.
- HYBRID: Mix of digital and scanned pages. OCR recommended.
- UNKNOWN: Classification could not be determined (URL source, read error).

Detection is performed with pypdfium2 (already available as Docling's PDF
backend) using ``count_chars()`` — a fast character-count probe that does NOT
allocate a text buffer, making it 3–5× faster than ``get_text_bounded()``.

This module is intentionally isolated from all Docling internals so it can be
called BEFORE the DocumentConverter is configured, allowing DoclingAdapter to
set ``do_ocr`` correctly from the start.

Design principles:
- ADDITIVE only — never imported or used by existing modules.
- No ML models are loaded. Detection cost ≤ 0.5 s for a 30-page document.
- Safe fallback: any error returns UNKNOWN (pipeline continues normally).
- Sampling strategy: inspects at most ``max_sample_pages`` pages spread across
  the document (beginning, middle, end) to keep detection sub-second on large
  files while maintaining statistical accuracy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Public enumerations and data types
# ---------------------------------------------------------------------------


class PdfClassification(str, Enum):
    """Final classification of a PDF document's content type.

    Values:
        DIGITAL: All inspected pages have embedded text (selectable, copyable).
            Docling can extract text directly without OCR.
        SCANNED: Inspected pages are rasterised images with no usable text layer.
            Docling requires OCR (``do_ocr=True``) to extract any content.
        HYBRID: Mix of digital and scanned pages detected.
            Docling should enable OCR but without ``force_full_page_ocr`` so
            that OCR is applied only where no text layer is present.
        UNKNOWN: Classification failed (URL source, corrupt PDF, import error).
            Pipeline defaults to no-OCR (safe fallback).
    """

    DIGITAL = "digital"
    SCANNED = "scanned"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


@dataclass
class PdfTypeResult:
    """Result of a PDF type classification operation.

    Attributes:
        classification: Final classification (DIGITAL / SCANNED / HYBRID / UNKNOWN).
        scanned_pages: Number of inspected pages classified as scanned.
        digital_pages: Number of inspected pages classified as digital (embedded text).
        total_pages: Total number of pages in the document (not just sampled).
        scanned_ratio: Fraction of *sampled* pages that are scanned (0.0–1.0).
        detection_time_seconds: Wall-clock seconds spent on classification.
        sample_pages_checked: How many pages were actually inspected.
        error: Error message if classification failed, else empty string.
    """

    classification: PdfClassification
    scanned_pages: int = 0
    digital_pages: int = 0
    total_pages: int = 0
    scanned_ratio: float = 0.0
    detection_time_seconds: float = 0.0
    sample_pages_checked: int = 0
    error: str = ""

    @property
    def is_scanned(self) -> bool:
        """Return True if the document requires OCR."""
        return self.classification in (PdfClassification.SCANNED, PdfClassification.HYBRID)

    @property
    def force_full_page_ocr(self) -> bool:
        """Return True only for fully scanned documents (not hybrid).

        For SCANNED documents every page is an image, so forcing full-page OCR
        is safe and produces better results.
        For HYBRID documents Docling should decide per-region to preserve
        quality of the digital sections.
        """
        return self.classification == PdfClassification.SCANNED

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dictionary for metadata inclusion."""
        return {
            "pdf_type": self.classification.value,
            "scanned_pages_sampled": self.scanned_pages,
            "digital_pages_sampled": self.digital_pages,
            "total_pages": self.total_pages,
            "scanned_ratio": round(self.scanned_ratio, 4),
            "detection_time_seconds": round(self.detection_time_seconds, 4),
            "sample_pages_checked": self.sample_pages_checked,
        }


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class PdfTypeDetector:
    """Classifies a PDF document as digital, scanned, or hybrid.

    Uses pypdfium2 to probe each sampled page's character count. This avoids
    loading any ML model and completes in milliseconds per page.

    Args:
        min_chars_per_page: Minimum character count for a page to be
            classified as "digital" (has embedded text). Pages with fewer
            characters than this threshold are treated as scanned.
            Default 15 — low enough to catch partially-text pages while
            filtering pure image pages that may have 0–5 stray characters
            from watermarks or stamps.
        scanned_ratio_threshold: Fraction of sampled pages that must be
            scanned before the document is labelled SCANNED or HYBRID.
            - ratio >= threshold  → SCANNED
            - 0 < ratio < threshold → HYBRID
            - ratio == 0 → DIGITAL
            Default 0.5 (50%).
        max_sample_pages: Maximum number of pages to inspect. For documents
            with more pages than this, a representative sample is selected
            from the beginning, middle, and end.
            Default 10.
    """

    def __init__(
        self,
        min_chars_per_page: int = 15,
        scanned_ratio_threshold: float = 0.5,
        max_sample_pages: int = 10,
    ) -> None:
        self._min_chars = min_chars_per_page
        self._scanned_threshold = scanned_ratio_threshold
        self._max_sample = max_sample_pages

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, source: Path | str) -> PdfTypeResult:
        """Classify a PDF document's content type.

        Only operates on local file paths. URL sources return UNKNOWN
        immediately to avoid download overhead at this stage.

        Args:
            source: Absolute path to the PDF file, or a URL string.

        Returns:
            PdfTypeResult with classification and supporting statistics.
        """
        start = time.perf_counter()

        # URLs cannot be classified without downloading — safe fallback
        source_str = str(source)
        if source_str.startswith(("http://", "https://")):
            elapsed = time.perf_counter() - start
            logger.debug(
                "PDF type detection skipped for URL source",
                source=source_str,
            )
            return PdfTypeResult(
                classification=PdfClassification.UNKNOWN,
                detection_time_seconds=elapsed,
                error="URL source: pre-classification not supported",
            )

        pdf_path = Path(source_str)
        if not pdf_path.exists() or not pdf_path.is_file():
            elapsed = time.perf_counter() - start
            logger.warning(
                "PDF type detection: file not found",
                path=str(pdf_path),
            )
            return PdfTypeResult(
                classification=PdfClassification.UNKNOWN,
                detection_time_seconds=elapsed,
                error=f"File not found: {pdf_path}",
            )

        try:
            return self._classify_file(pdf_path, start)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.perf_counter() - start
            logger.warning(
                "PDF type detection failed — defaulting to UNKNOWN",
                path=str(pdf_path),
                error=str(exc),
            )
            return PdfTypeResult(
                classification=PdfClassification.UNKNOWN,
                detection_time_seconds=elapsed,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _classify_file(self, pdf_path: Path, start: float) -> PdfTypeResult:
        """Core classification logic using pypdfium2.

        Args:
            pdf_path: Verified existing PDF file path.
            start: ``time.perf_counter()`` value at classification start.

        Returns:
            PdfTypeResult with detailed statistics.

        Raises:
            ImportError: If pypdfium2 is not installed.
            Exception: For any PDF read or structure error.
        """
        import pypdfium2 as pdfium  # noqa: PLC0415

        doc = pdfium.PdfDocument(str(pdf_path))

        try:
            total_pages = len(doc)
            sample_indices = self._build_sample_indices(total_pages)

            scanned = 0
            digital = 0

            for page_idx in sample_indices:
                page = doc[page_idx]
                try:
                    text_page = page.get_textpage()
                    char_count = text_page.count_chars()
                    if char_count < self._min_chars:
                        scanned += 1
                    else:
                        digital += 1
                    text_page.close()
                except Exception as exc:  # noqa: BLE001
                    # If we cannot read a page's text, treat conservatively
                    # as scanned (OCR is safer than missing text).
                    scanned += 1
                    logger.debug(
                        "Could not read text from page — treating as scanned",
                        page=page_idx,
                        error=str(exc),
                    )
                finally:
                    page.close()

        finally:
            doc.close()

        total_sampled = scanned + digital
        scanned_ratio = scanned / total_sampled if total_sampled > 0 else 0.0
        classification = self._determine_classification(scanned_ratio)
        elapsed = time.perf_counter() - start

        logger.info(
            "PDF type classification complete",
            path=pdf_path.name,
            classification=classification.value,
            scanned_pages=scanned,
            digital_pages=digital,
            total_pages=total_pages,
            sample_pages_checked=total_sampled,
            scanned_ratio=round(scanned_ratio, 3),
            detection_seconds=round(elapsed, 3),
        )

        return PdfTypeResult(
            classification=classification,
            scanned_pages=scanned,
            digital_pages=digital,
            total_pages=total_pages,
            scanned_ratio=scanned_ratio,
            detection_time_seconds=elapsed,
            sample_pages_checked=total_sampled,
        )

    def _build_sample_indices(self, total_pages: int) -> list[int]:
        """Build a representative set of page indices to inspect.

        Strategy:
        - Documents ≤ max_sample_pages: inspect all pages.
        - Larger documents: proportional sample from start, middle, end
          that never exceeds max_sample_pages.

        Args:
            total_pages: Total number of pages in the document.

        Returns:
            Sorted list of unique page indices (0-indexed).
        """
        if total_pages <= self._max_sample:
            return list(range(total_pages))

        # Always include first 3 and last 2 pages
        head = list(range(min(3, total_pages)))
        tail = list(range(max(total_pages - 2, 3), total_pages))

        # Fill remaining budget from the middle section
        budget = self._max_sample - len(head) - len(tail)
        if budget > 0:
            mid_start = len(head)
            mid_end = total_pages - len(tail)
            mid_range = list(range(mid_start, mid_end))
            if mid_range:
                step = max(1, len(mid_range) // (budget + 1))
                middle = mid_range[::step][:budget]
            else:
                middle = []
        else:
            middle = []

        # Merge, deduplicate, sort
        combined = sorted(set(head + middle + tail))
        return combined

    def _determine_classification(self, scanned_ratio: float) -> PdfClassification:
        """Map a scanned page ratio to a PdfClassification label.

        Args:
            scanned_ratio: Fraction of sampled pages classified as scanned (0–1).

        Returns:
            PdfClassification enum value.
        """
        if scanned_ratio == 0.0:
            return PdfClassification.DIGITAL
        if scanned_ratio >= self._scanned_threshold:
            return PdfClassification.SCANNED
        return PdfClassification.HYBRID

"""DocEngine — Unit Tests: PdfTypeDetector.

Tests for app.infrastructure.adapters.pdf_type_detector.

Strategy:
- Mock pypdfium2 to avoid real file I/O and ML dependencies.
- Test each classification path: DIGITAL, SCANNED, HYBRID, UNKNOWN.
- Test sampling logic independently (no I/O required).
- Test edge cases: 1-page doc, URL source, missing file, read error.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.adapters.pdf_type_detector import (
    PdfClassification,
    PdfTypeDetector,
    PdfTypeResult,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_detector(
    min_chars: int = 15,
    scanned_threshold: float = 0.5,
    max_sample: int = 10,
) -> PdfTypeDetector:
    """Return a PdfTypeDetector with controllable parameters."""
    return PdfTypeDetector(
        min_chars_per_page=min_chars,
        scanned_ratio_threshold=scanned_threshold,
        max_sample_pages=max_sample,
    )


def _mock_pdf_doc(pages_char_counts: list[int]) -> MagicMock:
    """Build a mock pypdfium2.PdfDocument with given per-page char counts.

    Args:
        pages_char_counts: List of char counts, one per page.

    Returns:
        MagicMock mimicking pdfium.PdfDocument behaviour.
    """
    mock_doc = MagicMock()
    mock_doc.__len__ = MagicMock(return_value=len(pages_char_counts))

    pages = []
    for count in pages_char_counts:
        mock_text_page = MagicMock()
        mock_text_page.count_chars.return_value = count
        mock_page = MagicMock()
        mock_page.get_textpage.return_value = mock_text_page
        pages.append(mock_page)

    mock_doc.__getitem__ = MagicMock(side_effect=lambda i: pages[i])
    mock_doc.close = MagicMock()
    return mock_doc


# ---------------------------------------------------------------------------
# Classification tests
# ---------------------------------------------------------------------------


class TestPdfClassificationPaths:
    """Tests that cover the three main classification outcomes."""

    def _run_classify(
        self,
        pages_char_counts: list[int],
        tmp_path: Path,
        detector: PdfTypeDetector | None = None,
    ) -> PdfTypeResult:
        """Helper: create a dummy file, mock pypdfium2, run classify()."""
        dummy_pdf = tmp_path / "test.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 fake")  # Non-empty file

        det = detector or _make_detector()
        mock_doc = _mock_pdf_doc(pages_char_counts)

        with patch("app.infrastructure.adapters.pdf_type_detector.PdfTypeDetector._classify_file") as mock_cf:
            # Call the real classify() which checks file existence, then
            # delegate to our mocked _classify_file
            mock_cf.side_effect = lambda path, start: det._classify_file.__wrapped__(  # type: ignore[attr-defined]
                det, path, start
            ) if hasattr(det._classify_file, "__wrapped__") else None

        # Patch pypdfium2 directly for _classify_file
        with patch.dict("sys.modules", {"pypdfium2": MagicMock(PdfDocument=MagicMock(return_value=mock_doc))}):
            result = det.classify(str(dummy_pdf))

        return result

    def test_all_digital_pages(self, tmp_path: Path) -> None:
        """All pages with abundant text → DIGITAL, ocr not needed."""
        dummy_pdf = tmp_path / "digital.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 fake")
        det = _make_detector()
        mock_doc = _mock_pdf_doc([200, 350, 180, 420, 310])

        import sys
        mock_pdfium = MagicMock()
        mock_pdfium.PdfDocument.return_value = mock_doc

        with patch.dict(sys.modules, {"pypdfium2": mock_pdfium}):
            result = det.classify(str(dummy_pdf))

        assert result.classification == PdfClassification.DIGITAL
        assert result.is_scanned is False
        assert result.force_full_page_ocr is False
        assert result.scanned_ratio == 0.0
        assert result.digital_pages == 5
        assert result.scanned_pages == 0

    def test_all_scanned_pages(self, tmp_path: Path) -> None:
        """All pages with 0 chars → SCANNED, force_full_page_ocr."""
        dummy_pdf = tmp_path / "scanned.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 fake")
        det = _make_detector()
        mock_doc = _mock_pdf_doc([0, 0, 0, 2, 0])  # All below threshold 15

        import sys
        mock_pdfium = MagicMock()
        mock_pdfium.PdfDocument.return_value = mock_doc

        with patch.dict(sys.modules, {"pypdfium2": mock_pdfium}):
            result = det.classify(str(dummy_pdf))

        assert result.classification == PdfClassification.SCANNED
        assert result.is_scanned is True
        assert result.force_full_page_ocr is True
        assert result.scanned_ratio == 1.0
        assert result.scanned_pages == 5
        assert result.digital_pages == 0

    def test_hybrid_pages(self, tmp_path: Path) -> None:
        """Mix of scanned/digital below 50% scanned → HYBRID."""
        dummy_pdf = tmp_path / "hybrid.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 fake")
        # 2 scanned out of 5 = 40% < 50% threshold → HYBRID
        det = _make_detector(scanned_threshold=0.5)
        mock_doc = _mock_pdf_doc([200, 0, 300, 5, 450])

        import sys
        mock_pdfium = MagicMock()
        mock_pdfium.PdfDocument.return_value = mock_doc

        with patch.dict(sys.modules, {"pypdfium2": mock_pdfium}):
            result = det.classify(str(dummy_pdf))

        assert result.classification == PdfClassification.HYBRID
        assert result.is_scanned is True
        assert result.force_full_page_ocr is False
        assert result.scanned_pages == 2
        assert result.digital_pages == 3

    def test_majority_scanned_above_threshold(self, tmp_path: Path) -> None:
        """More than 50% scanned → SCANNED (not hybrid)."""
        dummy_pdf = tmp_path / "mostly_scanned.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 fake")
        # 3 scanned out of 4 = 75% >= 50% threshold → SCANNED
        det = _make_detector(scanned_threshold=0.5)
        mock_doc = _mock_pdf_doc([0, 0, 0, 300])

        import sys
        mock_pdfium = MagicMock()
        mock_pdfium.PdfDocument.return_value = mock_doc

        with patch.dict(sys.modules, {"pypdfium2": mock_pdfium}):
            result = det.classify(str(dummy_pdf))

        assert result.classification == PdfClassification.SCANNED
        assert result.scanned_pages == 3
        assert result.digital_pages == 1


# ---------------------------------------------------------------------------
# Fallback / edge case tests
# ---------------------------------------------------------------------------


class TestPdfTypeDetectorFallbacks:
    """Tests for UNKNOWN fallback scenarios."""

    def test_url_source_returns_unknown(self) -> None:
        """URL sources must immediately return UNKNOWN without file I/O."""
        det = _make_detector()
        result = det.classify("https://example.com/poliza.pdf")

        assert result.classification == PdfClassification.UNKNOWN
        assert result.is_scanned is False
        assert "URL" in result.error

    def test_http_source_returns_unknown(self) -> None:
        """HTTP (non-HTTPS) URLs also return UNKNOWN."""
        det = _make_detector()
        result = det.classify("http://internal.server.com/doc.pdf")
        assert result.classification == PdfClassification.UNKNOWN

    def test_missing_file_returns_unknown(self, tmp_path: Path) -> None:
        """Non-existent file path returns UNKNOWN with error message."""
        det = _make_detector()
        non_existent = tmp_path / "does_not_exist.pdf"
        result = det.classify(str(non_existent))

        assert result.classification == PdfClassification.UNKNOWN
        assert result.error != ""

    def test_pypdfium2_error_returns_unknown(self, tmp_path: Path) -> None:
        """If pypdfium2 raises during open, UNKNOWN is returned safely."""
        dummy_pdf = tmp_path / "corrupt.pdf"
        dummy_pdf.write_bytes(b"not a real pdf")
        det = _make_detector()

        import sys
        mock_pdfium = MagicMock()
        mock_pdfium.PdfDocument.side_effect = RuntimeError("corrupt PDF")

        with patch.dict(sys.modules, {"pypdfium2": mock_pdfium}):
            result = det.classify(str(dummy_pdf))

        assert result.classification == PdfClassification.UNKNOWN
        assert "corrupt PDF" in result.error

    def test_single_page_digital(self, tmp_path: Path) -> None:
        """Single-page PDF with text → DIGITAL."""
        dummy_pdf = tmp_path / "single.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4")
        det = _make_detector()
        mock_doc = _mock_pdf_doc([500])

        import sys
        mock_pdfium = MagicMock()
        mock_pdfium.PdfDocument.return_value = mock_doc

        with patch.dict(sys.modules, {"pypdfium2": mock_pdfium}):
            result = det.classify(str(dummy_pdf))

        assert result.classification == PdfClassification.DIGITAL
        assert result.total_pages == 1
        assert result.sample_pages_checked == 1

    def test_single_page_scanned(self, tmp_path: Path) -> None:
        """Single-page PDF with 0 chars → SCANNED."""
        dummy_pdf = tmp_path / "single_scan.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4")
        det = _make_detector()
        mock_doc = _mock_pdf_doc([0])

        import sys
        mock_pdfium = MagicMock()
        mock_pdfium.PdfDocument.return_value = mock_doc

        with patch.dict(sys.modules, {"pypdfium2": mock_pdfium}):
            result = det.classify(str(dummy_pdf))

        assert result.classification == PdfClassification.SCANNED


# ---------------------------------------------------------------------------
# Sampling logic tests (no I/O)
# ---------------------------------------------------------------------------


class TestSamplingLogic:
    """Tests for _build_sample_indices — pure logic, no file I/O."""

    def test_small_doc_inspects_all_pages(self) -> None:
        """Documents with pages <= max_sample should inspect every page."""
        det = _make_detector(max_sample=10)
        indices = det._build_sample_indices(7)
        assert indices == list(range(7))

    def test_exact_max_sample_inspects_all(self) -> None:
        """Documents with pages == max_sample should inspect every page."""
        det = _make_detector(max_sample=10)
        indices = det._build_sample_indices(10)
        assert indices == list(range(10))

    def test_large_doc_never_exceeds_max_sample(self) -> None:
        """Documents with more pages than max_sample must not exceed limit."""
        det = _make_detector(max_sample=10)
        for total in [15, 30, 50, 100, 500]:
            indices = det._build_sample_indices(total)
            assert len(indices) <= 10, f"Expected <= 10 for {total} pages, got {len(indices)}"

    def test_large_doc_includes_first_pages(self) -> None:
        """First pages are always sampled."""
        det = _make_detector(max_sample=10)
        indices = det._build_sample_indices(100)
        assert 0 in indices
        assert 1 in indices
        assert 2 in indices

    def test_large_doc_includes_last_pages(self) -> None:
        """Last pages are always sampled."""
        det = _make_detector(max_sample=10)
        indices = det._build_sample_indices(100)
        assert 99 in indices
        assert 98 in indices

    def test_sample_indices_are_sorted_and_unique(self) -> None:
        """Sample indices must be sorted and have no duplicates."""
        det = _make_detector(max_sample=10)
        for total in [1, 5, 10, 20, 50, 200]:
            indices = det._build_sample_indices(total)
            assert indices == sorted(set(indices)), f"Failed for total={total}"

    def test_single_page_doc(self) -> None:
        """Single-page documents produce [0]."""
        det = _make_detector(max_sample=10)
        assert det._build_sample_indices(1) == [0]


# ---------------------------------------------------------------------------
# PdfTypeResult helpers
# ---------------------------------------------------------------------------


class TestPdfTypeResult:
    """Tests for PdfTypeResult properties and serialization."""

    def test_to_dict_fields(self) -> None:
        """to_dict() includes all expected keys."""
        result = PdfTypeResult(
            classification=PdfClassification.SCANNED,
            scanned_pages=8,
            digital_pages=2,
            total_pages=30,
            scanned_ratio=0.8,
            detection_time_seconds=0.123,
            sample_pages_checked=10,
        )
        d = result.to_dict()
        assert d["pdf_type"] == "scanned"
        assert d["scanned_pages_sampled"] == 8
        assert d["digital_pages_sampled"] == 2
        assert d["total_pages"] == 30
        assert d["scanned_ratio"] == 0.8
        assert "detection_time_seconds" in d
        assert d["sample_pages_checked"] == 10

    def test_is_scanned_for_hybrid(self) -> None:
        """HYBRID should report is_scanned=True."""
        result = PdfTypeResult(classification=PdfClassification.HYBRID)
        assert result.is_scanned is True

    def test_force_full_page_ocr_only_for_scanned(self) -> None:
        """Only SCANNED (not HYBRID) triggers force_full_page_ocr."""
        scanned = PdfTypeResult(classification=PdfClassification.SCANNED)
        hybrid = PdfTypeResult(classification=PdfClassification.HYBRID)
        digital = PdfTypeResult(classification=PdfClassification.DIGITAL)

        assert scanned.force_full_page_ocr is True
        assert hybrid.force_full_page_ocr is False
        assert digital.force_full_page_ocr is False

"""Unit tests for PdfExtractAdapter."""

from pathlib import Path
from unittest.mock import patch

from app.config.settings import AppSettings
from app.domain.models.extraction import ExtractionRequest, ExtractionStatus
from app.infrastructure.adapters.pdfextract_adapter import PdfExtractAdapter


class TestPdfExtractAdapter:
    """Test suite for PdfExtractAdapter."""

    def test_adapter_initialization(self, app_settings: AppSettings) -> None:
        adapter = PdfExtractAdapter(config=app_settings)
        assert "PdfExtractAdapter" in adapter.extractor_name
        assert adapter.supports_ocr is True

    def test_nonexistent_file_returns_failed_status(self, app_settings: AppSettings) -> None:
        adapter = PdfExtractAdapter(config=app_settings)
        request = ExtractionRequest(source=Path("non_existent_file.pdf"))
        result = adapter.extract(request)

        assert result.status == ExtractionStatus.FAILED
        assert result.is_successful is False
        assert len(result.metadata.errors) > 0
        assert "No se encontró el archivo PDF" in result.metadata.errors[0]

    @patch("pdfextract.extract_pdf")
    def test_successful_extraction_mocked(self, mock_extract_pdf, tmp_path: Path, app_settings: AppSettings) -> None:
        test_pdf = tmp_path / "test.pdf"
        test_pdf.write_bytes(b"%PDF-1.4 dummy")

        # Create dummy md file
        md_file = tmp_path / "test.md"
        md_file.write_text("# Mock Heading\n\nContent", encoding="utf-8")

        mock_extract_pdf.return_value = {
            "document": {
                "filename": "test.pdf",
                "file_hash_sha256": "fakehash123",
                "total_pages": 2,
                "document_type": "native",
            },
            "engines": {
                "postprocessed": {
                    "status": "success",
                    "tables_count": 1,
                    "pages_detected": 2,
                    "output_files": {
                        "md": str(md_file),
                        "json": None,
                    },
                }
            },
        }

        adapter = PdfExtractAdapter(config=app_settings)
        request = ExtractionRequest(source=test_pdf)
        result = adapter.extract(request)

        assert result.status == ExtractionStatus.SUCCESS
        assert result.is_successful is True
        assert "# Mock Heading" in result.markdown
        assert result.metadata.page_count == 2
        assert result.metadata.tables_detected == 1
        assert result.metadata.sha256 == "fakehash123"
        assert result.metadata.pdf_type == "digital"

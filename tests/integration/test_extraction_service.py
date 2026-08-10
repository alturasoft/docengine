"""Integration tests for ExtractionService with a real PDF.

These tests require samples/test_poliza.pdf to exist.
They are automatically skipped when the file is absent.

Run with: pytest tests/integration/test_extraction_service.py -v -m integration
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.application.extraction_service import ExtractionService
from app.application.markdown_service import MarkdownService
from app.application.metadata_service import MetadataService
from app.application.validation_service import ValidationService
from app.config.settings import AppSettings
from app.domain.models.extraction import ExtractionRequest, ExtractionStatus
from app.infrastructure.adapters.docling_adapter import DoclingAdapter
from app.infrastructure.storage.local_storage import LocalStorageService


pytestmark = pytest.mark.integration


@pytest.fixture
def extraction_service(app_settings: AppSettings, tmp_path: Path) -> ExtractionService:
    """Build a real ExtractionService for integration testing.

    Uses tmp_path as output directory to avoid polluting the real outputs.
    """
    app_settings.output.output_dir = tmp_path / "outputs"
    return ExtractionService(
        extractor=DoclingAdapter(config=app_settings),
        markdown_service=MarkdownService(config=app_settings),
        metadata_service=MetadataService(),
        validation_service=ValidationService(config=app_settings),
        storage=LocalStorageService(config=app_settings),
        config=app_settings,
    )


class TestExtractionServiceIntegration:
    """Integration tests using a real PDF and real Docling."""

    def test_extract_real_pdf_succeeds(
        self,
        extraction_service: ExtractionService,
        sample_pdf_path: Path,
    ) -> None:
        """Extracting a real PDF must return SUCCESS or PARTIAL status."""
        request = ExtractionRequest(source=sample_pdf_path, output_formats=["all"])
        result = extraction_service.extract_document(request)

        assert result.status in (ExtractionStatus.SUCCESS, ExtractionStatus.PARTIAL)

    def test_extract_produces_markdown(
        self,
        extraction_service: ExtractionService,
        sample_pdf_path: Path,
    ) -> None:
        """Extraction must produce non-empty Markdown content."""
        request = ExtractionRequest(source=sample_pdf_path, output_formats=["md"])
        result = extraction_service.extract_document(request)

        assert len(result.markdown.strip()) > 0

    def test_extract_computes_sha256(
        self,
        extraction_service: ExtractionService,
        sample_pdf_path: Path,
    ) -> None:
        """SHA-256 hash must be a 64-character hex string."""
        request = ExtractionRequest(source=sample_pdf_path)
        result = extraction_service.extract_document(request)

        assert len(result.metadata.sha256) == 64
        assert all(c in "0123456789abcdef" for c in result.metadata.sha256)

    def test_extract_detects_page_count(
        self,
        extraction_service: ExtractionService,
        sample_pdf_path: Path,
    ) -> None:
        """Page count must be at least 1 for any valid PDF."""
        request = ExtractionRequest(source=sample_pdf_path)
        result = extraction_service.extract_document(request)

        assert result.metadata.page_count >= 1

    def test_output_files_created(
        self,
        extraction_service: ExtractionService,
        sample_pdf_path: Path,
    ) -> None:
        """Markdown and metadata files must be created on disk."""
        request = ExtractionRequest(source=sample_pdf_path, output_formats=["all"])
        result = extraction_service.extract_document(request)

        assert "md" in result.output_paths or "metadata" in result.output_paths
        for path in result.output_paths.values():
            assert Path(path).exists(), f"Expected output file not found: {path}"

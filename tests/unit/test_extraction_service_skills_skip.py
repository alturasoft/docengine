"""Tests for ExtractionService skip_skills toggle."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from app.application.extraction_service import ExtractionService
from app.config.settings import AppSettings
from app.domain.models.document import DocumentMetadata, ExtractionResult
from app.domain.models.extraction import ExtractionRequest, ExtractionStatus


def test_extraction_service_skips_skills_when_configured(app_settings: AppSettings, tmp_path: Path) -> None:
    mock_extractor = MagicMock()
    mock_extractor.extractor_name = "PdfExtractAdapter v1.0.0"

    initial_md = "# Title\n\nRaw extracted text without skill modifications."
    mock_extractor.extract.return_value = ExtractionResult(
        document_id="test-doc-123",
        status=ExtractionStatus.SUCCESS,
        markdown=initial_md,
        json_data={},
        metadata=DocumentMetadata(
            filename="test.pdf",
            source_path=tmp_path / "test.pdf",
            sha256="abc",
            page_count=1,
            extraction_time_seconds=1.0,
            docling_version="PdfExtractAdapter",
            tables_detected=0,
            figures_detected=0,
            headers_removed=0,
            footers_removed=0,
            ocr_used=True,
            has_multi_column=False,
            markdown_size_bytes=len(initial_md),
            errors=[],
        ),
    )

    mock_md_service = MagicMock()
    mock_meta_service = MagicMock()
    mock_val_service = MagicMock()
    mock_storage = MagicMock()
    mock_storage.save_result.return_value = {"md": tmp_path / "test.md"}

    service = ExtractionService(
        extractor=mock_extractor,
        markdown_service=mock_md_service,
        metadata_service=mock_meta_service,
        validation_service=mock_val_service,
        storage=mock_storage,
        config=app_settings,
        skip_skills=True,
    )

    req = ExtractionRequest(source=tmp_path / "test.pdf")
    res = service.extract_document(req)

    # Verify markdown was NOT processed by markdown_service
    mock_md_service.post_process.assert_not_called()
    # Verify the markdown remained the exact raw output
    assert res.markdown == initial_md
    # Verify validation and storage were still called (Step 5)
    mock_val_service.validate_result.assert_called_once()
    mock_storage.save_result.assert_called_once()

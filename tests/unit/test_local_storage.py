"""Unit tests for LocalStorageService folder naming and persistence behavior."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.config.settings import AppSettings
from app.domain.models.document import DocumentMetadata, ExtractionResult
from app.domain.models.extraction import ExtractionStatus
from app.infrastructure.storage.local_storage import LocalStorageService


@pytest.fixture
def storage_service(app_settings: AppSettings, tmp_path: Path) -> LocalStorageService:
    """Fixture providing a LocalStorageService instance pointed at a temporary directory."""
    app_settings.output.output_dir = tmp_path / "outputs"
    return LocalStorageService(config=app_settings)


@pytest.fixture
def dummy_result(tmp_path: Path) -> ExtractionResult:
    """Fixture providing a dummy ExtractionResult with a sample filename."""
    doc_id = str(uuid.uuid4())
    metadata = DocumentMetadata(
        filename="POLIZA_PRUEBA_123.pdf",
        source_path=tmp_path / "POLIZA_PRUEBA_123.pdf",
        sha256="a" * 64,
        page_count=2,
        extraction_time_seconds=1.23,
        docling_version="2.0.0",
        tables_detected=1,
        figures_detected=0,
        headers_removed=0,
        footers_removed=0,
        ocr_used=False,
        has_multi_column=False,
        markdown_size_bytes=100,
        company_sigla="CRI",
    )
    return ExtractionResult(
        document_id=doc_id,
        status=ExtractionStatus.SUCCESS,
        markdown="# Document Header\nSome content",
        json_data={"dummy": "data"},
        metadata=metadata,
    )


class TestLocalStorageFolderNaming:
    """Tests for filename-based folder creation in LocalStorageService."""

    def test_output_dir_uses_filename_stem_with_company(
        self,
        storage_service: LocalStorageService,
    ) -> None:
        """When filename and company_sigla are provided, folder is named outputs/<SIGLA>/<filename_stem>."""
        doc_id = "test-uuid-123"
        dir_path = storage_service.get_output_dir(
            document_id=doc_id,
            company_sigla="CRI",
            filename="POLIZA_SALUD_2026.pdf",
        )
        assert dir_path.name == "POLIZA_SALUD_2026"
        assert dir_path.parent.name == "CRI"

    def test_output_dir_uses_filename_stem_without_company(
        self,
        storage_service: LocalStorageService,
    ) -> None:
        """When filename is provided but no company_sigla, folder is named outputs/<filename_stem>."""
        doc_id = "test-uuid-123"
        dir_path = storage_service.get_output_dir(
            document_id=doc_id,
            company_sigla=None,
            filename="POLIZA_AUTO.pdf",
        )
        assert dir_path.name == "POLIZA_AUTO"
        assert dir_path.parent.name == "outputs"

    def test_output_dir_falls_back_to_document_id(
        self,
        storage_service: LocalStorageService,
    ) -> None:
        """When filename is None or empty, folder falls back to using document_id."""
        doc_id = "uuid-fallback-456"
        dir_path = storage_service.get_output_dir(
            document_id=doc_id,
            company_sigla="ALI",
            filename=None,
        )
        assert dir_path.name == "uuid-fallback-456"
        assert dir_path.parent.name == "ALI"

    def test_save_result_creates_folder_named_after_file_stem(
        self,
        storage_service: LocalStorageService,
        dummy_result: ExtractionResult,
    ) -> None:
        """Saving a result creates the output directory with the file stem name and saves files inside."""
        saved_paths = storage_service.save_result(dummy_result)

        expected_folder_name = "POLIZA_PRUEBA_123"
        md_file = saved_paths["md"]

        assert md_file.parent.name == expected_folder_name
        assert md_file.parent.parent.name == "CRI"
        assert md_file.exists()
        assert md_file.name == "POLIZA_PRUEBA_123.md"

    def test_result_exists_checks_filename_folder(
        self,
        storage_service: LocalStorageService,
        dummy_result: ExtractionResult,
    ) -> None:
        """result_exists correctly finds output when passing filename."""
        assert not storage_service.result_exists(
            document_id=dummy_result.document_id,
            company_sigla="CRI",
            filename="POLIZA_PRUEBA_123.pdf",
        )

        storage_service.save_result(dummy_result)

        assert storage_service.result_exists(
            document_id=dummy_result.document_id,
            company_sigla="CRI",
            filename="POLIZA_PRUEBA_123.pdf",
        )

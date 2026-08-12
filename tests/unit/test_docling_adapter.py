"""Unit tests for DoclingAdapter — configuration and initialization."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.config.settings import AppSettings
from app.domain.models.extraction import ExtractionRequest, ExtractionStatus
from app.infrastructure.adapters.docling_adapter import DoclingAdapter


class TestDoclingAdapterInit:
    """Tests for DoclingAdapter initialization and configuration."""

    @patch("app.infrastructure.adapters.docling_adapter.DocumentConverter")
    def test_adapter_initializes(
        self, mock_converter_cls: MagicMock, app_settings: AppSettings
    ) -> None:
        """Adapter must initialize without errors."""
        adapter = DoclingAdapter(config=app_settings)
        assert adapter is not None

    @patch("app.infrastructure.adapters.docling_adapter.DocumentConverter")
    def test_ocr_disabled_in_phase1(
        self, mock_converter_cls: MagicMock, app_settings: AppSettings
    ) -> None:
        """OCR must be explicitly disabled (do_ocr=False) in Phase 1."""
        app_settings.extraction.do_ocr = False
        adapter = DoclingAdapter(config=app_settings)
        # Verify PdfPipelineOptions was called with do_ocr=False
        assert not app_settings.extraction.do_ocr

    @patch("app.infrastructure.adapters.docling_adapter.DocumentConverter")
    def test_table_structure_enabled(
        self, mock_converter_cls: MagicMock, app_settings: AppSettings
    ) -> None:
        """Table structure detection must be enabled."""
        assert app_settings.extraction.do_table_structure is True

    @patch("app.infrastructure.adapters.docling_adapter.DocumentConverter")
    def test_table_mode_accurate(
        self, mock_converter_cls: MagicMock, app_settings: AppSettings
    ) -> None:
        """Table mode must be ACCURATE for maximum quality."""
        assert app_settings.extraction.table_mode == "ACCURATE"

    @patch("app.infrastructure.adapters.docling_adapter.DocumentConverter")
    def test_extractor_name_contains_docling(
        self, mock_converter_cls: MagicMock, app_settings: AppSettings
    ) -> None:
        """extractor_name must mention DoclingAdapter."""
        adapter = DoclingAdapter(config=app_settings)
        assert "DoclingAdapter" in adapter.extractor_name

    @patch("app.infrastructure.adapters.docling_adapter.DocumentConverter")
    def test_supports_ocr_property(
        self, mock_converter_cls: MagicMock, app_settings: AppSettings
    ) -> None:
        """supports_ocr must return True (Phase 2 capable)."""
        adapter = DoclingAdapter(config=app_settings)
        assert adapter.supports_ocr is True


class TestDoclingAdapterExtractFailure:
    """Tests for DoclingAdapter error handling."""

    @patch("app.infrastructure.adapters.docling_adapter.DocumentConverter")
    def test_extract_returns_failed_result_on_exception(
        self, mock_converter_cls: MagicMock, app_settings: AppSettings
    ) -> None:
        """If Docling raises, adapter must return FAILED result (no re-raise)."""
        mock_converter_instance = MagicMock()
        mock_converter_instance.convert.side_effect = RuntimeError("Docling crash")
        mock_converter_cls.return_value = mock_converter_instance

        adapter = DoclingAdapter(config=app_settings)
        request = ExtractionRequest(source="nonexistent.pdf")
        result = adapter.extract(request)

        assert result.status == ExtractionStatus.FAILED
        assert result.markdown == ""
        assert len(result.metadata.errors) > 0

    @patch("app.infrastructure.adapters.docling_adapter.DocumentConverter")
    def test_sha256_computed_from_request_source(
        self, mock_converter_cls: MagicMock, app_settings: AppSettings, tmp_path
    ) -> None:
        """SHA-256 must be correctly computed when request.source points to a file in a subfolder."""
        dummy_file = tmp_path / "subfolder" / "test.pdf"
        dummy_file.parent.mkdir(parents=True)
        dummy_file.write_bytes(b"dummy pdf content for sha256 test")

        mock_converter_instance = MagicMock()
        conv_result = MagicMock()
        from docling.datamodel.base_models import ConversionStatus  # noqa: PLC0415
        conv_result.status = ConversionStatus.SUCCESS
        conv_result.input.file = "test.pdf"  # Only basename returned by Docling
        conv_result.document.export_to_markdown.return_value = "# Test Doc"
        conv_result.document.export_to_dict.return_value = {}
        conv_result.document.pages = []
        conv_result.document.tables = []
        conv_result.document.pictures = []
        conv_result.errors = []
        mock_converter_instance.convert.return_value = conv_result
        mock_converter_cls.return_value = mock_converter_instance

        adapter = DoclingAdapter(config=app_settings)
        request = ExtractionRequest(source=dummy_file)
        result = adapter.extract(request)

        assert result.is_successful
        assert result.metadata.sha256 != ""
        assert len(result.metadata.sha256) == 64


class TestOcrAdapterFactory:
    """Tests for get_ocr_adapter factory helper."""

    def test_get_ocr_adapter_returns_adapter(self, app_settings: AppSettings) -> None:
        """get_ocr_adapter returns an IOcrEngine implementation."""
        from app.infrastructure.adapters.ocr_adapter import (
            NullOcrAdapter,
            get_ocr_adapter,
        )

        adapter = get_ocr_adapter(app_settings)
        assert adapter is not None
        assert hasattr(adapter, "get_ocr_options")
        assert hasattr(adapter, "engine_name")

    def test_get_ocr_adapter_fallback_on_invalid_engine(
        self, app_settings: AppSettings
    ) -> None:
        """Unknown engine type falls back gracefully."""
        from app.infrastructure.adapters.ocr_adapter import get_ocr_adapter

        app_settings.ocr.engine = "nonexistent_engine"  # type: ignore[assignment]
        adapter = get_ocr_adapter(app_settings)
        assert adapter is not None



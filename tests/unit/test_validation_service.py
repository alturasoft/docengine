"""Unit tests for ValidationService."""

from __future__ import annotations

import pytest

from app.application.validation_service import ValidationService
from app.config.settings import AppSettings
from app.domain.models.document import ExtractionResult
from app.domain.models.extraction import ExtractionStatus


@pytest.fixture
def service(app_settings: AppSettings) -> ValidationService:
    """Return a ValidationService configured for testing."""
    return ValidationService(config=app_settings)


class TestValidateResult:
    """Tests for ValidationService.validate_result()."""

    def test_no_warnings_for_good_result(
        self,
        service: ValidationService,
        successful_extraction_result: ExtractionResult,
    ) -> None:
        """A well-formed result should produce no warnings."""
        # Give result enough content to pass density check
        successful_extraction_result.markdown = "# Título\n\n" + ("Contenido. " * 200)
        successful_extraction_result.metadata.page_count = 2
        warnings = service.validate_result(successful_extraction_result)
        # Should have at most 1 warning (heading ratio check)
        assert len(warnings) <= 2

    def test_warns_on_empty_markdown(
        self,
        service: ValidationService,
        successful_extraction_result: ExtractionResult,
    ) -> None:
        """Empty Markdown must trigger WARN:010."""
        successful_extraction_result.markdown = ""
        warnings = service.validate_result(successful_extraction_result)
        assert any("WARN:010" in w for w in warnings)

    def test_warns_on_very_short_markdown(
        self,
        service: ValidationService,
        successful_extraction_result: ExtractionResult,
    ) -> None:
        """Very short Markdown (< 50 chars) must trigger WARN:011."""
        successful_extraction_result.markdown = "OK"
        warnings = service.validate_result(successful_extraction_result)
        assert any("WARN:011" in w for w in warnings)

    def test_warns_on_low_content_density(
        self,
        service: ValidationService,
        successful_extraction_result: ExtractionResult,
    ) -> None:
        """Low chars/page ratio must trigger WARN:020."""
        successful_extraction_result.markdown = "# Texto corto."
        successful_extraction_result.metadata.page_count = 50
        warnings = service.validate_result(successful_extraction_result)
        assert any("WARN:020" in w for w in warnings)

    def test_warns_on_no_headings_in_long_doc(
        self,
        service: ValidationService,
        successful_extraction_result: ExtractionResult,
    ) -> None:
        """Long document without headings should trigger WARN:030."""
        successful_extraction_result.markdown = "Texto sin secciones. " * 100
        successful_extraction_result.metadata.page_count = 1
        warnings = service.validate_result(successful_extraction_result)
        assert any("WARN:030" in w for w in warnings)

    def test_failed_extraction_gives_short_circuit_warning(
        self,
        service: ValidationService,
        failed_extraction_result: ExtractionResult,
    ) -> None:
        """FAILED status must short-circuit all other checks."""
        warnings = service.validate_result(failed_extraction_result)
        assert any("WARN:001" in w for w in warnings)
        # Should NOT also trigger empty markdown warning on top of it
        assert all("WARN:010" not in w for w in warnings)

    def test_warnings_appended_to_metadata(
        self,
        service: ValidationService,
        successful_extraction_result: ExtractionResult,
    ) -> None:
        """Warnings must be added to result.metadata.warnings."""
        successful_extraction_result.markdown = ""
        service.validate_result(successful_extraction_result)
        assert len(successful_extraction_result.metadata.warnings) > 0

    def test_errors_in_metadata_generate_warnings(
        self,
        service: ValidationService,
        successful_extraction_result: ExtractionResult,
    ) -> None:
        """Errors in metadata must produce WARN:050 entries."""
        successful_extraction_result.metadata.errors = ["Corrupted page 3"]
        successful_extraction_result.markdown = "# OK\n\nContent. " * 50
        successful_extraction_result.metadata.page_count = 1
        warnings = service.validate_result(successful_extraction_result)
        assert any("WARN:050" in w for w in warnings)

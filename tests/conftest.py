"""DocEngine — Shared Test Fixtures (conftest.py).

Provides pytest fixtures used across unit and integration tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.config.settings import AppSettings, reset_settings
from app.domain.models.document import DocumentMetadata, ExtractionResult
from app.domain.models.extraction import ExtractionStatus


# ---------------------------------------------------------------------------
# Settings fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_settings_singleton() -> None:
    """Reset the settings singleton before each test.

    Ensures that environment variable patches in one test do not
    affect other tests.
    """
    reset_settings()
    yield
    reset_settings()


@pytest.fixture
def app_settings() -> AppSettings:
    """Return a test-mode AppSettings instance.

    Returns:
        AppSettings configured for test environment.
    """
    return AppSettings(environment="test")


# ---------------------------------------------------------------------------
# Domain model fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_document_metadata() -> DocumentMetadata:
    """Return a realistic DocumentMetadata instance for testing.

    Returns:
        DocumentMetadata with plausible values.
    """
    return DocumentMetadata(
        filename="poliza_test.pdf",
        source_path=Path("/tmp/poliza_test.pdf"),
        sha256="a" * 64,
        page_count=10,
        extraction_time_seconds=2.34,
        docling_version="2.5.0",
        tables_detected=3,
        figures_detected=1,
        headers_removed=2,
        footers_removed=2,
        ocr_used=False,
        has_multi_column=False,
        markdown_size_bytes=15_000,
        errors=[],
        warnings=[],
        extracted_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def successful_extraction_result(sample_document_metadata: DocumentMetadata) -> ExtractionResult:
    """Return a successful ExtractionResult for testing.

    Returns:
        ExtractionResult with SUCCESS status and sample content.
    """
    return ExtractionResult(
        document_id=str(uuid.uuid4()),
        status=ExtractionStatus.SUCCESS,
        markdown="# Póliza de Seguros\n\nContenido de prueba.\n\n## Sección 1\n\nTexto.",
        json_data={"pages": [], "tables": []},
        metadata=sample_document_metadata,
    )


@pytest.fixture
def failed_extraction_result(sample_document_metadata: DocumentMetadata) -> ExtractionResult:
    """Return a failed ExtractionResult for testing."""
    meta = sample_document_metadata
    meta.errors = ["Extraction failed: corrupted PDF"]
    return ExtractionResult(
        document_id=str(uuid.uuid4()),
        status=ExtractionStatus.FAILED,
        markdown="",
        json_data={},
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# Sample PDF fixture (requires physical file)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_pdf_path() -> Path:
    """Return path to the sample PDF for integration tests.

    The file must exist at samples/test_poliza.pdf.
    Integration tests are skipped if the file is absent.

    Returns:
        Path to the sample PDF file.
    """
    path = Path("samples/test_poliza.pdf")
    if not path.exists():
        pytest.skip(
            "Sample PDF not found at samples/test_poliza.pdf. "
            "Place a PDF there to run integration tests."
        )
    return path


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------


@pytest.fixture
def test_client(app_settings: AppSettings) -> TestClient:
    """Return a FastAPI TestClient with mocked ExtractionService.

    The DoclingAdapter is mocked to avoid loading ML models during testing.
    The lifespan is bypassed by pre-setting app.state.extraction_service.

    Returns:
        TestClient configured with a mock extraction service.
    """
    import uuid as _uuid  # noqa: PLC0415
    from contextlib import asynccontextmanager  # noqa: PLC0415
    from datetime import datetime, timezone as _tz  # noqa: PLC0415
    from typing import AsyncGenerator  # noqa: PLC0415
    from unittest.mock import MagicMock  # noqa: PLC0415

    from fastapi import FastAPI  # noqa: PLC0415

    from app.api.v1.router import router as v1_router  # noqa: PLC0415
    from app.domain.models.document import DocumentMetadata, ExtractionResult  # noqa: PLC0415
    from app.domain.models.extraction import ExtractionStatus  # noqa: PLC0415

    mock_service = MagicMock()
    mock_result = ExtractionResult(
        document_id=str(_uuid.uuid4()),
        status=ExtractionStatus.SUCCESS,
        markdown="# Test\n\nContent.",
        json_data={},
        metadata=DocumentMetadata(
            filename="test.pdf",
            source_path=Path("test.pdf"),
            sha256="a" * 64,
            page_count=1,
            extraction_time_seconds=0.5,
            docling_version="2.5.0",
            tables_detected=0,
            figures_detected=0,
            headers_removed=0,
            footers_removed=0,
            ocr_used=False,
            has_multi_column=False,
            markdown_size_bytes=100,
            extracted_at=datetime.now(tz=_tz.utc),
        ),
        output_paths={},
    )
    mock_service.extract_document.return_value = mock_result
    mock_service.extract_from_url.return_value = mock_result
    mock_service.extract_folder.return_value = [mock_result]

    @asynccontextmanager
    async def test_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        app.state.extraction_service = mock_service
        yield

    from app.api.main import create_app  # noqa: PLC0415

    test_app = create_app(settings=app_settings)
    test_app.router.lifespan_context = test_lifespan

    with TestClient(test_app, raise_server_exceptions=True) as client:
        yield client

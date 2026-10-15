"""DocEngine — Unit Tests: Phase 3 (Upload Limits & Async Jobs).

Tests verifying:
1. HTTP 413 Payload Too Large when file size exceeds max_upload_size_mb.
2. HTTP 422 Unprocessable Entity when page count exceeds max_pages_per_file.
3. HTTP 400 Bad Request when PDF is invalid or corrupt.
4. GET /api/v1/extract/jobs/{job_id} endpoint (200 OK and 404 Not Found).
5. POST /api/v1/extract with async_mode=True returning 202 Accepted.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch
import pypdf
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.v1.extraction import get_rag_repo


@pytest.fixture
def mock_app():
    with patch("app.api.main._build_extraction_service"):
        app = create_app()
        app.state.extraction_service = MagicMock()
        app.state.rag_service = MagicMock()
        app.state.rag_query_service = MagicMock()
        return app


@pytest.fixture
def client(mock_app) -> TestClient:
    return TestClient(mock_app)


def _create_minimal_pdf_bytes(page_count: int = 1) -> bytes:
    """Generate a valid in-memory PDF with the specified number of pages."""
    writer = pypdf.PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


# ---------------------------------------------------------------------------
# Test: File limits (413, 422, 400)
# ---------------------------------------------------------------------------


class TestUploadLimits:
    """Verify upload limits enforcement."""

    def test_upload_exceeds_max_size_mb_returns_413(self, client: TestClient, mock_app) -> None:
        # Configure max upload size to 1 MB for the test
        mock_app.state.settings.performance.max_upload_size_mb = 1

        # Create payload larger than 1 MB (1.5 MB)
        oversized_data = b"%PDF-1.4 " + (b"0" * (1024 * 1024 + 500000))
        files = {"file": ("large_doc.pdf", oversized_data, "application/pdf")}
        data = {"id_cliente": "123456 LP"}

        response = client.post("/api/v1/extract", files=files, data=data)
        assert response.status_code == 413
        assert "excede el tamaño máximo permitido de 1 MB" in response.json()["detail"]

    def test_upload_exceeds_max_pages_returns_422(self, client: TestClient, mock_app) -> None:
        # Configure max pages to 5 for test
        mock_app.state.settings.performance.max_pages_per_file = 5

        # Create a valid PDF with 6 pages
        pdf_bytes = _create_minimal_pdf_bytes(page_count=6)
        files = {"file": ("multi_page.pdf", pdf_bytes, "application/pdf")}
        data = {"id_cliente": "123456 LP"}

        response = client.post("/api/v1/extract", files=files, data=data)
        assert response.status_code == 422
        assert "contiene 6 páginas, superando el límite máximo permitido de 5 páginas" in response.json()["detail"]

    def test_upload_corrupt_pdf_returns_400(self, client: TestClient, mock_app) -> None:
        # Create non-PDF corrupted bytes with .pdf extension
        corrupt_bytes = b"NOT_A_REAL_PDF_HEADER_CONTENT_AT_ALL"
        files = {"file": ("corrupt.pdf", corrupt_bytes, "application/pdf")}
        data = {"id_cliente": "123456 LP"}

        response = client.post("/api/v1/extract", files=files, data=data)
        assert response.status_code == 400
        assert "no tiene un formato válido" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Test: GET /api/v1/extract/jobs/{job_id}
# ---------------------------------------------------------------------------


class TestJobStatusEndpoint:
    """Verify job tracking endpoint."""

    def test_get_job_status_found(self, client: TestClient, mock_app) -> None:
        mock_repo = MagicMock()
        mock_job = {
            "job_id": "job-uuid-12345",
            "file_name": "poliza_automotor.pdf",
            "status": "COMPLETED",
            "policy_id": "policy-uuid-99",
            "error_message": None,
            "created_at": "2026-10-14 10:00:00",
            "updated_at": "2026-10-14 10:03:00",
        }
        mock_repo.get_job_status.return_value = mock_job
        mock_app.dependency_overrides[get_rag_repo] = lambda: mock_repo

        try:
            response = client.get("/api/v1/extract/jobs/job-uuid-12345")
            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "job-uuid-12345"
            assert data["status"] == "COMPLETED"
            assert data["policy_id"] == "policy-uuid-99"
            assert data["file_name"] == "poliza_automotor.pdf"
        finally:
            mock_app.dependency_overrides.pop(get_rag_repo, None)

    def test_get_job_status_not_found(self, client: TestClient, mock_app) -> None:
        mock_repo = MagicMock()
        mock_repo.get_job_status.return_value = None
        mock_app.dependency_overrides[get_rag_repo] = lambda: mock_repo

        try:
            response = client.get("/api/v1/extract/jobs/non-existent-job")
            assert response.status_code == 404
            assert "no encontrado" in response.json()["detail"]
        finally:
            mock_app.dependency_overrides.pop(get_rag_repo, None)


# ---------------------------------------------------------------------------
# Test: POST /api/v1/extract with async_mode=True
# ---------------------------------------------------------------------------


class TestAsyncExtractionEndpoint:
    """Verify async extraction initiation."""

    def test_extract_file_async_mode_returns_202(self, client: TestClient, mock_app) -> None:
        mock_repo = MagicMock()
        mock_repo.create_job.return_value = "new-job-uuid-777"
        mock_app.dependency_overrides[get_rag_repo] = lambda: mock_repo

        pdf_bytes = _create_minimal_pdf_bytes(page_count=1)
        files = {"file": ("async_doc.pdf", pdf_bytes, "application/pdf")}
        data = {
            "id_cliente": "123456 LP",
            "async_mode": "true",
            "company_sigla": "CRE",
        }

        try:
            response = client.post("/api/v1/extract", files=files, data=data)
            assert response.status_code == 202

            payload = response.json()
            assert payload["job_id"] == "new-job-uuid-777"
            assert payload["status"] == "PROCESSING"
            assert "Consulte su estado en /api/v1/extract/jobs/new-job-uuid-777" in payload["message"]
            mock_repo.create_job.assert_called_once_with("async_doc.pdf")
        finally:
            mock_app.dependency_overrides.pop(get_rag_repo, None)

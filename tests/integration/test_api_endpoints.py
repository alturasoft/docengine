"""Integration tests for FastAPI endpoints.

These tests use the TestClient from conftest.py, which mocks
the ExtractionService so no Docling models are loaded.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoints:
    """Tests for /health, /version, /metrics."""

    def test_health_returns_ok(self, test_client: TestClient) -> None:
        response = test_client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "environment" in data
        assert "uptime_seconds" in data

    def test_version_returns_versions(self, test_client: TestClient) -> None:
        response = test_client.get("/api/v1/version")
        assert response.status_code == 200
        data = response.json()
        assert "app_version" in data
        assert "docling_version" in data
        assert "python_version" in data

    def test_metrics_returns_counters(self, test_client: TestClient) -> None:
        response = test_client.get("/api/v1/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "total_extractions" in data
        assert "successful_extractions" in data
        assert data["total_extractions"] >= 0


class TestExtractionEndpoints:
    """Tests for /extract endpoints."""

    def test_extract_valid_pdf(self, test_client: TestClient) -> None:
        """POST /extract with a valid PDF and id_cliente must return 200."""
        # Create a minimal fake PDF bytes
        fake_pdf = b"%PDF-1.4 fake content for testing"
        response = test_client.post(
            "/api/v1/extract",
            data={"id_cliente": "10203040"},
            files={"file": ("test_poliza.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert "document_id" in data
        assert "status" in data
        assert "metadata" in data
        assert "markdown_preview" in data

    def test_extract_rejects_missing_id_cliente(self, test_client: TestClient) -> None:
        """POST /extract without id_cliente must return 422 Unprocessable Entity."""
        fake_pdf = b"%PDF-1.4 fake content for testing"
        response = test_client.post(
            "/api/v1/extract",
            files={"file": ("test_poliza.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        )
        assert response.status_code == 422

    def test_extract_rejects_empty_id_cliente(self, test_client: TestClient) -> None:
        """POST /extract with blank id_cliente must return 400 Bad Request."""
        fake_pdf = b"%PDF-1.4 fake content for testing"
        response = test_client.post(
            "/api/v1/extract",
            data={"id_cliente": "   "},
            files={"file": ("test_poliza.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        )
        assert response.status_code == 400

    def test_extract_rejects_non_pdf(self, test_client: TestClient) -> None:
        """POST /extract with a non-PDF file must return 400."""
        response = test_client.post(
            "/api/v1/extract",
            data={"id_cliente": "10203040"},
            files={"file": ("document.docx", io.BytesIO(b"not a pdf"), "application/octet-stream")},
        )
        assert response.status_code == 400

    def test_extract_url(self, test_client: TestClient) -> None:
        """POST /extract/url with a PDF URL and id_cliente must return 200."""
        response = test_client.post(
            "/api/v1/extract/url",
            json={"url": "https://example.com/poliza.pdf", "id_cliente": "10203040"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "document_id" in data

    def test_extract_url_missing_id_cliente(self, test_client: TestClient) -> None:
        """POST /extract/url without id_cliente must return 422."""
        response = test_client.post(
            "/api/v1/extract/url",
            json={"url": "https://example.com/poliza.pdf"},
        )
        assert response.status_code == 422

    def test_extract_folder_not_found(self, test_client: TestClient) -> None:
        """POST /extract/folder with non-existent folder must return 400."""
        response = test_client.post(
            "/api/v1/extract/folder",
            json={"folder_path": "/nonexistent/path/to/folder"},
        )
        assert response.status_code == 400

    def test_extraction_response_structure(self, test_client: TestClient) -> None:
        """Validate the structure of the extraction response schema."""
        fake_pdf = b"%PDF-1.4 test"
        response = test_client.post(
            "/api/v1/extract",
            data={"id_cliente": "10203040"},
            files={"file": ("poliza.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()

        # Validate top-level fields
        required_fields = {
            "document_id", "status", "markdown_preview",
            "metadata", "output_paths", "created_at"
        }
        assert required_fields.issubset(data.keys())

        # Validate metadata fields
        meta_fields = {
            "filename", "sha256", "page_count", "extraction_time_seconds",
            "docling_version", "tables_detected", "figures_detected",
            "headers_removed", "footers_removed", "ocr_used",
            "has_multi_column", "markdown_size_bytes", "errors", "warnings",
            "extracted_at"
        }
        assert meta_fields.issubset(data["metadata"].keys())

    def test_get_markdown_not_found(self, test_client: TestClient) -> None:
        """GET /extract/{doc_id}/markdown for unknown doc returns 404."""
        response = test_client.get("/api/v1/extract/unknown_doc_id_999/markdown")
        assert response.status_code == 404

    def test_get_markdown_with_file(self, test_client: TestClient, tmp_path: Path) -> None:
        """GET /extract/{doc_id}/markdown with existing md file returns 200."""
        # Create a mock output folder in outputs
        out_dir = Path("outputs") / "test_doc_folder"
        out_dir.mkdir(parents=True, exist_ok=True)
        md_file = out_dir / "test_doc.md"
        md_file.write_text("# Test Policy Document\n\nContent", encoding="utf-8")

        try:
            response = test_client.get("/api/v1/extract/test_doc_folder/markdown")
            assert response.status_code == 200
            assert "# Test Policy Document" in response.text
            assert "text/markdown" in response.headers["content-type"]
        finally:
            if md_file.exists():
                md_file.unlink()
            if out_dir.exists():
                out_dir.rmdir()

    def test_web_ui_route(self, test_client: TestClient) -> None:
        """GET / and GET /ui should return HTML web interface."""
        res_root = test_client.get("/")
        assert res_root.status_code == 200
        assert "DocEngine" in res_root.text

        res_ui = test_client.get("/ui/")
        assert res_ui.status_code == 200
        assert "DocEngine" in res_ui.text

    def test_extract_pdf_with_company_sigla(self, test_client: TestClient) -> None:
        """POST /extract with company_sigla and id_cliente form field must return 200."""
        fake_pdf = b"%PDF-1.4 test with company"
        response = test_client.post(
            "/api/v1/extract",
            data={"company_sigla": "CRI", "id_cliente": "10203040"},
            files={"file": ("poliza_cri.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        )
        assert response.status_code == 200

    def test_get_companies_registry(self, test_client: TestClient) -> None:
        """GET /companies must return dictionary of company siglas."""
        response = test_client.get("/api/v1/companies")
        assert response.status_code == 200
        data = response.json()
        assert "LBC" in data
        assert "CRE" in data
        assert "BISA" in data

    def test_extract_pdf_with_nombre_cliente(self, test_client: TestClient) -> None:
        """POST /extract with nombre_cliente must return 200 and include nombre_cliente in metadata."""
        fake_pdf = b"%PDF-1.4 test with client name"
        response = test_client.post(
            "/api/v1/extract",
            data={
                "id_cliente": "10203040",
                "nombre_cliente": "Minera San Cristóbal S.A.",
            },
            files={"file": ("poliza_cliente.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["metadata"]["id_cliente"] == "10203040"
        assert data["metadata"]["nombre_cliente"] == "Minera San Cristóbal S.A."

    def test_extract_pdf_without_nombre_cliente_backward_compatibility(self, test_client: TestClient) -> None:
        """POST /extract without nombre_cliente must continue working and return None for nombre_cliente."""
        fake_pdf = b"%PDF-1.4 test without client name"
        response = test_client.post(
            "/api/v1/extract",
            data={"id_cliente": "10203040"},
            files={"file": ("poliza_legacy.pdf", io.BytesIO(fake_pdf), "application/pdf")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["metadata"]["id_cliente"] == "10203040"
        assert data["metadata"].get("nombre_cliente") is None

    def test_extract_url_with_nombre_cliente(self, test_client: TestClient) -> None:
        """POST /extract/url with nombre_cliente must return 200 and populate nombre_cliente."""
        response = test_client.post(
            "/api/v1/extract/url",
            json={
                "url": "https://example.com/poliza.pdf",
                "id_cliente": "10203040",
                "nombre_cliente": "Empresa Boliviana S.R.L.",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["metadata"]["id_cliente"] == "10203040"
        assert data["metadata"]["nombre_cliente"] == "Empresa Boliviana S.R.L."



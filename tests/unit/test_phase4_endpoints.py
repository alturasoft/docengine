"""DocEngine — Unit Tests: Phase 4 (Single Document Deletion & Extended Filters).

Tests verifying:
1. DELETE /api/v1/policies/{policy_id} endpoint (200 OK and 404 Not Found).
2. PgHybridSearchRepository SQL query and filter parameter expansion (numero_poliza, ramo, vigencia_fecha).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.v1.policies import get_envelope_repo, get_storage_service


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


# ---------------------------------------------------------------------------
# Test: DELETE /api/v1/policies/{policy_id}
# ---------------------------------------------------------------------------


class TestDeleteSingleDocumentEndpoint:
    """Verify single document atomic deletion endpoint."""

    def test_delete_single_document_success(self, client: TestClient, mock_app) -> None:
        mock_repo = MagicMock()
        mock_doc = {
            "policy_id": "doc-uuid-555",
            "file_name": "anexo_coberturas.pdf",
            "envelope_id": "envelope-uuid-111",
            "company_sigla": "CRE",
        }
        mock_repo.delete_document.return_value = mock_doc
        mock_storage = MagicMock()
        mock_storage.delete_result_files.return_value = ["outputs/CRE/doc-uuid-555"]

        mock_app.dependency_overrides[get_envelope_repo] = lambda: mock_repo
        mock_app.dependency_overrides[get_storage_service] = lambda: mock_storage

        try:
            response = client.delete("/api/v1/policies/doc-uuid-555?delete_files=true")
            assert response.status_code == 200

            data = response.json()
            assert data["policy_id"] == "doc-uuid-555"
            assert data["file_name"] == "anexo_coberturas.pdf"
            assert data["envelope_id"] == "envelope-uuid-111"
            assert data["company_sigla"] == "CRE"
            assert len(data["deleted_disk_dirs"]) == 1
            assert "outputs/CRE/doc-uuid-555" in data["deleted_disk_dirs"][0]
            mock_repo.delete_document.assert_called_once_with("doc-uuid-555")
            mock_storage.delete_result_files.assert_called_once()
        finally:
            mock_app.dependency_overrides.pop(get_envelope_repo, None)
            mock_app.dependency_overrides.pop(get_storage_service, None)

    def test_delete_single_document_not_found(self, client: TestClient, mock_app) -> None:
        mock_repo = MagicMock()
        mock_repo.delete_document.return_value = None
        mock_app.dependency_overrides[get_envelope_repo] = lambda: mock_repo

        try:
            response = client.delete("/api/v1/policies/missing-doc-uuid")
            assert response.status_code == 404
            assert "no encontrado" in response.json()["detail"]
        finally:
            mock_app.dependency_overrides.pop(get_envelope_repo, None)


# ---------------------------------------------------------------------------
# Test: Extended SQL Filters in PgHybridSearchRepository
# ---------------------------------------------------------------------------


class TestExtendedFiltersInHybridSearch:
    """Verify that extended filters (numero_poliza, ramo, vigencia_fecha) are correctly built."""

    def test_extended_filters_construction(self) -> None:
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.description = [("id",), ("chunk_id",), ("chunk_content",), ("policy_id",), ("chunk_index",), ("metadata_json",), ("parent_id",), ("chunk_type",), ("rrf_score",)]
        mock_cur.fetchall.return_value = []

        from app.infrastructure.database.pg_hybrid_search import PgHybridSearchRepository

        repo = PgHybridSearchRepository(mock_db)

        filters = {
            "numero_poliza": "POL-9988",
            "ramo": "AUTOMOTOR",
            "vigencia_fecha": "2026-06-15",
            "company_sigla": "CRE",
        }

        repo._hybrid_search(
            query_vector=[0.1] * 1024,
            query_text="cobertura de choque",
            top_k=5,
            rrf_pool=20,
            filters=filters,
        )

        assert mock_cur.execute.called
        executed_sql, params = mock_cur.execute.call_args[0]

        # Verify SQL contains joins
        assert "JOIN policies p ON pc.policy_id = p.id" in executed_sql
        assert "LEFT JOIN policy_envelopes pe ON p.envelope_id = pe.id" in executed_sql
        assert "LEFT JOIN policy_structured_data psd ON pc.policy_id = psd.policy_id" in executed_sql

        # Verify SQL filter clauses
        assert "pe.numero_poliza ILIKE %(numero_poliza)s" in executed_sql
        assert "pe.ramo ILIKE %(ramo)s" in executed_sql
        assert "vigencia_desde" in executed_sql

        # Verify parameters
        assert params["numero_poliza"] == "%POL-9988%"
        assert params["ramo"] == "%AUTOMOTOR%"
        assert params["vigencia_fecha"] == "2026-06-15"
        assert params["company_sigla"] == "CRE"

"""DocEngine — Unit Tests: Phase 1 & Phase 2 Endpoints.

Tests verifying:
1. POST /api/v1/query/search (Retrieval Only without LLM generation).
2. GET /api/v1/policies/{policy_id}/structured (Full structured policy JSON).
3. PgEnvelopeRepository.delete_document atomic deletion.
4. PgRagRepository.get_job_status query method.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.v1.policies import get_structured_search_repo
from app.domain.models.query_models import RetrievedChunk


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
# Test: POST /api/v1/query/search
# ---------------------------------------------------------------------------


class TestQuerySearchEndpoint:
    """Verify the pure retrieval/search endpoint without LLM synthesis."""

    def test_search_documents_success(self, client: TestClient, mock_app) -> None:
        mock_chunks = [
            RetrievedChunk(
                chunk_id="chunk-1",
                policy_id="policy-100",
                chunk_index=0,
                chunk_content="Cobertura de daños propios hasta $50,000 USD.",
                metadata_json={"page": 3, "section": "Coberturas", "file_name": "poliza.pdf"},
                similarity_score=0.88765,
            ),
            RetrievedChunk(
                chunk_id="chunk-2",
                policy_id="policy-100",
                chunk_index=1,
                chunk_content="Deducible de $500 USD para todo evento.",
                metadata_json={"page": 4, "file_name": "poliza.pdf"},
                similarity_score=0.75432,
            ),
        ]

        mock_app.state.rag_query_service.search_chunks.return_value = mock_chunks

        payload = {
            "question": "¿Cuál es el deducible y cobertura de daños propios?",
            "top_k": 5,
            "similarity_threshold": 0.5,
            "filters": {
                "company_sigla": "CRE",
                "ramo": "AUTOMOTOR",
            },
        }

        response = client.post("/api/v1/query/search", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["query"] == payload["question"]
        assert data["total_results"] == 2
        assert len(data["results"]) == 2

        first_chunk = data["results"][0]
        assert first_chunk["chunk_id"] == "chunk-1"
        assert first_chunk["policy_id"] == "policy-100"
        assert first_chunk["similarity_score"] == 0.8877
        assert "daños propios" in first_chunk["chunk_content"]

    def test_search_documents_validation_error_empty_question(self, client: TestClient) -> None:
        payload = {"question": "  "}
        response = client.post("/api/v1/query/search", json=payload)
        assert response.status_code == 422  # Pydantic min_length=3 validation

    def test_search_documents_service_unavailable(self, client: TestClient, mock_app) -> None:
        mock_app.state.rag_query_service = None
        payload = {"question": "¿Qué coberturas existen?"}
        response = client.post("/api/v1/query/search", json=payload)
        assert response.status_code == 503

    def test_search_documents_returns_numero_poliza_and_company_sigla(self, client: TestClient, mock_app) -> None:
        mock_chunks = [
            RetrievedChunk(
                chunk_id="chunk-3",
                policy_id="4b684531-10df-4f40-84cf-8d9633e6c0c2",
                chunk_index=0,
                chunk_content="Cobertura de daños propios.",
                metadata_json={"numero_poliza": "POL-2024-9988", "company_sigla": "BISA"},
                similarity_score=0.91,
                numero_poliza="POL-2024-9988",
                company_sigla="BISA",
            ),
        ]
        mock_app.state.rag_query_service.search_chunks.return_value = mock_chunks

        payload = {
            "question": "¿Cuál es la cobertura?",
            "filters": {
                "sigla_aseguradora": "BISA",
            },
        }

        response = client.post("/api/v1/query/search", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) == 1
        res = data["results"][0]
        assert res["policy_id"] == "4b684531-10df-4f40-84cf-8d9633e6c0c2"
        assert res["numero_poliza"] == "POL-2024-9988"
        assert res["company_sigla"] == "BISA"


# ---------------------------------------------------------------------------
# Test: GET /api/v1/policies/{policy_id}/structured
# ---------------------------------------------------------------------------


class TestPolicyStructuredEndpoint:
    """Verify the structured policy data JSON endpoint."""

    def test_get_policy_structured_success(self, client: TestClient, mock_app) -> None:
        mock_repo = MagicMock()
        mock_record = {
            "policy_id": "uuid-structured-123",
            "file_name": "poliza_automotor.pdf",
            "company_sigla": "CRE",
            "data": {
                "datos_cabecera": {
                    "numero_poliza": "AUT-2026-99",
                    "asegurado": "Industrias del Sur S.R.L.",
                    "documento_identidad": None,
                    "nit": "1029384756",
                    "vigencia_desde": "01/01/2026",
                    "vigencia_hasta": "31/12/2026",
                    "moneda": "USD",
                    "prima_total": "3,400.00",
                },
                "objeto_asegurado": {
                    "tipo_bien": "Vehículo",
                    "marca": "Toyota",
                    "modelo": "Hilux",
                    "ano": "2024",
                    "placa": "4020-XYZ",
                    "chasis": "CHASIS123456789",
                    "valor_declarado": "45,000 USD",
                },
                "coberturas": [
                    {
                        "nombre": "Responsabilidad Civil",
                        "suma_asegurada": "100,000 USD",
                        "deducible": "0 USD",
                        "limite": "Por evento",
                    },
                    {
                        "nombre": "Pérdida Total por Accidente",
                        "suma_asegurada": "45,000 USD",
                        "deducible": "10% del valor del vehículo",
                        "limite": "Valor convenido",
                    },
                ],
                "condiciones_especiales": [
                    "Ampliación de aviso de siniestro hasta 15 días.",
                    "Tolerancia de alcoholemia sólo 0.5% mg.",
                ],
            },
        }
        mock_repo.find_by_policy_id.return_value = mock_record
        mock_app.dependency_overrides[get_structured_search_repo] = lambda: mock_repo

        try:
            response = client.get("/api/v1/policies/uuid-structured-123/structured")
            assert response.status_code == 200

            data = response.json()
            assert data["policy_id"] == "uuid-structured-123"
            assert data["company_sigla"] == "CRE"
            assert data["id_cliente"] == "1029384756"
            assert data["datos_cabecera"]["numero_poliza"] == "AUT-2026-99"
            assert data["datos_cabecera"]["asegurado"] == "Industrias del Sur S.R.L."
            assert data["objeto_asegurado"]["marca"] == "Toyota"
            assert data["objeto_asegurado"]["placa"] == "4020-XYZ"
            assert len(data["coberturas"]) == 2
            assert data["coberturas"][0]["nombre"] == "Responsabilidad Civil"
            assert len(data["condiciones_especiales"]) == 2
            assert "15 días" in data["condiciones_especiales"][0]
        finally:
            mock_app.dependency_overrides.pop(get_structured_search_repo, None)

    def test_get_policy_structured_not_found(self, client: TestClient, mock_app) -> None:
        mock_repo = MagicMock()
        mock_repo.find_by_policy_id.return_value = None
        mock_repo.find_basic_by_policy_number_or_id.return_value = None
        mock_app.dependency_overrides[get_structured_search_repo] = lambda: mock_repo

        try:
            response = client.get("/api/v1/policies/non-existent-uuid/structured")
            assert response.status_code == 404
            assert "no encontrados" in response.json()["detail"]
        finally:
            mock_app.dependency_overrides.pop(get_structured_search_repo, None)


# ---------------------------------------------------------------------------
# Test: Repository Methods
# ---------------------------------------------------------------------------


class TestRepositoryMethods:
    """Verify new database repository methods."""

    def test_delete_document_method(self) -> None:
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.return_value = (
            "doc-uuid-1",
            "test_doc.pdf",
            "hash123",
            "CRE",
            "env-uuid-1",
        )

        from app.infrastructure.database.pg_envelope_repository import PgEnvelopeRepository
        repo = PgEnvelopeRepository(mock_db)
        result = repo.delete_document("doc-uuid-1")

        assert result is not None
        assert result["policy_id"] == "doc-uuid-1"
        assert result["file_name"] == "test_doc.pdf"
        assert result["envelope_id"] == "env-uuid-1"
        assert mock_cur.execute.call_count == 2
        mock_conn.commit.assert_called_once()

    def test_get_job_status_method(self) -> None:
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.return_value = (
            "job-uuid-1",
            "doc.pdf",
            "COMPLETED",
            None,
            "policy-uuid-1",
            "2026-10-14 10:00:00",
            "2026-10-14 10:02:00",
        )

        from app.infrastructure.database.pg_rag_repository import PgRagRepository
        repo = PgRagRepository(mock_db)
        result = repo.get_job_status("job-uuid-1")

        assert result is not None
        assert result["job_id"] == "job-uuid-1"
        assert result["status"] == "COMPLETED"
        assert result["policy_id"] == "policy-uuid-1"

"""DocEngine — Unit Tests: Policy Basic Info & Endpoints.

Tests verifying:
1. extract_basic_info helper extraction and fallback logic for all 6 required fields.
2. PgStructuredSearchRepository get_recent_policies and find_basic_by_policy_number_or_id.
3. FastAPI /api/v1/policies endpoints (recent, search, get by id).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.infrastructure.database.pg_structured_search import (
    PgStructuredSearchRepository,
    extract_basic_info,
)


# ---------------------------------------------------------------------------
# Unit Tests: extract_basic_info
# ---------------------------------------------------------------------------


class TestExtractBasicInfo:
    """Verify extraction and normalization of the 6 core policy fields."""

    def test_extract_basic_info_all_fields_present(self) -> None:
        record = {
            "policy_id": "test-uuid-1234",
            "file_name": "poliza_alianza_12345.pdf",
            "company_sigla": "ALI",
            "created_at": "2026-09-14 10:00:00",
            "data": {
                "datos_cabecera": {
                    "numero_poliza": "POL-998877",
                    "ramo": "Automotores",
                    "asegurado": "Juan Pérez",
                    "documento_identidad": "4892144 LP",
                    "nit": "1020304050",
                    "vigencia_desde": "01/01/2026",
                    "vigencia_hasta": "31/12/2026",
                    "prima_total": "1,250.00",
                    "moneda": "USD",
                },
                "objeto_asegurado": {
                    "tipo_bien": "Camioneta",
                    "marca": "Toyota",
                },
            },
        }

        basic = extract_basic_info(record)

        assert basic["policy_id"] == "test-uuid-1234"
        assert basic["numero_poliza"] == "POL-998877"
        assert basic["ramo"] == "Automotores"
        assert basic["asegurado"] == "Juan Pérez"
        assert basic["numero_documento"] == "CI: 4892144 LP / NIT: 1020304050"
        assert basic["vigencia"] == "Desde 01/01/2026 hasta 31/12/2026"
        assert basic["prima_total"] == "1,250.00 USD"
        assert basic["company_sigla"] == "ALI"

    def test_extract_basic_info_fallbacks(self) -> None:
        """When optional fields like ramo or doc are partial, fallback logic applies."""
        record = {
            "policy_id": "uuid-5678",
            "file_name": "poliza_sin_cabecera.pdf",
            "company_sigla": "CRI",
            "data": {
                "datos_cabecera": {
                    "asegurado": "Constructora Altura S.R.L.",
                    "documento_identidad": "7788990 SC",
                    "vigencia_desde": "15/03/2026",
                    "prima_total": "4,500.00",
                },
                "objeto_asegurado": {
                    "tipo_bien": "Equipo Pesado / Retroexcavadora",
                },
            },
        }

        basic = extract_basic_info(record)

        # Fallback to file_name when numero_poliza missing
        assert basic["numero_poliza"] == "poliza_sin_cabecera.pdf"
        # Fallback to objeto_asegurado.tipo_bien when ramo is missing
        assert basic["ramo"] == "Equipo Pesado / Retroexcavadora"
        assert basic["asegurado"] == "Constructora Altura S.R.L."
        assert basic["numero_documento"] == "7788990 SC"
        assert basic["vigencia"] == "Desde 15/03/2026"
        assert basic["prima_total"] == "4,500.00"

    def test_extract_basic_info_empty_record(self) -> None:
        """Completely empty record returns clean default placeholders."""
        record = {"policy_id": "empty-uuid"}
        basic = extract_basic_info(record)

        assert basic["policy_id"] == "empty-uuid"
        assert basic["numero_poliza"] == "Desconocido"
        assert basic["ramo"] == "No especificado"
        assert basic["asegurado"] == "No especificado"
        assert basic["numero_documento"] == "No registrado"
        assert basic["vigencia"] == "No especificada"
        assert basic["prima_total"] == "No especificada"


# ---------------------------------------------------------------------------
# Unit Tests: PgStructuredSearchRepository Methods
# ---------------------------------------------------------------------------


class TestPgStructuredSearchRecentAndFind:
    """Verify repository methods for recent policies and search."""

    def test_get_recent_policies_executes_query(self) -> None:
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchall.return_value = [
            (
                "uuid-1",
                "file1.pdf",
                "BIS",
                "2026-09-14 10:00:00",
                {
                    "datos_cabecera": {
                        "numero_poliza": "BIS-001",
                        "asegurado": "Empresa A",
                        "prima_total": "500",
                    }
                },
            ),
            (
                "uuid-2",
                "file2.pdf",
                "ALI",
                "2026-09-14 09:00:00",
                {
                    "datos_cabecera": {
                        "numero_poliza": "ALI-002",
                        "asegurado": "Empresa B",
                        "prima_total": "700",
                    }
                },
            ),
        ]

        repo = PgStructuredSearchRepository(mock_db)
        results = repo.get_recent_policies(limit=2)

        assert len(results) == 2
        assert results[0]["numero_poliza"] == "BIS-001"
        assert results[0]["asegurado"] == "Empresa A"
        assert results[1]["numero_poliza"] == "ALI-002"
        assert results[1]["asegurado"] == "Empresa B"

    def test_find_basic_by_policy_number_or_id_found(self) -> None:
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.return_value = (
            "uuid-123",
            "file_test.pdf",
            "CRI",
            "2026-09-14",
            {
                "datos_cabecera": {
                    "numero_poliza": "SCR0667473",
                    "asegurado": "Credinform Client",
                }
            },
        )

        repo = PgStructuredSearchRepository(mock_db)
        res = repo.find_basic_by_policy_number_or_id("SCR0667473")

        assert res is not None
        assert res["policy_id"] == "uuid-123"
        assert res["numero_poliza"] == "SCR0667473"
        assert res["asegurado"] == "Credinform Client"

    def test_find_basic_by_policy_number_or_id_not_found(self) -> None:
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        mock_cur.fetchone.return_value = None

        repo = PgStructuredSearchRepository(mock_db)
        res = repo.find_basic_by_policy_number_or_id("NONEXISTENT")
        assert res is None


# ---------------------------------------------------------------------------
# Integration Tests: FastAPI Endpoints
# ---------------------------------------------------------------------------


class TestPolicyApiEndpoints:
    """Verify FastAPI /api/v1/policies endpoints with mocked repository."""

    @pytest.fixture
    def client(self) -> TestClient:
        app = create_app()
        return TestClient(app, raise_server_exceptions=False)

    def test_get_recent_policies_endpoint(self, client: TestClient) -> None:
        mock_items = [
            {
                "policy_id": "test-uuid-1",
                "numero_poliza": "POL-100",
                "ramo": "Automotor",
                "asegurado": "Pedro Gomez",
                "numero_documento": "123456 LP",
                "vigencia": "01/01/2026 - 31/12/2026",
                "prima_total": "1,000 USD",
                "company_sigla": "ALI",
                "file_name": "pol_100.pdf",
                "created_at": "2026-09-14",
            }
        ]

        with patch("app.api.v1.policies.PgStructuredSearchRepository.get_recent_policies", return_value=mock_items):
            response = client.get("/api/v1/policies/recent?limit=20")
            assert response.status_code == 200
            data = response.json()
            assert data["total"] == 1
            assert len(data["policies"]) == 1
            assert data["policies"][0]["numero_poliza"] == "POL-100"
            assert data["policies"][0]["ramo"] == "Automotor"

    def test_search_policy_endpoint_found(self, client: TestClient) -> None:
        mock_item = {
            "policy_id": "uuid-find",
            "numero_poliza": "SCR0667473",
            "ramo": "Incendio",
            "asegurado": "Comercializadora S.A.",
            "numero_documento": "998877 CI",
            "vigencia": "Desde 01/01/2026 hasta 31/12/2026",
            "prima_total": "2,500 USD",
            "company_sigla": "CRI",
            "file_name": "scr0667473.pdf",
            "created_at": "2026-09-14",
        }

        with patch("app.api.v1.policies.PgStructuredSearchRepository.find_basic_by_policy_number_or_id", return_value=mock_item):
            response = client.get("/api/v1/policies/search?q=SCR0667473")
            assert response.status_code == 200
            data = response.json()
            assert data["found"] is True
            assert data["policy"]["numero_poliza"] == "SCR0667473"
            assert data["policy"]["asegurado"] == "Comercializadora S.A."

    def test_search_policy_endpoint_not_found(self, client: TestClient) -> None:
        with patch("app.api.v1.policies.PgStructuredSearchRepository.find_basic_by_policy_number_or_id", return_value=None):
            response = client.get("/api/v1/policies/search?q=INEXISTENTE")
            assert response.status_code == 200
            data = response.json()
            assert data["found"] is False
            assert data["policy"] is None

    def test_get_policy_by_id_endpoint_found(self, client: TestClient) -> None:
        mock_item = {
            "policy_id": "uuid-specific-99",
            "numero_poliza": "SPEC-99",
            "ramo": "Accidentes",
            "asegurado": "Ana Flores",
            "numero_documento": "456789 LP",
            "vigencia": "No especificada",
            "prima_total": "300 USD",
            "company_sigla": "BIS",
            "file_name": "spec99.pdf",
            "created_at": "2026-09-14",
        }

        with patch("app.api.v1.policies.PgStructuredSearchRepository.find_basic_by_policy_number_or_id", return_value=mock_item):
            response = client.get("/api/v1/policies/uuid-specific-99")
            assert response.status_code == 200
            data = response.json()
            assert data["policy_id"] == "uuid-specific-99"
            assert data["numero_poliza"] == "SPEC-99"

    def test_get_policy_by_id_endpoint_not_found(self, client: TestClient) -> None:
        with patch("app.api.v1.policies.PgStructuredSearchRepository.find_basic_by_policy_number_or_id", return_value=None):
            response = client.get("/api/v1/policies/missing-uuid")
            assert response.status_code == 404

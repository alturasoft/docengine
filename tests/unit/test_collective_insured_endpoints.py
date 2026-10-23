"""DocEngine — Unit Tests: Collective Insured Persons Endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.v1.insured_persons import get_insured_repo, get_insured_service


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


def test_get_policy_insured_persons(client: TestClient, mock_app) -> None:
    mock_repo = MagicMock()
    mock_repo.get_insured_summary.return_value = {
        "total_asegurados": 2,
        "total_suma_asegurada_usd": 150000.0,
        "total_prima_usd": 1200.0,
        "edad_promedio": 38.0,
        "distribucion_categoria": {"TITULAR": 2},
        "distribucion_genero": {},
        "muestra": [],
    }
    mock_repo.get_persons_for_policy.return_value = [
        {
            "item_number": 1,
            "nombre_completo": "JUAN PEREZ",
            "documento_identidad": "1234567",
            "parentesco_categoria": "TITULAR",
            "suma_asegurada_usd": 75000.0,
        },
        {
            "item_number": 2,
            "nombre_completo": "MARIA GOMEZ",
            "documento_identidad": "7654321",
            "parentesco_categoria": "TITULAR",
            "suma_asegurada_usd": 75000.0,
        },
    ]

    mock_app.dependency_overrides[get_insured_repo] = lambda: mock_repo
    mock_app.dependency_overrides[get_insured_service] = lambda: MagicMock()

    try:
        response = client.get("/api/v1/policies/test-pol-uuid/insured-persons")
        assert response.status_code == 200
        data = response.json()
        assert data["total_asegurados"] == 2
        assert len(data["items"]) == 2
        assert data["items"][0]["nombre_completo"] == "JUAN PEREZ"
    finally:
        mock_app.dependency_overrides.clear()


def test_export_policy_insured_persons_csv(client: TestClient, mock_app) -> None:
    mock_repo = MagicMock()
    mock_repo.get_persons_for_policy.return_value = [
        {
            "item_number": 1,
            "nombre_completo": "JUAN PEREZ",
            "documento_identidad": "1234567",
            "fecha_nacimiento": "15/05/1985",
            "edad": 39,
            "genero": "MASCULINO",
            "parentesco_categoria": "TITULAR",
            "cargo_ocupacion": "INGENIERO",
            "suma_asegurada_usd": 50000.0,
            "prima_usd": 250.0,
        }
    ]

    mock_app.dependency_overrides[get_insured_repo] = lambda: mock_repo
    mock_app.dependency_overrides[get_insured_service] = lambda: MagicMock()

    try:
        response = client.get("/api/v1/policies/test-pol-uuid/insured-persons/export")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/csv")
        assert "JUAN PEREZ" in response.text
        assert "1234567" in response.text
    finally:
        mock_app.dependency_overrides.clear()


def test_search_insured_persons(client: TestClient, mock_app) -> None:
    mock_repo = MagicMock()
    mock_repo.search_persons.return_value = [
        {
            "item_number": 1,
            "nombre_completo": "CARLOS MENDOZA",
            "documento_identidad": "4819201",
        }
    ]

    mock_app.dependency_overrides[get_insured_repo] = lambda: mock_repo

    try:
        response = client.get("/api/v1/insured-persons/search?q=Mendoza")
        assert response.status_code == 200
        data = response.json()
        assert data["total_encontrados"] == 1
        assert data["items"][0]["nombre_completo"] == "CARLOS MENDOZA"
    finally:
        mock_app.dependency_overrides.clear()

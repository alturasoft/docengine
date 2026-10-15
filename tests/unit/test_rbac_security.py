"""DocEngine — Unit Tests: RBAC Security (Req 8).

Tests verifying:
1. Anonymous permissive access when security is disabled (backward-compatibility).
2. 401 Unauthorized when security is enabled and X-API-Key is missing or invalid.
3. 403 Forbidden when role is insufficient (e.g. readonly trying to extract or delete).
4. Authorized access when role is sufficient (readonly for queries, writer for extract, admin for delete).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.v1.policies import get_envelope_repo


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


API_KEYS_CONFIG = json.dumps({
    "key_reader_1": "readonly",
    "key_writer_2": "writer",
    "key_admin_3": "admin",
})


class TestRbacSecurity:
    """Verify RBAC role enforcement and API Key authentication."""

    def test_anonymous_access_allowed_when_security_disabled(self, client: TestClient, mock_app) -> None:
        with patch.dict("os.environ", {"DOCENGINE_SECURITY_ENABLED": "false", "DOCENGINE_API_KEYS": ""}):
            mock_app.state.rag_query_service.search_chunks.return_value = []
            response = client.post("/api/v1/query/search", json={"question": "¿Cuáles son las coberturas?"})
            assert response.status_code == 200

    def test_missing_api_key_returns_401_when_security_enabled(self, client: TestClient) -> None:
        with patch.dict("os.environ", {"DOCENGINE_SECURITY_ENABLED": "true", "DOCENGINE_API_KEYS": API_KEYS_CONFIG}):
            response = client.post("/api/v1/query/search", json={"question": "¿Cuáles son las coberturas?"})
            assert response.status_code == 401
            assert "X-API-Key" in response.json()["detail"]

    def test_invalid_api_key_returns_401(self, client: TestClient) -> None:
        with patch.dict("os.environ", {"DOCENGINE_SECURITY_ENABLED": "true", "DOCENGINE_API_KEYS": API_KEYS_CONFIG}):
            headers = {"X-API-Key": "INVALID_KEY_999"}
            response = client.post("/api/v1/query/search", json={"question": "¿Cuáles son las coberturas?"}, headers=headers)
            assert response.status_code == 401
            assert "inválida" in response.json()["detail"]

    def test_readonly_user_can_search(self, client: TestClient, mock_app) -> None:
        with patch.dict("os.environ", {"DOCENGINE_SECURITY_ENABLED": "true", "DOCENGINE_API_KEYS": API_KEYS_CONFIG}):
            mock_app.state.rag_query_service.search_chunks.return_value = []
            headers = {"X-API-Key": "key_reader_1"}
            response = client.post("/api/v1/query/search", json={"question": "¿Cuáles son las coberturas?"}, headers=headers)
            assert response.status_code == 200

    def test_readonly_user_blocked_from_extract(self, client: TestClient) -> None:
        with patch.dict("os.environ", {"DOCENGINE_SECURITY_ENABLED": "true", "DOCENGINE_API_KEYS": API_KEYS_CONFIG}):
            headers = {"X-API-Key": "key_reader_1"}
            files = {"file": ("poliza.pdf", b"%PDF-1.4 mock", "application/pdf")}
            data = {"id_cliente": "123456 LP"}
            response = client.post("/api/v1/extract", files=files, data=data, headers=headers)
            assert response.status_code == 403
            assert "Permisos insuficientes" in response.json()["detail"]

    def test_readonly_user_blocked_from_delete(self, client: TestClient) -> None:
        with patch.dict("os.environ", {"DOCENGINE_SECURITY_ENABLED": "true", "DOCENGINE_API_KEYS": API_KEYS_CONFIG}):
            headers = {"X-API-Key": "key_reader_1"}
            response = client.delete("/api/v1/policies/doc-uuid-1", headers=headers)
            assert response.status_code == 403
            assert "Permisos insuficientes" in response.json()["detail"]

    def test_writer_user_blocked_from_delete(self, client: TestClient) -> None:
        with patch.dict("os.environ", {"DOCENGINE_SECURITY_ENABLED": "true", "DOCENGINE_API_KEYS": API_KEYS_CONFIG}):
            headers = {"X-API-Key": "key_writer_2"}
            response = client.delete("/api/v1/policies/doc-uuid-1", headers=headers)
            assert response.status_code == 403
            assert "Permisos insuficientes" in response.json()["detail"]

    def test_admin_user_allowed_to_delete(self, client: TestClient, mock_app) -> None:
        with patch.dict("os.environ", {"DOCENGINE_SECURITY_ENABLED": "true", "DOCENGINE_API_KEYS": API_KEYS_CONFIG}):
            mock_repo = MagicMock()
            mock_repo.delete_document.return_value = {
                "policy_id": "doc-uuid-1",
                "file_name": "test.pdf",
                "envelope_id": "env-1",
                "company_sigla": "CRE",
            }
            mock_app.dependency_overrides[get_envelope_repo] = lambda: mock_repo

            try:
                headers = {"X-API-Key": "key_admin_3"}
                response = client.delete("/api/v1/policies/doc-uuid-1", headers=headers)
                assert response.status_code == 200
            finally:
                mock_app.dependency_overrides.pop(get_envelope_repo, None)

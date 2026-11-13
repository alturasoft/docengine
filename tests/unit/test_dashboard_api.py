"""DocEngine — Unit Tests: Control Dashboard API, Repository & RBAC.

Tests strictly using mocked repository / mocked PostgreSQL connection (zero DB writes):
1. Web UI route availability (/dashboard and /dashboard.html).
2. GET /api/v1/dashboard/overview schema, granularity, high-water marks & filters.
3. GET /api/v1/dashboard/audit-ledger, /processing-stats, /jobs-errors pagination & filtering.
4. GET /api/v1/dashboard/export.csv (ledger, stats, jobs datasets, UTF-8 BOM).
5. RBAC enforcement (401 without key when enabled, 200 for readonly role).
6. PgAuditDashboardRepository filter builders & read-only SQL validation.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.api.v1.dashboard import get_dashboard_repo
from app.infrastructure.database.pg_audit_dashboard_repository import (
    PgAuditDashboardRepository,
    _validate_iso_date,
)


def _sample_overview_payload(granularity: str = "daily") -> dict:
    return {
        "kpis": {
            "documents_extracted_total": 42,
            "active_documents": 38,
            "documents_deleted_total": 4,
            "total_envelopes_historical": 16,
            "active_envelopes": 14,
            "envelopes_deleted_total": 2,
            "unique_clients": 9,
            "total_pages_processed": 612,
            "total_tables_detected": 89,
            "total_coberturas_extracted": 145,
            "total_chunks_created": 1820,
            "parent_chunks_count": 380,
            "child_chunks_count": 1440,
            "total_volume_bytes": 1_250_000,
            "jobs_total": 50,
            "jobs_completed": 42,
            "jobs_failed": 5,
            "jobs_skipped": 3,
            "jobs_processing": 0,
            "jobs_pending": 0,
            "success_rate_pct": 90.0,
            "error_rate_pct": 10.0,
            "failure_events_ledger": 2,
            "duplicate_events_ledger": 3,
            "avg_extraction_time_seconds": 48.25,
            "avg_time_per_page_seconds": 3.12,
            "avg_chunking_time_seconds": 0.42,
            "avg_embedding_time_seconds": 14.5,
            "avg_openai_time_seconds": 19.8,
            "avg_pipeline_time_seconds": 36.1,
            "avg_end_to_end_seconds": 84.35,
            "p95_pipeline_time_seconds": 62.4,
            "max_memory_peak_mb": 1450.5,
            "avg_memory_peak_mb": 1120.2,
            "openai_prompt_tokens": 120000,
            "openai_completion_tokens": 35000,
            "openai_total_tokens": 155000,
            "openai_estimated_cost_usd": 0.04125,
            "ocr_applied_count": 12,
            "ocr_rate_pct": 28.57,
            "avg_scanned_page_ratio": 0.24,
            "fleet_vehicles_count": 64,
            "insured_persons_count": 210,
            "section_summaries_count": 11,
            "high_water_extractions": 0,
            "high_water_pages": 0,
            "high_water_tables": 0,
        },
        "period_snapshot": {
            "today_documents": 3,
            "today_pages": 44,
            "today_errors": 1,
            "today_envelopes": 1,
            "today_cost_usd": 0.0021,
            "week_documents": 14,
            "week_pages": 210,
            "week_errors": 2,
            "week_envelopes": 5,
            "week_cost_usd": 0.0124,
            "prev_week_documents": 10,
            "week_growth_pct": 40.0,
        },
        "granularity": granularity,
        "time_series": [
            {
                "period": "2026-11-10",
                "period_label": "Sem 2026-11-09" if granularity == "weekly" else "2026-11-10",
                "documents_extracted": 3,
                "duplicates_skipped": 1,
                "jobs_completed": 3,
                "jobs_failed": 1,
                "jobs_skipped": 1,
                "envelopes_created": 1,
                "deletions_count": 0,
                "pages_processed": 44,
                "tables_detected": 6,
                "chunks_created": 120,
                "volume_bytes": 95000,
                "avg_extraction_time_seconds": 41.2,
                "avg_pipeline_time_seconds": 28.5,
                "openai_tokens": 11000,
                "openai_cost_usd": 0.0021,
            }
        ],
        "by_company": [
            {
                "company_sigla": "LBC",
                "company_name": "La Boliviana Ciacruz de Seguros",
                "documents_count": 18,
                "active_documents_count": 16,
                "envelopes_count": 6,
                "pages_count": 290,
                "tables_count": 41,
                "chunks_count": 880,
                "coberturas_count": 62,
                "volume_bytes": 620000,
                "avg_extraction_time_seconds": 44.0,
                "avg_pipeline_time_seconds": 33.2,
                "openai_tokens": 71000,
                "openai_cost_usd": 0.0195,
                "failed_count": 1,
                "deleted_count": 2,
            }
        ],
        "by_ramo": [
            {
                "ramo": "AUTOMOTORES",
                "ramo_tipo": "GENERALES",
                "envelopes_count": 8,
                "documents_count": 20,
                "pages_count": 250,
                "tables_count": 32,
                "openai_cost_usd": 0.015,
            }
        ],
        "by_document_type": [
            {
                "tipo_documento": "CONDICIONADO_PARTICULAR",
                "documents_count": 25,
                "pages_count": 340,
                "tables_count": 55,
                "chunks_count": 1020,
            }
        ],
        "by_file_type": [
            {
                "file_type": "DIGITAL",
                "documents_count": 30,
                "ocr_applied_count": 0,
                "pages_count": 410,
                "avg_time_per_page_seconds": 1.8,
                "avg_extraction_time_seconds": 29.0,
            },
            {
                "file_type": "SCANNED",
                "documents_count": 12,
                "ocr_applied_count": 12,
                "pages_count": 202,
                "avg_time_per_page_seconds": 6.4,
                "avg_extraction_time_seconds": 96.0,
            },
        ],
        "ledger_event_summary": [
            {"event_type": "DOCUMENT_EXTRACTED", "count": 42},
            {"event_type": "ENVELOPE_CREATED", "count": 16},
            {"event_type": "DOCUMENT_DELETED", "count": 4},
        ],
        "error_categories": [
            {
                "category": "Duplicado de Archivo (Hash SHA-256)",
                "count": 3,
                "latest_at": "2026-11-10T06:00:00+00:00",
                "sample_message": 'duplicate key value violates unique constraint "policies_file_hash_key"',
            }
        ],
        "worm_status": {
            "active": True,
            "protected_tables": [
                "audit_metrics_ledger",
                "policy_processing_stats",
                "processing_jobs",
            ],
            "triggers_count": 6,
            "trigger_names": [
                "trg_protect_audit_ledger_delete",
                "trg_protect_audit_ledger_truncate",
                "trg_protect_processing_jobs_delete",
                "trg_protect_processing_jobs_truncate",
                "trg_protect_processing_stats_delete",
                "trg_protect_processing_stats_truncate",
            ],
        },
        "filters_applied": {"granularity": granularity},
        "available_filters": {
            "companies": [{"sigla": "LBC", "nombre": "La Boliviana Ciacruz de Seguros"}],
            "document_types": ["CONDICIONADO_PARTICULAR"],
            "ramos": ["AUTOMOTORES"],
            "file_types": ["DIGITAL", "SCANNED", "HYBRID", "UNKNOWN"],
        },
    }


@pytest.fixture
def mock_dashboard_repo() -> MagicMock:
    repo = MagicMock(spec=PgAuditDashboardRepository)
    repo.get_dashboard_overview.side_effect = lambda **kw: _sample_overview_payload(
        granularity=kw.get("granularity", "daily")
    )
    repo.list_audit_ledger.return_value = (
        [
            {
                "event_id": "evt-0001",
                "event_type": "DOCUMENT_EXTRACTED",
                "policy_id": "pol-111",
                "envelope_id": "env-222",
                "job_id": "job-333",
                "numero_poliza": "AU-9001",
                "company_sigla": "LBC",
                "ramo": "AUTOMOTORES",
                "tipo_documento": "CONDICIONADO_PARTICULAR",
                "id_cliente": "4829102 LP",
                "nombre_cliente": "Juan Perez",
                "file_name": "poliza_lbc_auto.pdf",
                "file_hash": "a" * 64,
                "pages_count": 14,
                "tables_count": 3,
                "chunks_count": 48,
                "file_size_bytes": 42000,
                "duration_seconds": 38.4,
                "openai_tokens": 5200,
                "openai_cost_usd": 0.00142,
                "metadata": {"source": "api"},
                "created_at": "2026-11-10T06:15:00+00:00",
            }
        ],
        1,
    )
    repo.list_processing_stats.return_value = (
        [
            {
                "stat_id": "stat-0001",
                "policy_id": "pol-111",
                "envelope_id": "env-222",
                "job_id": "job-333",
                "policy_number": "AU-9001",
                "company_sigla": "LBC",
                "file_name": "poliza_lbc_auto.pdf",
                "file_hash": "a" * 64,
                "tipo_documento": "CONDICIONADO_PARTICULAR",
                "id_cliente": "4829102 LP",
                "file_type": "DIGITAL",
                "ocr_applied": False,
                "scanned_page_ratio": 0.0,
                "total_pages": 14,
                "extraction_time_seconds": 21.3,
                "time_per_page_seconds": 1.52,
                "chunking_time_seconds": 0.34,
                "embedding_time_seconds": 9.8,
                "openai_time_seconds": 12.1,
                "total_pipeline_time_seconds": 23.4,
                "total_chunks": 48,
                "parent_chunks": 10,
                "child_chunks": 38,
                "openai_prompt_tokens": 4000,
                "openai_completion_tokens": 1200,
                "openai_total_tokens": 5200,
                "openai_estimated_cost_usd": 0.00142,
                "coberturas_extracted_count": 7,
                "tables_detected": 3,
                "memory_peak_mb": 1024.5,
                "created_at": "2026-11-10T06:15:00+00:00",
            }
        ],
        1,
    )
    repo.list_jobs_and_errors.return_value = (
        [
            {
                "job_id": "job-err-99",
                "file_name": "escaneada_corrupta.pdf",
                "status": "FAILED",
                "error_message": 'duplicate key value violates unique constraint "policies_file_hash_key"',
                "policy_id": None,
                "company_sigla": "CRE",
                "numero_poliza": "2026-001",
                "created_at": "2026-11-10T05:10:00+00:00",
                "updated_at": "2026-11-10T05:11:12+00:00",
                "duration_seconds": 72.0,
            }
        ],
        1,
        {"FAILED": 5, "COMPLETED": 42, "SKIPPED": 3},
    )
    return repo


@pytest.fixture
def dashboard_app(mock_dashboard_repo: MagicMock):
    with patch("app.api.main._build_extraction_service"):
        app = create_app()
        app.state.extraction_service = MagicMock()
        app.state.rag_service = MagicMock()
        app.state.rag_query_service = MagicMock()
        app.dependency_overrides[get_dashboard_repo] = lambda: mock_dashboard_repo
        yield app
        app.dependency_overrides.pop(get_dashboard_repo, None)


@pytest.fixture
def client(dashboard_app) -> TestClient:
    return TestClient(dashboard_app)


class TestDashboardWebUI:
    """Verify Web UI serving routes for the dashboard."""

    def test_dashboard_html_routes(self, client: TestClient) -> None:
        for path in ("/dashboard", "/dashboard.html", "/ui/dashboard.html"):
            resp = client.get(path)
            assert resp.status_code == 200
            assert "text/html" in resp.headers.get("content-type", "")
            assert "DocEngine Control Center" in resp.text
            assert "/api/v1/dashboard/overview" in resp.text


class TestDashboardEndpoints:
    """Verify read-only dashboard analytics and export endpoints."""

    def test_overview_default_and_high_water_marks(
        self, client: TestClient, mock_dashboard_repo: MagicMock
    ) -> None:
        with patch.dict(
            "app.api.v1.health._METRICS",
            {
                "total_extractions": 99,
                "total_pages_processed": 1234,
                "total_tables_detected": 150,
            },
        ):
            resp = client.get("/api/v1/dashboard/overview")

        assert resp.status_code == 200
        body = resp.json()
        assert body["granularity"] == "daily"
        assert body["kpis"]["documents_extracted_total"] == 42
        assert body["kpis"]["high_water_extractions"] == 99
        assert body["kpis"]["high_water_pages"] == 1234
        assert body["kpis"]["high_water_tables"] == 150
        assert body["period_snapshot"]["week_growth_pct"] == 40.0
        assert body["worm_status"]["active"] is True
        assert body["worm_status"]["triggers_count"] == 6
        assert body["system_health"]["status"] == "ok"
        assert len(body["by_company"]) == 1
        assert body["by_company"][0]["company_sigla"] == "LBC"
        mock_dashboard_repo.get_dashboard_overview.assert_called_once_with(
            granularity="daily",
            date_from=None,
            date_to=None,
            company_sigla=None,
            ramo=None,
            tipo_documento=None,
            file_type=None,
        )

    def test_overview_weekly_and_filters(
        self, client: TestClient, mock_dashboard_repo: MagicMock
    ) -> None:
        resp = client.get(
            "/api/v1/dashboard/overview",
            params={
                "granularity": "weekly",
                "date_from": "2026-11-01",
                "date_to": "2026-11-10",
                "company_sigla": "LBC",
                "ramo": "AUTOMOTORES",
                "tipo_documento": "CONDICIONADO_PARTICULAR",
                "file_type": "SCANNED",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["granularity"] == "weekly"
        mock_dashboard_repo.get_dashboard_overview.assert_called_once_with(
            granularity="weekly",
            date_from="2026-11-01",
            date_to="2026-11-10",
            company_sigla="LBC",
            ramo="AUTOMOTORES",
            tipo_documento="CONDICIONADO_PARTICULAR",
            file_type="SCANNED",
        )

    def test_overview_invalid_granularity_422(self, client: TestClient) -> None:
        resp = client.get("/api/v1/dashboard/overview?granularity=hourly")
        assert resp.status_code == 422

    def test_audit_ledger_endpoint(
        self, client: TestClient, mock_dashboard_repo: MagicMock
    ) -> None:
        resp = client.get(
            "/api/v1/dashboard/audit-ledger",
            params={
                "limit": 10,
                "offset": 20,
                "company_sigla": "LBC",
                "event_type": "DOCUMENT_EXTRACTED",
                "search": "AU-9001",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["limit"] == 10
        assert body["offset"] == 20
        assert body["items"][0]["event_id"] == "evt-0001"
        assert body["items"][0]["numero_poliza"] == "AU-9001"
        mock_dashboard_repo.list_audit_ledger.assert_called_once_with(
            limit=10,
            offset=20,
            date_from=None,
            date_to=None,
            company_sigla="LBC",
            ramo=None,
            tipo_documento=None,
            event_type="DOCUMENT_EXTRACTED",
            search="AU-9001",
        )

    def test_processing_stats_endpoint(
        self, client: TestClient, mock_dashboard_repo: MagicMock
    ) -> None:
        resp = client.get(
            "/api/v1/dashboard/processing-stats",
            params={"limit": 15, "offset": 0, "file_type": "DIGITAL"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["stat_id"] == "stat-0001"
        assert body["items"][0]["total_chunks"] == 48
        mock_dashboard_repo.list_processing_stats.assert_called_once()

    def test_jobs_errors_endpoint(
        self, client: TestClient, mock_dashboard_repo: MagicMock
    ) -> None:
        resp = client.get(
            "/api/v1/dashboard/jobs-errors",
            params={"status": "FAILED", "company_sigla": "CRE", "search": "duplicate"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["status_counts"] == {"FAILED": 5, "COMPLETED": 42, "SKIPPED": 3}
        assert body["items"][0]["status"] == "FAILED"
        mock_dashboard_repo.list_jobs_and_errors.assert_called_once_with(
            limit=25,
            offset=0,
            date_from=None,
            date_to=None,
            company_sigla="CRE",
            status_filter="FAILED",
            search="duplicate",
        )

    @pytest.mark.parametrize(
        ("dataset", "expected_header"),
        [
            ("ledger", "Tipo Evento"),
            ("stats", "T. Extraccion (s)"),
            ("jobs", "Mensaje de Error"),
        ],
    )
    def test_export_csv_datasets(
        self, client: TestClient, dataset: str, expected_header: str
    ) -> None:
        resp = client.get(f"/api/v1/dashboard/export.csv?dataset={dataset}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert f'filename="docengine_auditoria_{dataset}.csv"' in resp.headers.get(
            "content-disposition", ""
        )
        text = resp.content.decode("utf-8-sig")
        assert resp.content.startswith(b"\xef\xbb\xbf")
        assert expected_header in text

    def test_export_csv_invalid_dataset_422(self, client: TestClient) -> None:
        resp = client.get("/api/v1/dashboard/export.csv?dataset=unknown")
        assert resp.status_code == 422


class TestDashboardRbac:
    """Verify RBAC API key enforcement on dashboard endpoints."""

    def test_dashboard_requires_readonly_key_when_security_enabled(
        self, client: TestClient
    ) -> None:
        keys = json.dumps({"reader_key": "readonly"})
        with patch.dict(
            "os.environ",
            {"DOCENGINE_SECURITY_ENABLED": "true", "DOCENGINE_API_KEYS": keys},
        ):
            r_unauth = client.get("/api/v1/dashboard/overview")
            assert r_unauth.status_code == 401

            r_csv_unauth = client.get("/api/v1/dashboard/export.csv?dataset=ledger")
            assert r_csv_unauth.status_code == 401

            r_auth = client.get(
                "/api/v1/dashboard/overview", headers={"X-API-Key": "reader_key"}
            )
            assert r_auth.status_code == 200


class TestDashboardRepositoryUnit:
    """Verify filter builders and strictly read-only SQL construction in repository."""

    def test_validate_iso_date(self) -> None:
        assert _validate_iso_date("2026-11-10") == "2026-11-10"
        assert _validate_iso_date(" 2026-11-10T12:00:00 ") == "2026-11-10"
        assert _validate_iso_date("not-a-date") is None
        assert _validate_iso_date("") is None

    def test_where_clause_builders(self) -> None:
        where_l, params_l = PgAuditDashboardRepository._build_ledger_where(
            date_from="2026-11-01",
            date_to="2026-11-10",
            company_sigla="lbc",
            ramo="auto",
            tipo_documento="condicionado_particular",
            file_type="scanned",
            event_type="document_extracted",
            search="pol-123",
        )
        assert "aml.created_at >= %s::date" in where_l
        assert "UPPER(aml.company_sigla) = %s" in where_l
        assert "EXISTS (SELECT 1 FROM policy_processing_stats" in where_l
        assert params_l[:4] == ["2026-11-01", "2026-11-10", "LBC", "%auto%"]

        where_s, params_s = PgAuditDashboardRepository._build_stats_where(
            company_sigla="cre", file_type="digital", ramo="incendio"
        )
        assert "UPPER(pps.company_sigla) = %s" in where_s
        assert "UPPER(pps.file_type) = %s" in where_s
        assert params_s == ["CRE", "%incendio%", "DIGITAL"]

    def test_repository_executes_only_select_queries(self) -> None:
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_db.get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = (0,) * 25
        mock_cur.fetchall.return_value = []

        repo = PgAuditDashboardRepository(mock_db)
        overview = repo.get_dashboard_overview(granularity="weekly")

        assert overview["granularity"] == "weekly"
        assert mock_cur.execute.called
        for call in mock_cur.execute.call_args_list:
            sql = call[0][0].strip().upper()
            assert "INSERT " not in sql
            assert "UPDATE " not in sql
            assert "DELETE " not in sql
            assert "DROP " not in sql
            assert "TRUNCATE " not in sql


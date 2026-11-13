"""Unit and database integration tests for Immutable Audit & Metrics Ledger (WORM)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.application.rag_pipeline_service import RagPipelineService
from app.config.settings import get_settings
from app.domain.models.document import DocumentMetadata, ExtractionResult
from app.domain.models.rag_models import PolicyProcessingStats
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_envelope_repository import PgEnvelopeRepository
from app.infrastructure.database.pg_rag_repository import PgRagRepository


class TestImmutableMetricsAPI:
    """Verify API endpoints for immutable metrics and blocked reset."""

    def test_metrics_reset_is_forbidden_403(self, test_client: TestClient) -> None:
        """POST /api/v1/metrics/reset must return 403 Forbidden in immutable mode."""
        res = test_client.post("/api/v1/metrics/reset")
        assert res.status_code == 403
        body = res.json()
        assert "inmutables" in body["detail"].lower()

    def test_metrics_endpoint_returns_extended_immutable_fields(self, test_client: TestClient) -> None:
        """GET /api/v1/metrics must include envelope, chunk, client and immutable_mode fields."""
        res = test_client.get("/api/v1/metrics")
        assert res.status_code == 200
        data = res.json()
        assert data["immutable_mode"] is True
        assert "total_extractions" in data
        assert "total_pages_processed" in data
        assert "total_tables_detected" in data
        assert "total_envelopes" in data
        assert "active_documents" in data
        assert "total_chunks_indexed" in data
        assert "skipped_duplicates" in data
        assert "total_clients" in data


class TestPipelineJobTrackingAndAudit:
    """Verify RagPipelineService reuses existing_job_id and records audit events."""

    def test_skip_duplicate_reuses_existing_job_id_and_logs_audit(self) -> None:
        mock_repo = MagicMock()
        mock_repo.policy_exists_by_hash.return_value = "existing-policy-uuid"

        service = RagPipelineService(
            chunking_service=MagicMock(),
            embedding_service=MagicMock(),
            structured_extractor=MagicMock(),
            repository=mock_repo,
        )

        result = ExtractionResult(
            document_id="doc-1",
            status="success",
            markdown="# Póliza",
            json_data={},
            metadata=DocumentMetadata(
                filename="poliza_dup.pdf",
                source_path="/tmp/poliza_dup.pdf",
                sha256="abc123hash",
                page_count=12,
                extraction_time_seconds=1.5,
                docling_version="2.0.0",
                tables_detected=3,
                figures_detected=0,
                headers_removed=0,
                footers_removed=0,
                ocr_used=False,
                has_multi_column=False,
                markdown_size_bytes=120,
                company_sigla="BISA",
            ),
        )

        report = service.process_extraction_result(
            result,
            numero_poliza="POL-999",
            id_cliente="10203040",
            existing_job_id="precreated-job-uuid",
        )

        assert report.skipped_duplicate is True
        assert report.job_id == "precreated-job-uuid"
        mock_repo.create_job.assert_not_called()
        mock_repo.update_job.assert_called_once_with(
            job_id="precreated-job-uuid",
            status="SKIPPED",
            policy_id="existing-policy-uuid",
        )
        mock_repo.record_audit_event.assert_called_once()
        call_kwargs = mock_repo.record_audit_event.call_args.kwargs
        assert call_kwargs["event_type"] == "DOCUMENT_SKIPPED_DUPLICATE"
        assert call_kwargs["pages_count"] == 12
        assert call_kwargs["tables_count"] == 3


class TestPostgreSQLImmutabilityAndSurvival:
    """Verify PostgreSQL WORM triggers and stats survival when operational documents are deleted."""

    @pytest.fixture()
    def db_manager(self) -> DatabaseManager:
        settings = get_settings()
        return DatabaseManager(settings.database)

    def test_triggers_block_delete_on_stats_ledger_and_jobs(self, db_manager: DatabaseManager) -> None:
        """Verify BEFORE DELETE triggers reject row deletion on all three audit/stats tables."""
        for table_name in ("policy_processing_stats", "audit_metrics_ledger", "processing_jobs"):
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    with pytest.raises(Exception) as exc_info:
                        cur.execute(f"DELETE FROM {table_name};")
                    assert "PRODUCCION-INMUTABLE" in str(exc_info.value)
                conn.rollback()

    def test_stats_and_ledger_survive_policy_and_envelope_deletion(self, db_manager: DatabaseManager) -> None:
        """Verify deleting a policy or envelope preserves historical page/table counts in stats and ledger."""
        rag_repo = PgRagRepository(db_manager)
        env_repo = PgEnvelopeRepository(db_manager)

        unique_suffix = uuid.uuid4().hex[:10]
        test_pol_num = f"TEST-IMM-{unique_suffix}"
        test_hash = f"hash_imm_{unique_suffix}"
        test_file = f"poliza_inmutable_{unique_suffix}.pdf"

        envelope_id = None
        try:
            # 1. Create envelope
            envelope_id = env_repo.get_or_create_envelope(
                numero_poliza=test_pol_num,
                company_sigla="BISA",
                ramo="AUTOMOTORES",
                id_cliente="99887766",
                nombre_cliente="Cliente Prueba Inmutable",
            )
            assert envelope_id

            # 2. Create job & save policy with stats (25 pages, 4 tables)
            job_id = rag_repo.create_job(file_name=test_file)
            stats = PolicyProcessingStats(
                policy_id="",
                job_id=job_id,
                policy_number=test_pol_num,
                company_sigla="BISA",
                file_type="DIGITAL",
                ocr_applied=False,
                total_pages=25,
                extraction_time_seconds=2.4,
                total_pipeline_time_seconds=3.1,
                total_chunks=10,
                parent_chunks=2,
                child_chunks=8,
                tables_detected=4,
                envelope_id=envelope_id,
                file_name=test_file,
                file_hash=test_hash,
                tipo_documento="CONDICIONADO_PARTICULAR",
                id_cliente="99887766",
            )

            policy_id = rag_repo.save_rag_policy_transactional(
                file_name=test_file,
                file_hash=test_hash,
                company_sigla="BISA",
                total_pages=25,
                file_size_bytes=4096,
                markdown_content="# Test Immutable Policy",
                structured_data={"datos_cabecera": {"numero_poliza": test_pol_num}},
                chunks=[],
                stats=stats,
                envelope_id=envelope_id,
                tipo_documento="CONDICIONADO_PARTICULAR",
                id_cliente="99887766",
                nombre_cliente="Cliente Prueba Inmutable",
            )
            rag_repo.update_job(job_id=job_id, status="COMPLETED", policy_id=policy_id)

            # 3. Delete operational document and envelope
            deleted_doc = env_repo.delete_document(policy_id)
            assert deleted_doc is not None
            deleted_env = env_repo.delete_envelope(envelope_id)
            assert deleted_env is not None

            # 4. Verify policy_processing_stats row SURVIVED with policy_id = NULL and intact metrics
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT policy_id, total_pages, tables_detected, file_name, file_hash, envelope_id, id_cliente
                        FROM policy_processing_stats
                        WHERE file_hash = %s;
                        """,
                        (test_hash,),
                    )
                    stat_row = cur.fetchone()
                    assert stat_row is not None
                    assert stat_row[0] is None  # policy_id set to NULL on delete, row NOT deleted
                    assert stat_row[1] == 25
                    assert stat_row[2] == 4
                    assert stat_row[3] == test_file
                    assert stat_row[4] == test_hash
                    assert str(stat_row[5]) == envelope_id
                    assert stat_row[6] == "99887766"

                    # 5. Verify audit_metrics_ledger recorded lifecycle events
                    cur.execute(
                        """
                        SELECT event_type, pages_count, tables_count
                        FROM audit_metrics_ledger
                        WHERE numero_poliza = %s OR file_hash = %s
                        ORDER BY created_at ASC;
                        """,
                        (test_pol_num, test_hash),
                    )
                    events = cur.fetchall()
                    event_types = [e[0] for e in events]
                    assert "ENVELOPE_CREATED" in event_types
                    assert "DOCUMENT_EXTRACTED" in event_types
                    assert "DOCUMENT_DELETED" in event_types
                    assert "ENVELOPE_DELETED" in event_types
        finally:
            # Clean up test artifacts cleanly without leaving residues in the live DB
            with db_manager.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("ALTER TABLE audit_metrics_ledger DISABLE TRIGGER trg_protect_audit_ledger_delete;")
                    cur.execute(
                        "DELETE FROM audit_metrics_ledger WHERE numero_poliza = %s OR file_hash = %s;",
                        (test_pol_num, test_hash),
                    )
                    cur.execute("ALTER TABLE audit_metrics_ledger ENABLE TRIGGER trg_protect_audit_ledger_delete;")

                    cur.execute("ALTER TABLE policy_processing_stats DISABLE TRIGGER trg_protect_processing_stats_delete;")
                    cur.execute("DELETE FROM policy_processing_stats WHERE file_hash = %s;", (test_hash,))
                    cur.execute("ALTER TABLE policy_processing_stats ENABLE TRIGGER trg_protect_processing_stats_delete;")

                    cur.execute("ALTER TABLE processing_jobs DISABLE TRIGGER trg_protect_processing_jobs_delete;")
                    cur.execute("DELETE FROM processing_jobs WHERE file_name = %s;", (test_file,))
                    cur.execute("ALTER TABLE processing_jobs ENABLE TRIGGER trg_protect_processing_jobs_delete;")

                    cur.execute("DELETE FROM policy_envelopes WHERE numero_poliza = %s;", (test_pol_num,))
                conn.commit()

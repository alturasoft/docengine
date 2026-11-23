"""Unit tests for async extraction concurrency guardrails and stale job recovery."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

from app.api.v1 import extraction as extraction_api
from app.infrastructure.database.pg_rag_repository import PgRagRepository


def test_async_extraction_semaphore_serializes_execution(tmp_path: Path) -> None:
    """Ensure concurrent _run_async_extraction calls do not exceed semaphore limit."""
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_extract(_request):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1
        result = MagicMock()
        result.is_successful = True
        result.metadata = MagicMock()
        return result

    extraction_svc = MagicMock()
    extraction_svc.extract_document.side_effect = fake_extract

    rag_svc = MagicMock()
    report = MagicMock()
    report.policy_id = "pol-1"
    report.errors = []
    report.skipped_duplicate = False
    report.job_id = "job-1"
    report.chunks_created = 1
    report.envelope_id = None
    report.tipo_documento = None
    rag_svc.process_extraction_result.return_value = report

    rag_repo = MagicMock()

    original_sem = extraction_api._ASYNC_EXTRACTION_SEMAPHORE
    extraction_api._ASYNC_EXTRACTION_SEMAPHORE = threading.BoundedSemaphore(1)
    try:
        threads = []
        for idx in range(3):
            f = tmp_path / f"doc_{idx}.pdf"
            f.write_bytes(b"%PDF-1.4")
            t = threading.Thread(
                target=extraction_api._run_async_extraction,
                kwargs={
                    "job_id": f"job-{idx}",
                    "temp_path": f,
                    "filename": f"doc_{idx}.pdf",
                    "id_cliente_clean": "123",
                    "sigla_clean": "CRI",
                    "num_poliza_clean": None,
                    "ramo_clean": None,
                    "tipo_doc_clean": None,
                    "extraction_service": extraction_svc,
                    "rag_service": rag_svc,
                    "rag_repo": rag_repo,
                },
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=5)
    finally:
        extraction_api._ASYNC_EXTRACTION_SEMAPHORE = original_sem

    assert max_active == 1
    assert rag_repo.update_job.call_count == 3


def test_fail_stale_processing_jobs_updates_and_returns_count() -> None:
    """Verify PgRagRepository.fail_stale_processing_jobs executes UPDATE and commits."""
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 7
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = False

    mock_db = MagicMock()

    @contextmanager
    def _fake_conn():
        yield mock_conn

    mock_db.get_connection = _fake_conn

    repo = PgRagRepository(mock_db)
    count = repo.fail_stale_processing_jobs(max_age_minutes=30, reason="worker crashed")

    assert count == 7
    mock_cursor.execute.assert_called_once()
    sql, params = mock_cursor.execute.call_args[0]
    assert "UPDATE processing_jobs" in sql
    assert "status = 'FAILED'" in sql
    assert params == ("worker crashed", 30)
    mock_conn.commit.assert_called_once()

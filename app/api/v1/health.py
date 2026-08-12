"""DocEngine — Health, Version and Metrics Endpoints."""

from __future__ import annotations

import sys
import time

from fastapi import APIRouter, Query

import json
from pathlib import Path
from fastapi import APIRouter, Query, Request

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

try:
    import docling
    _DOCLING_VERSION = getattr(docling, "__version__", "unknown")
except (ImportError, AttributeError):
    _DOCLING_VERSION = "unknown"

from app.api.v1.schemas import HealthResponse, MetricsResponse, VersionResponse
from app.config.settings import AppSettings, get_settings

router = APIRouter(tags=["System"])

_METRICS_FILE = Path("outputs") / "metrics.json"

def _load_metrics() -> dict:
    """Load persistent metrics from disk if available."""
    default_metrics = {
        "total_extractions": 0,
        "successful_extractions": 0,
        "failed_extractions": 0,
        "total_pages_processed": 0,
        "total_tables_detected": 0,
        "extraction_times": [],
    }
    if _METRICS_FILE.exists():
        try:
            data = json.loads(_METRICS_FILE.read_text(encoding="utf-8"))
            for key in default_metrics:
                if key in data:
                    default_metrics[key] = data[key]
        except Exception:
            pass
    return default_metrics

def _save_metrics() -> None:
    """Save persistent metrics to disk."""
    try:
        _METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _METRICS_FILE.write_text(json.dumps(_METRICS), encoding="utf-8")
    except Exception:
        pass

_METRICS: dict = _load_metrics()
_START_TIME = time.time()


def record_extraction(
    status: str,
    pages: int,
    tables: int,
    duration_seconds: float,
) -> None:
    """Update in-memory metrics after an extraction.

    Args:
        status: 'success' | 'partial' | 'failed'.
        pages: Number of pages extracted.
        tables: Number of tables detected.
        duration_seconds: Duration of extraction.
    """
    _METRICS["total_extractions"] += 1
    if status in ("success", "partial"):
        _METRICS["successful_extractions"] += 1
    else:
        _METRICS["failed_extractions"] += 1
    _METRICS["total_pages_processed"] += pages
    _METRICS["total_tables_detected"] += tables
    _METRICS["extraction_times"].append(duration_seconds)
    # Keep only last 1000 measurements to avoid memory growth
    if len(_METRICS["extraction_times"]) > 1000:
        _METRICS["extraction_times"] = _METRICS["extraction_times"][-1000:]
    _save_metrics()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns service health status.",
)
def health_check() -> HealthResponse:
    """Return service health status."""
    settings: AppSettings = get_settings()
    return HealthResponse(
        status="ok",
        environment=settings.environment,
        uptime_seconds=round(time.time() - _START_TIME, 1),
    )


@router.get(
    "/version",
    response_model=VersionResponse,
    summary="Version information",
    description="Returns versions of the service and Docling.",
)
def get_version() -> VersionResponse:
    """Return version information."""
    settings: AppSettings = get_settings()
    return VersionResponse(
        app_version=settings.app_version,
        docling_version=_DOCLING_VERSION,
        python_version=sys.version.split()[0],
    )


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Service metrics",
    description="Returns aggregate extraction statistics.",
)
def get_metrics(request: Request) -> MetricsResponse:
    """Return aggregate extraction metrics, querying PostgreSQL if available."""
    total_ext = _METRICS["total_extractions"]
    succ_ext = _METRICS["successful_extractions"]
    fail_ext = _METRICS["failed_extractions"]
    tables_det = _METRICS["total_tables_detected"]

    # If PostgreSQL repository is accessible via RAG service, sync metrics with DB tables
    if request and hasattr(request.app.state, "rag_service") and request.app.state.rag_service:
        try:
            repo = request.app.state.rag_service._repo
            with repo._db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM processing_jobs;")
                    db_jobs_total = cur.fetchone()[0] or 0
                    cur.execute("SELECT COUNT(*) FROM processing_jobs WHERE status IN ('COMPLETED', 'SKIPPED');")
                    db_jobs_succ = cur.fetchone()[0] or 0
                    cur.execute("SELECT COUNT(*) FROM processing_jobs WHERE status = 'FAILED';")
                    db_jobs_fail = cur.fetchone()[0] or 0
                    cur.execute("SELECT COUNT(*) FROM policies;")
                    db_policies = cur.fetchone()[0] or 0

                    if db_jobs_total > 0 or db_policies > 0:
                        total_ext = max(db_jobs_total, db_policies, total_ext)
                        succ_ext = max(db_jobs_succ, db_policies, succ_ext)
                        fail_ext = db_jobs_fail
        except Exception:
            pass

    times = _METRICS["extraction_times"]
    avg_time = sum(times) / len(times) if times else 0.0
    mem_mb = 0.0
    if _PSUTIL_AVAILABLE:
        try:
            mem_mb = psutil.Process().memory_info().rss / 1_048_576
        except Exception:
            pass

    return MetricsResponse(
        total_extractions=total_ext,
        successful_extractions=succ_ext,
        failed_extractions=fail_ext,
        total_pages_processed=_METRICS["total_pages_processed"],
        total_tables_detected=tables_det,
        avg_extraction_time_seconds=round(avg_time, 3),
        memory_usage_mb=round(mem_mb, 1),
    )


@router.get(
    "/logs",
    summary="Get process logs",
    description="Returns recent server log entries from in-memory circular buffer.",
)
def get_logs(
    lines: int = Query(default=200, ge=1, le=1000, description="Number of log lines to retrieve"),
    level: str | None = Query(default=None, description="Optional level filter (INFO, WARNING, ERROR)"),
) -> dict:
    """Return recent log entries from the server process."""
    from app.infrastructure.logging.logger import get_recent_logs  # noqa: PLC0415

    logs = get_recent_logs(limit=lines, level=level)
    return {
        "count": len(logs),
        "logs": logs,
    }


@router.post(
    "/logs/clear",
    summary="Clear process logs",
    description="Clears all recent server log entries from in-memory circular buffer.",
)
def clear_logs() -> dict:
    """Clear server log buffer."""
    from app.infrastructure.logging.logger import clear_log_buffer  # noqa: PLC0415

    clear_log_buffer()
    return {"status": "ok", "message": "Log buffer cleared"}



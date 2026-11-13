"""DocEngine — Health, Version and Metrics Endpoints."""

from __future__ import annotations

import sys
import time

from fastapi import APIRouter, Query

import json
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Request, status

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
    summary="Verificación de estado del servicio",
    description="Retorna el estado de operatividad del servicio, entorno de ejecución y tiempo de actividad acumulado (uptime).",
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
    summary="Información de versiones",
    description="Retorna las versiones instaladas de la aplicación DocEngine, del motor Docling y de Python.",
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
    summary="Métricas de extracción",
    description="Retorna estadísticas agregadas e inmutables de extracción (documentos procesados, exitosos, fallidos, páginas, tablas, sobres, chunks y tiempos), sincronizadas con la base de datos.",
)
def get_metrics(request: Request) -> MetricsResponse:
    """Return aggregate extraction metrics, querying PostgreSQL immutable tables if available."""
    total_ext = _METRICS["total_extractions"]
    succ_ext = _METRICS["successful_extractions"]
    fail_ext = _METRICS["failed_extractions"]
    pages_proc = _METRICS["total_pages_processed"]
    tables_det = _METRICS["total_tables_detected"]
    total_envelopes = 0
    active_documents = 0
    total_chunks = 0
    skipped_duplicates = 0
    total_clients = 0
    db_avg_time = 0.0

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
                    cur.execute("SELECT COUNT(*) FROM processing_jobs WHERE status = 'SKIPPED';")
                    skipped_duplicates = cur.fetchone()[0] or 0
                    cur.execute("SELECT COUNT(*) FROM policies;")
                    db_policies = cur.fetchone()[0] or 0
                    active_documents = db_policies

                    # Query immutable historical stats from policy_processing_stats
                    db_stats_count = 0
                    db_pages = 0
                    db_tables = 0
                    try:
                        cur.execute("SAVEPOINT sp_metrics_stats;")
                        cur.execute(
                            """
                            SELECT
                                COUNT(*),
                                COALESCE(SUM(total_pages), 0),
                                COALESCE(SUM(tables_detected), 0),
                                COALESCE(SUM(total_chunks), 0),
                                COALESCE(AVG(NULLIF(extraction_time_seconds, 0)), 0)
                            FROM policy_processing_stats;
                            """
                        )
                        stats_row = cur.fetchone()
                        if stats_row and len(stats_row) >= 5:
                            db_stats_count = int(stats_row[0] or 0)
                            db_pages = int(stats_row[1] or 0)
                            db_tables = int(stats_row[2] or 0)
                            total_chunks = int(stats_row[3] or 0)
                            db_avg_time = float(stats_row[4] or 0.0)
                        cur.execute("RELEASE SAVEPOINT sp_metrics_stats;")
                    except Exception:
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT sp_metrics_stats;")
                        except Exception:
                            pass

                    # Query envelope and client counts
                    try:
                        cur.execute("SAVEPOINT sp_metrics_env;")
                        cur.execute(
                            """
                            SELECT
                                COUNT(*),
                                COUNT(DISTINCT NULLIF(TRIM(id_cliente), ''))
                            FROM policy_envelopes;
                            """
                        )
                        env_row = cur.fetchone()
                        if env_row and len(env_row) >= 2:
                            total_envelopes = int(env_row[0] or 0)
                            total_clients = int(env_row[1] or 0)
                        cur.execute("RELEASE SAVEPOINT sp_metrics_env;")
                    except Exception:
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT sp_metrics_env;")
                        except Exception:
                            pass

                    # Query immutable audit ledger for historical envelope and extraction high-water marks
                    try:
                        cur.execute("SAVEPOINT sp_metrics_ledger;")
                        cur.execute(
                            """
                            SELECT
                                COUNT(DISTINCT envelope_id) FILTER (WHERE envelope_id IS NOT NULL),
                                COUNT(DISTINCT NULLIF(TRIM(id_cliente), '')),
                                COUNT(*) FILTER (WHERE event_type = 'DOCUMENT_EXTRACTED'),
                                COALESCE(SUM(pages_count) FILTER (WHERE event_type = 'DOCUMENT_EXTRACTED'), 0),
                                COALESCE(SUM(tables_count) FILTER (WHERE event_type = 'DOCUMENT_EXTRACTED'), 0)
                            FROM audit_metrics_ledger;
                            """
                        )
                        ledger_row = cur.fetchone()
                        if ledger_row and len(ledger_row) >= 5:
                            total_envelopes = max(total_envelopes, int(ledger_row[0] or 0))
                            total_clients = max(total_clients, int(ledger_row[1] or 0))
                            db_stats_count = max(db_stats_count, int(ledger_row[2] or 0))
                            db_pages = max(db_pages, int(ledger_row[3] or 0))
                            db_tables = max(db_tables, int(ledger_row[4] or 0))
                        cur.execute("RELEASE SAVEPOINT sp_metrics_ledger;")
                    except Exception:
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT sp_metrics_ledger;")
                        except Exception:
                            pass

                    # Monotonic high-water synchronization (never decreases even if policies are deleted)
                    succ_ext = max(succ_ext, db_jobs_succ, db_policies, db_stats_count)
                    fail_ext = max(fail_ext, db_jobs_fail)
                    total_ext = max(total_ext, db_jobs_total, succ_ext + fail_ext)
                    pages_proc = max(pages_proc, db_pages)
                    tables_det = max(tables_det, db_tables)

                    # Persist high-water marks to local cache file as well
                    if (
                        total_ext > _METRICS["total_extractions"]
                        or succ_ext > _METRICS["successful_extractions"]
                        or pages_proc > _METRICS["total_pages_processed"]
                        or tables_det > _METRICS["total_tables_detected"]
                    ):
                        _METRICS["total_extractions"] = total_ext
                        _METRICS["successful_extractions"] = succ_ext
                        _METRICS["failed_extractions"] = fail_ext
                        _METRICS["total_pages_processed"] = pages_proc
                        _METRICS["total_tables_detected"] = tables_det
                        _save_metrics()
        except Exception:
            pass

    times = _METRICS["extraction_times"]
    avg_time = sum(times) / len(times) if times else db_avg_time
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
        total_pages_processed=pages_proc,
        total_tables_detected=tables_det,
        avg_extraction_time_seconds=round(avg_time, 3),
        memory_usage_mb=round(mem_mb, 1),
        total_envelopes=total_envelopes,
        active_documents=active_documents,
        total_chunks_indexed=total_chunks,
        skipped_duplicates=skipped_duplicates,
        total_clients=total_clients,
        immutable_mode=True,
    )



@router.get(
    "/logs",
    summary="Consultar registros del proceso",
    description="Retorna las entradas recientes de log desde el búfer circular en memoria del servidor.",
)
def get_logs(
    lines: int = Query(default=200, ge=1, le=1000, description="Cantidad de líneas de log a recuperar (1 a 1000)"),
    level: str | None = Query(default=None, description="Filtro opcional por nivel de severidad (INFO, WARNING, ERROR)"),
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
    summary="Limpiar registros del proceso",
    description="Limpia todas las entradas de log almacenadas en el búfer circular en memoria del servidor.",
)
def clear_logs() -> dict:
    """Clear server log buffer."""
    from app.infrastructure.logging.logger import clear_log_buffer  # noqa: PLC0415

    clear_log_buffer()
    return {"status": "ok", "message": "Log buffer cleared"}


@router.post(
    "/metrics/reset",
    summary="Restablecer métricas del servicio (Bloqueado en modo inmutable)",
    description="Operación bloqueada por política de auditoría inmutable (WORM). Las estadísticas e indicadores históricos no pueden ser eliminados ni reiniciados.",
)
def reset_metrics() -> dict:
    """Block reset of aggregate extraction metrics in immutable production mode."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Operación prohibida: Las estadísticas y registros de seguimiento/auditoría "
            "son inmutables y no pueden ser reiniciados ni eliminados."
        ),
    )




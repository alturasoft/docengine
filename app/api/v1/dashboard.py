"""DocEngine — Dashboard Control & Audit API Endpoints (v1).

[ADITIVO] Endpoints de solo lectura para alimentar el Dashboard de Control de
Procesamiento de Pólizas, Telemetría y Auditoría Inmutable (WORM).

GET /api/v1/dashboard/overview          — KPIs globales, series diarias/semanales/mensuales, desgloses y salud.
GET /api/v1/dashboard/audit-ledger      — Libro mayor inmutable (audit_metrics_ledger) paginado.
GET /api/v1/dashboard/processing-stats  — Telemetría detallada por documento (policy_processing_stats).
GET /api/v1/dashboard/jobs-errors       — Trabajos y errores detectados (processing_jobs).
GET /api/v1/dashboard/export.csv        — Exportación CSV filtrada de auditoría, telemetría o jobs.
"""

from __future__ import annotations

import csv
import io
import sys
import time
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.security import require_role
from app.api.v1 import health as health_module
from app.api.v1.dashboard_schemas import (
    AuditLedgerItem,
    AuditLedgerPageResponse,
    DashboardOverviewResponse,
    JobErrorItem,
    JobsErrorsPageResponse,
    ProcessingStatItem,
    ProcessingStatsPageResponse,
)
from app.config.settings import get_settings
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_audit_dashboard_repository import (
    PgAuditDashboardRepository,
)
from app.infrastructure.logging.logger import get_logger, get_recent_logs

try:
    import psutil

    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

logger = get_logger(__name__)
router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def get_dashboard_repo(request: Request) -> PgAuditDashboardRepository:
    """Dependency to retrieve or instantiate PgAuditDashboardRepository reusing existing DB pool."""
    cached = getattr(request.app.state, "dashboard_repo", None)
    if cached is not None:
        return cached

    rag_svc = getattr(request.app.state, "rag_service", None)
    if rag_svc and getattr(rag_svc, "_repo", None) is not None and getattr(rag_svc._repo, "_db", None) is not None:
        repo = PgAuditDashboardRepository(rag_svc._repo._db)
        request.app.state.dashboard_repo = repo
        return repo

    settings = getattr(request.app.state, "settings", None) or get_settings()
    db_manager = DatabaseManager(settings.database)
    repo = PgAuditDashboardRepository(db_manager)
    request.app.state.dashboard_repo = repo
    return repo


DashboardRepoDep = Annotated[PgAuditDashboardRepository, Depends(get_dashboard_repo)]


def _collect_system_health(request: Request) -> dict[str, Any]:
    """Build real-time server process & log buffer snapshot."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    mem_mb = 0.0
    if _PSUTIL_AVAILABLE:
        try:
            mem_mb = psutil.Process().memory_info().rss / 1_048_576
        except Exception:
            pass

    recent_logs = get_recent_logs(limit=1000)
    err_cnt = sum(1 for line in recent_logs if "[ERROR]" in line.upper() or " ERROR " in line.upper() or "LEVEL=ERROR" in line.upper())
    warn_cnt = sum(1 for line in recent_logs if "[WARNING]" in line.upper() or " WARNING " in line.upper() or "[WARN]" in line.upper())

    return {
        "status": "ok",
        "environment": settings.environment,
        "uptime_seconds": round(time.time() - health_module._START_TIME, 1),
        "memory_usage_mb": round(mem_mb, 1),
        "app_version": settings.app_version,
        "docling_version": health_module._DOCLING_VERSION,
        "python_version": sys.version.split()[0],
        "log_buffer_count": len(recent_logs),
        "log_error_count": err_cnt,
        "log_warning_count": warn_cnt,
    }


@router.get(
    "/overview",
    response_model=DashboardOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Resumen ejecutivo, series temporales y analítica de auditoría",
    description=(
        "Retorna todas las métricas de las estructuras de auditoría (audit_metrics_ledger, "
        "policy_processing_stats, processing_jobs, sobres e inventario) con soporte de series "
        "diarias, semanales y mensuales y filtros multidimensionales."
    ),
    dependencies=[Depends(require_role("readonly"))],
)
def get_dashboard_overview(
    request: Request,
    repo: DashboardRepoDep,
    granularity: Literal["daily", "weekly", "monthly"] = Query(
        default="daily", description="Granularidad de la serie temporal: daily | weekly | monthly"
    ),
    date_from: str | None = Query(default=None, description="Fecha inicial (YYYY-MM-DD)"),
    date_to: str | None = Query(default=None, description="Fecha final (YYYY-MM-DD)"),
    company_sigla: str | None = Query(default=None, description="Filtro por sigla de aseguradora"),
    ramo: str | None = Query(default=None, description="Filtro por ramo de seguro"),
    tipo_documento: str | None = Query(default=None, description="Filtro por tipo de documento"),
    file_type: str | None = Query(default=None, description="Filtro por tipología PDF (DIGITAL, SCANNED, HYBRID, UNKNOWN)"),
) -> DashboardOverviewResponse:
    """Return consolidated dashboard overview metrics and breakdowns."""
    try:
        data = repo.get_dashboard_overview(
            granularity=granularity,
            date_from=date_from,
            date_to=date_to,
            company_sigla=company_sigla,
            ramo=ramo,
            tipo_documento=tipo_documento,
            file_type=file_type,
        )
        # Inject local monotonic high-water marks from health module
        hw = getattr(health_module, "_METRICS", {}) or {}
        data["kpis"]["high_water_extractions"] = int(hw.get("total_extractions", 0) or 0)
        data["kpis"]["high_water_pages"] = int(hw.get("total_pages_processed", 0) or 0)
        data["kpis"]["high_water_tables"] = int(hw.get("total_tables_detected", 0) or 0)
        data["system_health"] = _collect_system_health(request)
        return DashboardOverviewResponse(**data)
    except Exception as exc:
        logger.error("Error generating dashboard overview", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error generando resumen de dashboard: {exc}",
        ) from exc


@router.get(
    "/audit-ledger",
    response_model=AuditLedgerPageResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar eventos del libro mayor inmutable (audit_metrics_ledger)",
    description="Retorna registros paginados y filtrables del libro mayor inmutable WORM de auditoría.",
    dependencies=[Depends(require_role("readonly"))],
)
def get_audit_ledger(
    repo: DashboardRepoDep,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    company_sigla: str | None = Query(default=None),
    ramo: str | None = Query(default=None),
    tipo_documento: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    search: str | None = Query(default=None, description="Búsqueda por archivo, póliza, cliente o hash"),
) -> AuditLedgerPageResponse:
    """List immutable audit ledger events with pagination and filters."""
    try:
        items, total = repo.list_audit_ledger(
            limit=limit,
            offset=offset,
            date_from=date_from,
            date_to=date_to,
            company_sigla=company_sigla,
            ramo=ramo,
            tipo_documento=tipo_documento,
            event_type=event_type,
            search=search,
        )
        return AuditLedgerPageResponse(
            total=total,
            limit=limit,
            offset=offset,
            items=[AuditLedgerItem(**item) for item in items],
        )
    except Exception as exc:
        logger.error("Error listing audit ledger", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error consultando libro mayor de auditoría: {exc}",
        ) from exc


@router.get(
    "/processing-stats",
    response_model=ProcessingStatsPageResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar telemetría detallada por documento (policy_processing_stats)",
    description="Retorna tiempos por etapa, consumo OpenAI, chunks jerárquicos, OCR y memoria RAM por documento.",
    dependencies=[Depends(require_role("readonly"))],
)
def get_processing_stats(
    repo: DashboardRepoDep,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    company_sigla: str | None = Query(default=None),
    ramo: str | None = Query(default=None),
    tipo_documento: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
) -> ProcessingStatsPageResponse:
    """List per-document processing telemetry with pagination and filters."""
    try:
        items, total = repo.list_processing_stats(
            limit=limit,
            offset=offset,
            date_from=date_from,
            date_to=date_to,
            company_sigla=company_sigla,
            ramo=ramo,
            tipo_documento=tipo_documento,
            file_type=file_type,
            search=search,
        )
        return ProcessingStatsPageResponse(
            total=total,
            limit=limit,
            offset=offset,
            items=[ProcessingStatItem(**item) for item in items],
        )
    except Exception as exc:
        logger.error("Error listing processing stats", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error consultando telemetría de procesamiento: {exc}",
        ) from exc


@router.get(
    "/jobs-errors",
    response_model=JobsErrorsPageResponse,
    status_code=status.HTTP_200_OK,
    summary="Consultar trabajos y errores detectados (processing_jobs)",
    description="Retorna el historial paginado de trabajos de extracción incluyendo trazas de error para jobs fallidos.",
    dependencies=[Depends(require_role("readonly"))],
)
def get_jobs_errors(
    repo: DashboardRepoDep,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    company_sigla: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status", description="Filtro: FAILED, COMPLETED, SKIPPED, PROCESSING, PENDING"),
    search: str | None = Query(default=None),
) -> JobsErrorsPageResponse:
    """List processing jobs and error details with status summary counts."""
    try:
        items, total, status_counts = repo.list_jobs_and_errors(
            limit=limit,
            offset=offset,
            date_from=date_from,
            date_to=date_to,
            company_sigla=company_sigla,
            status_filter=status_filter,
            search=search,
        )
        return JobsErrorsPageResponse(
            total=total,
            limit=limit,
            offset=offset,
            status_counts=status_counts,
            items=[JobErrorItem(**item) for item in items],
        )
    except Exception as exc:
        logger.error("Error listing processing jobs", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error consultando trabajos y errores: {exc}",
        ) from exc


@router.get(
    "/export.csv",
    summary="Exportar registros de auditoría o telemetría en formato CSV",
    description="Genera una descarga CSV compatible con Excel (UTF-8 con BOM) aplicando los filtros activos del dashboard.",
    dependencies=[Depends(require_role("readonly"))],
)
def export_dashboard_csv(
    repo: DashboardRepoDep,
    dataset: Literal["ledger", "stats", "jobs"] = Query(default="ledger", description="Conjunto de datos a exportar"),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    company_sigla: str | None = Query(default=None),
    ramo: str | None = Query(default=None),
    tipo_documento: str | None = Query(default=None),
    file_type: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
) -> Response:
    """Export filtered audit ledger, processing stats, or jobs/errors to CSV."""
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    try:
        if dataset == "ledger":
            items, _ = repo.list_audit_ledger(
                limit=5000,
                offset=0,
                date_from=date_from,
                date_to=date_to,
                company_sigla=company_sigla,
                ramo=ramo,
                tipo_documento=tipo_documento,
                event_type=event_type,
                search=search,
            )
            writer.writerow([
                "Fecha", "Tipo Evento", "Aseguradora", "Ramo", "N° Poliza",
                "Tipo Documento", "ID Cliente", "Nombre Cliente", "Archivo",
                "Paginas", "Tablas", "Chunks", "Tamano Bytes",
                "Duracion (s)", "Tokens OpenAI", "Costo USD", "Hash SHA-256", "Event ID",
            ])
            for row in items:
                writer.writerow([
                    row.get("created_at", ""),
                    row.get("event_type", ""),
                    row.get("company_sigla", ""),
                    row.get("ramo", ""),
                    row.get("numero_poliza", ""),
                    row.get("tipo_documento", ""),
                    row.get("id_cliente", ""),
                    row.get("nombre_cliente", ""),
                    row.get("file_name", ""),
                    row.get("pages_count", 0),
                    row.get("tables_count", 0),
                    row.get("chunks_count", 0),
                    row.get("file_size_bytes", 0),
                    f"{row.get('duration_seconds', 0.0):.3f}",
                    row.get("openai_tokens", 0),
                    f"{row.get('openai_cost_usd', 0.0):.5f}",
                    row.get("file_hash", ""),
                    row.get("event_id", ""),
                ])
        elif dataset == "stats":
            items, _ = repo.list_processing_stats(
                limit=5000,
                offset=0,
                date_from=date_from,
                date_to=date_to,
                company_sigla=company_sigla,
                ramo=ramo,
                tipo_documento=tipo_documento,
                file_type=file_type,
                search=search,
            )
            writer.writerow([
                "Fecha", "Aseguradora", "N° Poliza", "Archivo", "Tipo PDF",
                "OCR Aplicado", "Ratio Escaneo", "Paginas", "Tablas", "Coberturas",
                "T. Extraccion (s)", "T/Pagina (s)", "T. Chunking (s)",
                "T. Embeddings (s)", "T. OpenAI (s)", "T. Pipeline (s)",
                "Chunks Totales", "Chunks Padre", "Chunks Hijo",
                "Prompt Tokens", "Completion Tokens", "Total Tokens", "Costo USD",
                "Pico RAM (MB)", "Stat ID",
            ])
            for row in items:
                writer.writerow([
                    row.get("created_at", ""),
                    row.get("company_sigla", ""),
                    row.get("policy_number", ""),
                    row.get("file_name", ""),
                    row.get("file_type", ""),
                    "SI" if row.get("ocr_applied") else "NO",
                    row.get("scanned_page_ratio") if row.get("scanned_page_ratio") is not None else "",
                    row.get("total_pages", 0),
                    row.get("tables_detected", 0),
                    row.get("coberturas_extracted_count", 0),
                    f"{row.get('extraction_time_seconds', 0.0):.3f}",
                    f"{row.get('time_per_page_seconds', 0.0):.3f}",
                    f"{row.get('chunking_time_seconds', 0.0):.3f}",
                    f"{row.get('embedding_time_seconds', 0.0):.3f}",
                    f"{row.get('openai_time_seconds', 0.0):.3f}",
                    f"{row.get('total_pipeline_time_seconds', 0.0):.3f}",
                    row.get("total_chunks", 0),
                    row.get("parent_chunks", 0),
                    row.get("child_chunks", 0),
                    row.get("openai_prompt_tokens", 0),
                    row.get("openai_completion_tokens", 0),
                    row.get("openai_total_tokens", 0),
                    f"{row.get('openai_estimated_cost_usd', 0.0):.5f}",
                    f"{row.get('memory_peak_mb', 0.0):.2f}" if row.get("memory_peak_mb") is not None else "",
                    row.get("stat_id", ""),
                ])
        else:
            items, _, _ = repo.list_jobs_and_errors(
                limit=5000,
                offset=0,
                date_from=date_from,
                date_to=date_to,
                company_sigla=company_sigla,
                status_filter=status_filter,
                search=search,
            )
            writer.writerow([
                "Job ID", "Estado", "Archivo", "Aseguradora", "N° Poliza",
                "Policy ID", "Mensaje de Error", "Duracion (s)", "Creado", "Actualizado",
            ])
            for row in items:
                writer.writerow([
                    row.get("job_id", ""),
                    row.get("status", ""),
                    row.get("file_name", ""),
                    row.get("company_sigla", ""),
                    row.get("numero_poliza", ""),
                    row.get("policy_id", ""),
                    row.get("error_message", ""),
                    row.get("duration_seconds") if row.get("duration_seconds") is not None else "",
                    row.get("created_at", ""),
                    row.get("updated_at", ""),
                ])

        csv_data = output.getvalue()
        filename = f"docengine_auditoria_{dataset}.csv"
        return Response(
            content=csv_data.encode("utf-8-sig"),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Type": "text/csv; charset=utf-8",
            },
        )
    except Exception as exc:
        logger.error("Error exporting dashboard CSV", dataset=dataset, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error exportando CSV de auditoría: {exc}",
        ) from exc


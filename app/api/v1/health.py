"""DocEngine — Health, Version and Metrics Endpoints."""

from __future__ import annotations

import sys
import time

from fastapi import APIRouter, Query

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

try:
    import docling
    _DOCLING_VERSION = docling.__version__
except AttributeError:
    _DOCLING_VERSION = "unknown"

from app.api.v1.schemas import HealthResponse, MetricsResponse, VersionResponse
from app.config.settings import AppSettings, get_settings

router = APIRouter(tags=["System"])

# Simple in-memory counters (for production use a proper metrics backend)
_METRICS: dict = {
    "total_extractions": 0,
    "successful_extractions": 0,
    "failed_extractions": 0,
    "total_pages_processed": 0,
    "total_tables_detected": 0,
    "extraction_times": [],
}
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
def get_metrics() -> MetricsResponse:
    """Return aggregate extraction metrics."""
    times = _METRICS["extraction_times"]
    avg_time = sum(times) / len(times) if times else 0.0
    mem_mb = 0.0
    if _PSUTIL_AVAILABLE:
        try:
            mem_mb = psutil.Process().memory_info().rss / 1_048_576
        except Exception:
            pass

    return MetricsResponse(
        total_extractions=_METRICS["total_extractions"],
        successful_extractions=_METRICS["successful_extractions"],
        failed_extractions=_METRICS["failed_extractions"],
        total_pages_processed=_METRICS["total_pages_processed"],
        total_tables_detected=_METRICS["total_tables_detected"],
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


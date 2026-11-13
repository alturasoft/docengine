"""DocEngine — Dashboard API Pydantic Schemas (v1).

[ADITIVO] Esquemas de respuesta de solo lectura para el Dashboard de Control de
Procesamiento de Pólizas, Telemetría y Auditoría Inmutable (WORM).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DashboardKpiSummary(BaseModel):
    """Métricas consolidadas globales o filtradas de auditoría y telemetría."""

    # Inventario y Ciclo de Vida
    documents_extracted_total: int = Field(default=0, description="Total de eventos DOCUMENT_EXTRACTED en el libro mayor inmutable")
    active_documents: int = Field(default=0, description="Documentos activos actuales en la tabla policies")
    documents_deleted_total: int = Field(default=0, description="Total histórico de eventos DOCUMENT_DELETED")
    total_envelopes_historical: int = Field(default=0, description="Total histórico de sobres digitales creados")
    active_envelopes: int = Field(default=0, description="Sobres digitales activos actuales en policy_envelopes")
    envelopes_deleted_total: int = Field(default=0, description="Total histórico de eventos ENVELOPE_DELETED")
    unique_clients: int = Field(default=0, description="Clientes únicos identificados por Carnet/NIT")

    # Volumen de Contenido y RAG
    total_pages_processed: int = Field(default=0, description="Total de páginas PDF procesadas")
    total_tables_detected: int = Field(default=0, description="Total de tablas detectadas y estructuradas")
    total_coberturas_extracted: int = Field(default=0, description="Total de coberturas atomizadas")
    total_chunks_created: int = Field(default=0, description="Total de fragmentos semánticos generados")
    parent_chunks_count: int = Field(default=0, description="Fragmentos padre (jerarquía RAG)")
    child_chunks_count: int = Field(default=0, description="Fragmentos hijo (jerarquía RAG)")
    total_volume_bytes: int = Field(default=0, description="Volumen acumulado de texto/datos procesados en bytes")

    # Control de Trabajos y Errores
    jobs_total: int = Field(default=0, description="Total de trabajos registrados en processing_jobs")
    jobs_completed: int = Field(default=0, description="Trabajos finalizados exitosamente (COMPLETED)")
    jobs_failed: int = Field(default=0, description="Trabajos fallidos (FAILED)")
    jobs_skipped: int = Field(default=0, description="Trabajos omitidos por duplicidad SHA-256 (SKIPPED)")
    jobs_processing: int = Field(default=0, description="Trabajos actualmente en ejecución (PROCESSING)")
    jobs_pending: int = Field(default=0, description="Trabajos en cola (PENDING)")
    success_rate_pct: float = Field(default=100.0, description="Tasa de éxito sobre trabajos finalizados (%)")
    error_rate_pct: float = Field(default=0.0, description="Tasa de fallo sobre trabajos finalizados (%)")
    failure_events_ledger: int = Field(default=0, description="Eventos DOCUMENT_EXTRACTION_FAILED en ledger")
    duplicate_events_ledger: int = Field(default=0, description="Eventos DOCUMENT_SKIPPED_DUPLICATE en ledger")

    # Rendimiento por Etapa y Hardware
    avg_extraction_time_seconds: float = Field(default=0.0, description="Tiempo promedio de extracción Docling (s)")
    avg_time_per_page_seconds: float = Field(default=0.0, description="Tiempo promedio por página (s)")
    avg_chunking_time_seconds: float = Field(default=0.0, description="Tiempo promedio de chunking (s)")
    avg_embedding_time_seconds: float = Field(default=0.0, description="Tiempo promedio de embeddings BGE-M3 (s)")
    avg_openai_time_seconds: float = Field(default=0.0, description="Tiempo promedio de extracción LLM OpenAI (s)")
    avg_pipeline_time_seconds: float = Field(default=0.0, description="Tiempo promedio del pipeline RAG (s)")
    avg_end_to_end_seconds: float = Field(default=0.0, description="Tiempo promedio total (Extracción + RAG) (s)")
    p95_pipeline_time_seconds: float = Field(default=0.0, description="Percentil 95 de duración de pipeline (s)")
    max_memory_peak_mb: float = Field(default=0.0, description="Pico máximo de memoria RAM registrado (MB)")
    avg_memory_peak_mb: float = Field(default=0.0, description="Promedio de pico de RAM por documento (MB)")

    # Consumo OpenAI
    openai_prompt_tokens: int = Field(default=0, description="Tokens de entrada consumidos en OpenAI")
    openai_completion_tokens: int = Field(default=0, description="Tokens de salida generados en OpenAI")
    openai_total_tokens: int = Field(default=0, description="Total de tokens OpenAI consumidos")
    openai_estimated_cost_usd: float = Field(default=0.0, description="Costo estimado acumulado en USD")

    # OCR y Tipología
    ocr_applied_count: int = Field(default=0, description="Documentos procesados con OCR aplicado")
    ocr_rate_pct: float = Field(default=0.0, description="Porcentaje de documentos con OCR (%)")
    avg_scanned_page_ratio: float = Field(default=0.0, description="Proporción promedio de páginas escaneadas (0.0-1.0)")

    # Extractores Especializados
    fleet_vehicles_count: int = Field(default=0, description="Vehículos extraídos en pólizas de flota")
    insured_persons_count: int = Field(default=0, description="Asegurados extraídos en pólizas colectivas")
    section_summaries_count: int = Field(default=0, description="Resúmenes estructurales de pólizas grandes")

    # High-Water Marks locales (metrics.json)
    high_water_extractions: int = Field(default=0, description="Marcador monotónico histórico de extracciones")
    high_water_pages: int = Field(default=0, description="Marcador monotónico histórico de páginas")
    high_water_tables: int = Field(default=0, description="Marcador monotónico histórico de tablas")


class PeriodSnapshot(BaseModel):
    """Comparativa rápida de procesamiento Diario (Hoy) y Semanal (Últimos 7 días)."""

    today_documents: int = 0
    today_pages: int = 0
    today_errors: int = 0
    today_envelopes: int = 0
    today_cost_usd: float = 0.0
    week_documents: int = 0
    week_pages: int = 0
    week_errors: int = 0
    week_envelopes: int = 0
    week_cost_usd: float = 0.0
    prev_week_documents: int = 0
    week_growth_pct: float | None = None


class TimeSeriesPoint(BaseModel):
    """Punto de serie temporal (diario, semanal o mensual)."""

    period: str
    period_label: str
    documents_extracted: int = 0
    duplicates_skipped: int = 0
    jobs_completed: int = 0
    jobs_failed: int = 0
    jobs_skipped: int = 0
    envelopes_created: int = 0
    deletions_count: int = 0
    pages_processed: int = 0
    tables_detected: int = 0
    chunks_created: int = 0
    volume_bytes: int = 0
    avg_extraction_time_seconds: float = 0.0
    avg_pipeline_time_seconds: float = 0.0
    openai_tokens: int = 0
    openai_cost_usd: float = 0.0


class CompanyBreakdownItem(BaseModel):
    """Métricas agregadas por aseguradora."""

    company_sigla: str
    company_name: str
    documents_count: int = 0
    active_documents_count: int = 0
    envelopes_count: int = 0
    pages_count: int = 0
    tables_count: int = 0
    chunks_count: int = 0
    coberturas_count: int = 0
    volume_bytes: int = 0
    avg_extraction_time_seconds: float = 0.0
    avg_pipeline_time_seconds: float = 0.0
    openai_tokens: int = 0
    openai_cost_usd: float = 0.0
    failed_count: int = 0
    deleted_count: int = 0


class RamoBreakdownItem(BaseModel):
    """Métricas agregadas por ramo de seguro."""

    ramo: str
    ramo_tipo: str | None = None
    envelopes_count: int = 0
    documents_count: int = 0
    pages_count: int = 0
    tables_count: int = 0
    openai_cost_usd: float = 0.0


class DocumentTypeBreakdownItem(BaseModel):
    """Métricas agregadas por tipo documental."""

    tipo_documento: str
    documents_count: int = 0
    pages_count: int = 0
    tables_count: int = 0
    chunks_count: int = 0


class FileTypeBreakdownItem(BaseModel):
    """Métricas por tipología PDF (DIGITAL, SCANNED, HYBRID, UNKNOWN)."""

    file_type: str
    documents_count: int = 0
    ocr_applied_count: int = 0
    pages_count: int = 0
    avg_time_per_page_seconds: float = 0.0
    avg_extraction_time_seconds: float = 0.0


class LedgerEventSummaryItem(BaseModel):
    """Conteo agrupado por event_type del libro mayor inmutable."""

    event_type: str
    count: int = 0


class ErrorCategoryItem(BaseModel):
    """Agrupación de mensajes de error frecuentes en processing_jobs."""

    category: str
    count: int = 0
    latest_at: str | None = None
    sample_message: str


class WormProtectionStatus(BaseModel):
    """Estado de verificación de triggers WORM (Inmutabilidad) en PostgreSQL."""

    active: bool = False
    protected_tables: list[str] = Field(default_factory=list)
    triggers_count: int = 0
    trigger_names: list[str] = Field(default_factory=list)


class SystemHealthSnapshot(BaseModel):
    """Estado operativo en tiempo real del proceso FastAPI y búfer de logs."""

    status: str = "ok"
    environment: str = "development"
    uptime_seconds: float = 0.0
    memory_usage_mb: float = 0.0
    app_version: str = "1.0.0"
    docling_version: str = "unknown"
    python_version: str = ""
    log_buffer_count: int = 0
    log_error_count: int = 0
    log_warning_count: int = 0


class DashboardOverviewResponse(BaseModel):
    """Respuesta consolidada principal para el Dashboard de Control."""

    kpis: DashboardKpiSummary
    period_snapshot: PeriodSnapshot
    granularity: str
    time_series: list[TimeSeriesPoint] = Field(default_factory=list)
    by_company: list[CompanyBreakdownItem] = Field(default_factory=list)
    by_ramo: list[RamoBreakdownItem] = Field(default_factory=list)
    by_document_type: list[DocumentTypeBreakdownItem] = Field(default_factory=list)
    by_file_type: list[FileTypeBreakdownItem] = Field(default_factory=list)
    ledger_event_summary: list[LedgerEventSummaryItem] = Field(default_factory=list)
    error_categories: list[ErrorCategoryItem] = Field(default_factory=list)
    worm_status: WormProtectionStatus
    system_health: SystemHealthSnapshot
    filters_applied: dict[str, Any] = Field(default_factory=dict)
    available_filters: dict[str, Any] = Field(default_factory=dict)


class AuditLedgerItem(BaseModel):
    """Registro individual del libro mayor inmutable audit_metrics_ledger."""

    event_id: str
    event_type: str
    policy_id: str | None = None
    envelope_id: str | None = None
    job_id: str | None = None
    numero_poliza: str | None = None
    company_sigla: str | None = None
    ramo: str | None = None
    tipo_documento: str | None = None
    id_cliente: str | None = None
    nombre_cliente: str | None = None
    file_name: str | None = None
    file_hash: str | None = None
    pages_count: int = 0
    tables_count: int = 0
    chunks_count: int = 0
    file_size_bytes: int = 0
    duration_seconds: float = 0.0
    openai_tokens: int = 0
    openai_cost_usd: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AuditLedgerPageResponse(BaseModel):
    """Respuesta paginada del libro mayor inmutable."""

    total: int
    limit: int
    offset: int
    items: list[AuditLedgerItem] = Field(default_factory=list)


class ProcessingStatItem(BaseModel):
    """Registro individual de telemetría de policy_processing_stats."""

    stat_id: str
    policy_id: str | None = None
    envelope_id: str | None = None
    job_id: str | None = None
    policy_number: str | None = None
    company_sigla: str | None = None
    file_name: str | None = None
    file_hash: str | None = None
    tipo_documento: str | None = None
    id_cliente: str | None = None
    file_type: str = "UNKNOWN"
    ocr_applied: bool = False
    scanned_page_ratio: float | None = None
    total_pages: int = 0
    extraction_time_seconds: float = 0.0
    time_per_page_seconds: float = 0.0
    chunking_time_seconds: float = 0.0
    embedding_time_seconds: float = 0.0
    openai_time_seconds: float = 0.0
    total_pipeline_time_seconds: float = 0.0
    total_chunks: int = 0
    parent_chunks: int = 0
    child_chunks: int = 0
    openai_prompt_tokens: int = 0
    openai_completion_tokens: int = 0
    openai_total_tokens: int = 0
    openai_estimated_cost_usd: float = 0.0
    coberturas_extracted_count: int = 0
    tables_detected: int = 0
    memory_peak_mb: float | None = None
    created_at: str


class ProcessingStatsPageResponse(BaseModel):
    """Respuesta paginada de telemetría por documento."""

    total: int
    limit: int
    offset: int
    items: list[ProcessingStatItem] = Field(default_factory=list)


class JobErrorItem(BaseModel):
    """Registro de trabajo de procesamiento (processing_jobs) enriquecido con contexto."""

    job_id: str
    file_name: str
    status: str
    error_message: str | None = None
    policy_id: str | None = None
    company_sigla: str | None = None
    numero_poliza: str | None = None
    created_at: str
    updated_at: str
    duration_seconds: float | None = None


class JobsErrorsPageResponse(BaseModel):
    """Respuesta paginada de trabajos y errores detectados."""

    total: int
    limit: int
    offset: int
    status_counts: dict[str, int] = Field(default_factory=dict)
    items: list[JobErrorItem] = Field(default_factory=list)


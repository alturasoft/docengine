"""DocEngine — Infrastructure: PostgreSQL Audit & Processing Dashboard Repository.

[ADITIVO] Repositorio de consultas analíticas de SOLO LECTURA sobre las estructuras
inmutables de auditoría y telemetría (audit_metrics_ledger, policy_processing_stats,
processing_jobs, policy_envelopes, policies y catálogos maestros).

No ejecuta ninguna operación de escritura (INSERT/UPDATE/DELETE) y no altera
ninguna lógica del pipeline de extracción o RAG existente.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


def _validate_iso_date(value: str | None) -> str | None:
    """Validate YYYY-MM-DD date string safely."""
    if not value or not value.strip():
        return None
    clean = value.strip()[:10]
    try:
        date.fromisoformat(clean)
        return clean
    except ValueError:
        return None


class PgAuditDashboardRepository:
    """Read-only analytical repository for the processing control & audit dashboard."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    # ------------------------------------------------------------------
    # Internal filter builder helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_ledger_where(
        date_from: str | None = None,
        date_to: str | None = None,
        company_sigla: str | None = None,
        ramo: str | None = None,
        tipo_documento: str | None = None,
        file_type: str | None = None,
        event_type: str | None = None,
        search: str | None = None,
        alias: str = "aml",
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = [
            f"({alias}.numero_poliza NOT LIKE 'TEST-%%' OR {alias}.numero_poliza IS NULL)",
            f"({alias}.file_name NOT LIKE 'poliza_inmutable_%%' OR {alias}.file_name IS NULL)",
        ]
        params: list[Any] = []

        d_from = _validate_iso_date(date_from)
        d_to = _validate_iso_date(date_to)
        if d_from:
            clauses.append(f"{alias}.created_at >= %s::date")
            params.append(d_from)
        if d_to:
            clauses.append(f"{alias}.created_at < (%s::date + INTERVAL '1 day')")
            params.append(d_to)
        if company_sigla and company_sigla.strip():
            clauses.append(f"UPPER({alias}.company_sigla) = %s")
            params.append(company_sigla.strip().upper())
        if ramo and ramo.strip():
            clauses.append(f"{alias}.ramo ILIKE %s")
            params.append(f"%{ramo.strip()}%")
        if tipo_documento and tipo_documento.strip():
            clauses.append(f"UPPER({alias}.tipo_documento) = %s")
            params.append(tipo_documento.strip().upper())
        if file_type and file_type.strip():
            clauses.append(
                f"EXISTS (SELECT 1 FROM policy_processing_stats pps_ft "
                f"WHERE (pps_ft.policy_id = {alias}.policy_id OR pps_ft.job_id = {alias}.job_id "
                f"OR (pps_ft.file_hash IS NOT NULL AND pps_ft.file_hash = {alias}.file_hash)) "
                f"AND UPPER(pps_ft.file_type) = %s)"
            )
            params.append(file_type.strip().upper())
        if event_type and event_type.strip():
            clauses.append(f"{alias}.event_type = %s")
            params.append(event_type.strip().upper())
        if search and search.strip():
            q = f"%{search.strip()}%"
            clauses.append(
                f"({alias}.file_name ILIKE %s OR {alias}.numero_poliza ILIKE %s "
                f"OR {alias}.id_cliente ILIKE %s OR {alias}.nombre_cliente ILIKE %s "
                f"OR {alias}.file_hash ILIKE %s)"
            )
            params.extend([q, q, q, q, q])

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where_sql, params

    @staticmethod
    def _build_stats_where(
        date_from: str | None = None,
        date_to: str | None = None,
        company_sigla: str | None = None,
        ramo: str | None = None,
        tipo_documento: str | None = None,
        file_type: str | None = None,
        search: str | None = None,
        alias: str = "pps",
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = [
            f"({alias}.policy_number NOT LIKE 'TEST-%%' OR {alias}.policy_number IS NULL)",
            f"({alias}.file_name NOT LIKE 'poliza_inmutable_%%' OR {alias}.file_name IS NULL)",
        ]
        params: list[Any] = []

        d_from = _validate_iso_date(date_from)
        d_to = _validate_iso_date(date_to)
        if d_from:
            clauses.append(f"{alias}.created_at >= %s::date")
            params.append(d_from)
        if d_to:
            clauses.append(f"{alias}.created_at < (%s::date + INTERVAL '1 day')")
            params.append(d_to)
        if company_sigla and company_sigla.strip():
            clauses.append(f"UPPER({alias}.company_sigla) = %s")
            params.append(company_sigla.strip().upper())
        if ramo and ramo.strip():
            clauses.append(
                f"EXISTS (SELECT 1 FROM policy_envelopes pe_r "
                f"WHERE pe_r.id = {alias}.envelope_id AND pe_r.ramo ILIKE %s)"
            )
            params.append(f"%{ramo.strip()}%")
        if tipo_documento and tipo_documento.strip():
            clauses.append(f"UPPER({alias}.tipo_documento) = %s")
            params.append(tipo_documento.strip().upper())
        if file_type and file_type.strip():
            clauses.append(f"UPPER({alias}.file_type) = %s")
            params.append(file_type.strip().upper())
        if search and search.strip():
            q = f"%{search.strip()}%"
            clauses.append(
                f"({alias}.file_name ILIKE %s OR {alias}.policy_number ILIKE %s "
                f"OR {alias}.id_cliente ILIKE %s OR {alias}.file_hash ILIKE %s)"
            )
            params.extend([q, q, q, q])

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where_sql, params

    @staticmethod
    def _build_jobs_where(
        date_from: str | None = None,
        date_to: str | None = None,
        company_sigla: str | None = None,
        status_filter: str | None = None,
        search: str | None = None,
        alias: str = "pj",
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = [
            f"({alias}.file_name NOT LIKE 'poliza_inmutable_%%' OR {alias}.file_name IS NULL)",
        ]
        params: list[Any] = []

        d_from = _validate_iso_date(date_from)
        d_to = _validate_iso_date(date_to)
        if d_from:
            clauses.append(f"{alias}.created_at >= %s::date")
            params.append(d_from)
        if d_to:
            clauses.append(f"{alias}.created_at < (%s::date + INTERVAL '1 day')")
            params.append(d_to)
        if company_sigla and company_sigla.strip():
            sigla_u = company_sigla.strip().upper()
            clauses.append(
                f"(EXISTS (SELECT 1 FROM policy_processing_stats pps_j WHERE pps_j.job_id = {alias}.job_id AND UPPER(pps_j.company_sigla) = %s) "
                f"OR EXISTS (SELECT 1 FROM policies p_j WHERE p_j.id = {alias}.policy_id AND UPPER(p_j.company_sigla) = %s) "
                f"OR EXISTS (SELECT 1 FROM audit_metrics_ledger aml_j WHERE aml_j.job_id = {alias}.job_id AND UPPER(aml_j.company_sigla) = %s))"
            )
            params.extend([sigla_u, sigla_u, sigla_u])
        if status_filter and status_filter.strip():
            clauses.append(f"UPPER({alias}.status) = %s")
            params.append(status_filter.strip().upper())
        if search and search.strip():
            q = f"%{search.strip()}%"
            clauses.append(
                f"({alias}.file_name ILIKE %s OR COALESCE({alias}.error_message, '') ILIKE %s "
                f"OR {alias}.job_id::text ILIKE %s)"
            )
            params.extend([q, q, q])

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        return where_sql, params

    # ------------------------------------------------------------------
    # Overview & Aggregations
    # ------------------------------------------------------------------

    def get_dashboard_overview(
        self,
        granularity: str = "daily",
        date_from: str | None = None,
        date_to: str | None = None,
        company_sigla: str | None = None,
        ramo: str | None = None,
        tipo_documento: str | None = None,
        file_type: str | None = None,
    ) -> dict[str, Any]:
        """Return comprehensive read-only audit & telemetry summary for the dashboard."""
        clean_granularity = granularity.lower().strip()
        if clean_granularity not in ("daily", "weekly", "monthly"):
            clean_granularity = "daily"

        trunc_unit = {"daily": "day", "weekly": "week", "monthly": "month"}[clean_granularity]

        ledger_where, ledger_params = self._build_ledger_where(
            date_from=date_from,
            date_to=date_to,
            company_sigla=company_sigla,
            ramo=ramo,
            tipo_documento=tipo_documento,
            file_type=file_type,
            alias="aml",
        )
        stats_where, stats_params = self._build_stats_where(
            date_from=date_from,
            date_to=date_to,
            company_sigla=company_sigla,
            ramo=ramo,
            tipo_documento=tipo_documento,
            file_type=file_type,
            alias="pps",
        )
        jobs_where, jobs_params = self._build_jobs_where(
            date_from=date_from,
            date_to=date_to,
            company_sigla=company_sigla,
            alias="pj",
        )

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                # 1. KPIs from audit_metrics_ledger
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED') AS docs_extracted,
                        COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_DELETED') AS docs_deleted,
                        COUNT(*) FILTER (WHERE aml.event_type = 'ENVELOPE_CREATED') AS env_created,
                        COUNT(*) FILTER (WHERE aml.event_type = 'ENVELOPE_DELETED') AS env_deleted,
                        COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_SKIPPED_DUPLICATE') AS dup_events,
                        COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTION_FAILED') AS fail_events,
                        COUNT(DISTINCT NULLIF(TRIM(aml.id_cliente), '')) AS unique_clients,
                        COALESCE(SUM(aml.pages_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS pages_sum,
                        COALESCE(SUM(aml.tables_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS tables_sum,
                        COALESCE(SUM(aml.chunks_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS chunks_sum,
                        COALESCE(SUM(aml.file_size_bytes) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS bytes_sum,
                        COALESCE(SUM(aml.openai_tokens) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS tokens_sum,
                        COALESCE(SUM(aml.openai_cost_usd) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS cost_sum
                    FROM audit_metrics_ledger aml
                    {ledger_where};
                    """,
                    tuple(ledger_params),
                )
                l_row = cur.fetchone() or (0,) * 13

                # 2. KPIs from policy_processing_stats (detailed stage timing & RAG hierarchy)
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) AS stats_count,
                        COALESCE(SUM(pps.total_pages), 0) AS stats_pages,
                        COALESCE(SUM(pps.tables_detected), 0) AS stats_tables,
                        COALESCE(SUM(pps.coberturas_extracted_count), 0) AS coberturas_sum,
                        COALESCE(SUM(pps.total_chunks), 0) AS total_chunks,
                        COALESCE(SUM(pps.parent_chunks), 0) AS parent_chunks,
                        COALESCE(SUM(pps.child_chunks), 0) AS child_chunks,
                        COALESCE(AVG(NULLIF(pps.extraction_time_seconds, 0)), 0) AS avg_ext,
                        COALESCE(AVG(NULLIF(pps.time_per_page_seconds, 0)), 0) AS avg_per_page,
                        COALESCE(AVG(pps.chunking_time_seconds), 0) AS avg_chunk,
                        COALESCE(AVG(NULLIF(pps.embedding_time_seconds, 0)), 0) AS avg_emb,
                        COALESCE(AVG(NULLIF(pps.openai_time_seconds, 0)), 0) AS avg_oai,
                        COALESCE(AVG(NULLIF(pps.total_pipeline_time_seconds, 0)), 0) AS avg_pipe,
                        COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY pps.total_pipeline_time_seconds), 0) AS p95_pipe,
                        COALESCE(MAX(pps.memory_peak_mb), 0) AS max_mem,
                        COALESCE(AVG(NULLIF(pps.memory_peak_mb, 0)), 0) AS avg_mem,
                        COALESCE(SUM(pps.openai_prompt_tokens), 0) AS prompt_tok,
                        COALESCE(SUM(pps.openai_completion_tokens), 0) AS comp_tok,
                        COALESCE(SUM(pps.openai_total_tokens), 0) AS total_tok,
                        COALESCE(SUM(pps.openai_estimated_cost_usd), 0) AS total_cost,
                        COUNT(*) FILTER (WHERE pps.ocr_applied IS TRUE) AS ocr_count,
                        COALESCE(AVG(pps.scanned_page_ratio), 0) AS avg_scan_ratio
                    FROM policy_processing_stats pps
                    {stats_where};
                    """,
                    tuple(stats_params),
                )
                s_row = cur.fetchone() or (0,) * 22

                # 3. KPIs from processing_jobs
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) AS total_jobs,
                        COUNT(*) FILTER (WHERE pj.status = 'COMPLETED') AS completed_jobs,
                        COUNT(*) FILTER (WHERE pj.status = 'FAILED') AS failed_jobs,
                        COUNT(*) FILTER (WHERE pj.status = 'SKIPPED') AS skipped_jobs,
                        COUNT(*) FILTER (WHERE pj.status = 'PROCESSING') AS processing_jobs,
                        COUNT(*) FILTER (WHERE pj.status = 'PENDING') AS pending_jobs
                    FROM processing_jobs pj
                    {jobs_where};
                    """,
                    tuple(jobs_params),
                )
                j_row = cur.fetchone() or (0,) * 6

                # 4. Active operational inventory (respecting company/ramo/tipo_documento and date range if given)
                p_clauses: list[str] = [
                    "(p.file_name NOT LIKE 'poliza_inmutable_%%' OR p.file_name IS NULL)"
                ]
                p_params: list[Any] = []
                e_clauses: list[str] = [
                    "(pe.numero_poliza NOT LIKE 'TEST-%%' OR pe.numero_poliza IS NULL)"
                ]
                e_params: list[Any] = []

                d_from = _validate_iso_date(date_from)
                d_to = _validate_iso_date(date_to)
                if d_from:
                    p_clauses.append("p.created_at >= %s::date")
                    p_params.append(d_from)
                    e_clauses.append("pe.created_at >= %s::date")
                    e_params.append(d_from)
                if d_to:
                    p_clauses.append("p.created_at < (%s::date + INTERVAL '1 day')")
                    p_params.append(d_to)
                    e_clauses.append("pe.created_at < (%s::date + INTERVAL '1 day')")
                    e_params.append(d_to)

                if company_sigla and company_sigla.strip():
                    p_clauses.append("UPPER(p.company_sigla) = %s")
                    p_params.append(company_sigla.strip().upper())
                    e_clauses.append("UPPER(pe.company_sigla) = %s")
                    e_params.append(company_sigla.strip().upper())
                if tipo_documento and tipo_documento.strip():
                    p_clauses.append("UPPER(p.tipo_documento) = %s")
                    p_params.append(tipo_documento.strip().upper())
                if ramo and ramo.strip():
                    p_clauses.append(
                        "EXISTS (SELECT 1 FROM policy_envelopes pe_p WHERE pe_p.id = p.envelope_id AND pe_p.ramo ILIKE %s)"
                    )
                    p_params.append(f"%{ramo.strip()}%")
                    e_clauses.append("pe.ramo ILIKE %s")
                    e_params.append(f"%{ramo.strip()}%")
                p_where = ("WHERE " + " AND ".join(p_clauses)) if p_clauses else ""
                e_where = ("WHERE " + " AND ".join(e_clauses)) if e_clauses else ""

                cur.execute(
                    f"""
                    SELECT
                        COUNT(*),
                        COUNT(DISTINCT NULLIF(TRIM(p.id_cliente), '')),
                        COALESCE(SUM(p.file_size_bytes), 0)
                    FROM policies p
                    {p_where};
                    """,
                    tuple(p_params),
                )
                pol_row = cur.fetchone() or (0, 0, 0)

                cur.execute(
                    f"""
                    SELECT
                        COUNT(*),
                        COUNT(DISTINCT NULLIF(TRIM(pe.id_cliente), ''))
                    FROM policy_envelopes pe
                    {e_where};
                    """,
                    tuple(e_params),
                )
                env_row = cur.fetchone() or (0, 0)

                # Optional specialized tables (fleet vehicles, insured persons, section summaries)
                fleet_count = self._safe_count(cur, "policy_fleet_vehicles")
                insured_count = self._safe_count(cur, "policy_insured_persons")
                summaries_count = self._safe_count(cur, "policy_section_summaries")

                # 5. Period Snapshot (Today vs Last 7 Days vs Previous 7 Days)
                # Respects company_sigla, ramo, tipo_documento, file_type
                snap_where, snap_params = self._build_ledger_where(
                    company_sigla=company_sigla,
                    ramo=ramo,
                    tipo_documento=tipo_documento,
                    file_type=file_type,
                    alias="aml",
                )
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED' AND aml.created_at >= DATE_TRUNC('day', CURRENT_TIMESTAMP)) AS today_docs,
                        COALESCE(SUM(aml.pages_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED' AND aml.created_at >= DATE_TRUNC('day', CURRENT_TIMESTAMP)), 0) AS today_pages,
                        COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTION_FAILED' AND aml.created_at >= DATE_TRUNC('day', CURRENT_TIMESTAMP)) AS today_fail_evt,
                        COUNT(*) FILTER (WHERE aml.event_type = 'ENVELOPE_CREATED' AND aml.created_at >= DATE_TRUNC('day', CURRENT_TIMESTAMP)) AS today_env,
                        COALESCE(SUM(aml.openai_cost_usd) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED' AND aml.created_at >= DATE_TRUNC('day', CURRENT_TIMESTAMP)), 0) AS today_cost,
                        COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED' AND aml.created_at >= (DATE_TRUNC('day', CURRENT_TIMESTAMP) - INTERVAL '6 days')) AS week_docs,
                        COALESCE(SUM(aml.pages_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED' AND aml.created_at >= (DATE_TRUNC('day', CURRENT_TIMESTAMP) - INTERVAL '6 days')), 0) AS week_pages,
                        COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTION_FAILED' AND aml.created_at >= (DATE_TRUNC('day', CURRENT_TIMESTAMP) - INTERVAL '6 days')) AS week_fail_evt,
                        COUNT(*) FILTER (WHERE aml.event_type = 'ENVELOPE_CREATED' AND aml.created_at >= (DATE_TRUNC('day', CURRENT_TIMESTAMP) - INTERVAL '6 days')) AS week_env,
                        COALESCE(SUM(aml.openai_cost_usd) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED' AND aml.created_at >= (DATE_TRUNC('day', CURRENT_TIMESTAMP) - INTERVAL '6 days')), 0) AS week_cost,
                        COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED' AND aml.created_at >= (DATE_TRUNC('day', CURRENT_TIMESTAMP) - INTERVAL '13 days') AND aml.created_at < (DATE_TRUNC('day', CURRENT_TIMESTAMP) - INTERVAL '6 days')) AS prev_week_docs
                    FROM audit_metrics_ledger aml
                    {snap_where};
                    """,
                    tuple(snap_params),
                )
                snap_l = cur.fetchone() or (0,) * 11

                snap_jobs_where, snap_jobs_params = self._build_jobs_where(
                    company_sigla=company_sigla,
                    alias="pj",
                )
                cur.execute(
                    f"""
                    SELECT
                        COUNT(*) FILTER (WHERE pj.status = 'FAILED' AND pj.created_at >= DATE_TRUNC('day', CURRENT_TIMESTAMP)) AS today_job_fail,
                        COUNT(*) FILTER (WHERE pj.status = 'FAILED' AND pj.created_at >= (DATE_TRUNC('day', CURRENT_TIMESTAMP) - INTERVAL '6 days')) AS week_job_fail
                    FROM processing_jobs pj
                    {snap_jobs_where};
                    """,
                    tuple(snap_jobs_params),
                )
                snap_j = cur.fetchone() or (0, 0)

                # 6. Time Series (Daily / Weekly / Monthly)
                period_fmt = "YYYY-MM" if clean_granularity == "monthly" else "YYYY-MM-DD"
                cur.execute(
                    f"""
                    WITH ledger_agg AS (
                        SELECT
                            DATE_TRUNC('{trunc_unit}', aml.created_at) AS bucket,
                            COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED') AS docs_ext,
                            COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_SKIPPED_DUPLICATE') AS dup_skip,
                            COUNT(*) FILTER (WHERE aml.event_type = 'ENVELOPE_CREATED') AS env_created,
                            COUNT(*) FILTER (WHERE aml.event_type IN ('DOCUMENT_DELETED', 'ENVELOPE_DELETED')) AS deletions,
                            COALESCE(SUM(aml.pages_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS pages,
                            COALESCE(SUM(aml.tables_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS tables,
                            COALESCE(SUM(aml.chunks_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS chunks,
                            COALESCE(SUM(aml.file_size_bytes) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS bytes,
                            COALESCE(SUM(aml.openai_tokens) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS tokens,
                            COALESCE(SUM(aml.openai_cost_usd) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS cost
                        FROM audit_metrics_ledger aml
                        {ledger_where}
                        GROUP BY 1
                    ),
                    jobs_agg AS (
                        SELECT
                            DATE_TRUNC('{trunc_unit}', pj.created_at) AS bucket,
                            COUNT(*) FILTER (WHERE pj.status = 'COMPLETED') AS jobs_comp,
                            COUNT(*) FILTER (WHERE pj.status = 'FAILED') AS jobs_fail,
                            COUNT(*) FILTER (WHERE pj.status = 'SKIPPED') AS jobs_skip
                        FROM processing_jobs pj
                        {jobs_where}
                        GROUP BY 1
                    ),
                    stats_agg AS (
                        SELECT
                            DATE_TRUNC('{trunc_unit}', pps.created_at) AS bucket,
                            COALESCE(AVG(NULLIF(pps.extraction_time_seconds, 0)), 0) AS avg_ext,
                            COALESCE(AVG(NULLIF(pps.total_pipeline_time_seconds, 0)), 0) AS avg_pipe
                        FROM policy_processing_stats pps
                        {stats_where}
                        GROUP BY 1
                    ),
                    all_buckets AS (
                        SELECT bucket FROM ledger_agg
                        UNION
                        SELECT bucket FROM jobs_agg
                        UNION
                        SELECT bucket FROM stats_agg
                    )
                    SELECT
                        TO_CHAR(ab.bucket, '{period_fmt}') AS period_key,
                        COALESCE(la.docs_ext, 0),
                        COALESCE(la.dup_skip, 0),
                        COALESCE(ja.jobs_comp, 0),
                        COALESCE(ja.jobs_fail, 0),
                        COALESCE(ja.jobs_skip, 0),
                        COALESCE(la.env_created, 0),
                        COALESCE(la.deletions, 0),
                        COALESCE(la.pages, 0),
                        COALESCE(la.tables, 0),
                        COALESCE(la.chunks, 0),
                        COALESCE(la.bytes, 0),
                        ROUND(COALESCE(sa.avg_ext, 0)::numeric, 3),
                        ROUND(COALESCE(sa.avg_pipe, 0)::numeric, 3),
                        COALESCE(la.tokens, 0),
                        COALESCE(la.cost, 0)
                    FROM all_buckets ab
                    LEFT JOIN ledger_agg la ON la.bucket = ab.bucket
                    LEFT JOIN jobs_agg ja ON ja.bucket = ab.bucket
                    LEFT JOIN stats_agg sa ON sa.bucket = ab.bucket
                    WHERE ab.bucket IS NOT NULL
                    ORDER BY ab.bucket ASC;
                    """,
                    tuple(ledger_params + jobs_params + stats_params),
                )
                ts_rows = cur.fetchall()

                # 7. Breakdown by Company
                cur.execute(
                    f"""
                    WITH ledger_co AS (
                        SELECT
                            COALESCE(NULLIF(UPPER(TRIM(aml.company_sigla)), ''), 'SIN_SIGLA') AS sigla,
                            COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED') AS docs_count,
                            COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTION_FAILED') AS fail_count,
                            COUNT(*) FILTER (WHERE aml.event_type IN ('DOCUMENT_DELETED', 'ENVELOPE_DELETED')) AS del_count,
                            COALESCE(SUM(aml.pages_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS pages_count,
                            COALESCE(SUM(aml.tables_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS tables_count,
                            COALESCE(SUM(aml.chunks_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS chunks_count,
                            COALESCE(SUM(aml.file_size_bytes) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS bytes_count,
                            COALESCE(SUM(aml.openai_tokens) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS tokens_count,
                            COALESCE(SUM(aml.openai_cost_usd) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS cost_sum
                        FROM audit_metrics_ledger aml
                        {ledger_where}
                        GROUP BY 1
                    ),
                    stats_co AS (
                        SELECT
                            COALESCE(NULLIF(UPPER(TRIM(pps.company_sigla)), ''), 'SIN_SIGLA') AS sigla,
                            COALESCE(SUM(pps.coberturas_extracted_count), 0) AS coberturas_count,
                            COALESCE(AVG(NULLIF(pps.extraction_time_seconds, 0)), 0) AS avg_ext,
                            COALESCE(AVG(NULLIF(pps.total_pipeline_time_seconds, 0)), 0) AS avg_pipe
                        FROM policy_processing_stats pps
                        {stats_where}
                        GROUP BY 1
                    ),
                    active_pol AS (
                        SELECT
                            COALESCE(NULLIF(UPPER(TRIM(company_sigla)), ''), 'SIN_SIGLA') AS sigla,
                            COUNT(*) AS active_docs
                        FROM policies
                        GROUP BY 1
                    ),
                    active_env AS (
                        SELECT
                            COALESCE(NULLIF(UPPER(TRIM(company_sigla)), ''), 'SIN_SIGLA') AS sigla,
                            COUNT(*) AS env_count
                        FROM policy_envelopes
                        GROUP BY 1
                    )
                    SELECT
                        lc.sigla,
                        COALESCE(ca.nombre, lc.sigla) AS company_name,
                        lc.docs_count,
                        COALESCE(ap.active_docs, 0),
                        COALESCE(ae.env_count, 0),
                        lc.pages_count,
                        lc.tables_count,
                        lc.chunks_count,
                        COALESCE(sc.coberturas_count, 0),
                        lc.bytes_count,
                        ROUND(COALESCE(sc.avg_ext, 0)::numeric, 3),
                        ROUND(COALESCE(sc.avg_pipe, 0)::numeric, 3),
                        lc.tokens_count,
                        lc.cost_sum,
                        lc.fail_count,
                        lc.del_count
                    FROM ledger_co lc
                    LEFT JOIN LATERAL (
                        SELECT nombre FROM cat_aseguradoras c
                        WHERE UPPER(c.sigla) = lc.sigla OR UPPER(COALESCE(c.sigla_anterior, '')) = lc.sigla
                        ORDER BY (UPPER(c.sigla) = lc.sigla) DESC
                        LIMIT 1
                    ) ca ON TRUE
                    LEFT JOIN stats_co sc ON sc.sigla = lc.sigla
                    LEFT JOIN active_pol ap ON ap.sigla = lc.sigla
                    LEFT JOIN active_env ae ON ae.sigla = lc.sigla
                    ORDER BY lc.docs_count DESC, lc.pages_count DESC;
                    """,
                    tuple(ledger_params + stats_params),
                )
                co_rows = cur.fetchall()

                # 8. Breakdown by Ramo
                cur.execute(
                    f"""
                    SELECT
                        COALESCE(NULLIF(TRIM(aml.ramo), ''), 'NO ESPECIFICADO') AS ramo_name,
                        MAX(cr.tipo) AS ramo_tipo,
                        COUNT(DISTINCT aml.envelope_id) FILTER (WHERE aml.envelope_id IS NOT NULL) AS env_cnt,
                        COUNT(*) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED') AS docs_cnt,
                        COALESCE(SUM(aml.pages_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS pages_cnt,
                        COALESCE(SUM(aml.tables_count) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS tables_cnt,
                        COALESCE(SUM(aml.openai_cost_usd) FILTER (WHERE aml.event_type = 'DOCUMENT_EXTRACTED'), 0) AS cost_sum
                    FROM audit_metrics_ledger aml
                    LEFT JOIN cat_ramos cr ON UPPER(cr.ramo) = UPPER(TRIM(aml.ramo))
                    {ledger_where}
                    GROUP BY 1
                    ORDER BY docs_cnt DESC, env_cnt DESC
                    LIMIT 25;
                    """,
                    tuple(ledger_params),
                )
                ramo_rows = cur.fetchall()

                # 9. Breakdown by Document Type
                cur.execute(
                    f"""
                    SELECT
                        COALESCE(NULLIF(TRIM(aml.tipo_documento), ''), 'NO_ESPECIFICADO') AS tipo_doc,
                        COUNT(*) AS docs_cnt,
                        COALESCE(SUM(aml.pages_count), 0) AS pages_cnt,
                        COALESCE(SUM(aml.tables_count), 0) AS tables_cnt,
                        COALESCE(SUM(aml.chunks_count), 0) AS chunks_cnt
                    FROM audit_metrics_ledger aml
                    {ledger_where + (' AND ' if ledger_where else 'WHERE ')} aml.event_type = 'DOCUMENT_EXTRACTED'
                    GROUP BY 1
                    ORDER BY docs_cnt DESC;
                    """,
                    tuple(ledger_params),
                )
                doctype_rows = cur.fetchall()

                # 10. Breakdown by PDF File Type (DIGITAL / SCANNED / HYBRID / UNKNOWN)
                cur.execute(
                    f"""
                    SELECT
                        COALESCE(NULLIF(TRIM(pps.file_type), ''), 'UNKNOWN') AS ftype,
                        COUNT(*) AS docs_cnt,
                        COUNT(*) FILTER (WHERE pps.ocr_applied IS TRUE) AS ocr_cnt,
                        COALESCE(SUM(pps.total_pages), 0) AS pages_cnt,
                        ROUND(COALESCE(AVG(NULLIF(pps.time_per_page_seconds, 0)), 0)::numeric, 3),
                        ROUND(COALESCE(AVG(NULLIF(pps.extraction_time_seconds, 0)), 0)::numeric, 3)
                    FROM policy_processing_stats pps
                    {stats_where}
                    GROUP BY 1
                    ORDER BY docs_cnt DESC;
                    """,
                    tuple(stats_params),
                )
                ftype_rows = cur.fetchall()

                # 11. Ledger Event Type Summary
                cur.execute(
                    f"""
                    SELECT aml.event_type, COUNT(*)
                    FROM audit_metrics_ledger aml
                    {ledger_where}
                    GROUP BY aml.event_type
                    ORDER BY COUNT(*) DESC;
                    """,
                    tuple(ledger_params),
                )
                event_summary_rows = cur.fetchall()

                # 12. Error Categories from processing_jobs
                err_extra = " AND pj.status = 'FAILED'" if jobs_where else "WHERE pj.status = 'FAILED'"
                cur.execute(
                    f"""
                    SELECT
                        CASE
                            WHEN pj.error_message ILIKE '%%policies_file_hash_key%%' OR pj.error_message ILIKE '%%duplicate key%%'
                                THEN 'Duplicado de Archivo (Hash SHA-256)'
                            WHEN pj.error_message ILIKE '%%huérfano%%' OR pj.error_message ILIKE '%%reconciliado%%'
                                THEN 'Job Huérfano Reconciliado'
                            WHEN pj.error_message ILIKE '%%timeout%%' OR pj.error_message ILIKE '%%timed out%%'
                                THEN 'Timeout de Procesamiento'
                            WHEN pj.error_message ILIKE '%%openai%%' OR pj.error_message ILIKE '%%rate limit%%' OR pj.error_message ILIKE '%%429%%'
                                THEN 'Error de API OpenAI / Límite'
                            WHEN pj.error_message ILIKE '%%pdf%%' OR pj.error_message ILIKE '%%corrupt%%' OR pj.error_message ILIKE '%%docling%%'
                                THEN 'Error de Lectura / Estructura PDF'
                            WHEN pj.error_message ILIKE '%%memory%%' OR pj.error_message ILIKE '%%bad_alloc%%'
                                THEN 'Límite de Memoria RAM'
                            ELSE 'Otros Errores de Ejecución'
                        END AS category,
                        COUNT(*) AS cnt,
                        MAX(pj.updated_at)::text AS latest_at,
                        MAX(COALESCE(pj.error_message, 'Sin detalle')) AS sample_msg
                    FROM processing_jobs pj
                    {jobs_where}{err_extra}
                    GROUP BY 1
                    ORDER BY cnt DESC;
                    """,
                    tuple(jobs_params),
                )
                err_cat_rows = cur.fetchall()

                # 13. WORM Protection Verification
                cur.execute(
                    """
                    SELECT tgname, tgrelid::regclass::text
                    FROM pg_trigger
                    WHERE tgname LIKE 'trg_protect_%'
                      AND NOT tgisinternal
                    ORDER BY tgname;
                    """
                )
                worm_rows = cur.fetchall()

                # 14. Available filter options (unfiltered catalogs/distinct values)
                cur.execute(
                    """
                    SELECT DISTINCT sigla, nombre
                    FROM (
                        SELECT ca.sigla, ca.nombre
                        FROM cat_aseguradoras ca
                        WHERE ca.activa IS TRUE
                        UNION
                        SELECT DISTINCT UPPER(TRIM(company_sigla)), UPPER(TRIM(company_sigla))
                        FROM audit_metrics_ledger
                        WHERE company_sigla IS NOT NULL AND TRIM(company_sigla) <> ''
                    ) t
                    ORDER BY sigla;
                    """
                )
                avail_companies = [{"sigla": r[0], "nombre": r[1]} for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT DISTINCT UPPER(TRIM(tipo_documento))
                    FROM audit_metrics_ledger
                    WHERE tipo_documento IS NOT NULL AND TRIM(tipo_documento) <> ''
                    ORDER BY 1;
                    """
                )
                avail_doc_types = [r[0] for r in cur.fetchall()]

                cur.execute(
                    """
                    SELECT DISTINCT TRIM(ramo)
                    FROM (
                        SELECT ramo FROM audit_metrics_ledger WHERE ramo IS NOT NULL AND TRIM(ramo) <> ''
                        UNION
                        SELECT ramo FROM policy_envelopes WHERE ramo IS NOT NULL AND TRIM(ramo) <> ''
                    ) r
                    ORDER BY 1;
                    """
                )
                avail_ramos = [r[0] for r in cur.fetchall()]

        # Assemble structured Python dictionaries
        docs_extracted = max(int(l_row[0] or 0), int(s_row[0] or 0))
        jobs_completed = int(j_row[1] or 0)
        jobs_failed = int(j_row[2] or 0)
        jobs_skipped = int(j_row[3] or 0)
        finished_jobs = jobs_completed + jobs_skipped + jobs_failed
        success_rate = round(((jobs_completed + jobs_skipped) / finished_jobs) * 100.0, 2) if finished_jobs > 0 else 100.0
        error_rate = round((jobs_failed / finished_jobs) * 100.0, 2) if finished_jobs > 0 else 0.0

        stats_count = int(s_row[0] or 0)
        ocr_count = int(s_row[20] or 0)
        ocr_rate = round((ocr_count / stats_count) * 100.0, 2) if stats_count > 0 else 0.0

        avg_ext = float(s_row[7] or 0.0)
        avg_pipe = float(s_row[12] or 0.0)

        week_docs = int(snap_l[5] or 0)
        prev_week_docs = int(snap_l[10] or 0)
        week_growth_pct: float | None = None
        if prev_week_docs > 0:
            week_growth_pct = round(((week_docs - prev_week_docs) / prev_week_docs) * 100.0, 1)

        total_chunks_val = max(int(l_row[9] or 0), int(s_row[4] or 0))
        total_pages_val = max(int(l_row[7] or 0), int(s_row[1] or 0))
        total_tables_val = max(int(l_row[8] or 0), int(s_row[2] or 0))
        total_tokens_val = max(int(l_row[11] or 0), int(s_row[18] or 0))
        total_cost_val = max(float(l_row[12] or 0.0), float(s_row[19] or 0.0))

        kpis = {
            "documents_extracted_total": docs_extracted,
            "active_documents": int(pol_row[0] or 0),
            "documents_deleted_total": int(l_row[1] or 0),
            "total_envelopes_historical": max(int(l_row[2] or 0), int(env_row[0] or 0)),
            "active_envelopes": int(env_row[0] or 0),
            "envelopes_deleted_total": int(l_row[3] or 0),
            "unique_clients": max(int(l_row[6] or 0), int(pol_row[1] or 0), int(env_row[1] or 0)),
            "total_pages_processed": total_pages_val,
            "total_tables_detected": total_tables_val,
            "total_coberturas_extracted": int(s_row[3] or 0),
            "total_chunks_created": total_chunks_val,
            "parent_chunks_count": int(s_row[5] or 0),
            "child_chunks_count": int(s_row[6] or 0),
            "total_volume_bytes": max(int(l_row[10] or 0), int(pol_row[2] or 0)),
            "jobs_total": int(j_row[0] or 0),
            "jobs_completed": jobs_completed,
            "jobs_failed": jobs_failed,
            "jobs_skipped": jobs_skipped,
            "jobs_processing": int(j_row[4] or 0),
            "jobs_pending": int(j_row[5] or 0),
            "success_rate_pct": success_rate,
            "error_rate_pct": error_rate,
            "failure_events_ledger": int(l_row[5] or 0),
            "duplicate_events_ledger": int(l_row[4] or 0),
            "avg_extraction_time_seconds": round(avg_ext, 3),
            "avg_time_per_page_seconds": round(float(s_row[8] or 0.0), 3),
            "avg_chunking_time_seconds": round(float(s_row[9] or 0.0), 3),
            "avg_embedding_time_seconds": round(float(s_row[10] or 0.0), 3),
            "avg_openai_time_seconds": round(float(s_row[11] or 0.0), 3),
            "avg_pipeline_time_seconds": round(avg_pipe, 3),
            "avg_end_to_end_seconds": round(avg_ext + avg_pipe, 3),
            "p95_pipeline_time_seconds": round(float(s_row[13] or 0.0), 3),
            "max_memory_peak_mb": round(float(s_row[14] or 0.0), 2),
            "avg_memory_peak_mb": round(float(s_row[15] or 0.0), 2),
            "openai_prompt_tokens": int(s_row[16] or 0),
            "openai_completion_tokens": int(s_row[17] or 0),
            "openai_total_tokens": total_tokens_val,
            "openai_estimated_cost_usd": round(total_cost_val, 5),
            "ocr_applied_count": ocr_count,
            "ocr_rate_pct": ocr_rate,
            "avg_scanned_page_ratio": round(float(s_row[21] or 0.0), 3),
            "fleet_vehicles_count": fleet_count,
            "insured_persons_count": insured_count,
            "section_summaries_count": summaries_count,
            "high_water_extractions": 0,
            "high_water_pages": 0,
            "high_water_tables": 0,
        }

        period_snapshot = {
            "today_documents": int(snap_l[0] or 0),
            "today_pages": int(snap_l[1] or 0),
            "today_errors": int(snap_l[2] or 0) + int(snap_j[0] or 0),
            "today_envelopes": int(snap_l[3] or 0),
            "today_cost_usd": round(float(snap_l[4] or 0.0), 5),
            "week_documents": week_docs,
            "week_pages": int(snap_l[6] or 0),
            "week_errors": int(snap_l[7] or 0) + int(snap_j[1] or 0),
            "week_envelopes": int(snap_l[8] or 0),
            "week_cost_usd": round(float(snap_l[9] or 0.0), 5),
            "prev_week_documents": prev_week_docs,
            "week_growth_pct": week_growth_pct,
        }

        time_series = []
        for r in ts_rows:
            p_key = str(r[0])
            p_label = f"Sem {p_key}" if clean_granularity == "weekly" else p_key
            time_series.append(
                {
                    "period": p_key,
                    "period_label": p_label,
                    "documents_extracted": int(r[1] or 0),
                    "duplicates_skipped": int(r[2] or 0),
                    "jobs_completed": int(r[3] or 0),
                    "jobs_failed": int(r[4] or 0),
                    "jobs_skipped": int(r[5] or 0),
                    "envelopes_created": int(r[6] or 0),
                    "deletions_count": int(r[7] or 0),
                    "pages_processed": int(r[8] or 0),
                    "tables_detected": int(r[9] or 0),
                    "chunks_created": int(r[10] or 0),
                    "volume_bytes": int(r[11] or 0),
                    "avg_extraction_time_seconds": float(r[12] or 0.0),
                    "avg_pipeline_time_seconds": float(r[13] or 0.0),
                    "openai_tokens": int(r[14] or 0),
                    "openai_cost_usd": round(float(r[15] or 0.0), 5),
                }
            )

        by_company = [
            {
                "company_sigla": r[0],
                "company_name": r[1],
                "documents_count": int(r[2] or 0),
                "active_documents_count": int(r[3] or 0),
                "envelopes_count": int(r[4] or 0),
                "pages_count": int(r[5] or 0),
                "tables_count": int(r[6] or 0),
                "chunks_count": int(r[7] or 0),
                "coberturas_count": int(r[8] or 0),
                "volume_bytes": int(r[9] or 0),
                "avg_extraction_time_seconds": float(r[10] or 0.0),
                "avg_pipeline_time_seconds": float(r[11] or 0.0),
                "openai_tokens": int(r[12] or 0),
                "openai_cost_usd": round(float(r[13] or 0.0), 5),
                "failed_count": int(r[14] or 0),
                "deleted_count": int(r[15] or 0),
            }
            for r in co_rows
        ]

        by_ramo = [
            {
                "ramo": r[0],
                "ramo_tipo": r[1],
                "envelopes_count": int(r[2] or 0),
                "documents_count": int(r[3] or 0),
                "pages_count": int(r[4] or 0),
                "tables_count": int(r[5] or 0),
                "openai_cost_usd": round(float(r[6] or 0.0), 5),
            }
            for r in ramo_rows
        ]

        by_document_type = [
            {
                "tipo_documento": r[0],
                "documents_count": int(r[1] or 0),
                "pages_count": int(r[2] or 0),
                "tables_count": int(r[3] or 0),
                "chunks_count": int(r[4] or 0),
            }
            for r in doctype_rows
        ]

        by_file_type = [
            {
                "file_type": r[0],
                "documents_count": int(r[1] or 0),
                "ocr_applied_count": int(r[2] or 0),
                "pages_count": int(r[3] or 0),
                "avg_time_per_page_seconds": float(r[4] or 0.0),
                "avg_extraction_time_seconds": float(r[5] or 0.0),
            }
            for r in ftype_rows
        ]

        ledger_event_summary = [
            {"event_type": r[0], "count": int(r[1] or 0)} for r in event_summary_rows
        ]

        error_categories = [
            {
                "category": r[0],
                "count": int(r[1] or 0),
                "latest_at": r[2],
                "sample_message": r[3],
            }
            for r in err_cat_rows
        ]

        protected_tables = sorted({str(r[1]) for r in worm_rows})
        trigger_names = [str(r[0]) for r in worm_rows]
        worm_status = {
            "active": len(trigger_names) >= 6,
            "protected_tables": protected_tables,
            "triggers_count": len(trigger_names),
            "trigger_names": trigger_names,
        }

        return {
            "kpis": kpis,
            "period_snapshot": period_snapshot,
            "granularity": clean_granularity,
            "time_series": time_series,
            "by_company": by_company,
            "by_ramo": by_ramo,
            "by_document_type": by_document_type,
            "by_file_type": by_file_type,
            "ledger_event_summary": ledger_event_summary,
            "error_categories": error_categories,
            "worm_status": worm_status,
            "filters_applied": {
                "granularity": clean_granularity,
                "date_from": _validate_iso_date(date_from),
                "date_to": _validate_iso_date(date_to),
                "company_sigla": company_sigla.strip().upper() if company_sigla else None,
                "ramo": ramo.strip() if ramo else None,
                "tipo_documento": tipo_documento.strip().upper() if tipo_documento else None,
                "file_type": file_type.strip().upper() if file_type else None,
            },
            "available_filters": {
                "companies": avail_companies,
                "document_types": avail_doc_types,
                "ramos": avail_ramos,
                "file_types": ["DIGITAL", "SCANNED", "HYBRID", "UNKNOWN"],
            },
        }

    # ------------------------------------------------------------------
    # Paginated Drill-down Tables
    # ------------------------------------------------------------------

    def list_audit_ledger(
        self,
        limit: int = 50,
        offset: int = 0,
        date_from: str | None = None,
        date_to: str | None = None,
        company_sigla: str | None = None,
        ramo: str | None = None,
        tipo_documento: str | None = None,
        event_type: str | None = None,
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return paginated rows from immutable audit_metrics_ledger."""
        where_sql, params = self._build_ledger_where(
            date_from=date_from,
            date_to=date_to,
            company_sigla=company_sigla,
            ramo=ramo,
            tipo_documento=tipo_documento,
            event_type=event_type,
            search=search,
            alias="aml",
        )
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM audit_metrics_ledger aml {where_sql};", tuple(params))
                total = int((cur.fetchone() or [0])[0] or 0)

                cur.execute(
                    f"""
                    SELECT
                        aml.event_id::text,
                        aml.event_type,
                        aml.policy_id::text,
                        aml.envelope_id::text,
                        aml.job_id::text,
                        aml.numero_poliza,
                        aml.company_sigla,
                        aml.ramo,
                        aml.tipo_documento,
                        aml.id_cliente,
                        aml.nombre_cliente,
                        aml.file_name,
                        aml.file_hash,
                        aml.pages_count,
                        aml.tables_count,
                        aml.chunks_count,
                        aml.file_size_bytes,
                        aml.duration_seconds,
                        aml.openai_tokens,
                        aml.openai_cost_usd,
                        COALESCE(aml.metadata, '{{}}'::jsonb),
                        aml.created_at::text
                    FROM audit_metrics_ledger aml
                    {where_sql}
                    ORDER BY aml.created_at DESC
                    LIMIT %s OFFSET %s;
                    """,
                    tuple(params + [max(1, limit), max(0, offset)]),
                )
                rows = cur.fetchall()

        items = [
            {
                "event_id": r[0],
                "event_type": r[1],
                "policy_id": r[2],
                "envelope_id": r[3],
                "job_id": r[4],
                "numero_poliza": r[5],
                "company_sigla": r[6],
                "ramo": r[7],
                "tipo_documento": r[8],
                "id_cliente": r[9],
                "nombre_cliente": r[10],
                "file_name": r[11],
                "file_hash": r[12],
                "pages_count": int(r[13] or 0),
                "tables_count": int(r[14] or 0),
                "chunks_count": int(r[15] or 0),
                "file_size_bytes": int(r[16] or 0),
                "duration_seconds": float(r[17] or 0.0),
                "openai_tokens": int(r[18] or 0),
                "openai_cost_usd": float(r[19] or 0.0),
                "metadata": r[20] if isinstance(r[20], dict) else {},
                "created_at": r[21],
            }
            for r in rows
        ]
        return items, total

    def list_processing_stats(
        self,
        limit: int = 50,
        offset: int = 0,
        date_from: str | None = None,
        date_to: str | None = None,
        company_sigla: str | None = None,
        ramo: str | None = None,
        tipo_documento: str | None = None,
        file_type: str | None = None,
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return paginated rows from policy_processing_stats."""
        where_sql, params = self._build_stats_where(
            date_from=date_from,
            date_to=date_to,
            company_sigla=company_sigla,
            ramo=ramo,
            tipo_documento=tipo_documento,
            file_type=file_type,
            search=search,
            alias="pps",
        )
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM policy_processing_stats pps {where_sql};", tuple(params))
                total = int((cur.fetchone() or [0])[0] or 0)

                cur.execute(
                    f"""
                    SELECT
                        COALESCE(pps.stat_id::text, pps.policy_id::text, gen_random_uuid()::text),
                        pps.policy_id::text,
                        pps.envelope_id::text,
                        pps.job_id::text,
                        pps.policy_number,
                        pps.company_sigla,
                        pps.file_name,
                        pps.file_hash,
                        pps.tipo_documento,
                        pps.id_cliente,
                        pps.file_type,
                        COALESCE(pps.ocr_applied, FALSE),
                        pps.scanned_page_ratio,
                        pps.total_pages,
                        pps.extraction_time_seconds,
                        pps.time_per_page_seconds,
                        pps.chunking_time_seconds,
                        pps.embedding_time_seconds,
                        pps.openai_time_seconds,
                        pps.total_pipeline_time_seconds,
                        pps.total_chunks,
                        COALESCE(pps.parent_chunks, 0),
                        COALESCE(pps.child_chunks, 0),
                        COALESCE(pps.openai_prompt_tokens, 0),
                        COALESCE(pps.openai_completion_tokens, 0),
                        COALESCE(pps.openai_total_tokens, 0),
                        COALESCE(pps.openai_estimated_cost_usd, 0),
                        COALESCE(pps.coberturas_extracted_count, 0),
                        COALESCE(pps.tables_detected, 0),
                        pps.memory_peak_mb,
                        pps.created_at::text
                    FROM policy_processing_stats pps
                    {where_sql}
                    ORDER BY pps.created_at DESC
                    LIMIT %s OFFSET %s;
                    """,
                    tuple(params + [max(1, limit), max(0, offset)]),
                )
                rows = cur.fetchall()

        items = [
            {
                "stat_id": r[0],
                "policy_id": r[1],
                "envelope_id": r[2],
                "job_id": r[3],
                "policy_number": r[4],
                "company_sigla": r[5],
                "file_name": r[6],
                "file_hash": r[7],
                "tipo_documento": r[8],
                "id_cliente": r[9],
                "file_type": r[10],
                "ocr_applied": bool(r[11]),
                "scanned_page_ratio": float(r[12]) if r[12] is not None else None,
                "total_pages": int(r[13] or 0),
                "extraction_time_seconds": float(r[14] or 0.0),
                "time_per_page_seconds": float(r[15] or 0.0),
                "chunking_time_seconds": float(r[16] or 0.0),
                "embedding_time_seconds": float(r[17] or 0.0),
                "openai_time_seconds": float(r[18] or 0.0),
                "total_pipeline_time_seconds": float(r[19] or 0.0),
                "total_chunks": int(r[20] or 0),
                "parent_chunks": int(r[21] or 0),
                "child_chunks": int(r[22] or 0),
                "openai_prompt_tokens": int(r[23] or 0),
                "openai_completion_tokens": int(r[24] or 0),
                "openai_total_tokens": int(r[25] or 0),
                "openai_estimated_cost_usd": float(r[26] or 0.0),
                "coberturas_extracted_count": int(r[27] or 0),
                "tables_detected": int(r[28] or 0),
                "memory_peak_mb": float(r[29]) if r[29] is not None else None,
                "created_at": r[30],
            }
            for r in rows
        ]
        return items, total

    def list_jobs_and_errors(
        self,
        limit: int = 50,
        offset: int = 0,
        date_from: str | None = None,
        date_to: str | None = None,
        company_sigla: str | None = None,
        status_filter: str | None = None,
        search: str | None = None,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        """Return paginated processing_jobs enriched with company/policy info and status counts."""
        where_sql, params = self._build_jobs_where(
            date_from=date_from,
            date_to=date_to,
            company_sigla=company_sigla,
            status_filter=status_filter,
            search=search,
            alias="pj",
        )
        # Status summary ignores status_filter so tabs show counts for all statuses under active date/company filters
        base_where, base_params = self._build_jobs_where(
            date_from=date_from,
            date_to=date_to,
            company_sigla=company_sigla,
            status_filter=None,
            search=search,
            alias="pj",
        )

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT pj.status, COUNT(*) FROM processing_jobs pj {base_where} GROUP BY pj.status;",
                    tuple(base_params),
                )
                status_counts = {str(r[0]): int(r[1] or 0) for r in cur.fetchall()}

                cur.execute(f"SELECT COUNT(*) FROM processing_jobs pj {where_sql};", tuple(params))
                total = int((cur.fetchone() or [0])[0] or 0)

                cur.execute(
                    f"""
                    SELECT
                        pj.job_id::text,
                        pj.file_name,
                        pj.status,
                        pj.error_message,
                        pj.policy_id::text,
                        COALESCE(
                            (SELECT pps.company_sigla FROM policy_processing_stats pps WHERE pps.job_id = pj.job_id LIMIT 1),
                            (SELECT p.company_sigla FROM policies p WHERE p.id = pj.policy_id LIMIT 1),
                            (SELECT aml.company_sigla FROM audit_metrics_ledger aml WHERE aml.job_id = pj.job_id LIMIT 1)
                        ) AS company_sigla,
                        COALESCE(
                            (SELECT pps.policy_number FROM policy_processing_stats pps WHERE pps.job_id = pj.job_id LIMIT 1),
                            (SELECT aml.numero_poliza FROM audit_metrics_ledger aml WHERE aml.job_id = pj.job_id LIMIT 1)
                        ) AS numero_poliza,
                        pj.created_at::text,
                        pj.updated_at::text,
                        EXTRACT(EPOCH FROM (pj.updated_at - pj.created_at))::numeric(10,2) AS duration_sec
                    FROM processing_jobs pj
                    {where_sql}
                    ORDER BY pj.created_at DESC
                    LIMIT %s OFFSET %s;
                    """,
                    tuple(params + [max(1, limit), max(0, offset)]),
                )
                rows = cur.fetchall()

        items = [
            {
                "job_id": r[0],
                "file_name": r[1],
                "status": r[2],
                "error_message": r[3],
                "policy_id": r[4],
                "company_sigla": r[5],
                "numero_poliza": r[6],
                "created_at": r[7],
                "updated_at": r[8],
                "duration_seconds": float(r[9]) if r[9] is not None else None,
            }
            for r in rows
        ]
        return items, total, status_counts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_count(cur: Any, table_name: str) -> int:
        try:
            cur.execute(f"SAVEPOINT sp_cnt_{table_name};")
            cur.execute(f"SELECT COUNT(*) FROM {table_name};")
            row = cur.fetchone()
            cur.execute(f"RELEASE SAVEPOINT sp_cnt_{table_name};")
            return int(row[0] or 0) if row else 0
        except Exception:
            try:
                cur.execute(f"ROLLBACK TO SAVEPOINT sp_cnt_{table_name};")
            except Exception:
                pass
            return 0


"""DocEngine — Batch Initial Load Runner.

Processes bulk insurance policy PDFs distributed in hierarchical folders:
    {EMPRESA ASEGURADORA}/{RAMO}/{CONTRATO}/{POLIZA}/{TIPO_DOC}/{FILE}.pdf

Features:
- Full end-to-end ingestion:
    1. Extraction with company-specific merged Skill
    2. Local storage persistence (Markdown + JSON)
    3. PostgreSQL RAG vectorization (Parent-Child chunking + embeddings)
    4. Policy envelope grouping (numero_poliza, ramo, tipo_documento)
- Idempotency & Resumability:
    SQLite checkpoint tracker (.batch_checkpoint.sqlite) skips previously completed files.
- Fault Tolerance:
    Per-file try/except prevents bad/encrypted PDFs from interrupting the batch.
- Comprehensive Auditing & Logging:
    Generates batch_execution.log, batch_status.csv, and batch_report.txt.
- Multiplatform:
    Compatible with Windows and Linux (respecting .env.linux / .env.windows).

Usage:
    python scripts/batch_initial_load.py --dry-run
    python scripts/batch_initial_load.py --limit 5
    python scripts/batch_initial_load.py --company BIS
    python scripts/batch_initial_load.py
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import gc
import logging
from pathlib import Path
import re
import sqlite3
import sys
import time
from typing import Any
import unicodedata

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.application.company_skill_loader import (  # noqa: E402
    COMPANY_REGISTRY,
    load_company_skill_merged,
)
from app.application.extraction_service import ExtractionService  # noqa: E402
from app.application.markdown_service import MarkdownService  # noqa: E402
from app.application.metadata_service import MetadataService  # noqa: E402
from app.application.validation_service import ValidationService  # noqa: E402
from app.cli.rag_factory import create_rag_pipeline_service  # noqa: E402
from app.config.settings import AppSettings, get_settings  # noqa: E402
from app.domain.models.document import compute_sha256  # noqa: E402
from app.domain.models.envelope import normalize_document_type  # noqa: E402
from app.domain.models.extraction import ExtractionRequest, ExtractionStatus  # noqa: E402
from app.infrastructure.storage.local_storage import LocalStorageService  # noqa: E402

# ---------------------------------------------------------------------------
# Company Normalization Mapping
# ---------------------------------------------------------------------------

COMPANY_NAME_TO_SIGLA: dict[str, str] = {
    "ALIANZA CIA DE SEGUROS Y REASEGUROS SA": "ALI",
    "ALIANZA VIDA SEGUROS Y REASEGUROS SA": "ALV",
    "ALIANZA VIDA SEGUROS Y REASEGUROS S.A": "ALV",
    "BISA SEGUROS Y REASEGUROS": "BIS",
    "COMPANIA DE SEGUROS DE VIDA FORTALEZA SA": "FOV",
    "COMPANIA DE SEGUROS DE VIDA FORTALEZA S.A": "FOV",
    "CREDINFORM INTERNATIONAL SA": "CRI",
    "CREDINFORM INTERNATIONAL S.A": "CRI",
    "CREDISEGURO SA SEGUROS GENERALES": "CRG",
    "CREDISEGURO S.A. SEGUROS GENERALES": "CRG",
    "CREDISEGURO SA SEGUROS PERSONALES": "CRP",
    "CREDISEGURO S.A. SEGUROS PERSONALES": "CRP",
    "FORTALEZA COMPANIA DE SEGUROS Y REASEGUROS": "FOR",
    "FORTALEZA COMPANIA DE SEGUROS Y REASEGUROS": "FOR",
    "LA BOLIVIANA CIACRUZ DE SEGUROS Y REASEGUROS": "LBC",
    "LA BOLIVIANA CIACRUZ SEGUROS PERSONALES": "LBP",
    "LA VITALICIA DE SEGUROS Y REASEGUROS": "VIT",
    "MERCANTIL SANTA CRUZ SEGUROS Y REASEGUROS GENERALES SA": "MSC",
    "MERCANTIL SANTA CRUZ SEGUROS Y REASEGUROS GENERALES S.A": "MSC",
    "NACIONAL SEGUROS PATRIMONIALES Y FIANZAS SA": "NPF",
    "NACIONAL SEGUROS PATRIMONIALES Y FIANZAS S.A": "NPF",
    "NACIONAL SEGUROS VIDA Y SALUD SA": "NVS",
    "NACIONAL SEGUROS VIDA Y SALUD S.A": "NVS",
    "SEGUROS Y REASEGUROS PERSONALES UNIVIDA SA": "UNI",
    "SEGUROS Y REASEGUROS PERSONALES UNIVIDA S.A": "UNI",
    "UNIBIENES SEGUROS Y REASEGUROS": "UBI",
}


def _strip_accents(text: str) -> str:
    """Normalize and remove diacritical marks."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).strip()


_NORMALIZED_COMPANY_MAP: dict[str, str] = {
    re.sub(r"[^A-Z0-9]+", " ", _strip_accents(k).upper()).strip(): v
    for k, v in COMPANY_NAME_TO_SIGLA.items()
}


def resolve_company_sigla(folder_name: str) -> str | None:
    """Resolve insurer folder name to 3-letter SIGLA.

    Args:
        folder_name: Raw directory name from filesystem.

    Returns:
        3-letter SIGLA (e.g. 'BIS', 'ALI') or None if unmapped.
    """
    clean = re.sub(r"[^A-Z0-9]+", " ", _strip_accents(folder_name).upper()).strip()
    if clean in _NORMALIZED_COMPANY_MAP:
        return _NORMALIZED_COMPANY_MAP[clean]

    # Partial / substring fallback
    for norm_name, sigla in _NORMALIZED_COMPANY_MAP.items():
        if norm_name in clean or clean in norm_name:
            return sigla

    return None


# ---------------------------------------------------------------------------
# Path & Metadata Discovery
# ---------------------------------------------------------------------------


@dataclass
class DocumentJob:
    """Information extracted from the folder hierarchy for one PDF."""

    file_path: Path
    rel_path: str
    company_sigla: str
    company_name: str
    ramo: str
    tipo_contrato: str
    numero_poliza: str
    tipo_doc_raw: str
    tipo_documento: str
    file_size_bytes: int


def parse_document_job(pdf_path: Path, root_dir: Path) -> DocumentJob | None:
    """Parse hierarchical directory structure into DocumentJob metadata."""
    rel = pdf_path.relative_to(root_dir)
    parts = rel.parts

    if len(parts) < 2:
        return None

    company_folder = parts[0]
    sigla = resolve_company_sigla(company_folder)
    if not sigla:
        return None

    # Standard expected structure (6 levels):
    # [0] Empresa / [1] Ramo / [2] Contrato / [3] Poliza / [4] TipoDoc / [5] File.pdf
    if len(parts) >= 6:
        ramo = parts[1].strip()
        contrato = parts[2].strip()
        poliza = parts[3].strip()
        tipo_doc_raw = parts[4].strip()
    elif len(parts) == 5:
        ramo = parts[1].strip()
        contrato = "DESCONOCIDO"
        poliza = parts[2].strip()
        tipo_doc_raw = parts[3].strip()
    else:
        ramo = parts[1].strip() if len(parts) > 2 else "GENERAL"
        contrato = "DESCONOCIDO"
        poliza = parts[-2].strip() if len(parts) > 2 else "0"
        tipo_doc_raw = parts[-2].strip()

    # Determine resolved tipo_documento:
    # 1. Try file name classification first
    resolved_tipo = normalize_document_type(pdf_path.name)
    # 2. If filename gives generic 'OTRO' or itself, check folder name
    if resolved_tipo in ("OTRO", None) or resolved_tipo == pdf_path.stem:
        resolved_tipo = normalize_document_type(tipo_doc_raw) or tipo_doc_raw.upper()

    return DocumentJob(
        file_path=pdf_path,
        rel_path=str(rel),
        company_sigla=sigla,
        company_name=company_folder,
        ramo=ramo,
        tipo_contrato=contrato,
        numero_poliza=poliza,
        tipo_doc_raw=tipo_doc_raw,
        tipo_documento=resolved_tipo or "DOCUMENTO",
        file_size_bytes=pdf_path.stat().st_size,
    )


# ---------------------------------------------------------------------------
# Checkpoint Database (SQLite)
# ---------------------------------------------------------------------------


class CheckpointManager:
    """SQLite-backed checkpoint tracker for resumable batch execution."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS batch_checkpoint (
                    file_hash TEXT PRIMARY KEY,
                    rel_path TEXT NOT NULL,
                    company_sigla TEXT NOT NULL,
                    numero_poliza TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_seconds REAL,
                    pages INTEGER,
                    chunks INTEGER,
                    error_message TEXT,
                    processed_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chk_status ON batch_checkpoint(status);"
            )
            conn.commit()

    def is_completed(self, file_hash: str) -> bool:
        """Check if file hash was already successfully processed."""
        if not file_hash:
            return False
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT status FROM batch_checkpoint WHERE file_hash = ?;",
                (file_hash,),
            )
            row = cur.fetchone()
            return row is not None and row[0] in ("SUCCESS", "SKIPPED_DUPLICATE")

    def record_job(
        self,
        file_hash: str,
        rel_path: str,
        company_sigla: str,
        numero_poliza: str,
        status: str,
        duration_seconds: float,
        pages: int = 0,
        chunks: int = 0,
        error_message: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Record or update execution checkpoint for a file."""
        now_str = datetime.now(tz=timezone.utc).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO batch_checkpoint (
                    file_hash, rel_path, company_sigla, numero_poliza, status,
                    duration_seconds, pages, chunks, error_message, processed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    file_hash,
                    rel_path,
                    company_sigla,
                    numero_poliza,
                    status,
                    duration_seconds,
                    pages,
                    chunks,
                    error_message,
                    now_str,
                ),
            )
            conn.commit()


# ---------------------------------------------------------------------------
# Status CSV & Reporting
# ---------------------------------------------------------------------------


class BatchReporter:
    """Manages appending status CSV lines and writing human-readable summary reports."""

    def __init__(self, csv_path: Path, report_path: Path) -> None:
        self.csv_path = csv_path
        self.report_path = report_path
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_csv()

    def _init_csv(self) -> None:
        if not self.csv_path.exists():
            with self.csv_path.open("w", encoding="utf-8") as f:
                f.write(
                    "timestamp,rel_path,company_sigla,numero_poliza,ramo,tipo_documento,"
                    "status,duration_seconds,pages,tables,chunks,error_msg\n"
                )

    def log_result(
        self,
        job: DocumentJob,
        status: str,
        duration: float,
        pages: int = 0,
        tables: int = 0,
        chunks: int = 0,
        error_msg: str = "",
    ) -> None:
        """Append result row to CSV."""
        now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        clean_err = error_msg.replace(",", ";").replace("\n", " ").strip()
        clean_path = job.rel_path.replace(",", "_")
        line = (
            f"{now_str},{clean_path},{job.company_sigla},{job.numero_poliza},"
            f"{job.ramo},{job.tipo_documento},{status},{duration:.2f},"
            f"{pages},{tables},{chunks},{clean_err}\n"
        )
        with self.csv_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def write_summary_report(
        self,
        start_time: float,
        total_discovered: int,
        processed_count: int,
        skipped_count: int,
        error_count: int,
        total_pages: int,
        total_chunks: int,
        failed_jobs: list[tuple[DocumentJob, str]],
    ) -> None:
        """Write human-readable report to batch_report.txt."""
        elapsed = time.perf_counter() - start_time
        avg_time = elapsed / max(1, processed_count)

        with self.report_path.open("w", encoding="utf-8") as f:
            f.write("=" * 70 + "\n")
            f.write("        DocEngine — REPORTE DE EJECUCIÓN BATCH INICIAL\n")
            f.write("=" * 70 + "\n")
            f.write(
                f"Fecha de reporte   : {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            )
            f.write(f"Tiempo total       : {elapsed:.2f} s ({elapsed / 60:.2f} min)\n")
            f.write(f"Total PDFs hallados: {total_discovered}\n")
            f.write(f"Procesados con éxito: {processed_count}\n")
            f.write(f"Omitidos (previos) : {skipped_count}\n")
            f.write(f"Fallidos con error : {error_count}\n")
            f.write(f"Páginas extraídas  : {total_pages}\n")
            f.write(f"Chunks vectorizados: {total_chunks}\n")
            f.write(f"Tiempo promedio/doc: {avg_time:.2f} s\n")
            f.write("=" * 70 + "\n\n")

            if failed_jobs:
                f.write("LISTADO DE DOCUMENTOS CON ERRORES:\n")
                f.write("-" * 70 + "\n")
                for j, err in failed_jobs:
                    f.write(f"• Archivo: {j.rel_path}\n")
                    f.write(f"  Póliza : {j.numero_poliza} [{j.company_sigla}]\n")
                    f.write(f"  Error  : {err}\n\n")
            else:
                f.write("¡Todos los documentos fueron procesados sin errores!\n")


# ---------------------------------------------------------------------------
# Service Builders
# ---------------------------------------------------------------------------


def build_extraction_service(settings: AppSettings) -> ExtractionService:
    """Build ExtractionService instance according to settings."""
    if getattr(settings, "extractor_engine", "pdfextract") == "pdfextract":
        from app.infrastructure.adapters.pdfextract_adapter import PdfExtractAdapter
        extractor = PdfExtractAdapter(config=settings)
    else:
        from app.infrastructure.adapters.docling_adapter import DoclingAdapter
        extractor = DoclingAdapter(config=settings)

    return ExtractionService(
        extractor=extractor,
        markdown_service=MarkdownService(config=settings),
        metadata_service=MetadataService(),
        validation_service=ValidationService(config=settings),
        storage=LocalStorageService(config=settings),
        config=settings,
    )


# ---------------------------------------------------------------------------
# Main Execution Loop
# ---------------------------------------------------------------------------


def run_batch(
    source_dir: Path,
    company_filter: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
    resume: bool = True,
    skip_rag: bool = False,
    checkpoint_db_path: Path | None = None,
    report_path: Path | None = None,
    csv_path: Path | None = None,
    log_file_path: Path | None = None,
    torch_threads: int | None = None,
) -> None:
    """Execute bulk processing of policy documents."""
    start_total_time = time.perf_counter()

    # Paths setup
    chk_path = checkpoint_db_path or (source_dir / ".batch_checkpoint.sqlite")
    rep_path = report_path or (source_dir / "batch_report.txt")
    c_path = csv_path or (source_dir / "batch_status.csv")
    l_path = log_file_path or (source_dir / "batch_execution.log")

    # Logging setup
    logger = logging.getLogger("batch_loader")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    # Console handler
    c_handler = logging.StreamHandler(sys.stdout)
    c_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    )
    logger.addHandler(c_handler)

    # File handler
    f_handler = logging.FileHandler(l_path, encoding="utf-8")
    f_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(f_handler)

    logger.info("=" * 60)
    logger.info("Iniciando Proceso Batch de Carga Inicial — DocEngine")
    logger.info(f"Directorio origen: {source_dir.resolve()}")
    logger.info(
        f"Modo: {'DRY RUN (Simulación)' if dry_run else 'PRODUCCIÓN (Ingesta Completa)'}"
    )
    logger.info(f"Filtro empresa   : {company_filter or 'TODAS (16 aseguradoras)'}")
    logger.info(f"Límite           : {limit or 'SIN LÍMITE'}")
    logger.info(f"Persistencia RAG : {'DESACTIVADA (--skip-rag)' if skip_rag else 'ACTIVADA (PostgreSQL)'}")
    logger.info(f"Reanudación      : {'ACTIVADA' if resume else 'DESACTIVADA'}")
    logger.info("=" * 60)

    # 1. Discover all PDF files
    logger.info("Escaneando archivos PDF en el directorio...")
    all_pdfs = sorted(source_dir.rglob("*.pdf"))
    logger.info(f"Se encontraron {len(all_pdfs)} archivos PDF en total.")

    # 2. Parse and filter jobs
    jobs: list[DocumentJob] = []
    unmapped_count = 0
    for pdf in all_pdfs:
        job = parse_document_job(pdf, source_dir)
        if not job:
            unmapped_count += 1
            continue
        if company_filter and job.company_sigla != company_filter.upper():
            continue
        jobs.append(job)

    if unmapped_count:
        logger.warning(
            f"Se omitieron {unmapped_count} archivos cuyo directorio no coincide con ninguna aseguradora registrada."
        )

    logger.info(f"Archivos listos para procesar tras filtros: {len(jobs)}")

    if limit and limit > 0:
        jobs = jobs[:limit]
        logger.info(f"Aplicando límite: se procesarán únicamente los primeros {len(jobs)} archivos.")

    if not jobs:
        logger.info("No hay archivos para procesar.")
        return

    # Checkpoint & Reporter
    checkpoint = CheckpointManager(chk_path)
    reporter = BatchReporter(c_path, rep_path)

    # Dry-run check
    if dry_run:
        logger.info("\n--- RESUMEN DE ARCHIVOS DETECTADOS (DRY RUN) ---")
        by_company: dict[str, int] = {}
        for j in jobs:
            by_company[j.company_sigla] = by_company.get(j.company_sigla, 0) + 1

        for sigla, cnt in sorted(by_company.items()):
            logger.info(f"  [{sigla}] {COMPANY_REGISTRY.get(sigla, sigla)}: {cnt} PDFs")

        logger.info("\nPrimeros 5 archivos de muestra:")
        for idx, j in enumerate(jobs[:5], 1):
            logger.info(
                f"  {idx}. [{j.company_sigla}] Poliza: {j.numero_poliza} | Tipo: {j.tipo_documento} | {j.rel_path}"
            )
        logger.info("\n[DRY RUN FINALIZADO] Rutas y metadatos verificados correctamente. No se realizaron cambios.")
        return

    # 3. Initialize Services
    settings = get_settings()
    logger.info(f"Inicializando ExtractionService (Motor: {getattr(settings, 'extractor_engine', 'pdfextract')})...")
    extraction_service = build_extraction_service(settings)

    rag_service = None
    if not skip_rag:
        logger.info("Inicializando RagPipelineService y conexión a PostgreSQL...")
        try:
            rag_service = create_rag_pipeline_service()
            logger.info("Conexión con PostgreSQL + pgvector establecida exitosamente.")
        except Exception as exc:
            logger.error(f"Error al conectar con PostgreSQL para RAG: {exc}")
            logger.error("Si deseas extraer únicamente a disco sin base de datos, ejecuta con --skip-rag.")
            sys.exit(1)

    effective_torch_threads = torch_threads or getattr(settings.embedding, "num_threads", None)
    if effective_torch_threads:
        try:
            import torch
            torch.set_num_threads(effective_torch_threads)
            logger.info(f"PyTorch thread pool explícitamente configurado a {effective_torch_threads} hilos.")
        except Exception:
            pass

    # 4. Processing Loop
    processed_count = 0
    skipped_count = 0
    error_count = 0
    total_pages = 0
    total_chunks = 0
    failed_jobs: list[tuple[DocumentJob, str]] = []

    logger.info("\nIniciando ciclo de procesamiento...")

    try:
        for idx, job in enumerate(jobs, 1):
            t0 = time.perf_counter()
            prefix = f"[{idx}/{len(jobs)}] [{job.company_sigla}] Pol: {job.numero_poliza}"
            f_hash = ""

            try:
                # Calculate SHA-256 for checkpointing & deduplication
                try:
                    f_hash = compute_sha256(job.file_path)
                except Exception as exc:
                    logger.error(f"{prefix} Error calculando hash: {exc}")
                    error_count += 1
                    failed_jobs.append((job, str(exc)))
                    reporter.log_result(job, "FAILED", 0.0, error_msg=f"Hash calculation error: {exc}")
                    continue

                # Checkpoint Skip
                if resume and checkpoint.is_completed(f_hash):
                    skipped_count += 1
                    logger.info(f"{prefix} [SKIP] Ya procesado previamente en checkpoint.")
                    continue

                logger.info(f"{prefix} -> Procesando: {job.file_path.name} ({job.tipo_documento})")

                # Load company-specific skill
                skill = load_company_skill_merged(job.company_sigla)

                # Build extraction request
                req = ExtractionRequest(
                    source=job.file_path,
                    output_formats=["all"],
                    company_sigla=job.company_sigla,
                    numero_poliza=job.numero_poliza,
                    ramo=job.ramo,
                    tipo_documento=job.tipo_documento,
                )
                req._company_skill = skill  # type: ignore[attr-defined]

                # 4.1 Document Extraction
                try:
                    result = extraction_service.extract_document(req)
                except Exception as exc:
                    elapsed_fail = time.perf_counter() - t0
                    error_msg = f"Extraction failure: {exc}"
                    logger.error(f"{prefix} [FAIL] {error_msg}")
                    error_count += 1
                    failed_jobs.append((job, error_msg))
                    checkpoint.record_job(
                        f_hash, job.rel_path, job.company_sigla, job.numero_poliza,
                        "FAILED", elapsed_fail, error_message=error_msg
                    )
                    reporter.log_result(job, "FAILED", elapsed_fail, error_msg=error_msg)
                    continue

                if not result.is_successful:
                    elapsed_fail = time.perf_counter() - t0
                    err_detail = "; ".join(result.metadata.errors) or "Extraction unsuccesful"
                    logger.error(f"{prefix} [FAIL] {err_detail}")
                    error_count += 1
                    failed_jobs.append((job, err_detail))
                    checkpoint.record_job(
                        f_hash, job.rel_path, job.company_sigla, job.numero_poliza,
                        "FAILED", elapsed_fail, pages=result.metadata.page_count,
                        tables=result.metadata.tables_detected, error_message=err_detail
                    )
                    reporter.log_result(job, "FAILED", elapsed_fail, pages=result.metadata.page_count, error_msg=err_detail)
                    continue

                pages = result.metadata.page_count
                tables = result.metadata.tables_detected
                total_pages += pages

                # 4.2 RAG Vectorization & PostgreSQL Persistence
                chunks = 0
                rag_failed = False
                rag_error_detail = ""
                if rag_service:
                    try:
                        rag_report = rag_service.process_extraction_result(
                            result,
                            numero_poliza=job.numero_poliza,
                            ramo=job.ramo,
                            tipo_documento=job.tipo_documento,
                        )
                        if rag_report.skipped_duplicate:
                            logger.info(f"{prefix}    [RAG] Duplicado omitido en PostgreSQL ({f_hash[:10]}...)")
                        elif rag_report.policy_id:
                            chunks = rag_report.chunks_created
                            total_chunks += chunks
                            logger.info(f"{prefix}    [RAG] Persistido en PostgreSQL! ({chunks} chunks)")
                        elif rag_report.errors:
                            rag_failed = True
                            rag_error_detail = "; ".join(rag_report.errors)
                            logger.error(f"{prefix}    [RAG ERROR] Falló persistencia RAG: {rag_error_detail}")
                        else:
                            rag_failed = True
                            rag_error_detail = "No se generó policy_id en RAG"
                            logger.error(f"{prefix}    [RAG ERROR] Falló persistencia RAG: {rag_error_detail}")
                    except Exception as exc:
                        rag_failed = True
                        rag_error_detail = str(exc)
                        logger.error(f"{prefix}    [RAG ERROR] Falló persistencia RAG: {exc}")

                if rag_failed:
                    elapsed_fail = time.perf_counter() - t0
                    error_count += 1
                    failed_jobs.append((job, f"RAG Error: {rag_error_detail}"))
                    checkpoint.record_job(
                        f_hash, job.rel_path, job.company_sigla, job.numero_poliza,
                        "FAILED", elapsed_fail, pages=pages,
                        error_message=f"RAG Error: {rag_error_detail}"
                    )
                    reporter.log_result(job, "FAILED", elapsed_fail, pages=pages, tables=tables, error_msg=rag_error_detail)
                    continue

                elapsed = time.perf_counter() - t0
                processed_count += 1

                # Record success in Checkpoint & CSV
                checkpoint.record_job(
                    f_hash, job.rel_path, job.company_sigla, job.numero_poliza,
                    "SUCCESS", elapsed, pages=pages, chunks=chunks
                )
                reporter.log_result(
                    job, "SUCCESS", elapsed, pages=pages, tables=tables, chunks=chunks
                )
                logger.info(f"{prefix} [OK] Completado en {elapsed:.2f}s ({pages} págs, {tables} tablas, {chunks} chunks)")

                # Periodic garbage collection to maintain flat memory profile over thousands of PDFs
                if idx % 10 == 0:
                    gc.collect()

                # Periodic update of batch_report.txt every 25 files
                if processed_count % 25 == 0:
                    reporter.write_summary_report(
                        start_total_time, len(jobs), processed_count, skipped_count,
                        error_count, total_pages, total_chunks, failed_jobs
                    )

            except Exception as unexp_exc:
                elapsed_fail = time.perf_counter() - t0
                err_msg = f"Unexpected failure: {unexp_exc}"
                logger.error(f"{prefix} [UNEXPECTED FAIL] {err_msg}", exc_info=True)
                error_count += 1
                failed_jobs.append((job, err_msg))
                try:
                    if not f_hash:
                        f_hash = compute_sha256(job.file_path)
                    checkpoint.record_job(
                        f_hash, job.rel_path, job.company_sigla, job.numero_poliza,
                        "FAILED", elapsed_fail, error_message=err_msg
                    )
                    reporter.log_result(job, "FAILED", elapsed_fail, error_msg=err_msg)
                except Exception:
                    pass
                continue

    except KeyboardInterrupt:
        logger.warning("\n[INTERRUPCIÓN MANUAL] Proceso detenido por el usuario (Ctrl+C).")
        logger.warning("El progreso hasta este punto fue guardado. Puedes reanudar en cualquier momento.")

    # 5. Final Report
    reporter.write_summary_report(
        start_total_time, len(jobs), processed_count, skipped_count,
        error_count, total_pages, total_chunks, failed_jobs
    )

    total_elapsed = time.perf_counter() - start_total_time
    logger.info("\n" + "=" * 60)
    logger.info("PROCESO BATCH FINALIZADO")
    logger.info(f"Tiempo total          : {total_elapsed:.2f} s ({total_elapsed / 60:.2f} min)")
    logger.info(f"Documentos procesados : {processed_count}")
    logger.info(f"Documentos omitidos   : {skipped_count}")
    logger.info(f"Documentos con error  : {error_count}")
    logger.info(f"Reporte detallado en  : {rep_path.resolve()}")
    logger.info(f"Historial CSV en      : {c_path.resolve()}")
    logger.info("=" * 60)


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="DocEngine — Batch Initial Load Runner para carga masiva de pólizas."
    )
    parser.add_argument(
        "--source-dir",
        type=str,
        default="carga_inicial",
        help="Directorio raíz que contiene las carpetas de las aseguradoras (por defecto: carga_inicial).",
    )
    parser.add_argument(
        "--company",
        type=str,
        default=None,
        help="Filtrar por sigla de aseguradora (ej. BIS, ALI, CRI).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Procesar como máximo N archivos (ideal para pruebas y validaciones iniciales).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Modo simulación: valida rutas, parsea metadatos y cuenta archivos sin procesar.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Deshabilita el chequeo de checkpoint (reprocesa archivos ya completados).",
    )
    parser.add_argument(
        "--skip-rag",
        action="store_true",
        help="Extrae únicamente a disco (Markdown/JSON) sin persistir en base de datos PostgreSQL.",
    )
    parser.add_argument(
        "--report-file",
        type=str,
        default=None,
        help="Ruta personalizada para el archivo de reporte final (batch_report.txt).",
    )
    parser.add_argument(
        "--csv-file",
        type=str,
        default=None,
        help="Ruta personalizada para el archivo de historial CSV (batch_status.csv).",
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=None,
        help="Ruta personalizada para el archivo de log (batch_execution.log).",
    )
    parser.add_argument(
        "--checkpoint-db",
        type=str,
        default=None,
        help="Ruta personalizada para la base SQLite de checkpoint.",
    )
    parser.add_argument(
        "--torch-threads",
        type=int,
        default=None,
        help="Número de hilos de CPU explícitos para PyTorch (ej. 6).",
    )

    args = parser.parse_args()

    source_path = Path(args.source_dir).resolve()
    if not source_path.exists():
        print(f"[ERROR] El directorio origen no existe: {source_path}", file=sys.stderr)
        sys.exit(1)

    run_batch(
        source_dir=source_path,
        company_filter=args.company,
        limit=args.limit,
        dry_run=args.dry_run,
        resume=not args.no_resume,
        skip_rag=args.skip_rag,
        checkpoint_db_path=Path(args.checkpoint_db) if args.checkpoint_db else None,
        report_path=Path(args.report_file) if args.report_file else None,
        csv_path=Path(args.csv_file) if args.csv_file else None,
        log_file_path=Path(args.log_file) if args.log_file else None,
        torch_threads=args.torch_threads,
    )


if __name__ == "__main__":
    main()

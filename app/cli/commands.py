"""DocEngine — CLI Commands.

Provides a command-line interface for document extraction.
The CLI is a thin wrapper around ExtractionService — no Docling calls here.

Usage:
    python main.py extract document.pdf
    python main.py extract ./folder --format all
    python main.py extract https://example.com/poliza.pdf
    python main.py version
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click

from app.application.company_skill_loader import (
    COMPANY_REGISTRY,
    detect_company_from_path,
    load_company_skill,
)
from app.application.extraction_service import ExtractionService
from app.application.markdown_service import MarkdownService
from app.application.metadata_service import MetadataService
from app.application.validation_service import ValidationService
from app.config.settings import AppSettings, get_settings
from app.domain.models.document import ExtractionResult
from app.domain.models.extraction import ExtractionRequest, ExtractionStatus
from app.infrastructure.adapters.docling_adapter import DoclingAdapter
from app.infrastructure.logging.logger import configure_logging, get_logger
from app.infrastructure.storage.local_storage import LocalStorageService

logger = get_logger(__name__)


def _build_service(settings: AppSettings) -> ExtractionService:
    """Compose ExtractionService for CLI use.

    Args:
        settings: Application configuration.

    Returns:
        Configured ExtractionService.
    """
    return ExtractionService(
        extractor=DoclingAdapter(config=settings),
        markdown_service=MarkdownService(config=settings),
        metadata_service=MetadataService(),
        validation_service=ValidationService(config=settings),
        storage=LocalStorageService(config=settings),
        config=settings,
    )


@click.group()
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Logging level.",
    show_default=True,
)
@click.pass_context
def cli(ctx: click.Context, log_level: str) -> None:
    """DocEngine — Motor de Extracción Documental.

    Extrae contenido de PDFs de pólizas de seguros con máxima fidelidad.
    """
    # Ensure stdout/stderr use UTF-8 on Windows terminals
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    ctx.ensure_object(dict)
    settings = get_settings()
    configure_logging(level=log_level, format_="console")
    ctx.obj["settings"] = settings
    ctx.obj["service"] = _build_service(settings)


@cli.command()
@click.argument("source")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["md", "json", "all"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Output format(s) to generate.",
)
@click.option(
    "--output-dir",
    type=click.Path(),
    default=None,
    help="Override output directory.",
)
@click.option(
    "--company",
    "company_sigla",
    default=None,
    metavar="SIGLA",
    help=(
        "Company sigla (e.g. CRI, ALI).  Auto-detected from folder name "
        "when source is under empresas/<SIGLA>/."
    ),
)
@click.pass_context
def extract(
    ctx: click.Context,
    source: str,
    output_format: str,
    output_dir: str | None,
    company_sigla: str | None,
) -> None:
    """Extract content from a PDF file, folder, or URL.

    SOURCE can be:
    \b
        - A local PDF file path
        - A folder containing PDF files
        - An HTTP/HTTPS URL pointing to a PDF

    Examples:
    \b
        python main.py extract poliza.pdf
        python main.py extract empresas/CRI/                (auto-detects CRI)
        python main.py extract ./documentos --company MSC
        python main.py extract https://example.com/poliza.pdf
    """
    service: ExtractionService = ctx.obj["service"]
    settings: AppSettings = ctx.obj["settings"]

    if output_dir:
        settings.output.output_dir = Path(output_dir).resolve()

    # Normalise company sigla
    if company_sigla:
        company_sigla = company_sigla.strip().upper()
        if company_sigla not in COMPANY_REGISTRY:
            click.echo(
                f"[WARN] Unknown company sigla: {company_sigla}.  "
                "Proceeding without company skill.",
                err=True,
            )
            company_sigla = None

    start = time.perf_counter()

    try:
        # Determine source type
        source_path = Path(source)

        if source.startswith(("http://", "https://")):
            click.echo(f"[URL] Extracting from URL: {source}")
            result = service.extract_from_url(source)
            _print_result(result)

        elif source_path.is_dir():
            # Auto-detect company from folder path if not explicitly provided
            effective_sigla = company_sigla or detect_company_from_path(source_path)
            if effective_sigla:
                click.echo(f"[COMPANY] Using skill for: {effective_sigla}")
            click.echo(f"[FOLDER] Extracting folder: {source}")
            results = service.extract_folder(source_path, company_sigla=effective_sigla)
            _print_batch_results(results)

        elif source_path.is_file():
            click.echo(f"[FILE] Extracting file: {source}")
            request = ExtractionRequest(
                source=source_path,
                output_formats=[output_format],
            )
            # Auto-detect or attach company info / general skill when processing a single file
            effective_sigla = company_sigla or detect_company_from_path(source_path)
            from app.application.company_skill_loader import (  # noqa: PLC0415
                load_company_skill_merged,
                load_general_skill,
            )
            if effective_sigla:
                request._company_sigla = effective_sigla  # type: ignore[attr-defined]
                skill = load_company_skill_merged(effective_sigla)
            else:
                skill = load_general_skill()
            request._company_skill = skill  # type: ignore[attr-defined]
            result = service.extract_document(request)
            _print_result(result)

        else:
            click.echo(f"[ERROR] Source not found: {source}", err=True)
            sys.exit(1)

    except Exception as exc:
        click.echo(f"[ERROR] Extraction failed: {exc}", err=True)
        logger.exception("CLI extraction error", source=source)
        sys.exit(1)

    elapsed = time.perf_counter() - start
    click.echo(f"\n[TIME] Total time: {elapsed:.2f}s")


@cli.command(name="process-rag")
@click.argument("source")
@click.option(
    "--company",
    "company_sigla",
    default=None,
    metavar="SIGLA",
    help="Company sigla (e.g. CRI, ALI). Auto-detected from folder path if under empresas/<SIGLA>/.",
)
@click.pass_context
def process_rag(
    ctx: click.Context,
    source: str,
    company_sigla: str | None,
) -> None:
    """Extract PDF and process through local RAG pipeline directly into PostgreSQL.

    SOURCE can be a PDF file or a folder of PDFs.
    """
    from app.cli.rag_factory import create_rag_pipeline_service  # noqa: PLC0415

    service: ExtractionService = ctx.obj["service"]
    settings: AppSettings = ctx.obj["settings"]
    rag_service = create_rag_pipeline_service()

    if company_sigla:
        company_sigla = company_sigla.strip().upper()

    source_path = Path(source)
    if not source_path.exists():
        click.echo(f"[ERROR] Source path does not exist: {source}", err=True)
        sys.exit(1)

    pdf_files = [source_path] if source_path.is_file() else sorted(source_path.rglob("*.pdf"))
    if not pdf_files:
        click.echo(f"[WARN] No PDF files found in {source}", err=True)
        return

    click.echo(f"🚀 Processing {len(pdf_files)} file(s) through RAG pipeline...")

    for pdf in pdf_files:
        click.echo(f"\n[RAG] Processing: {pdf.name}")
        effective_sigla = company_sigla or detect_company_from_path(pdf)

        req = ExtractionRequest(source=pdf, output_formats=["all"])
        if effective_sigla:
            req._company_sigla = effective_sigla  # type: ignore[attr-defined]
            from app.application.company_skill_loader import load_company_skill_merged  # noqa: PLC0415
            skill = load_company_skill_merged(effective_sigla)
            req._company_skill = skill  # type: ignore[attr-defined]

        # 1. Extraction via Docling
        result = service.extract_document(req)

        # Ensure company sigla is preserved in metadata
        if effective_sigla and not result.metadata.company_sigla:
            result.metadata.company_sigla = effective_sigla

        if not result.is_successful:
            click.echo(f"[FAIL] Extraction failed for {pdf.name}", err=True)
            continue

        # 2. Local RAG Pipeline + PostgreSQL persistence
        report = rag_service.process_extraction_result(result)

        if report.skipped_duplicate:
            click.echo(f"   [SKIP] Duplicate hash detected ({report.file_hash[:12]}...). Omitted.")
        elif report.policy_id:
            click.echo(f"   [OK] Persisted to PostgreSQL!")
            click.echo(f"   Policy ID   : {report.policy_id}")
            click.echo(f"   Company     : {report.company_sigla or 'N/A'}")
            click.echo(f"   Chunks      : {report.chunks_created} (1024d embeddings)")
            click.echo(f"   Job ID      : {report.job_id}")
            click.echo(f"   Duration    : {report.processing_time_seconds:.2f}s")
        else:
            click.echo(f"   [FAIL] RAG processing failed: {report.errors}", err=True)



@cli.command()
@click.pass_context
def version(ctx: click.Context) -> None:
    """Show DocEngine and Docling version information."""
    settings: AppSettings = ctx.obj["settings"]
    try:
        import docling  # noqa: PLC0415
        docling_ver = getattr(docling, "__version__", "unknown")
    except Exception:
        docling_ver = "unknown"


    click.echo(f"DocEngine version : {settings.app_version}")
    click.echo(f"Docling version   : {docling_ver}")
    click.echo(f"Python version    : {sys.version.split()[0]}")


# ---------------------------------------------------------------------------
# Skill commands
# ---------------------------------------------------------------------------


@cli.group()
def skill() -> None:  # type: ignore[attr-defined]
    """Manage company extraction skills.

    Skills are Markdown files in the ``skills/`` directory that accumulate
    extraction rules for each insurance company.
    """


@skill.command(name="analyze")
@click.argument("sigla")
@click.option(
    "--output-dir",
    type=click.Path(exists=True),
    default=None,
    help="Directory where extraction outputs are stored (default: ./outputs).",
)
@click.pass_context
def skill_analyze(ctx: click.Context, sigla: str, output_dir: str | None) -> None:
    """Analyze extraction outputs for SIGLA and report skill gaps.

    Reads all Markdown files previously extracted for the given company and
    detects key-value field names that appear in the documents but are NOT
    yet defined in the company skill file.

    SIGLA: 3-letter company code (e.g. CRI, ALI).

    Examples:
    \b
        python main.py extract skill analyze CRI
        python main.py extract skill analyze CRI --output-dir ./outputs
    """
    import re as _re  # noqa: PLC0415

    sigla = sigla.strip().upper()

    if sigla not in COMPANY_REGISTRY:
        click.echo(
            f"[ERROR] Unknown company sigla: {sigla}.\n"
            f"Known siglas: {', '.join(sorted(COMPANY_REGISTRY))}",
            err=True,
        )
        sys.exit(1)

    settings: AppSettings = ctx.obj["settings"]
    base_outputs = Path(output_dir) if output_dir else settings.output.output_dir
    company_dir = base_outputs / sigla

    click.echo(f"\n[SKILL] Analyzing outputs for: {sigla} — {COMPANY_REGISTRY[sigla]}")
    click.echo(f"[SKILL] Looking for Markdown files in: {company_dir}")

    if not company_dir.exists():
        click.echo(
            f"[WARN] No output directory found for {sigla}. "
            "Run extractions first.",
            err=True,
        )
        sys.exit(0)

    md_files = list(company_dir.rglob("*.md"))
    if not md_files:
        click.echo(f"[WARN] No Markdown files found under {company_dir}.", err=True)
        sys.exit(0)

    click.echo(f"[SKILL] Found {len(md_files)} Markdown file(s) to analyze.")

    # Load existing skill to know what's already covered
    existing_skill = load_company_skill(sigla)
    covered_keys: set[str] = set()
    if existing_skill:
        covered_keys = {k.lower() for k in existing_skill.kv_keys}
        click.echo(
            f"[SKILL] Current skill has {len(existing_skill.kv_keys)} KV key(s) defined."
        )
    else:
        click.echo("[SKILL] No skill file found — all detected keys are new.")

    # Common KV separators patterns:  "Key:"  or  "Key :"
    _kv_pattern = _re.compile(
        r"^([A-ZÁÉÍÓÚÑ][\w\s\.\(\)/]{2,50})\s*:\s*\S",
        _re.IGNORECASE | _re.MULTILINE,
    )

    detected: dict[str, int] = {}
    for md_path in md_files:
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _kv_pattern.finditer(text):
            key = m.group(1).strip()
            detected[key] = detected.get(key, 0) + 1

    # Sort by frequency descending
    sorted_detected = sorted(detected.items(), key=lambda x: x[1], reverse=True)

    new_keys = [
        (k, cnt) for k, cnt in sorted_detected if k.lower() not in covered_keys
    ]
    already_covered = [
        (k, cnt) for k, cnt in sorted_detected if k.lower() in covered_keys
    ]

    click.echo(f"\n[SKILL] Detected {len(detected)} unique KV keys in documents.")
    click.echo(f"[SKILL] {len(already_covered)} already covered by skill.")
    click.echo(f"[SKILL] {len(new_keys)} NEW keys not yet in skill.")

    if new_keys:
        click.echo("\n--- Suggested additions to kv_keys in skill file ---")
        click.echo("    (add to the yaml block in skills/skill-"
                   f"{sigla.lower()}.md)\n")
        click.echo("kv_keys:")
        for key, cnt in new_keys[:30]:  # Show top 30
            click.echo(f'  - "{key}"  # found {cnt}x')
        if len(new_keys) > 30:
            click.echo(f"  # ... and {len(new_keys) - 30} more")
    else:
        click.echo("\n[OK] Skill already covers all detected KV keys.")


# ---------------------------------------------------------------------------
# Private output helpers
# ---------------------------------------------------------------------------


def _print_result(result: ExtractionResult) -> None:
    """Print a formatted summary of a single extraction result.

    Args:
        result: The extraction result to display.
    """
    status_icon = "[OK]" if result.is_successful else "[FAIL]"
    click.echo(f"\n{status_icon} Status          : {result.status.value.upper()}")
    click.echo(f"   Document ID    : {result.document_id}")
    click.echo(f"   Filename       : {result.metadata.filename}")
    click.echo(f"   Pages          : {result.metadata.page_count}")
    click.echo(f"   Tables found   : {result.metadata.tables_detected}")
    click.echo(f"   Markdown size  : {result.metadata.markdown_size_bytes:,} bytes")
    click.echo(f"   Extract time   : {result.metadata.extraction_time_seconds:.2f}s")
    click.echo(f"   SHA-256        : {result.metadata.sha256[:16]}...")

    if result.output_paths:
        click.echo("   Output files   :")
        for fmt, path in result.output_paths.items():
            click.echo(f"     [{fmt}] {path}")

    if result.metadata.warnings:
        click.echo(f"\n[WARN] Warnings ({len(result.metadata.warnings)}):")
        for w in result.metadata.warnings[:5]:
            click.echo(f"   • {w}")

    if result.metadata.errors:
        click.echo(f"\n[ERROR] Errors ({len(result.metadata.errors)}):")
        for e in result.metadata.errors[:5]:
            click.echo(f"   • {e}")


def _print_batch_results(results: list[ExtractionResult]) -> None:
    """Print a summary of a batch extraction operation.

    Args:
        results: List of extraction results from a folder operation.
    """
    successful = sum(1 for r in results if r.is_successful)
    failed = len(results) - successful

    click.echo(f"\n[SUMMARY] Batch Summary")
    click.echo(f"   Total processed : {len(results)}")
    click.echo(f"   [OK] Successful : {successful}")
    click.echo(f"   [FAIL] Failed   : {failed}")
    click.echo("")

    for result in results:
        icon = "[OK]" if result.is_successful else "[FAIL]"
        click.echo(
            f"   {icon} {result.metadata.filename:<40} "
            f"{result.status.value:8} "
            f"{result.metadata.page_count:3}p "
            f"{result.metadata.tables_detected:2}t "
            f"{result.metadata.extraction_time_seconds:.1f}s"
        )

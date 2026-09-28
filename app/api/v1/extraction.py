"""DocEngine — Extraction API Endpoints (v1).

POST /api/v1/extract          — Upload and extract a PDF file
POST /api/v1/extract/url      — Extract from a URL
POST /api/v1/extract/folder   — Extract all PDFs in a server-side folder
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse, Response

from app.config.settings import get_settings

from app.api.dependencies import ExtractionServiceDep, RagPipelineServiceDep
from app.api.v1.health import record_extraction
from app.api.v1.schemas import (
    BatchExtractionResultSchema,
    ExtractionResultSchema,
    FolderExtractionRequest,
    MetadataSchema,
    RagReportSchema,
    UrlExtractionRequest,
)
from app.domain.models.document import ExtractionResult
from app.domain.models.extraction import ExtractionRequest
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(tags=["Extraction"])

# Allowed MIME types for upload
_ALLOWED_MIME_TYPES = {"application/pdf", "application/octet-stream"}
_MAX_FILENAME_LEN = 255


@router.post(
    "/extract",
    response_model=ExtractionResultSchema,
    status_code=status.HTTP_200_OK,
    summary="Extraer documento PDF (subida de archivo)",
    description=(
        "Carga un archivo PDF de póliza y extrae su contenido transformándolo en Markdown estructurado y JSON. "
        "El archivo se procesa de forma segura aplicando las reglas especializadas de la aseguradora si se especifica su sigla."
    ),
)
async def extract_file(
    file: UploadFile,
    extraction_service: ExtractionServiceDep,
    rag_service: RagPipelineServiceDep = None,
    company_sigla: str | None = Form(default=None, description="Sigla identificadora de la compañía aseguradora (ej. CRI, LBC, ALI) para aplicar reglas especializadas"),
    numero_poliza: str | None = Form(default=None, description="Número de póliza para vincular el documento a un sobre de póliza (envelope)"),
    ramo: str | None = Form(default=None, description="Ramo del seguro (ej. AUTOMOTOR, INCENDIO, SALUD)"),
    tipo_documento: str | None = Form(default=None, description="Clasificación o tipo de documento (ej. CONDICIONADO_GENERAL, CONDICIONADO_PARTICULAR, LIQUIDACION_PAGOS)"),
) -> ExtractionResultSchema:
    """Extract content from an uploaded PDF file.

    Args:
        file: Uploaded PDF file via multipart/form-data.
        extraction_service: Injected ExtractionService.
        rag_service: Injected RagPipelineService (optional).
        company_sigla: Optional 3-letter company code.
        numero_poliza: Optional policy number to bind this file to a policy envelope.
        ramo: Optional insurance branch.
        tipo_documento: Optional document classification.

    Returns:
        ExtractionResultSchema with Markdown preview and metadata.

    Raises:
        HTTPException 400: If the file is not a valid PDF.
        HTTPException 500: If extraction fails unexpectedly.
    """
    _validate_upload(file)

    # Save uploaded file to a temporary location
    temp_path = Path("outputs") / "_uploads" / f"{uuid.uuid4()}_{file.filename}"
    temp_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        content = await file.read()
        temp_path.write_bytes(content)

        sigla_clean = company_sigla.strip().upper() if company_sigla else None
        num_poliza_clean = numero_poliza.strip() if numero_poliza else None
        ramo_clean = ramo.strip() if ramo else None
        tipo_doc_clean = tipo_documento.strip() if tipo_documento else None

        logger.info(
            "[Upload] Archivo PDF recibido para extracción",
            filename=file.filename,
            size_bytes=len(content),
            company_sigla=sigla_clean or "NO_ESPECIFICADA",
            numero_poliza=num_poliza_clean,
            tipo_documento=tipo_doc_clean,
        )

        request = ExtractionRequest(
            source=temp_path,
            output_formats=["all"],
            request_id=str(uuid.uuid4()),
            company_sigla=sigla_clean,
            numero_poliza=num_poliza_clean,
            ramo=ramo_clean,
            tipo_documento=tipo_doc_clean,
        )

        result = extraction_service.extract_document(request)
        if file.filename:
            result.metadata.filename = file.filename
        _record_and_log(result)

        rag_report_schema = _process_rag_safe(
            rag_service,
            result,
            numero_poliza=num_poliza_clean,
            ramo=ramo_clean,
            tipo_documento=tipo_doc_clean,
        )
        return _to_schema(result, rag_report=rag_report_schema)

    except Exception as exc:
        logger.error("[ERROR] [Upload] Error durante la extracción del archivo", filename=file.filename, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Extraction failed: {exc}",
        ) from exc
    finally:
        # Clean up uploaded temp file
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


@router.post(
    "/extract/url",
    response_model=ExtractionResultSchema,
    status_code=status.HTTP_200_OK,
    summary="Extraer documento PDF desde URL",
    description="Descarga y procesa un documento PDF accesible a través de una URL pública proporcionada.",
)
def extract_url(
    body: UrlExtractionRequest,
    extraction_service: ExtractionServiceDep,
    rag_service: RagPipelineServiceDep = None,
) -> ExtractionResultSchema:
    """Extract content from a PDF available at a URL.

    Args:
        body: Request body containing the URL and optional company_sigla.
        extraction_service: Injected ExtractionService.
        rag_service: Injected RagPipelineService (optional).

    Returns:
        ExtractionResultSchema with Markdown preview and metadata.

    Raises:
        HTTPException 400: If the URL does not appear to point to a PDF.
        HTTPException 500: If extraction fails unexpectedly.
    """
    try:
        sigla_clean = body.company_sigla.strip().upper() if body.company_sigla else None
        result = extraction_service.extract_from_url(body.url, company_sigla=sigla_clean)
        _record_and_log(result)
        rag_report_schema = _process_rag_safe(rag_service, result)
        return _to_schema(result, rag_report=rag_report_schema)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.error("URL extraction endpoint error", url=body.url, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Extraction failed: {exc}",
        ) from exc


@router.post(
    "/extract/folder",
    response_model=BatchExtractionResultSchema,
    status_code=status.HTTP_200_OK,
    summary="Extraer todos los PDFs de una carpeta",
    description=(
        "Procesa de forma recursiva todos los archivos PDF encontrados en un directorio del servidor. "
        "Retorna un reporte consolidado por lote con el estado individual de cada documento procesado."
    ),
)
def extract_folder(
    body: FolderExtractionRequest,
    extraction_service: ExtractionServiceDep,
    rag_service: RagPipelineServiceDep = None,
) -> BatchExtractionResultSchema:
    """Extract all PDFs in a server-side directory.

    Args:
        body: Request body with folder_path and optional company_sigla.
        extraction_service: Injected ExtractionService.
        rag_service: Injected RagPipelineService (optional).

    Returns:
        BatchExtractionResultSchema with results for each PDF.

    Raises:
        HTTPException 400: If the folder does not exist.
        HTTPException 500: If batch extraction fails unexpectedly.
    """
    folder = Path(body.folder_path)
    if not folder.exists() or not folder.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Folder not found or not a directory: {body.folder_path}",
        )

    try:
        sigla_clean = body.company_sigla.strip().upper() if body.company_sigla else None
        results = extraction_service.extract_folder(folder, company_sigla=sigla_clean)
        successful = sum(1 for r in results if r.is_successful)

        schema_results = []
        for r in results:
            rag_report_schema = _process_rag_safe(rag_service, r)
            schema_results.append(_to_schema(r, rag_report=rag_report_schema))

        return BatchExtractionResultSchema(
            total_documents=len(results),
            successful=successful,
            failed=len(results) - successful,
            results=schema_results,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.error(
            "Folder extraction endpoint error",
            folder=body.folder_path,
            error=str(exc),
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch extraction failed: {exc}",
        ) from exc





@router.get(
    "/extract/{document_id}/markdown",
    summary="Obtener contenido Markdown de una extracción",
    description="Recupera el contenido completo en texto Markdown generado a partir de una extracción previa, identificado por document_id o ruta de archivo.",
)
def get_extraction_markdown(
    document_id: str,
    path: str | None = Query(default=None, description="Ruta de archivo relativa o absoluta opcional hacia el archivo .md"),
    download: bool = Query(default=False, description="Si es True, incluye cabeceras para forzar la descarga del archivo (Content-Disposition: attachment)"),
) -> Response:
    """Retrieve full Markdown content for an extracted document.

    Args:
        document_id: Extraction ID or document folder stem.
        path: Optional explicit file path from output_paths['md'].
        download: If True, set headers for file download (attachment).

    Returns:
        Response containing the raw Markdown text.
    """
    settings = get_settings()
    base_dir = settings.output.output_dir.resolve()

    target_md_path: Path | None = None

    if path:
        p = Path(path).resolve()
        if p.exists() and p.is_file() and p.suffix == ".md":
            try:
                p.relative_to(base_dir)
                target_md_path = p
            except ValueError:
                pass

    if not target_md_path:
        # Search recursively in base_dir for a matching .md file
        matches = list(base_dir.rglob(f"*{document_id}*/*.md"))
        if not matches:
            all_mds = list(base_dir.rglob("*.md"))
            matches = [m for m in all_mds if document_id.lower() in str(m).lower()]
        
        if matches:
            target_md_path = matches[0]

    if not target_md_path or not target_md_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Markdown file not found for document_id '{document_id}'",
        )

    content = target_md_path.read_text(encoding="utf-8")
    filename = target_md_path.name
    disposition = "attachment" if download else "inline"

    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'{disposition}; filename="{filename}"'
        },
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _validate_upload(file: UploadFile) -> None:
    """Validate that an uploaded file appears to be a PDF.

    Args:
        file: The uploaded file to validate.

    Raises:
        HTTPException 400: If the file is not a PDF.
    """
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided.",
        )
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted.",
        )
    if len(file.filename) > _MAX_FILENAME_LEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is too long.",
        )


def _process_rag_safe(
    rag_service: Any,
    result: ExtractionResult,
    numero_poliza: str | None = None,
    ramo: str | None = None,
    tipo_documento: str | None = None,
) -> RagReportSchema | None:
    """Helper to safely execute RAG pipeline without failing primary extraction."""
    if not rag_service or not result.is_successful:
        return None
    try:
        report = rag_service.process_extraction_result(
            result,
            numero_poliza=numero_poliza,
            ramo=ramo,
            tipo_documento=tipo_documento,
        )
        if report:
            return RagReportSchema(
                policy_id=report.policy_id,
                job_id=report.job_id,
                skipped_duplicate=report.skipped_duplicate,
                chunks_created=report.chunks_created,
                errors=report.errors,
                envelope_id=report.envelope_id,
                tipo_documento=report.tipo_documento,
            )
    except Exception as exc:
        logger.error("RAG pipeline execution error", error=str(exc))
        return RagReportSchema(errors=[str(exc)])
    return None


def _to_schema(
    result: ExtractionResult,
    rag_report: RagReportSchema | None = None,
) -> ExtractionResultSchema:
    """Convert domain ExtractionResult to API schema.

    Args:
        result: Domain extraction result.
        rag_report: Optional RAG persistence report.

    Returns:
        API schema suitable for JSON serialization.
    """
    meta = result.metadata
    return ExtractionResultSchema(
        document_id=result.document_id,
        status=result.status.value,
        markdown_preview=result.markdown_preview,
        metadata=MetadataSchema(
            filename=meta.filename,
            sha256=meta.sha256,
            page_count=meta.page_count,
            extraction_time_seconds=meta.extraction_time_seconds,
            docling_version=meta.docling_version,
            tables_detected=meta.tables_detected,
            figures_detected=meta.figures_detected,
            headers_removed=meta.headers_removed,
            footers_removed=meta.footers_removed,
            ocr_used=meta.ocr_used,
            has_multi_column=meta.has_multi_column,
            markdown_size_bytes=meta.markdown_size_bytes,
            errors=meta.errors,
            warnings=meta.warnings,
            extracted_at=meta.extracted_at,
            company_sigla=meta.company_sigla,
            pdf_type=getattr(meta, "pdf_type", None),
            scanned_page_ratio=getattr(meta, "scanned_page_ratio", None),
            pdf_detection_time_seconds=getattr(meta, "pdf_detection_time_seconds", None),
            envelope_id=getattr(meta, "envelope_id", None),
            tipo_documento=getattr(meta, "tipo_documento", None),
        ),
        output_paths={k: str(v) for k, v in result.output_paths.items()},
        rag_report=rag_report,
        created_at=result.created_at,
    )



def _record_and_log(result: ExtractionResult) -> None:
    """Record metrics and log result summary.

    Args:
        result: Completed extraction result.
    """
    record_extraction(
        status=result.status.value,
        pages=result.metadata.page_count,
        tables=result.metadata.tables_detected,
        duration_seconds=result.metadata.extraction_time_seconds,
    )


@router.get(
    "/companies",
    summary="Listar compañías aseguradoras registradas",
    description="Retorna el catálogo completo de compañías aseguradoras soportadas con sus siglas oficiales y nombres completos.",
)
def get_companies() -> dict[str, str]:
    """Return dictionary of supported insurance company siglas to full names."""
    from app.application.company_skill_loader import COMPANY_REGISTRY  # noqa: PLC0415
    return COMPANY_REGISTRY

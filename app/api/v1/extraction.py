"""DocEngine — Extraction API Endpoints (v1).

POST /api/v1/extract          — Upload and extract a PDF file
POST /api/v1/extract/url      — Extract from a URL
POST /api/v1/extract/folder   — Extract all PDFs in a server-side folder
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse, Response

from app.config.settings import get_settings

from app.api.dependencies import ExtractionServiceDep
from app.api.v1.health import record_extraction
from app.api.v1.schemas import (
    BatchExtractionResultSchema,
    ExtractionResultSchema,
    FolderExtractionRequest,
    MetadataSchema,
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
    summary="Extract PDF (file upload)",
    description=(
        "Upload a PDF file and extract its content as Markdown and JSON. "
        "The file is saved temporarily, processed, and the output is stored on disk."
    ),
)
async def extract_file(
    file: UploadFile,
    extraction_service: ExtractionServiceDep,
    company_sigla: str | None = Form(default=None, description="Sigla de la empresa aseguradora (ej. CRI, LBC, ALI)"),
) -> ExtractionResultSchema:
    """Extract content from an uploaded PDF file.

    Args:
        file: Uploaded PDF file via multipart/form-data.
        extraction_service: Injected ExtractionService.
        company_sigla: Optional 3-letter company code.

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

        request = ExtractionRequest(
            source=temp_path,
            output_formats=["all"],
            request_id=str(uuid.uuid4()),
            company_sigla=sigla_clean,
        )

        result = extraction_service.extract_document(request)
        _record_and_log(result)
        return _to_schema(result)

    except Exception as exc:
        logger.error("File extraction endpoint error", error=str(exc))
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
    summary="Extract PDF from URL",
    description="Download and extract a PDF from a given URL.",
)
def extract_url(
    body: UrlExtractionRequest,
    extraction_service: ExtractionServiceDep,
) -> ExtractionResultSchema:
    """Extract content from a PDF available at a URL.

    Args:
        body: Request body containing the URL and optional company_sigla.
        extraction_service: Injected ExtractionService.

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
        return _to_schema(result)
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
    summary="Extract all PDFs in a folder",
    description=(
        "Extract all PDF files found recursively in a server-side folder. "
        "Returns a batch result with individual status per file."
    ),
)
def extract_folder(
    body: FolderExtractionRequest,
    extraction_service: ExtractionServiceDep,
) -> BatchExtractionResultSchema:
    """Extract all PDFs in a server-side directory.

    Args:
        body: Request body with folder_path and optional company_sigla.
        extraction_service: Injected ExtractionService.

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
        return BatchExtractionResultSchema(
            total_documents=len(results),
            successful=successful,
            failed=len(results) - successful,
            results=[_to_schema(r) for r in results],
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
    summary="Get full Markdown for an extraction",
    description="Retrieve full Markdown content of a processed document by document_id or file path.",
)
def get_extraction_markdown(
    document_id: str,
    path: str | None = Query(default=None, description="Optional relative or absolute file path to .md"),
    download: bool = Query(default=False, description="Set Content-Disposition for file download"),
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


def _to_schema(result: ExtractionResult) -> ExtractionResultSchema:
    """Convert domain ExtractionResult to API schema.

    Args:
        result: Domain extraction result.

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
        ),
        output_paths={k: str(v) for k, v in result.output_paths.items()},
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
    summary="List insurance companies",
    description="Returns the registry of supported insurance companies and their siglas.",
)
def get_companies() -> dict[str, str]:
    """Return dictionary of supported insurance company siglas to full names."""
    from app.application.company_skill_loader import COMPANY_REGISTRY  # noqa: PLC0415
    return COMPANY_REGISTRY


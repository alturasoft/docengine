"""DocEngine — Extraction API Endpoints (v1).

POST /api/v1/extract          — Upload and extract a PDF file
POST /api/v1/extract/url      — Extract from a URL
POST /api/v1/extract/folder   — Extract all PDFs in a server-side folder
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse

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
) -> ExtractionResultSchema:
    """Extract content from an uploaded PDF file.

    Args:
        file: Uploaded PDF file via multipart/form-data.
        extraction_service: Injected ExtractionService.

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

        request = ExtractionRequest(
            source=temp_path,
            output_formats=["all"],
            request_id=str(uuid.uuid4()),
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
        body: Request body containing the URL.
        extraction_service: Injected ExtractionService.

    Returns:
        ExtractionResultSchema with Markdown preview and metadata.

    Raises:
        HTTPException 400: If the URL does not appear to point to a PDF.
        HTTPException 500: If extraction fails unexpectedly.
    """
    try:
        result = extraction_service.extract_from_url(body.url)
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
        body: Request body with folder_path.
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
        results = extraction_service.extract_folder(folder)
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

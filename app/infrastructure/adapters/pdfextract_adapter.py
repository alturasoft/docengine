"""DocEngine — Infrastructure Adapter: PdfExtractAdapter.

Extracts structured Markdown, JSON, and document metadata from PDF files
using the `pdfextract` library.

Implements the IDocumentExtractor domain interface so it is completely
interchangeable with DoclingAdapter.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from app.config.settings import AppSettings
from app.domain.interfaces.extractor import IDocumentExtractor
from app.domain.models.document import DocumentMetadata, ExtractionResult
from app.domain.models.extraction import ExtractionRequest, ExtractionStatus
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


def _patch_torch_compile_for_windows() -> None:
    """Ensure torch.compile does not fail on Windows CPU environments with Inductor."""
    try:
        import torch

        if hasattr(torch, "compile"):
            # Bypass inductor compile on Windows CPU where triton template duplicates occur
            torch.compile = lambda m, *args, **kwargs: m
    except Exception:
        pass


class PdfExtractAdapter(IDocumentExtractor):
    """Document extractor adapter powered by `pdfextract`.

    Coordinates PDF extraction, OCR, and table reconstruction via `pdfextract`.

    Args:
        config: Application settings.
    """

    def __init__(self, config: AppSettings) -> None:
        self._config = config
        _patch_torch_compile_for_windows()
        logger.info(
            "PdfExtractAdapter initialized",
            extractor=self.extractor_name,
            supports_ocr=self.supports_ocr,
        )

    # ------------------------------------------------------------------
    # IDocumentExtractor implementation
    # ------------------------------------------------------------------

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        """Extract content from a single document using pdfextract.

        Args:
            request: Extraction request with source path/URL and options.

        Returns:
            Populated ExtractionResult with Markdown, JSON, and metadata.
        """
        source = str(request.source)
        doc_id = request.request_id or str(uuid.uuid4())
        start_time = time.perf_counter()

        logger.info("[pdfextract] Iniciando extracción de documento", document_id=doc_id, source=source)

        source_path = Path(source)
        if not source_path.exists():
            elapsed = time.perf_counter() - start_time
            err_msg = f"No se encontró el archivo PDF: {source}"
            logger.error("[pdfextract] Archivo inexistente", source=source, error=err_msg)
            return self._build_failed_result(
                document_id=doc_id,
                source_path=source_path,
                error=err_msg,
                elapsed=elapsed,
            )

        try:
            from pdfextract import extract_pdf

            with tempfile.TemporaryDirectory(prefix="pdfextract_") as tmp_dir:
                out_dir = Path(tmp_dir)
                raw_meta = extract_pdf(
                    input_path=source_path,
                    output_dir=out_dir,
                    engine="docling",
                )

                elapsed = time.perf_counter() - start_time
                return self._build_extraction_result(
                    raw_meta=raw_meta,
                    source_path=source_path,
                    document_id=doc_id,
                    elapsed=elapsed,
                )

        except Exception as exc:
            elapsed = time.perf_counter() - start_time
            logger.error(
                "[pdfextract] Error no manejado durante la extracción",
                document_id=doc_id,
                source=source,
                error=str(exc),
                duration_seconds=round(elapsed, 3),
                exc_info=True,
            )
            return self._build_failed_result(
                document_id=doc_id,
                source_path=source_path,
                error=str(exc),
                elapsed=elapsed,
            )

    def extract_batch(
        self, requests: list[ExtractionRequest]
    ) -> list[ExtractionResult]:
        """Extract content from multiple documents.

        Args:
            requests: List of extraction requests.

        Returns:
            List of ExtractionResult objects.
        """
        if not requests:
            return []

        logger.info("[pdfextract] Iniciando extracción en lote", batch_size=len(requests))
        results: list[ExtractionResult] = []

        for req in requests:
            res = self.extract(req)
            results.append(res)

        successful = sum(1 for r in results if r.is_successful)
        logger.info(
            "[pdfextract] Extracción en lote completada",
            total=len(requests),
            successful=successful,
            failed=len(requests) - successful,
        )
        return results

    @property
    def extractor_name(self) -> str:
        """Return the extractor name with version."""
        try:
            import pdfextract

            ver = getattr(pdfextract, "__version__", "1.0.0")
        except Exception:
            ver = "1.0.0"
        return f"PdfExtractAdapter v{ver}"

    @property
    def supports_ocr(self) -> bool:
        """PdfExtractAdapter supports OCR via underlying PaddleOCR/Docling."""
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_extraction_result(
        self,
        raw_meta: dict[str, Any],
        source_path: Path,
        document_id: str,
        elapsed: float,
    ) -> ExtractionResult:
        """Translate pdfextract result dict into an ExtractionResult domain model."""
        doc_info = raw_meta.get("document", {})
        engines = raw_meta.get("engines", {})

        # Priority of markdown sources: docling -> postprocessed -> paddleocr
        selected_engine_name = "pdfextract"
        md_content = ""
        json_data: dict[str, Any] = {}
        tables_count = 0
        pages_count = doc_info.get("total_pages", 0)
        errors: list[str] = []

        # Find best available engine output
        candidate_engines = ["docling", "postprocessed", "paddleocr"]
        best_engine_data = None

        for eng_name in candidate_engines:
            if eng_name in engines and engines[eng_name].get("status") == "success":
                best_engine_data = engines[eng_name]
                selected_engine_name = eng_name
                break

        if best_engine_data is None:
            # Fallback to any engine in dict
            for eng_name, eng_val in engines.items():
                if eng_val.get("status") == "success":
                    best_engine_data = eng_val
                    selected_engine_name = eng_name
                    break

        if best_engine_data:
            out_files = best_engine_data.get("output_files", {})
            md_path_str = out_files.get("md")
            if md_path_str and Path(md_path_str).exists():
                try:
                    md_content = Path(md_path_str).read_text(encoding="utf-8")
                except Exception as e:
                    errors.append(f"Error leyendo archivo markdown generado: {e}")

            json_path_str = out_files.get("json")
            if json_path_str and Path(json_path_str).exists():
                try:
                    with open(json_path_str, "r", encoding="utf-8") as jf:
                        json_data = json.load(jf)
                except Exception as e:
                    errors.append(f"Error leyendo archivo json generado: {e}")

            tables_count = best_engine_data.get("tables_count", 0)
            if not pages_count:
                pages_count = best_engine_data.get("pages_detected", 0)
        else:
            # Collect error messages from all failed engines
            for eng_name, eng_val in engines.items():
                if eng_val.get("error_message"):
                    errors.append(f"{eng_name}: {eng_val['error_message']}")

        # Compute SHA256
        sha256 = doc_info.get("file_hash_sha256") or ""
        if not sha256 and source_path.exists():
            try:
                sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
            except Exception:
                pass

        if not sha256 and md_content:
            sha256 = hashlib.sha256(md_content.encode("utf-8")).hexdigest()

        status = ExtractionStatus.SUCCESS if md_content else ExtractionStatus.FAILED
        if not md_content and not errors:
            errors.append("pdfextract no produjo texto Markdown en ninguno de los motores.")

        raw_doc_type = (doc_info.get("document_type") or "").strip().lower()
        if raw_doc_type in ("native", "digital"):
            normalized_pdf_type = "digital"
        elif raw_doc_type in ("scanned", "hybrid", "unknown"):
            normalized_pdf_type = raw_doc_type
        else:
            normalized_pdf_type = raw_doc_type if raw_doc_type else None

        metadata = DocumentMetadata(
            filename=source_path.name,
            source_path=source_path,
            sha256=sha256,
            page_count=pages_count,
            extraction_time_seconds=elapsed,
            docling_version=self.extractor_name,
            tables_detected=tables_count,
            figures_detected=0,
            headers_removed=0,
            footers_removed=0,
            ocr_used=True,
            has_multi_column=False,
            markdown_size_bytes=len(md_content.encode("utf-8")),
            errors=errors,
            pdf_type=normalized_pdf_type,
        )

        logger.info(
            "[pdfextract] Extracción completada",
            document_id=document_id,
            status=status.value,
            selected_engine=selected_engine_name,
            pages=pages_count,
            tables=tables_count,
            markdown_bytes=metadata.markdown_size_bytes,
            duration_seconds=round(elapsed, 3),
            errors=len(errors),
        )

        return ExtractionResult(
            document_id=document_id,
            status=status,
            markdown=md_content,
            json_data=json_data,
            metadata=metadata,
        )

    def _build_failed_result(
        self,
        document_id: str,
        source_path: Path,
        error: str,
        elapsed: float,
    ) -> ExtractionResult:
        """Build an ExtractionResult with FAILED status."""
        sha256 = ""
        if source_path.exists() and source_path.is_file():
            try:
                sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
            except Exception:
                pass

        metadata = DocumentMetadata(
            filename=source_path.name,
            source_path=source_path,
            sha256=sha256,
            page_count=0,
            extraction_time_seconds=elapsed,
            docling_version=self.extractor_name,
            tables_detected=0,
            figures_detected=0,
            headers_removed=0,
            footers_removed=0,
            ocr_used=False,
            has_multi_column=False,
            markdown_size_bytes=0,
            errors=[error],
        )

        return ExtractionResult(
            document_id=document_id,
            status=ExtractionStatus.FAILED,
            markdown="",
            json_data={},
            metadata=metadata,
        )

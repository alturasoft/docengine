"""DocEngine — Infrastructure Adapter: DoclingAdapter.

This is the ONLY place in the entire system where Docling is imported
and invoked. All other components interact with IDocumentExtractor only.

Design decisions:
- DocumentConverter is built once (expensive — loads ML models) and reused.
- OCR is explicitly disabled for Phase 1 (do_ocr=False).
- TableFormerMode.ACCURATE is used for maximum table fidelity.
- convert_all() is used for batches, convert() for single documents.
- All Docling exceptions are caught and translated to domain exceptions.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import docling
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption

from app.config.settings import AppSettings
from app.domain.interfaces.extractor import IDocumentExtractor
from app.domain.models.document import (
    DocumentMetadata,
    ExtractionResult,
    compute_sha256,
)
from app.domain.models.extraction import ExtractionRequest, ExtractionStatus
from app.infrastructure.logging.logger import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


def _get_docling_version() -> str:
    """Retrieve installed Docling package version safely."""
    try:
        return importlib.metadata.version("docling")
    except Exception:
        return getattr(docling, "__version__", "unknown")


def _collapse_spaced_tokens(tokens: list[str]) -> str:
    """Join letter-spaced tokens back into natural words.

    Converts text like ``"E n  V i r t u d  d e  l a  s o l i c i t u d"`` into
    ``"En Virtud de la solicitud"``.

    PDF letter-spacing places single spaces between characters and double spaces
    between distinct words. This function preserves word boundaries while
    collapsing spaced letters within words.

    Args:
        tokens: Whitespace-split tokens from a letter-spaced line.

    Returns:
        Natural-language string with words correctly rejoined.
    """
    raw_line = " ".join(tokens)
    if "  " in raw_line:
        word_chunks = raw_line.split("  ")
        fixed_words: list[str] = []
        for chunk in word_chunks:
            chunk_tokens = chunk.strip().split(" ")
            if chunk_tokens and (
                sum(1 for t in chunk_tokens if len(t) == 1) / len(chunk_tokens)
                >= 0.5
            ):
                fixed_words.append("".join(chunk_tokens))
            else:
                fixed_words.append(chunk.strip())
        return " ".join(w for w in fixed_words if w)

    # Fallback for single-spaced character streams
    result: list[str] = []
    char_buffer: list[str] = []

    def _flush_buffer() -> None:
        if char_buffer:
            result.append("".join(char_buffer))
            char_buffer.clear()

    for token in tokens:
        if len(token) == 1 and token.isalpha():
            char_buffer.append(token)
        else:
            _flush_buffer()
            result.append(token)

    _flush_buffer()
    return " ".join(result)


class DoclingAdapter(IDocumentExtractor):
    """Docling-based document extractor implementation.

    Encapsulates the complete Docling pipeline configuration and execution.
    The DocumentConverter instance is created once during __init__ because
    model loading is expensive (several seconds and ~1 GB RAM).

    Thread Safety:
        DocumentConverter is NOT thread-safe. For concurrent API use,
        create one adapter per worker process (via FastAPI lifespan).

    Args:
        config: Application settings containing all pipeline options.
    """

    def __init__(self, config: AppSettings) -> None:
        self._config = config
        self._converter: DocumentConverter = self._build_converter()
        logger.info(
            "DoclingAdapter initialized",
            extractor=self.extractor_name,
            ocr_enabled=config.extraction.do_ocr,
            table_mode=config.extraction.table_mode,
            accelerator=config.pipeline.accelerator_device,
        )

    # ------------------------------------------------------------------
    # IDocumentExtractor implementation
    # ------------------------------------------------------------------

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        """Extract content from a single document.

        For local file sources, auto-detects whether the PDF is scanned or
        digital (if ``config.extraction.auto_detect_pdf_type`` is True) and
        configures Docling OCR accordingly before starting conversion.

        URL sources skip pre-classification and use the configured do_ocr value.

        Args:
            request: Extraction request with source path/URL and options.

        Returns:
            ExtractionResult with Markdown, JSON data, and metadata.
        """
        source = str(request.source)
        doc_id = request.request_id or str(uuid.uuid4())

        logger.info("Starting extraction", document_id=doc_id, source=source)
        start_time = time.perf_counter()

        # --- Dynamic OCR detection (Phase 2) ---
        # Classify the PDF type BEFORE calling Docling so we can configure
        # do_ocr correctly from the start. Uses the default converter (no OCR)
        # for digital PDFs to preserve startup efficiency.
        pdf_type_result = self._detect_pdf_type(source)
        if pdf_type_result.is_scanned:
            converter = self._build_converter_with_ocr(
                force_full_page=pdf_type_result.force_full_page_ocr
            )
            ocr_was_used = True
        else:
            converter = self._converter  # Reuse the pre-built no-OCR converter
            ocr_was_used = self._config.extraction.do_ocr

        try:
            conv_result = converter.convert(source, raises_on_error=False)
            elapsed = time.perf_counter() - start_time

            return self._build_extraction_result(
                conv_result=conv_result,
                request=request,
                document_id=doc_id,
                elapsed=elapsed,
                ocr_used=ocr_was_used,
                pdf_type_result=pdf_type_result,
            )

        except Exception as exc:
            elapsed = time.perf_counter() - start_time
            logger.error(
                "Extraction failed with unhandled exception",
                document_id=doc_id,
                source=source,
                error=str(exc),
                duration_seconds=round(elapsed, 3),
            )
            return self._build_failed_result(
                document_id=doc_id,
                source=source,
                error=str(exc),
                elapsed=elapsed,
            )

    def extract_batch(
        self, requests: list[ExtractionRequest]
    ) -> list[ExtractionResult]:
        """Extract content from multiple documents using Docling batch API.

        Uses DocumentConverter.convert_all() for efficiency. Failed
        individual documents are captured as FAILED results and do not
        abort the batch.

        Args:
            requests: List of extraction requests.

        Returns:
            List of ExtractionResult objects (one per request, same order).
        """
        if not requests:
            return []

        logger.info("Starting batch extraction", batch_size=len(requests))
        batch_start = time.perf_counter()

        sources = [str(r.source) for r in requests]
        id_map = {
            str(r.source): (r, r.request_id or str(uuid.uuid4()))
            for r in requests
        }

        results: list[ExtractionResult] = []

        try:
            conv_results = list(
                self._converter.convert_all(sources, raises_on_error=False)
            )

            for conv_result in conv_results:
                source_key = str(conv_result.input.file)
                original_request, doc_id = id_map.get(
                    source_key, (requests[0], str(uuid.uuid4()))
                )
                elapsed_per_doc = time.perf_counter() - batch_start

                result = self._build_extraction_result(
                    conv_result=conv_result,
                    request=original_request,
                    document_id=doc_id,
                    elapsed=elapsed_per_doc,
                )
                results.append(result)

        except Exception as exc:
            logger.error("Batch extraction failed", error=str(exc))
            for req in requests:
                _, doc_id = id_map.get(str(req.source), (req, str(uuid.uuid4())))
                results.append(
                    self._build_failed_result(
                        document_id=doc_id,
                        source=str(req.source),
                        error=str(exc),
                        elapsed=time.perf_counter() - batch_start,
                    )
                )

        total_elapsed = time.perf_counter() - batch_start
        successful = sum(1 for r in results if r.is_successful)
        logger.info(
            "Batch extraction complete",
            total=len(requests),
            successful=successful,
            failed=len(requests) - successful,
            total_duration_seconds=round(total_elapsed, 3),
        )

        return results

    @property
    def extractor_name(self) -> str:
        """Return the extractor name with Docling version."""
        version = _get_docling_version()
        return f"DoclingAdapter v{version}"

    @property
    def supports_ocr(self) -> bool:
        """DoclingAdapter supports OCR via configuration."""
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_converter(self) -> DocumentConverter:
        """Construct and configure the Docling DocumentConverter.

        This is where all Docling API calls for configuration happen.
        Using only verified, stable Docling 2.x APIs.

        Backend selection rationale:
        - ``docling_parse_v2`` (default): Best handling of non-standard embedded
          font glyph maps common in Latin-American insurance PDFs. Tested up to
          500 pages without memory issues under normal conditions.
        - ``pypdfium2``: Recommended fallback for corrupt or memory-intensive PDFs.
          Uses the PDFium C++ engine with a smaller memory footprint.
        - ``docling_parse`` (v1): Legacy; retained for compatibility only.

        Returns:
            Configured DocumentConverter instance.
        """
        cfg = self._config
        ext_cfg = cfg.extraction

        # Build PDF pipeline options
        pipeline_options = PdfPipelineOptions()

        # --- OCR ---
        # Phase 1: OCR explicitly disabled.
        # Phase 2: Set do_ocr=True and configure ocr_options via IOcrEngine.
        pipeline_options.do_ocr = ext_cfg.do_ocr

        # --- Table Structure ---
        pipeline_options.do_table_structure = ext_cfg.do_table_structure
        pipeline_options.table_structure_options = TableStructureOptions(
            do_cell_matching=ext_cfg.do_cell_matching,
            mode=(
                TableFormerMode.ACCURATE
                if ext_cfg.table_mode == "ACCURATE"
                else TableFormerMode.FAST
            ),
        )

        # --- Layout Analysis Scale ---
        # Higher scale improves region detection for dense multi-column layouts
        # and complex table boundaries in insurance documents.
        # 2.0 is the sweet-spot: better detection without excessive memory use.
        pipeline_options.images_scale = cfg.pipeline.images_scale

        # --- Images ---
        # Phase 1: We do NOT extract image binaries (only detect positions).
        pipeline_options.generate_picture_images = ext_cfg.generate_picture_images

        # --- Artifacts path (for air-gapped environments) ---
        if cfg.pipeline.artifacts_path is not None:
            pipeline_options.artifacts_path = str(cfg.pipeline.artifacts_path)

        # --- PDF Backend ---
        # Selection is controlled by DOCENGINE_PIPELINE_PDF_BACKEND env var.
        # Default is 'pypdfium2' which avoids std::bad_alloc memory issues.
        backend = cfg.pipeline.pdf_backend
        if backend == "docling_parse":
            from docling.backend.docling_parse_backend import (
                DoclingParseDocumentBackend,
            )

            backend_cls = DoclingParseDocumentBackend
        else:
            # 'pypdfium2' (default) — PDFium engine
            from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend

            backend_cls = PyPdfiumDocumentBackend

        logger.debug(
            "PDF backend selected",
            backend=backend,
            images_scale=cfg.pipeline.images_scale,
        )

        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                    backend=backend_cls,
                )
            }
        )

    def _detect_pdf_type(
        self, source: str
    ) -> "PdfTypeResult":  # noqa: F821 — resolved at runtime
        """Detect whether the PDF is digital, scanned, or hybrid.

        Returns UNKNOWN immediately (safe fallback) when:
        - auto_detect_pdf_type is disabled in config.
        - Source is a URL.
        - pypdfium2 is not available or raises.

        Args:
            source: Source path or URL string.

        Returns:
            PdfTypeResult with classification details.
        """
        from app.infrastructure.adapters.pdf_type_detector import (  # noqa: PLC0415
            PdfClassification,
            PdfTypeDetector,
            PdfTypeResult,
        )

        if not self._config.extraction.auto_detect_pdf_type:
            logger.debug("PDF type auto-detection disabled by config")
            return PdfTypeResult(classification=PdfClassification.UNKNOWN)

        detector = PdfTypeDetector(
            min_chars_per_page=self._config.extraction.min_chars_per_page,
            scanned_ratio_threshold=self._config.extraction.scanned_page_ratio_threshold,
            max_sample_pages=self._config.extraction.max_sample_pages,
        )
        return detector.classify(source)

    def _build_converter_with_ocr(
        self, force_full_page: bool = False
    ) -> DocumentConverter:
        """Build a NEW DocumentConverter with OCR enabled (EasyOCR, es+en).

        Called only when PDF type detection determines the document is scanned
        or hybrid. A fresh converter is built per-call because OCR pipelines
        load additional models that we do not want pre-loaded for digital PDFs.

        Note: This method deliberately mirrors _build_converter() structure
        so both remain independently maintainable. No shared mutable state.

        Args:
            force_full_page: If True, EasyOCR processes the entire page image.
                Set for SCANNED documents. For HYBRID documents, leave False
                so Docling applies OCR only where no text layer is present.

        Returns:
            New DocumentConverter with OCR enabled.
        """
        from docling.datamodel.pipeline_options import EasyOcrOptions  # noqa: PLC0415

        cfg = self._config
        ext_cfg = cfg.extraction

        pipeline_options = PdfPipelineOptions()

        # --- OCR: enabled dynamically ---
        pipeline_options.do_ocr = True
        pipeline_options.ocr_options = EasyOcrOptions(
            force_full_page_ocr=force_full_page,
            lang=["es", "en"],  # Spanish + English for Bolivian insurance documents
        )

        # --- Table Structure (same as default converter) ---
        pipeline_options.do_table_structure = ext_cfg.do_table_structure
        pipeline_options.table_structure_options = TableStructureOptions(
            do_cell_matching=ext_cfg.do_cell_matching,
            mode=(
                TableFormerMode.ACCURATE
                if ext_cfg.table_mode == "ACCURATE"
                else TableFormerMode.FAST
            ),
        )

        # --- Layout and image scale (same as default converter) ---
        pipeline_options.images_scale = cfg.pipeline.images_scale
        pipeline_options.generate_picture_images = ext_cfg.generate_picture_images

        # --- Artifacts path (air-gapped environments) ---
        if cfg.pipeline.artifacts_path is not None:
            pipeline_options.artifacts_path = str(cfg.pipeline.artifacts_path)

        # --- PDF Backend (same selection logic as _build_converter) ---
        backend = cfg.pipeline.pdf_backend
        if backend == "docling_parse":
            from docling.backend.docling_parse_backend import (  # noqa: PLC0415
                DoclingParseDocumentBackend,
            )
            backend_cls = DoclingParseDocumentBackend
        else:
            from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend  # noqa: PLC0415
            backend_cls = PyPdfiumDocumentBackend

        logger.info(
            "Building OCR-enabled DocumentConverter",
            force_full_page_ocr=force_full_page,
            ocr_engine="EasyOCR",
            languages=["es", "en"],
            backend=backend,
        )

        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                    backend=backend_cls,
                )
            }
        )

    def _build_extraction_result(
        self,
        conv_result: ConversionResult,
        request: ExtractionRequest,
        document_id: str,
        elapsed: float,
        ocr_used: bool | None = None,
        pdf_type_result: "PdfTypeResult | None" = None,  # noqa: F821
    ) -> ExtractionResult:
        """Translate a Docling ConversionResult into an ExtractionResult.

        Args:
            conv_result: The ConversionResult from DocumentConverter.
            request: The original extraction request.
            document_id: Unique ID for this extraction.
            elapsed: Wall-clock seconds elapsed.
            ocr_used: Whether OCR was actually used. If None, falls back to
                config value (preserves backward-compatibility).
            pdf_type_result: Result of PDF type pre-classification, or None
                when detection was skipped (e.g. batch mode, URL).

        Returns:
            Populated ExtractionResult domain object.
        """
        # Determine status
        if conv_result.status == ConversionStatus.SUCCESS:
            status = ExtractionStatus.SUCCESS
        elif conv_result.status == ConversionStatus.PARTIAL_SUCCESS:
            status = ExtractionStatus.PARTIAL
        else:
            status = ExtractionStatus.FAILED

        # Extract document content
        doc = conv_result.document
        markdown_text = ""
        json_data: dict = {}
        tables_count = 0
        figures_count = 0
        errors: list[str] = []

        if doc is not None:
            try:
                # Use native export options to improve output quality:
                # - strict_text=False: preserve ligatures and special chars
                # - escape_underscores=True: avoid spurious Markdown emphasis
                # - compact_tables=False: full-width tables for readability
                markdown_text = doc.export_to_markdown(
                    strict_text=False,
                    escape_underscores=True,
                    compact_tables=False,
                    image_placeholder="<!-- image -->",
                )
            except Exception as exc:
                errors.append(f"Markdown export error: {exc}")

            # --- Post-processing ---
            # Applied after Docling export to fix known PDF extraction artifacts.

            if self._config.extraction.fix_spaced_text and markdown_text:
                try:
                    markdown_text = self._fix_spaced_text(markdown_text)
                except Exception as exc:
                    errors.append(f"Spaced-text fix error: {exc}")

            if self._config.extraction.split_merged_tables and markdown_text:
                try:
                    markdown_text = self._split_merged_tables(markdown_text)
                except Exception as exc:
                    errors.append(f"Table split error: {exc}")

            try:
                json_data = doc.export_to_dict()
            except Exception as exc:
                errors.append(f"JSON export error: {exc}")

            try:
                tables_count = len(doc.tables)
            except Exception:
                tables_count = 0

            try:
                figures_count = len(doc.pictures)
            except Exception:
                figures_count = 0

        # Extract error messages from Docling result
        if hasattr(conv_result, "errors") and conv_result.errors:
            for err in conv_result.errors:
                errors.append(str(err))

        # Compute source file metadata
        source_path = (
            Path(str(request.source))
            if request and hasattr(request, "source") and request.source
            else Path(str(conv_result.input.file))
        )
        if not source_path.exists() and hasattr(conv_result.input, "file") and conv_result.input.file:
            candidate = Path(str(conv_result.input.file))
            if candidate.exists():
                source_path = candidate

        sha256 = ""
        if source_path.exists() and source_path.is_file():
            try:
                sha256 = compute_sha256(source_path)
            except Exception as exc:
                errors.append(f"SHA256 computation error: {exc}")

        if not sha256 and markdown_text:
            sha256 = hashlib.sha256(markdown_text.encode("utf-8")).hexdigest()

        # Page count
        page_count = 0
        try:
            if doc is not None and hasattr(doc, "pages"):
                page_count = len(doc.pages)
        except Exception:
            page_count = 0

        # Docling version
        docling_ver = _get_docling_version()

        # Resolve actual OCR usage: prefer explicit argument, fall back to config
        actual_ocr_used = ocr_used if ocr_used is not None else self._config.extraction.do_ocr

        metadata = DocumentMetadata(
            filename=source_path.name,
            source_path=source_path,
            sha256=sha256,
            page_count=page_count,
            extraction_time_seconds=elapsed,
            docling_version=docling_ver,
            tables_detected=tables_count,
            figures_detected=figures_count,
            headers_removed=0,  # Updated by MarkdownService after post-processing
            footers_removed=0,  # Updated by MarkdownService after post-processing
            ocr_used=actual_ocr_used,
            has_multi_column=False,  # Docling detects layout; updated post-analysis
            markdown_size_bytes=len(markdown_text.encode("utf-8")),
            errors=errors,
            # PDF type detection fields (None when detection was skipped)
            pdf_type=pdf_type_result.classification.value if pdf_type_result else None,
            scanned_page_ratio=pdf_type_result.scanned_ratio if pdf_type_result else None,
            pdf_detection_time_seconds=pdf_type_result.detection_time_seconds if pdf_type_result else None,
        )

        logger.info(
            "Extraction result built",
            document_id=document_id,
            status=status.value,
            pages=page_count,
            tables=tables_count,
            markdown_bytes=metadata.markdown_size_bytes,
            duration_seconds=round(elapsed, 3),
            errors=len(errors),
        )

        return ExtractionResult(
            document_id=document_id,
            status=status,
            markdown=markdown_text,
            json_data=json_data,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Post-processing helpers
    # ------------------------------------------------------------------

    def _fix_spaced_text(self, text: str) -> str:
        """Collapse letter-spaced text produced by non-standard PDF font maps.

        Some PDFs (particularly Latin-American insurance documents) embed fonts
        with non-standard glyph maps.  The PDF parser extracts each glyph as a
        separate character with a space, producing output like:

            ``E n V i r t u d d e l a s o l i c i t u d ...``

        This method detects lines where the majority of tokens are single
        characters and collapses them into natural words.

        Detection heuristic:
            A line is considered "spaced" when the ratio of single-character
            tokens to total tokens is >= ``spaced_text_min_ratio`` AND the line
            contains at least one run of 3 consecutive single-char tokens.

        Args:
            text: Raw Markdown string from Docling export.

        Returns:
            Markdown string with spaced-text lines collapsed.
        """
        threshold = self._config.extraction.spaced_text_min_ratio
        # Pattern: at least 3 single non-space chars each followed by a space
        _SPACED_RUN = re.compile(r"(?:\S ){3,}")

        lines = text.split("\n")
        fixed: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped or not _SPACED_RUN.search(stripped):
                fixed.append(line)
                continue

            tokens = stripped.split(" ")
            if not tokens:
                fixed.append(line)
                continue

            single_char_ratio = sum(1 for t in tokens if len(t) == 1) / len(tokens)
            if single_char_ratio >= threshold:
                collapsed = _collapse_spaced_tokens(tokens)
                # Preserve original leading whitespace (e.g. inside table cells)
                leading = line[: len(line) - len(line.lstrip())]
                fixed.append(leading + collapsed)
                logger.debug(
                    "Spaced-text line collapsed",
                    ratio=round(single_char_ratio, 2),
                    before=stripped[:60],
                    after=collapsed[:60],
                )
            else:
                fixed.append(line)

        fixed_text = "\n".join(fixed)
        return fixed_text

    def _split_merged_tables(self, text: str) -> str:
        """Detect and split Markdown tables incorrectly merged by TableFormer.

        TableFormer may merge two visually adjacent tables into a single
        Markdown table when they share a bounding region in the PDF.  This
        produces:
        - Duplicate column headers as data rows
        - Columns with mismatched semantic groups (e.g. client data merged with
          coverage data in an insurance póliza)

        Strategy:
        1. Locate every Markdown table in the text.
        2. For each table, scan data rows for cells that look like a header
           repetition (bold text, ALL-CAPS label, or repeated column count
           mismatch).
        3. When detected, split the table at that row and insert a blank line
           + new table header reconstructed from the repeated row.

        Args:
            text: Markdown string (already spaced-text corrected).

        Returns:
            Markdown string with merged tables separated.
        """
        # Match a full Markdown table: header | separator | data rows
        _TABLE_BLOCK = re.compile(
            r"((?:\|[^\n]+\|\n)+"
            r"(?:\|[-:| ]+\|\n)"
            r"(?:\|[^\n]+\|\n?)+)",
            re.MULTILINE,
        )
        # A row looks like a header if ALL non-empty cells are either:
        # bold (**text**), ALL-CAPS, or contain Markdown header-like text
        _HEADER_LIKE_CELL = re.compile(
            r"^(?:\*\*[^*]+\*\*|[A-Z\s\/]+|#{1,3}\s.+)$"
        )

        def _is_header_row(row: str) -> bool:
            """Return True if this pipe-delimited row looks like a table header."""
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            non_empty = [c for c in cells if c]
            if not non_empty:
                return False
            header_like = sum(
                1 for c in non_empty if _HEADER_LIKE_CELL.match(c)
            )
            return header_like / len(non_empty) >= 0.6

        def _make_separator(header_row: str) -> str:
            """Build a Markdown separator row matching the column count."""
            cols = header_row.strip().strip("|").split("|")
            return "| " + " | ".join(["---"] * len(cols)) + " |\n"

        def _split_table(table_text: str) -> str:
            """Split a single table block if an internal header row is found."""
            rows = table_text.strip().split("\n")
            if len(rows) < 4:  # header + sep + at least 2 data rows needed
                return table_text

            header_row = rows[0]
            sep_row = rows[1]
            data_rows = rows[2:]

            split_idx = None
            for i, row in enumerate(data_rows):
                if row.strip() and _is_header_row(row):
                    split_idx = i
                    break

            if split_idx is None:
                return table_text  # No merge detected

            # Build two separate tables
            table_a_rows = [header_row, sep_row] + data_rows[:split_idx]
            new_header = data_rows[split_idx]
            new_sep = _make_separator(new_header)
            table_b_rows = [new_header, new_sep] + data_rows[split_idx + 1 :]

            table_a = "\n".join(table_a_rows)
            table_b = "\n".join(r for r in table_b_rows if r.strip())

            logger.debug(
                "Merged table split detected",
                split_at_row=split_idx,
                table_a_rows=len(table_a_rows),
                table_b_rows=len(table_b_rows),
            )
            return table_a + "\n\n" + table_b

        result = _TABLE_BLOCK.sub(lambda m: _split_table(m.group(0)), text)
        return result

    def _build_failed_result(
        self,
        document_id: str,
        source: str,
        error: str,
        elapsed: float,
    ) -> ExtractionResult:
        """Build a FAILED ExtractionResult when extraction cannot proceed.

        Args:
            document_id: Unique ID for this extraction.
            source: Source path or URL string.
            error: Error description.
            elapsed: Seconds elapsed before failure.

        Returns:
            ExtractionResult with FAILED status and error in metadata.
        """
        docling_ver = _get_docling_version()

        source_path = Path(source)
        metadata = DocumentMetadata(
            filename=source_path.name if not source.startswith("http") else source,
            source_path=source_path,
            sha256="",
            page_count=0,
            extraction_time_seconds=elapsed,
            docling_version=docling_ver,
            tables_detected=0,
            figures_detected=0,
            headers_removed=0,
            footers_removed=0,
            ocr_used=self._config.extraction.do_ocr,
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

"""DocEngine — Application Service: ExtractionService.

The main orchestrator of the extraction pipeline.
Coordinates IDocumentExtractor, MarkdownService, MetadataService,
ValidationService, and IStorageService.

FastAPI and CLI both call this service — they never touch Docling directly.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import psutil

from app.application.company_skill_loader import (
    CompanySkill,
    detect_company_from_path,
    load_company_skill,
    load_company_skill_merged,
)
from app.application.markdown_service import MarkdownService
from app.application.metadata_service import MetadataService
from app.application.validation_service import ValidationService
from app.config.settings import AppSettings
from app.domain.interfaces.extractor import IDocumentExtractor
from app.domain.interfaces.storage import IStorageService
from app.domain.models.document import ExtractionResult
from app.domain.models.extraction import (
    BatchExtractionRequest,
    ExtractionRequest,
    ExtractionStatus,
)
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class ExtractionService:
    """Main orchestrator for the document extraction pipeline.

    Coordinate order:
    1. Validate input
    2. Run extraction via IDocumentExtractor (DoclingAdapter)
    3. Post-process Markdown via MarkdownService
    4. Enrich metadata via MetadataService
    5. Validate result quality via ValidationService
    6. Persist result via IStorageService

    Args:
        extractor: The IDocumentExtractor implementation (DoclingAdapter).
        markdown_service: Post-processing service for Markdown quality.
        metadata_service: Metadata enrichment service.
        validation_service: Quality validation service.
        storage: Storage service for persisting results.
        config: Application configuration.
    """

    def __init__(
        self,
        extractor: IDocumentExtractor,
        markdown_service: MarkdownService,
        metadata_service: MetadataService,
        validation_service: ValidationService,
        storage: IStorageService,
        config: AppSettings,
    ) -> None:
        self._extractor = extractor
        self._markdown_service = markdown_service
        self._metadata_service = metadata_service
        self._validation_service = validation_service
        self._storage = storage
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract_document(self, request: ExtractionRequest) -> ExtractionResult:
        """Extract a single document and persist the result.

        Args:
            request: Extraction request with source and options.

        Returns:
            Fully processed and persisted ExtractionResult.
        """
        mem_before = self._metadata_service.estimate_memory_usage_mb()
        pipeline_start = time.perf_counter()

        logger.info(
            "Pipeline start",
            source=str(request.source),
            formats=request.effective_formats(),
            memory_mb_before=round(mem_before, 1),
        )

        # 1. Run extraction
        result = self._extractor.extract(request)

        # 2. Post-process Markdown (only if extraction succeeded)
        if result.is_successful and result.markdown:
            company_skill = getattr(request, "_company_skill", None)
            if company_skill is None:
                company_sigla = getattr(request, "_company_sigla", None)
                from app.application.company_skill_loader import (  # noqa: PLC0415
                    load_company_skill_merged,
                    load_general_skill,
                )
                if company_sigla:
                    company_skill = load_company_skill_merged(company_sigla)
                else:
                    company_skill = load_general_skill()

            post_result = self._markdown_service.post_process(
                result.markdown,
                company_skill=company_skill,
            )
            result.markdown = post_result.markdown

            # 3. Enrich metadata with post-processing statistics
            self._metadata_service.enrich_metadata(
                metadata=result.metadata,
                headers_removed=post_result.headers_removed,
                footers_removed=post_result.footers_removed,
                processed_markdown=result.markdown,
            )

        # 4. Validate quality
        self._validation_service.validate_result(result)

        # 5. Persist result
        saved_paths = self._storage.save_result(result)
        result.output_paths = saved_paths

        # Log pipeline summary
        pipeline_elapsed = time.perf_counter() - pipeline_start
        mem_after = self._metadata_service.estimate_memory_usage_mb()

        logger.info(
            "Pipeline complete",
            document_id=result.document_id,
            status=result.status.value,
            total_duration_seconds=round(pipeline_elapsed, 3),
            memory_mb_delta=round(mem_after - mem_before, 1),
            warnings=len(result.metadata.warnings),
            errors=len(result.metadata.errors),
        )

        return result

    def extract_folder(
        self, folder: Path, company_sigla: str | None = None
    ) -> list[ExtractionResult]:
        """Extract all PDF files in a directory.

        Automatically detects the company sigla from the folder path when
        the folder is under an ``empresas/<SIGLA>/`` structure.  A skill
        can also be provided explicitly via ``company_sigla``.

        Args:
            folder: Path to the directory containing PDF files.
            company_sigla: Optional explicit 3-letter company code.
                If None, the sigla is inferred from the folder path.

        Returns:
            List of ExtractionResult objects, one per PDF found.

        Raises:
            ValueError: If the folder does not exist or is not a directory.
        """
        if not folder.exists():
            raise ValueError(f"Folder does not exist: {folder}")
        if not folder.is_dir():
            raise ValueError(f"Path is not a directory: {folder}")

        # Detect or accept explicit sigla
        sigla = company_sigla or detect_company_from_path(folder)
        skill: CompanySkill | None = None
        if sigla:
            skill = load_company_skill_merged(sigla)
            if skill:
                logger.info(
                    "Company skill loaded for folder extraction",
                    sigla=sigla,
                    estado=skill.estado,
                    is_empty=skill.is_empty,
                )

        pdf_files = sorted(folder.rglob("*.pdf"))

        if not pdf_files:
            logger.warning("No PDF files found in folder", folder=str(folder))
            return []

        logger.info(
            "Starting folder extraction",
            folder=str(folder),
            pdf_count=len(pdf_files),
            company_sigla=sigla,
        )

        requests = [
            ExtractionRequest(
                source=pdf,
                output_formats=["all"],
                request_id=str(uuid.uuid4()),
            )
            for pdf in pdf_files
        ]

        # Attach skill to each request as a transient attribute so
        # _extract_batch can access it without changing the public API
        for req in requests:
            req._company_skill = skill  # type: ignore[attr-defined]
            if sigla:
                req._company_sigla = sigla  # type: ignore[attr-defined]

        batch_request = BatchExtractionRequest(requests=requests)
        return self._extract_batch(batch_request)

    def extract_from_url(self, url: str) -> ExtractionResult:
        """Extract content from a PDF available at a URL.

        Downloads the PDF and processes it through the standard pipeline.

        Args:
            url: URL pointing to a PDF document.

        Returns:
            ExtractionResult for the downloaded document.

        Raises:
            ValueError: If the URL does not point to a PDF.
        """
        if not url.lower().endswith(".pdf") and "pdf" not in url.lower():
            logger.warning("URL may not point to a PDF", url=url)

        request = ExtractionRequest(
            source=url,
            output_formats=["all"],
            request_id=str(uuid.uuid4()),
        )
        return self.extract_document(request)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_batch(
        self, batch: BatchExtractionRequest
    ) -> list[ExtractionResult]:
        """Execute batch extraction and post-process each result.

        Args:
            batch: Batch extraction request.

        Returns:
            List of processed ExtractionResult objects.
        """
        raw_results = self._extractor.extract_batch(list(batch.requests))
        processed: list[ExtractionResult] = []

        for request, result in zip(batch.requests, raw_results):
            company_skill: CompanySkill | None = getattr(request, "_company_skill", None)
            company_sigla: str | None = getattr(request, "_company_sigla", None)

            if result.is_successful and result.markdown:
                post_result = self._markdown_service.post_process(
                    result.markdown,
                    company_skill=company_skill,
                )
                result.markdown = post_result.markdown
                self._metadata_service.enrich_metadata(
                    metadata=result.metadata,
                    headers_removed=post_result.headers_removed,
                    footers_removed=post_result.footers_removed,
                    processed_markdown=result.markdown,
                )

            # Tag result metadata with company sigla for organised storage
            if company_sigla:
                result.metadata.company_sigla = company_sigla

            self._validation_service.validate_result(result)
            saved_paths = self._storage.save_result(result)
            result.output_paths = saved_paths
            processed.append(result)

        successful = sum(1 for r in processed if r.is_successful)
        logger.info(
            "Batch processing complete",
            total=len(processed),
            successful=successful,
            failed=len(processed) - successful,
        )

        return processed

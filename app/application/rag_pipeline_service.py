"""DocEngine — Application Service: RagPipelineService.

Orchestrates the RAG processing pipeline:
1. Idempotency verification via SHA-256 hash
2. Local Markdown chunking (ChunkingService)
3. Local vector embedding generation (EmbeddingService with BAAI/bge-m3)
4. Structured JSON extraction (OpenAIStructuredExtractor)
5. Transactional PostgreSQL + pgvector persistence
6. Async job tracking in processing_jobs table
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.application.chunking_service import ChunkingService
from app.application.embedding_service import EmbeddingService
from app.application.openai_structured_extractor import OpenAIStructuredExtractor
from app.domain.models.document import ExtractionResult
from app.domain.models.rag_models import RagProcessingReport
from app.infrastructure.database.pg_rag_repository import PgRagRepository
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class RagPipelineService:
    """Main orchestrator for RAG processing & PostgreSQL persistence."""

    def __init__(
        self,
        chunking_service: ChunkingService,
        embedding_service: EmbeddingService,
        structured_extractor: OpenAIStructuredExtractor,
        repository: PgRagRepository,
    ) -> None:
        self._chunker = chunking_service
        self._embedder = embedding_service
        self._extractor = structured_extractor
        self._repo = repository

    def process_extraction_result(
        self, result: ExtractionResult
    ) -> RagProcessingReport:
        """Process an ExtractionResult through the RAG pipeline and persist to PostgreSQL.

        Args:
            result: The ExtractionResult produced by Docling/ExtractionService.

        Returns:
            RagProcessingReport with execution stats and status.
        """
        start_time = time.perf_counter()
        file_name = result.metadata.filename
        file_hash = result.metadata.sha256
        if not file_hash and result.metadata.source_path and result.metadata.source_path.exists() and result.metadata.source_path.is_file():
            from app.domain.models.document import compute_sha256  # noqa: PLC0415
            try:
                file_hash = compute_sha256(result.metadata.source_path)
                result.metadata.sha256 = file_hash
            except Exception:
                pass
        if not file_hash and result.markdown:
            import hashlib  # noqa: PLC0415
            file_hash = hashlib.sha256(result.markdown.encode("utf-8")).hexdigest()
            result.metadata.sha256 = file_hash

        company_sigla = result.metadata.company_sigla

        logger.info(
            "Starting RAG processing pipeline",
            file_name=file_name,
            file_hash=file_hash,
            company_sigla=company_sigla,
        )

        job_id = None
        try:
            # 1. Idempotency Check
            existing_policy_id = self._repo.policy_exists_by_hash(file_hash)
            if existing_policy_id:
                logger.info(
                    "Policy already processed (hash exists in policies). Skipping execution.",
                    file_name=file_name,
                    file_hash=file_hash,
                    policy_id=existing_policy_id,
                )
                job_id = self._repo.create_job(file_name)
                self._repo.update_job(
                    job_id=job_id,
                    status="SKIPPED",
                    policy_id=existing_policy_id,
                )
                return RagProcessingReport(
                    policy_id=existing_policy_id,
                    file_name=file_name,
                    file_hash=file_hash,
                    company_sigla=company_sigla,
                    skipped_duplicate=True,
                    job_id=job_id,
                    processing_time_seconds=time.perf_counter() - start_time,
                )

            # Create processing job record
            job_id = self._repo.create_job(file_name)

            # 2. Local Chunking
            chunks = self._chunker.chunk_markdown(
                markdown=result.markdown,
                file_name=file_name,
            )

            # 3. Local Embeddings Generation (bge-m3, 1024d)
            chunks_with_embeddings = self._embedder.generate_embeddings_for_chunks(chunks)

            # 4. Structured JSON Extraction (gpt-4o)
            structured_json = self._extractor.extract_structured_json(
                markdown=result.markdown,
                company_sigla=company_sigla,
            )

            # 5. Transactional PostgreSQL Persistence
            policy_id = self._repo.save_rag_policy_transactional(
                file_name=file_name,
                file_hash=file_hash,
                company_sigla=company_sigla,
                total_pages=result.metadata.page_count,
                file_size_bytes=result.metadata.markdown_size_bytes,
                markdown_content=result.markdown,
                structured_data=structured_json,
                chunks=chunks_with_embeddings,
            )

            # 6. Update Job Status to COMPLETED
            self._repo.update_job(
                job_id=job_id,
                status="COMPLETED",
                policy_id=policy_id,
            )

            elapsed = time.perf_counter() - start_time
            logger.info(
                "RAG pipeline successfully completed",
                policy_id=policy_id,
                file_name=file_name,
                chunks_count=len(chunks_with_embeddings),
                duration_seconds=round(elapsed, 3),
            )

            return RagProcessingReport(
                policy_id=policy_id,
                file_name=file_name,
                file_hash=file_hash,
                company_sigla=company_sigla,
                chunks_created=len(chunks_with_embeddings),
                embedding_dim=1024,
                skipped_duplicate=False,
                processing_time_seconds=elapsed,
                job_id=job_id,
            )

        except Exception as e:
            logger.error(
                "RAG processing pipeline failed",
                file_name=file_name,
                error=str(e),
            )
            if job_id:
                try:
                    self._repo.update_job(
                        job_id=job_id,
                        status="FAILED",
                        error_message=str(e),
                    )
                except Exception:
                    pass
            return RagProcessingReport(
                policy_id=None,
                file_name=file_name,
                file_hash=file_hash,
                company_sigla=company_sigla,
                job_id=job_id,
                processing_time_seconds=time.perf_counter() - start_time,
                errors=[str(e)],
            )


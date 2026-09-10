"""DocEngine — Application Service: RagPipelineService.

Orchestrates the RAG processing pipeline:
1. Idempotency verification via SHA-256 hash
2. Local Markdown chunking (ChunkingService)
3. Local vector embedding generation (EmbeddingService with BAAI/bge-m3)
   └─ Steps 3 & 4 run in parallel via ThreadPoolExecutor (independent tasks)
4. Structured JSON extraction (OpenAIStructuredExtractor)
5. Transactional PostgreSQL + pgvector persistence
6. Async job tracking in processing_jobs table
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from app.application.chunking_service import ChunkingService
from app.application.embedding_service import EmbeddingService
from app.application.openai_structured_extractor import OpenAIStructuredExtractor
from app.domain.models.document import ExtractionResult
from app.domain.models.rag_models import PolicyProcessingStats, RagProcessingReport
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
            "[RAG] Iniciando pipeline RAG y almacenamiento vectorial...",
            file_name=file_name,
            file_hash=file_hash,
            company_sigla=company_sigla,
        )

        job_id = None
        try:
            # 1. Idempotency Check
            logger.info(
                "[Idempotencia] Verificando si el documento ya existe en base de datos...",
                file_hash=file_hash,
            )
            existing_policy_id = self._repo.policy_exists_by_hash(file_hash)
            if existing_policy_id:
                logger.info(
                    "[Idempotencia] Póliza previamente procesada en BD. Omitiendo duplicado.",
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

            # 2. Local Chunking (must run first — embeddings depend on chunks)
            logger.info(
                "[Chunking] Iniciando división del Markdown en fragmentos jerárquicos (Parent-Child)...",
                file_name=file_name,
                markdown_chars=len(result.markdown) if result.markdown else 0,
            )
            t_chunk_start = time.perf_counter()
            chunks = self._chunker.chunk_markdown(
                markdown=result.markdown,
                file_name=file_name,
            )
            chunking_duration = time.perf_counter() - t_chunk_start
            logger.info(
                "[Chunking] Chunking finalizado exitosamente",
                total_chunks=len(chunks),
                file_name=file_name,
                duration_seconds=round(chunking_duration, 3),
            )

            # 3 & 4. Parallel execution: Embeddings + OpenAI (fully independent)
            # Both operations work on distinct inputs — no shared state.
            t_parallel_start = time.perf_counter()
            chunks_with_embeddings: list
            structured_json: dict
            embedding_duration: float = 0.0
            openai_duration: float = 0.0

            logger.info(
                "[Paralelo] Iniciando generación de Embeddings (BGE-M3) y Extracción de JSON (OpenAI)...",
                chunks_count=len(chunks),
            )

            def _run_embeddings() -> tuple[list, float]:
                logger.info(
                    "[Embeddings] Generando vectores densos de 1024-d con modelo local BAAI/bge-m3...",
                    total_chunks=len(chunks),
                )
                t_emb_start = time.perf_counter()
                emb_res = self._embedder.generate_embeddings_for_chunks(chunks)
                emb_dur = time.perf_counter() - t_emb_start
                logger.info(
                    "[Embeddings] Vectores generados exitosamente",
                    total_vectors=len(emb_res),
                    duration_seconds=round(emb_dur, 3),
                )
                return emb_res, emb_dur

            def _run_openai() -> tuple[dict, float]:
                logger.info(
                    "[JSON Estructurado] Extrayendo entidades y coberturas de la póliza vía OpenAI LLM...",
                    company_sigla=company_sigla,
                )
                t_oai_start = time.perf_counter()
                json_res = self._extractor.extract_structured_json(
                    markdown=result.markdown,
                    company_sigla=company_sigla,
                )
                oai_dur = time.perf_counter() - t_oai_start
                numero_pol = (
                    json_res.get("datos_cabecera", {}).get("numero_poliza")
                    if isinstance(json_res.get("datos_cabecera"), dict)
                    else json_res.get("numero_poliza")
                )
                logger.info(
                    "[JSON Estructurado] Extracción de JSON completada",
                    coberturas_count=len(json_res.get("coberturas", [])),
                    numero_poliza=numero_pol,
                    duration_seconds=round(oai_dur, 3),
                )
                return json_res, oai_dur

            with ThreadPoolExecutor(max_workers=2) as executor:
                future_emb = executor.submit(_run_embeddings)
                future_oai = executor.submit(_run_openai)

                # Collect results — re-raise any exception to trigger rollback
                for future in as_completed([future_emb, future_oai]):
                    exc = future.exception()
                    if exc is not None:
                        raise exc

                chunks_with_embeddings, embedding_duration = future_emb.result()
                structured_json, openai_duration = future_oai.result()

            logger.info(
                "[Paralelo] Embeddings y JSON estructurado completados",
                duration_seconds=round(time.perf_counter() - t_parallel_start, 3),
                chunks_count=len(chunks_with_embeddings),
            )

            # Build PolicyProcessingStats
            total_pages = result.metadata.page_count or 1
            extraction_time = result.metadata.extraction_time_seconds or 0.0
            time_per_page = extraction_time / max(1, total_pages)
            raw_pdf_type = getattr(result.metadata, "pdf_type", None)
            if raw_pdf_type:
                raw_upper = str(raw_pdf_type).strip().upper()
                if raw_upper in ("NATIVE", "DIGITAL"):
                    file_type = "DIGITAL"
                elif raw_upper in ("SCANNED", "HYBRID"):
                    file_type = raw_upper
                else:
                    file_type = "UNKNOWN"
            else:
                file_type = "SCANNED" if getattr(result.metadata, "ocr_used", False) else "DIGITAL"

            parent_chunks = sum(
                1 for c in chunks_with_embeddings if getattr(c, "chunk_type", "parent") == "parent"
            )
            child_chunks = sum(
                1 for c in chunks_with_embeddings if getattr(c, "chunk_type", "") == "child"
            )

            usage_dict = structured_json.get("_usage", {})
            prompt_tokens = usage_dict.get("prompt_tokens", 0)
            completion_tokens = usage_dict.get("completion_tokens", 0)
            total_tokens = usage_dict.get("total_tokens", 0)
            estimated_cost = usage_dict.get("estimated_cost_usd", 0.0)

            # Memory tracking
            mem_peak = None
            try:
                import psutil  # noqa: PLC0415
                mem_peak = psutil.Process().memory_info().rss / (1024 * 1024)
            except Exception:
                pass

            total_pipe_time = time.perf_counter() - start_time
            extracted_policy_num = (
                structured_json.get("datos_cabecera", {}).get("numero_poliza")
                if isinstance(structured_json.get("datos_cabecera"), dict)
                else structured_json.get("numero_poliza")
            )
            stats = PolicyProcessingStats(
                policy_id="",  # Assigned dynamically during repo transactional save
                job_id=job_id,
                policy_number=extracted_policy_num,
                company_sigla=company_sigla,
                file_type=file_type,
                ocr_applied=getattr(result.metadata, "ocr_used", False),
                scanned_page_ratio=getattr(result.metadata, "scanned_page_ratio", None),
                total_pages=total_pages,
                extraction_time_seconds=extraction_time,
                time_per_page_seconds=time_per_page,
                chunking_time_seconds=chunking_duration,
                embedding_time_seconds=embedding_duration,
                openai_time_seconds=openai_duration,
                total_pipeline_time_seconds=total_pipe_time,
                total_chunks=len(chunks_with_embeddings),
                parent_chunks=parent_chunks,
                child_chunks=child_chunks,
                openai_prompt_tokens=prompt_tokens,
                openai_completion_tokens=completion_tokens,
                openai_total_tokens=total_tokens,
                openai_estimated_cost_usd=estimated_cost,
                coberturas_extracted_count=len(structured_json.get("coberturas", [])),
                tables_detected=getattr(result.metadata, "tables_detected", 0),
                memory_peak_mb=mem_peak,
            )

            # 5. Transactional PostgreSQL Persistence
            logger.info(
                "[Persistencia BD] Guardando póliza, chunks, vectores y estadísticas en PostgreSQL (pgvector)...",
                chunks_count=len(chunks_with_embeddings),
                file_name=file_name,
            )
            policy_id = self._repo.save_rag_policy_transactional(
                file_name=file_name,
                file_hash=file_hash,
                company_sigla=company_sigla,
                total_pages=result.metadata.page_count,
                file_size_bytes=result.metadata.markdown_size_bytes,
                markdown_content=result.markdown,
                structured_data=structured_json,
                chunks=chunks_with_embeddings,
                stats=stats,
            )
            logger.info(
                "[Persistencia BD] Registro transaccional completado en PostgreSQL",
                policy_id=policy_id,
            )

            # 6. Update Job Status to COMPLETED
            self._repo.update_job(
                job_id=job_id,
                status="COMPLETED",
                policy_id=policy_id,
            )

            elapsed = time.perf_counter() - start_time
            logger.info(
                "[RAG] Pipeline RAG completado exitosamente",
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
                "[ERROR] [RAG] Fallo crítico durante la ejecución del pipeline RAG",
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


"""DocEngine — Infrastructure: PostgreSQL RAG Repository.

Handles all persistence operations for RAG pipeline results in a single SQL transaction.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg2
from psycopg2.extras import Json, execute_values

from app.domain.models.chunks import PolicyChunk
from app.domain.models.rag_models import PolicyProcessingStats
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


def _normalize_file_type(raw_file_type: str | None) -> str:
    """Normalize file_type string to satisfy SQL check constraint.

    Allowed: 'DIGITAL', 'SCANNED', 'HYBRID', 'UNKNOWN'.
    'NATIVE' is mapped to 'DIGITAL'.
    """
    if not raw_file_type:
        return "UNKNOWN"
    val = str(raw_file_type).strip().upper()
    if val in ("DIGITAL", "NATIVE"):
        return "DIGITAL"
    if val in ("SCANNED", "HYBRID"):
        return val
    return "UNKNOWN"


class PgRagRepository:
    """Repository for managing policy RAG persistence in PostgreSQL + pgvector."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    def policy_exists_by_hash(self, file_hash: str) -> str | None:
        """Check if a policy already exists by SHA-256 hash.

        Args:
            file_hash: SHA-256 digest of the PDF file.

        Returns:
            Existing policy_id (UUID string) if found, otherwise None.
        """
        if not file_hash or not file_hash.strip():
            return None
        query = "SELECT id FROM policies WHERE file_hash = %s;"
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (file_hash,))
                row = cur.fetchone()
                return str(row[0]) if row else None

    def create_job(self, file_name: str) -> str:
        """Create a new job entry in processing_jobs table with status 'PROCESSING'.

        Args:
            file_name: Name of the PDF file being processed.

        Returns:
            job_id string (UUID).
        """
        query = """
            INSERT INTO processing_jobs (file_name, status)
            VALUES (%s, 'PROCESSING')
            RETURNING job_id;
        """
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (file_name,))
                row = cur.fetchone()
                if not row:
                    raise RuntimeError(f"Failed to create processing job for {file_name}")
                job_id = str(row[0])
            conn.commit()
            return job_id


    def update_job(
        self,
        job_id: str,
        status: str,
        error_message: str | None = None,
        policy_id: str | None = None,
    ) -> None:
        """Update job status and details in processing_jobs table.

        Args:
            job_id: UUID string of the job.
            status: Status string ('COMPLETED', 'FAILED', 'SKIPPED').
            error_message: Optional error message if status is FAILED.
            policy_id: Optional policy_id UUID string.
        """
        query = """
            UPDATE processing_jobs
            SET status = %s,
                error_message = %s,
                policy_id = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE job_id = %s;
        """
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, (status, error_message, policy_id, job_id))
            conn.commit()

    def save_rag_policy_transactional(
        self,
        file_name: str,
        file_hash: str,
        company_sigla: str | None,
        total_pages: int,
        file_size_bytes: int,
        markdown_content: str,
        structured_data: dict[str, Any],
        chunks: list[PolicyChunk],
        stats: PolicyProcessingStats | None = None,
    ) -> str:
        """Persist all RAG data into PostgreSQL within a single atomic transaction.

        Inserts records across up to 5 tables:
        1. policies
        2. policy_raw_md
        3. policy_structured_data
        4. policy_chunks
        5. policy_processing_stats (if stats provided)

        Args:
            file_name: PDF filename.
            file_hash: SHA-256 digest.
            company_sigla: 3-letter company code (or None).
            total_pages: Number of pages in PDF.
            file_size_bytes: Size of PDF in bytes.
            markdown_content: Markdown text extracted by Docling.
            structured_data: JSON dictionary atomized by gpt-4.1-mini.
            chunks: List of PolicyChunk objects with 1024d embeddings.
            stats: Optional PolicyProcessingStats object with performance metrics.

        Returns:
            Newly created policy_id (UUID string).

        Raises:
            Exception: If any insert fails, triggering automatic ROLLBACK.
        """
        policy_id = str(uuid.uuid4())

        # Normalize company_sigla to uppercase if provided
        sigla = company_sigla.upper() if company_sigla else None

        with self._db.get_connection() as conn:
            try:
                with conn.cursor() as cur:
                    # 1. Insert into policies
                    cur.execute(
                        """
                        INSERT INTO policies (id, file_name, file_hash, company_sigla, total_pages, file_size_bytes)
                        VALUES (%s, %s, %s, %s, %s, %s);
                        """,
                        (policy_id, file_name, file_hash, sigla, total_pages, file_size_bytes),
                    )

                    # 2. Insert into policy_raw_md
                    cur.execute(
                        """
                        INSERT INTO policy_raw_md (policy_id, markdown_content)
                        VALUES (%s, %s);
                        """,
                        (policy_id, markdown_content),
                    )

                    # 3. Insert into policy_structured_data
                    cur.execute(
                        """
                        INSERT INTO policy_structured_data (policy_id, data)
                        VALUES (%s, %s);
                        """,
                        (policy_id, Json(structured_data)),
                    )

                    # 4. Insert into policy_chunks (batch execute)
                    if chunks:
                        chunk_tuples = []
                        for chunk in chunks:
                            # Format embedding list as string vector representation '[0.1, 0.2, ...]'
                            vector_str = (
                                json.dumps(chunk.embedding)
                                if chunk.embedding is not None
                                else None
                            )
                            chunk_tuples.append(
                                (
                                    policy_id,
                                    chunk.chunk_index,
                                    chunk.chunk_content,
                                    Json(chunk.metadata_json),
                                    vector_str,
                                    chunk.chunk_id,
                                    chunk.parent_id,
                                    chunk.chunk_type or "parent",
                                )
                            )

                        execute_values(
                            cur,
                            """
                            INSERT INTO policy_chunks (policy_id, chunk_index, chunk_content, metadata_json, embedding, chunk_id, parent_id, chunk_type)
                            VALUES %s;
                            """,
                            chunk_tuples,
                            template="(%s, %s, %s, %s, %s::vector, %s::uuid, %s::uuid, %s)",
                        )

                    # 5. Insert into policy_processing_stats (if provided)
                    if stats:
                        cur.execute(
                            """
                            INSERT INTO policy_processing_stats (
                                policy_id, job_id, policy_number, company_sigla, file_type,
                                ocr_applied, scanned_page_ratio, total_pages, extraction_time_seconds,
                                time_per_page_seconds, chunking_time_seconds, embedding_time_seconds,
                                openai_time_seconds, total_pipeline_time_seconds, total_chunks,
                                parent_chunks, child_chunks, openai_prompt_tokens, openai_completion_tokens,
                                openai_total_tokens, openai_estimated_cost_usd, coberturas_extracted_count,
                                tables_detected, memory_peak_mb
                            )
                            VALUES (
                                %s, %s, %s, %s, %s,
                                %s, %s, %s, %s,
                                %s, %s, %s,
                                %s, %s, %s,
                                %s, %s, %s, %s,
                                %s, %s, %s,
                                %s, %s
                            )
                            ON CONFLICT (policy_id) DO UPDATE SET
                                job_id = EXCLUDED.job_id,
                                policy_number = EXCLUDED.policy_number,
                                company_sigla = EXCLUDED.company_sigla,
                                file_type = EXCLUDED.file_type,
                                ocr_applied = EXCLUDED.ocr_applied,
                                scanned_page_ratio = EXCLUDED.scanned_page_ratio,
                                total_pages = EXCLUDED.total_pages,
                                extraction_time_seconds = EXCLUDED.extraction_time_seconds,
                                time_per_page_seconds = EXCLUDED.time_per_page_seconds,
                                chunking_time_seconds = EXCLUDED.chunking_time_seconds,
                                embedding_time_seconds = EXCLUDED.embedding_time_seconds,
                                openai_time_seconds = EXCLUDED.openai_time_seconds,
                                total_pipeline_time_seconds = EXCLUDED.total_pipeline_time_seconds,
                                total_chunks = EXCLUDED.total_chunks,
                                parent_chunks = EXCLUDED.parent_chunks,
                                child_chunks = EXCLUDED.child_chunks,
                                openai_prompt_tokens = EXCLUDED.openai_prompt_tokens,
                                openai_completion_tokens = EXCLUDED.openai_completion_tokens,
                                openai_total_tokens = EXCLUDED.openai_total_tokens,
                                openai_estimated_cost_usd = EXCLUDED.openai_estimated_cost_usd,
                                coberturas_extracted_count = EXCLUDED.coberturas_extracted_count,
                                tables_detected = EXCLUDED.tables_detected,
                                memory_peak_mb = EXCLUDED.memory_peak_mb;
                            """,
                            (
                                policy_id,
                                stats.job_id,
                                stats.policy_number,
                                sigla,
                                _normalize_file_type(stats.file_type),
                                stats.ocr_applied,
                                stats.scanned_page_ratio,
                                stats.total_pages,
                                stats.extraction_time_seconds,
                                stats.time_per_page_seconds,
                                stats.chunking_time_seconds,
                                stats.embedding_time_seconds,
                                stats.openai_time_seconds,
                                stats.total_pipeline_time_seconds,
                                stats.total_chunks,
                                stats.parent_chunks,
                                stats.child_chunks,
                                stats.openai_prompt_tokens,
                                stats.openai_completion_tokens,
                                stats.openai_total_tokens,
                                stats.openai_estimated_cost_usd,
                                stats.coberturas_extracted_count,
                                stats.tables_detected,
                                stats.memory_peak_mb,
                            ),
                        )

                # Commit transaction
                conn.commit()
                logger.info(
                    "Policy RAG data persisted transactionally",
                    policy_id=policy_id,
                    chunks_count=len(chunks),
                    company_sigla=sigla,
                    has_stats=stats is not None,
                )
                return policy_id

            except Exception as e:
                conn.rollback()
                logger.error(
                    "Transaction failed while persisting policy RAG data. Rolled back.",
                    file_name=file_name,
                    error=str(e),
                )
                raise

    def save_processing_stats(self, stats: PolicyProcessingStats) -> None:
        """Persist or update processing statistics for a policy.

        Args:
            stats: PolicyProcessingStats instance.
        """
        query = """
            INSERT INTO policy_processing_stats (
                policy_id, job_id, policy_number, company_sigla, file_type,
                ocr_applied, scanned_page_ratio, total_pages, extraction_time_seconds,
                time_per_page_seconds, chunking_time_seconds, embedding_time_seconds,
                openai_time_seconds, total_pipeline_time_seconds, total_chunks,
                parent_chunks, child_chunks, openai_prompt_tokens, openai_completion_tokens,
                openai_total_tokens, openai_estimated_cost_usd, coberturas_extracted_count,
                tables_detected, memory_peak_mb
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            ON CONFLICT (policy_id) DO UPDATE SET
                job_id = EXCLUDED.job_id,
                policy_number = EXCLUDED.policy_number,
                company_sigla = EXCLUDED.company_sigla,
                file_type = EXCLUDED.file_type,
                ocr_applied = EXCLUDED.ocr_applied,
                scanned_page_ratio = EXCLUDED.scanned_page_ratio,
                total_pages = EXCLUDED.total_pages,
                extraction_time_seconds = EXCLUDED.extraction_time_seconds,
                time_per_page_seconds = EXCLUDED.time_per_page_seconds,
                chunking_time_seconds = EXCLUDED.chunking_time_seconds,
                embedding_time_seconds = EXCLUDED.embedding_time_seconds,
                openai_time_seconds = EXCLUDED.openai_time_seconds,
                total_pipeline_time_seconds = EXCLUDED.total_pipeline_time_seconds,
                total_chunks = EXCLUDED.total_chunks,
                parent_chunks = EXCLUDED.parent_chunks,
                child_chunks = EXCLUDED.child_chunks,
                openai_prompt_tokens = EXCLUDED.openai_prompt_tokens,
                openai_completion_tokens = EXCLUDED.openai_completion_tokens,
                openai_total_tokens = EXCLUDED.openai_total_tokens,
                openai_estimated_cost_usd = EXCLUDED.openai_estimated_cost_usd,
                coberturas_extracted_count = EXCLUDED.coberturas_extracted_count,
                tables_detected = EXCLUDED.tables_detected,
                memory_peak_mb = EXCLUDED.memory_peak_mb;
        """
        sigla = stats.company_sigla.upper() if stats.company_sigla else None
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        stats.policy_id,
                        stats.job_id,
                        stats.policy_number,
                        sigla,
                        _normalize_file_type(stats.file_type),
                        stats.ocr_applied,
                        stats.scanned_page_ratio,
                        stats.total_pages,
                        stats.extraction_time_seconds,
                        stats.time_per_page_seconds,
                        stats.chunking_time_seconds,
                        stats.embedding_time_seconds,
                        stats.openai_time_seconds,
                        stats.total_pipeline_time_seconds,
                        stats.total_chunks,
                        stats.parent_chunks,
                        stats.child_chunks,
                        stats.openai_prompt_tokens,
                        stats.openai_completion_tokens,
                        stats.openai_total_tokens,
                        stats.openai_estimated_cost_usd,
                        stats.coberturas_extracted_count,
                        stats.tables_detected,
                        stats.memory_peak_mb,
                    ),
                )
            conn.commit()


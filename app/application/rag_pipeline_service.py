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
from app.domain.models.envelope import DocumentType, normalize_document_type
from app.domain.models.rag_models import PolicyProcessingStats, RagProcessingReport
from app.infrastructure.database.pg_envelope_repository import PgEnvelopeRepository
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
        envelope_repository: PgEnvelopeRepository | None = None,
    ) -> None:
        self._chunker = chunking_service
        self._embedder = embedding_service
        self._extractor = structured_extractor
        self._repo = repository
        if envelope_repository is not None:
            self._envelope_repo = envelope_repository
        elif hasattr(repository, "_db") and repository._db is not None:
            self._envelope_repo = PgEnvelopeRepository(repository._db)
        else:
            self._envelope_repo = None

    def _resolve_and_ensure_envelope(
        self,
        pol_num: str | None,
        company_sigla: str | None,
        ramo: str | None,
        id_cliente: str | None,
        nombre_cliente: str | None,
        file_name: str | None = None,
        file_hash: str | None = None,
    ) -> str | None:
        """Safeguard: Resolves, retrieves or creates a valid policy envelope.

        Ensures envelope_id is NEVER None when self._envelope_repo is configured.
        Implements fallback strategies:
          1. Matches existing envelope by (id_cliente, company_sigla) if pol_num is missing.
          2. Infers policy number from filename tokens.
          3. Synthesizes a deterministic policy number if none can be inferred.
          4. Employs resilient retry with minimal parameters in case of unexpected metadata errors.
        """
        if not self._envelope_repo:
            return None

        effective_num = (pol_num or "").strip()
        effective_sigla = (company_sigla or "").strip().upper() or None
        effective_client = (id_cliente or "").strip() or None
        effective_name = (nombre_cliente or "").strip() or None
        effective_ramo = (ramo or "").strip() or None

        # Strategy 1: If pol_num is missing, search existing envelopes for this client & company
        if not effective_num and effective_client and hasattr(self._envelope_repo, "get_envelopes_by_client_id"):
            try:
                client_envs = self._envelope_repo.get_envelopes_by_client_id(effective_client)
                if client_envs:
                    matched = [e for e in client_envs if effective_sigla and e.get("company_sigla") == effective_sigla]
                    if not matched:
                        matched = client_envs
                    if matched:
                        if effective_ramo:
                            by_ramo = [e for e in matched if e.get("ramo") == effective_ramo]
                            if by_ramo:
                                matched = by_ramo
                        chosen_env = matched[0]
                        logger.info(
                            "[Envelope Safeguard] Asociando documento huérfano a sobre existente del cliente",
                            envelope_id=chosen_env.get("id"),
                            numero_poliza=chosen_env.get("numero_poliza"),
                            id_cliente=effective_client,
                        )
                        return chosen_env.get("id")
            except Exception as e:
                logger.warning("[Envelope Safeguard] Error buscando sobres existentes del cliente", error=str(e))

        # Strategy 2: If still no policy number, infer from filename
        if not effective_num and file_name:
            import re  # noqa: PLC0415
            from pathlib import Path  # noqa: PLC0415
            stem = Path(file_name).stem
            tokens = [t.strip() for t in re.split(r"[_\#\-]+", stem) if t.strip()]
            for token in tokens:
                if any(c.isdigit() for c in token) and len(token) >= 4:
                    upper_t = token.upper()
                    if upper_t not in ("CONDICIONADO", "LIQUIDACION", "ANEXO", "CARATULA", "GENERAL", "PARTICULAR", "POLIZA"):
                        effective_num = token
                        break

        # Strategy 3: Deterministic fallback policy number if still missing
        if not effective_num:
            safe_suffix = effective_client or (file_hash[:8] if file_hash else "DOC")
            effective_num = f"POL-{effective_sigla or 'DOC'}-{safe_suffix}"
            logger.info(
                "[Envelope Safeguard] Generando número de póliza sintético para garantizar existencia de sobre",
                synthetic_pol_num=effective_num,
                file_name=file_name,
            )

        # Call get_or_create_envelope with standard parameters
        env_kwargs: dict[str, Any] = {
            "numero_poliza": effective_num,
            "company_sigla": effective_sigla,
            "ramo": effective_ramo,
        }
        if effective_client:
            env_kwargs["id_cliente"] = effective_client
        if effective_name:
            env_kwargs["nombre_cliente"] = effective_name

        try:
            envelope_id = self._envelope_repo.get_or_create_envelope(**env_kwargs)
            if envelope_id:
                return envelope_id
        except Exception as exc:
            logger.error(
                "[Envelope Safeguard] Error en get_or_create_envelope con metadatos completos, reintentando con parámetros mínimos",
                error=str(exc),
            )

        # Resilient fallback retry: Minimal parameters (prevents string bounds/metadata errors)
        try:
            return self._envelope_repo.get_or_create_envelope(
                numero_poliza=effective_num[:100],
                company_sigla=effective_sigla[:20] if effective_sigla else None,
            )
        except Exception as exc_minimal:
            logger.critical(
                "[Envelope Safeguard] Fallo crítico definitivo al crear envelope",
                error=str(exc_minimal),
                file_name=file_name,
            )
            return None


    def process_extraction_result(
        self,
        result: ExtractionResult,
        numero_poliza: str | None = None,
        ramo: str | None = None,
        tipo_documento: str | None = None,
        id_cliente: str | None = None,
        nombre_cliente: str | None = None,
    ) -> RagProcessingReport:
        """Process an ExtractionResult through the RAG pipeline and persist to PostgreSQL.

        Args:
            result: The ExtractionResult produced by Docling/ExtractionService.
            numero_poliza: Optional policy number hint for envelope binding.
            ramo: Optional insurance branch/line name.
            tipo_documento: Optional document classification (e.g. CONDICIONADO_GENERAL).
            id_cliente: Optional customer identifier (Carnet or NIT).
            nombre_cliente: Optional customer name or business name.

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

        # Resolve policy envelope parameters (explicit arguments override metadata)
        pol_num = numero_poliza or getattr(result.metadata, "numero_poliza", None)
        pol_ramo = ramo or getattr(result.metadata, "ramo", None)
        doc_type = tipo_documento or getattr(result.metadata, "tipo_documento", None)
        client_id_hint = id_cliente or getattr(result.metadata, "id_cliente", None)
        client_name_hint = nombre_cliente or getattr(result.metadata, "nombre_cliente", None)

        logger.info(
            "[RAG] Iniciando pipeline RAG y almacenamiento vectorial...",
            file_name=file_name,
            file_hash=file_hash,
            company_sigla=company_sigla,
            numero_poliza=pol_num,
            tipo_documento=doc_type,
            id_cliente=client_id_hint,
            nombre_cliente=client_name_hint,
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
                envelope_id = None
                effective_doc_type = (
                    normalize_document_type(doc_type)
                    or normalize_document_type(file_name)
                    or DocumentType.POLIZA_PRINCIPAL.value
                )

                if self._envelope_repo:
                    effective_pol_num = pol_num
                    effective_ramo = pol_ramo
                    effective_sigla = company_sigla
                    if not effective_pol_num and hasattr(self._repo, "_db") and self._repo._db is not None:
                        try:
                            with self._repo._db.get_connection() as conn:
                                with conn.cursor() as cur:
                                    cur.execute(
                                        "SELECT data FROM policy_structured_data WHERE policy_id = %s;",
                                        (existing_policy_id,),
                                    )
                                    row = cur.fetchone()
                                    if row and row[0]:
                                        data_dict = row[0]
                                        cabecera = data_dict.get("datos_cabecera", {}) if isinstance(data_dict, dict) else {}
                                        effective_pol_num = cabecera.get("numero_poliza") or data_dict.get("numero_poliza")
                                        effective_ramo = effective_ramo or cabecera.get("ramo") or data_dict.get("ramo")
                                        effective_sigla = effective_sigla or cabecera.get("sigla_empresa") or data_dict.get("sigla_empresa")
                        except Exception as e:
                            logger.debug("No se pudo obtener structured_data para idempotencia", error=str(e))


                    envelope_id = self._resolve_and_ensure_envelope(
                        pol_num=effective_pol_num,
                        company_sigla=effective_sigla,
                        ramo=effective_ramo,
                        id_cliente=client_id_hint,
                        nombre_cliente=client_name_hint,
                        file_name=file_name,
                        file_hash=file_hash,
                    )
                    if envelope_id:
                        try:
                            self._envelope_repo.link_policy_to_envelope(
                                policy_id=existing_policy_id,
                                envelope_id=envelope_id,
                                tipo_documento=effective_doc_type,
                                id_cliente=client_id_hint,
                                nombre_cliente=client_name_hint,
                            )
                        except Exception as link_exc:
                            logger.warning("Error vinculando póliza duplicada a envelope", error=str(link_exc))
                        result.metadata.envelope_id = envelope_id
                        result.metadata.tipo_documento = effective_doc_type
                        if client_id_hint:
                            result.metadata.id_cliente = client_id_hint
                        if client_name_hint:
                            result.metadata.nombre_cliente = client_name_hint

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
                    envelope_id=envelope_id,
                    tipo_documento=effective_doc_type,
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

            extracted_policy_num = (
                structured_json.get("datos_cabecera", {}).get("numero_poliza")
                if isinstance(structured_json.get("datos_cabecera"), dict)
                else structured_json.get("numero_poliza")
            )
            extracted_sigla = (
                structured_json.get("datos_cabecera", {}).get("sigla_empresa")
                if isinstance(structured_json.get("datos_cabecera"), dict)
                else structured_json.get("sigla_empresa")
            )
            extracted_ramo = (
                structured_json.get("datos_cabecera", {}).get("ramo")
                if isinstance(structured_json.get("datos_cabecera"), dict)
                else structured_json.get("ramo")
            )
            extracted_nit = (
                structured_json.get("datos_cabecera", {}).get("nit")
                if isinstance(structured_json.get("datos_cabecera"), dict)
                else structured_json.get("nit")
            )
            extracted_ci = (
                structured_json.get("datos_cabecera", {}).get("documento_identidad")
                if isinstance(structured_json.get("datos_cabecera"), dict)
                else structured_json.get("documento_identidad")
            )
            extracted_tomador = (
                structured_json.get("datos_cabecera", {}).get("tomador")
                if isinstance(structured_json.get("datos_cabecera"), dict)
                else structured_json.get("tomador")
            )
            extracted_asegurado = (
                structured_json.get("datos_cabecera", {}).get("asegurado")
                if isinstance(structured_json.get("datos_cabecera"), dict)
                else structured_json.get("asegurado")
            )

            effective_pol_num = pol_num or extracted_policy_num
            effective_sigla = company_sigla or extracted_sigla or getattr(result.metadata, "company_sigla", None)
            effective_ramo = pol_ramo or extracted_ramo or getattr(result.metadata, "ramo", None)
            effective_id_cliente = client_id_hint or extracted_nit or extracted_ci
            effective_nombre_cliente = client_name_hint or extracted_tomador or extracted_asegurado
            effective_doc_type = (
                normalize_document_type(doc_type)
                or normalize_document_type(file_name)
                or DocumentType.POLIZA_PRINCIPAL.value
            )

            envelope_id = self._resolve_and_ensure_envelope(
                pol_num=effective_pol_num,
                company_sigla=effective_sigla,
                ramo=effective_ramo,
                id_cliente=effective_id_cliente,
                nombre_cliente=effective_nombre_cliente,
                file_name=file_name,
                file_hash=file_hash,
            )
            if self._envelope_repo and not envelope_id:
                logger.error(
                    "[Envelope Safeguard] ALERTA CRÍTICA: No se pudo asignar envelope_id",
                    file_name=file_name,
                    file_hash=file_hash,
                )

            # Enrich chunks metadata with id_cliente and nombre_cliente if available
            if effective_id_cliente or effective_nombre_cliente:
                for c in chunks_with_embeddings:
                    if c.metadata_json is None:
                        c.metadata_json = {}
                    if effective_id_cliente and "id_cliente" not in c.metadata_json:
                        c.metadata_json["id_cliente"] = effective_id_cliente
                    if effective_nombre_cliente and "nombre_cliente" not in c.metadata_json:
                        c.metadata_json["nombre_cliente"] = effective_nombre_cliente

            logger.info(
                "[Persistencia BD] Guardando póliza, chunks, vectores y estadísticas en PostgreSQL (pgvector)...",
                chunks_count=len(chunks_with_embeddings),
                file_name=file_name,
                envelope_id=envelope_id,
                tipo_documento=effective_doc_type,
                id_cliente=effective_id_cliente,
                nombre_cliente=effective_nombre_cliente,
            )
            policy_id = self._repo.save_rag_policy_transactional(
                file_name=file_name,
                file_hash=file_hash,
                company_sigla=effective_sigla,
                total_pages=result.metadata.page_count,
                file_size_bytes=result.metadata.markdown_size_bytes,
                markdown_content=result.markdown,
                structured_data=structured_json,
                chunks=chunks_with_embeddings,
                stats=stats,
                envelope_id=envelope_id,
                tipo_documento=effective_doc_type,
                id_cliente=effective_id_cliente,
                nombre_cliente=effective_nombre_cliente,
            )
            result.metadata.envelope_id = envelope_id
            result.metadata.tipo_documento = effective_doc_type
            result.metadata.id_cliente = effective_id_cliente
            result.metadata.nombre_cliente = effective_nombre_cliente

            logger.info(
                "[Persistencia BD] Registro transaccional completado en PostgreSQL",
                policy_id=policy_id,
                envelope_id=envelope_id,
                id_cliente=effective_id_cliente,
                nombre_cliente=effective_nombre_cliente,
            )

            # 6. Update Job Status to COMPLETED
            self._repo.update_job(
                job_id=job_id,
                status="COMPLETED",
                policy_id=policy_id,
            )

            # [ADITIVO FASE 2] Pólizas GRANDES: generar mapa estructural en segundo plano
            if (result.metadata.page_count >= 500 or len(chunks_with_embeddings) >= 1500) and hasattr(self._repo, "_db"):
                try:
                    from app.application.policy_map_service import PolicyMapService
                    PolicyMapService(self._repo._db).generate_map_for_policy(
                        policy_id=policy_id,
                        envelope_id=envelope_id,
                    )
                except Exception as map_err:
                    logger.warning("No se pudo generar mapa de póliza grande durante ingesta", error=str(map_err))

            # [ADITIVO] Nómina de Flota: extracción determinista en pólizas de automotores colectivas
            if hasattr(self._repo, "_db"):
                try:
                    is_automotor = bool(
                        (effective_ramo and "AUTO" in str(effective_ramo).upper())
                        or ("VEHICULO" in str(result.markdown or "")[:50000].upper() and "PLACA" in str(result.markdown or "")[:50000].upper())
                    )
                    if is_automotor:
                        from app.application.fleet_extractor_service import FleetExtractorService
                        FleetExtractorService(self._repo._db).extract_and_save_policy_fleet(
                            policy_id=policy_id,
                            envelope_id=envelope_id,
                        )
                except Exception as fleet_err:
                    logger.warning("No se pudo extraer nómina de flota durante ingesta", error=str(fleet_err))

            # [ADITIVO] Nómina Colectiva de Personas: extracción determinista en Salud, Accidentes y Vida
            if hasattr(self._repo, "_db"):
                try:
                    md_sample = str(result.markdown or "")[:80000].upper()
                    is_collective_person = bool(
                        (effective_ramo and any(r in str(effective_ramo).upper() for r in ["ACCIDENTE", "SALUD", "MEDICA", "ENFERMEDAD", "VIDA", "PERSONAS"]))
                        or ("NOMINA DE ASEGURADOS" in md_sample or "NÓMINA DE ASEGURADOS" in md_sample or "REGISTRO DE ASEGURADOS" in md_sample)
                    )
                    if is_collective_person:
                        from app.application.collective_insured_extractor_service import CollectiveInsuredExtractorService
                        CollectiveInsuredExtractorService(self._repo._db).extract_and_save_policy_insured(
                            policy_id=policy_id,
                            envelope_id=envelope_id,
                        )
                except Exception as insured_err:
                    logger.warning("No se pudo extraer nómina colectiva de personas durante ingesta", error=str(insured_err))

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
                company_sigla=effective_sigla,
                chunks_created=len(chunks_with_embeddings),
                embedding_dim=1024,
                skipped_duplicate=False,
                processing_time_seconds=elapsed,
                job_id=job_id,
                envelope_id=envelope_id,
                tipo_documento=effective_doc_type,
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


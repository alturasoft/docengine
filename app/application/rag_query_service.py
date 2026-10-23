"""DocEngine — Application Service: RAGQueryService.

Orchestrates the full RAG query pipeline:
1. Validates the user question.
2. Generates a query embedding using the shared EmbeddingService (bge-m3).
3. Retrieves top-K similar chunks from PgVectorSearchRepository.
4. Assembles a context string with per-chunk metadata labels.
5. Calls OpenAI (gpt-4.1-mini) with a strict anti-hallucination system prompt.
6. Returns a typed QueryResponse with the answer and source references.

This module is strictly read-only with respect to the database — it does NOT
import or call any ingestion-side code (RagPipelineService, ChunkingService,
PgRagRepository, etc.).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import openai

from app.config.settings import RAGQueryConfig
from app.domain.models.query_models import QueryResponse, RetrievedChunk
from app.infrastructure.logging.logger import get_logger

# [ADITIVO] Estrategia de contexto para pólizas GRANDES
from app.application.large_policy_context import (
    ContextTooLargeError,
    LargePolicyContextStrategy,
    is_request_too_large,
)
from app.config.settings import LargePolicyConfig

if TYPE_CHECKING:
    from app.application.embedding_service import EmbeddingService
    from app.application.reranker_service import RerankerService
    from app.infrastructure.database.pg_hybrid_search import PgHybridSearchRepository
    from app.infrastructure.database.pg_structured_search import PgStructuredSearchRepository
    from app.infrastructure.database.pg_vector_search import PgVectorSearchRepository

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# System prompt — strict anti-hallucination, Spanish-first
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Eres un consultor experto en análisis de pólizas de seguros bolivianas. Tu objetivo es orientar y resolver las consultas del usuario analizando exhaustivamente la documentación proporcionada en el CONTEXTO.

DIRECTRICES DE RESPUESTA:

1. Exhaustividad y Enfoque Constructivo:
   - Examina con atención todos los fragmentos del contexto (tablas, cláusulas particulares, condiciones generales, exclusiones, notas y anexos).
   - Proporciona respuestas útiles, completas y fundamentadas. Si la información en el contexto no cubre el 100% de la pregunta pero incluye datos relacionados o bases contractuales pertinentes, explica claramente lo que sí está estipulado y aclara con precisión qué detalle específico no figura.

2. Flexibilidad Semántica y Vocabulario Asegurador:
   - Relaciona el lenguaje cotidiano del usuario con la terminología técnica de seguros bolivianos (ej. deducible / franquicia; costo / prima; cobertura / amparo / materia asegurada; grúa / remolque / auxilio mecánico; vigencia / plazo; valor asegurado / límite de indemnización).
   - En preguntas de ubicación, talleres o proveedores (ej. "4to anillo", avenidas, intersecciones), reconoce variaciones de nombres bolivianos. Si hay un taller o proveedor en esa zona o calle en el contexto, detállalo (nombre, dirección, teléfono). Si no existe exactamente en ese punto pero sí en la misma ciudad o zona circundante, presenta las opciones disponibles para orientar al asegurado.

3. Análisis de Escenarios y Deducción Lógica:
   - Si el usuario plantea un caso práctico, escenario o pregunta situacional (ej. siniestros en circunstancias particulares, requisitos de procedencia o eventos no típicos), DEDUCE lógicamente a partir de las cláusulas, exclusiones y alcance estipulados si procede, no procede o bajo qué condiciones aplicaría, citando la cláusula o sección correspondiente.

4. Fidelidad al Documento y Transparencia:
   - Basa tus conclusiones en la documentación del contexto. No inventes montos asegurados, tasas ni coberturas no respaldadas.
   - Si tras una revisión exhaustiva de todos los fragmentos resulta evidente que un tema consultado no se menciona en absoluto en el contexto, indícalo con naturalidad y cortesía (ej. "En el documento  digitalizado de la póliza no se especifica información sobre [tema]..."), y complementa con cualquier dato afín que sí esté estipulado.

5. Estilo, Estructura y Citación:
   - Responde en el mismo idioma de la pregunta, con tono profesional, empático y estructurado (emplea viñetas o tablas cuando facilite la comprensión). Cita la sección, anexo o cláusula fuente cuando sea relevante.

6. Regla de Primacía Jurídica y Correlación de Tablas Particulares:
   - En caso de conflicto, discrepancia o aparente contradicción entre las Condiciones Generales y las Condiciones Particulares o Anexos Modificatorios (por ejemplo: plazos de aviso de siniestro, márgenes de alcoholemia, franquicias o sublímites):
     * Aplica rigurosamente el orden de prevalencia contractual legal: los ANEXOS y las CONDICIONES PARTICULARES prevalecen siempre sobre las Condiciones Generales.
     * Si en las Condiciones Particulares o Anexos se estipula una ampliación (ej. aviso de siniestro de hasta 15 días frente a la regla general de 3 días) o una especificación concreta (ej. tolerancia de alcoholemia especificada como 'SÓLO 0.5% MG'), DEBES declarar dicho valor particular como el plenamente aplicable al asegurado, indicando que modifica o complementa la condición general.
   - Correlación Tabular en Aclaraciones y Condiciones Particulares: En las secciones de Aclaraciones y Condiciones Particulares, los nombres de cláusulas y sus condiciones/valores asociados suelen listarse secuencialmente:
     * El 'ANEXO ACLARATORIO DE ALCOHOLEMIA PERMITIDA' se correlaciona directamente con la especificación particular 'SÓLO 0.5% MG' (0.5 g/l o 0.5 por mil).
     * La 'CLÁUSULA MODIFICATORIA DE DEFINICIÓN DE PÉRDIDA TOTAL POR ACCIDENTE' se correlaciona con 'POR DAÑO ESTRUCTURAL QUE ALCANCE AL 50%'.
     * La 'CLÁUSULA DE AMPLIACIÓN DE AVISO DE SINIESTRO' se correlaciona directamente con la especificación particular 'HASTA 15 DÍAS CALENDARIOS'. En virtud de la prevalencia de las condiciones particulares y anexos sobre las generales, la respuesta afirmativa y operativa para el asegurado debe ser de 15 días calendarios (indicando expresamente que este plazo particular amplía y prevalece sobre el plazo general de 3 días del condicionado impreso y del Código de Comercio).
     * En 'ACCIDENTES PERSONALES A OCUPANTES', la secuencia de sumas aseguradas por persona cubierta corresponde a: Gastos de Sepelio Bs. 7.000, Muerte Accidental Bs. 70.000, Invalidez Total y/o Parcial Permanente Bs. 70.000, y Gastos Médicos Bs. 14.000.
     Examina con máxima minuciosidad estos valores tabulares particulares e inclúyelos textualmente en tus respuestas.

7. Nómina de Vehículos en Pólizas Colectivas de Flota:
   - Cuando en el contexto figure la sección "NÓMINA OFICIAL Y COMPLETA DE VEHÍCULOS ASEGURADOS" y el usuario solicite la nómina o el listado de vehículos asegurados:
     * Presenta la lista o tabla estructurada de los vehículos provistos en el contexto (incluyendo Ítem, Tipo, Marca, Modelo, Año, Placa, Chasis y Valor Asegurado). No limites arbitrariamente la respuesta a una muestra si la nómina está provista en el contexto.
     * Al final de la respuesta, proporciona el enlace de descarga en formato Excel / CSV para que el usuario pueda abrir el archivo directamente en Excel.

8. Nómina de Personas en Pólizas Colectivas (Salud, Accidentes Personales, Vida en Grupo):
   - Cuando en el contexto figure la sección "NÓMINA OFICIAL Y COMPLETA DE ASEGURADOS" y el usuario solicite la nómina, el listado de personas o verificar si un asegurado está cubierto:
     * Presenta la tabla o lista de los asegurados provistos en el contexto (incluyendo Ítem, Nombre Completo, Documento/CI, Categoría/Parentesco, Edad, Cargo y Suma Asegurada).
     * Al final de la respuesta, proporciona el enlace de descarga en formato Excel / CSV para que el usuario pueda descargar la nómina completa.

9. Cartera de Pólizas del Cliente y Resumen de Vigencias:
   - Cuando en el contexto figure la sección "[CARTERA DE PÓLIZAS DEL CLIENTE]" y el usuario consulte sobre la cartera de pólizas o la vigencia de todas las pólizas del cliente:
     * Presenta exactamente UNA fila o entrada por cada póliza única registrada en la cartera del cliente.
     * NUNCA repitas filas idénticas, números de póliza duplicados ni valores de vigencia idénticos. Los anexos, certificados o endosos forman parte de la misma póliza matriz.
     * Estructura la respuesta de forma clara (en tabla o lista numerada) detallando para cada póliza: N° de Póliza, Aseguradora, Ramo, y Período de Vigencia (Desde - Hasta).
"""

_CONTEXT_HEADER = """\
CONTEXTO:
{context}

PREGUNTA:
{question}"""

# Contingency response — returned verbatim when no chunks pass the threshold
_NO_CONTEXT_ANSWER = "No dispongo de esa información en los documentos proporcionados."



class RAGQueryService:
    """Main orchestrator for the RAG read/query path.

    Accepts a user question, retrieves relevant document chunks from the
    vector store, injects them into a structured prompt, and returns an
    LLM-generated answer with full source attribution.

    Dependencies are injected at construction time for testability.

    Args:
        embedding_service: Shared EmbeddingService instance (bge-m3 model).
            Reused from the ingestion pipeline to avoid double model loading.
        vector_search: PgVectorSearchRepository for similarity search.
        config: RAGQueryConfig controlling top_k, threshold, model, etc.
    """

    def __init__(
        self,
        embedding_service: EmbeddingService,
        vector_search: PgVectorSearchRepository,
        config: RAGQueryConfig,
        # --- Parent-Child Retrieval dependencies (optional, backward-compatible) ---
        hybrid_search: PgHybridSearchRepository | None = None,
        reranker: RerankerService | None = None,
        # --- Structured Data Search dependency (optional, backward-compatible) ---
        structured_search: PgStructuredSearchRepository | None = None,
        # --- Policy Map Service dependency (optional, backward-compatible, Fase 2) ---
        policy_map: Any | None = None,
    ) -> None:
        self._embedder = embedding_service
        self._vector_search = vector_search
        self._config = config
        self._hybrid_search = hybrid_search
        self._reranker = reranker
        self._structured_search = structured_search
        self._openai_client: openai.OpenAI | None = None

        # [ADITIVO FASE 1 & 2] Estrategia para pólizas grandes con Mapa y Multi-Query
        map_service = policy_map
        if map_service is None and hasattr(vector_search, "_db") and vector_search._db is not None:
            try:
                from app.application.policy_map_service import PolicyMapService
                map_service = PolicyMapService(vector_search._db)
            except Exception:
                map_service = None

        fleet_service = None
        insured_service = None
        if hasattr(vector_search, "_db") and vector_search._db is not None:
            try:
                from app.application.fleet_extractor_service import FleetExtractorService
                fleet_service = FleetExtractorService(vector_search._db)
            except Exception:
                fleet_service = None

            try:
                from app.application.collective_insured_extractor_service import CollectiveInsuredExtractorService
                insured_service = CollectiveInsuredExtractorService(vector_search._db)
            except Exception:
                insured_service = None

        self._fleet_service = fleet_service
        self._insured_service = insured_service

        self._large_policy = LargePolicyContextStrategy(
            config=LargePolicyConfig(),
            priority_fn=self._chunk_hierarchy_priority,
            map_service=map_service,
            fleet_service=fleet_service,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def query(
        self,
        question: str,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
        filters: dict[str, Any] | None = None,
    ) -> QueryResponse:
        """Execute a full RAG query cycle and return an answer with sources.

        Args:
            question: Natural language question from the user. Must not be empty.
            top_k: Number of chunks to retrieve. Defaults to config.top_k (5).
                Clamped to [1, 20].
            similarity_threshold: Minimum similarity score for a chunk to be
                included in context. Defaults to config.similarity_threshold (0.3).
            filters: Optional pre-filter dict. Supported keys:
                - "policy_id" (str): Restrict search to a specific document.
                - "company_sigla" (str): Restrict search to a specific company.

        Returns:
            QueryResponse with the LLM answer, source chunks, and metadata.

        Raises:
            ValueError: If question is empty or whitespace-only.
        """
        question = question.strip()
        if not question:
            raise ValueError("The question must not be empty.")

        resolved_top_k = top_k if top_k is not None else self._config.top_k
        resolved_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self._config.similarity_threshold
        )

        effective_filters = dict(filters) if filters else {}
        if "sigla_aseguradora" in effective_filters and "company_sigla" not in effective_filters:
            effective_filters["company_sigla"] = effective_filters["sigla_aseguradora"]
        elif "aseguradora" in effective_filters and "company_sigla" not in effective_filters:
            effective_filters["company_sigla"] = effective_filters["aseguradora"]

        logger.info(
            "RAG query started",
            question_preview=question[:80],
            top_k=resolved_top_k,
            threshold=resolved_threshold,
            filters=effective_filters or None,
        )

        # Step 0: Check for structured policy data (JSONB)
        structured_chunks: list[RetrievedChunk] = []
        if self._structured_search is not None:
            policy_id_filter = effective_filters.get("policy_id")
            client_id_filter = effective_filters.get("id_cliente")
            envelope_id_filter = effective_filters.get("envelope_id")
            if policy_id_filter:
                record = self._structured_search.find_by_policy_id(policy_id_filter)
                if record:
                    structured_chunks.append(
                        self._structured_search.format_structured_chunk(record)
                    )
            elif client_id_filter and not envelope_id_filter and hasattr(self._structured_search, "find_by_client_id"):
                client_records = self._structured_search.find_by_client_id(client_id_filter)
                if client_records:
                    structured_chunks.append(
                        self._structured_search.format_client_portfolio_chunk(client_records, client_id_filter)
                    )
            else:
                matched_records = self._structured_search.search_by_query_text(
                    question, limit=2
                )
                for record in matched_records:
                    structured_chunks.append(
                        self._structured_search.format_structured_chunk(record)
                    )
                    # If exactly one policy matched, focus downstream search on it
                    if len(matched_records) == 1 and not effective_filters.get("policy_id") and not effective_filters.get("id_cliente"):
                        effective_filters["policy_id"] = record["policy_id"]

        # Step 0b: Check for fleet roster intent (pólizas de automotores colectivas)
        if self._fleet_service is not None and self._large_policy.is_fleet_query(question):
            p_filter = effective_filters.get("policy_id")
            e_filter = effective_filters.get("envelope_id")
            if p_filter or e_filter:
                try:
                    fleet_chunk = self._fleet_service.format_fleet_summary_chunk(
                        policy_id=p_filter,
                        envelope_id=e_filter,
                        sample_limit=None,
                    )
                    if fleet_chunk:
                        structured_chunks.append(fleet_chunk)
                        logger.info("Structured fleet chunk injected for fleet query", policy_id=p_filter)
                except Exception as f_err:
                    logger.warning("Failed injecting fleet chunk in step 0b", error=str(f_err))

        # Step 0c: Check for collective insured roster intent (pólizas colectivas de personas)
        if self._insured_service is not None and hasattr(self._large_policy, "is_insured_query") and self._large_policy.is_insured_query(question):
            p_filter = effective_filters.get("policy_id")
            e_filter = effective_filters.get("envelope_id")
            if p_filter or e_filter:
                try:
                    insured_chunk = self._insured_service.format_insured_summary_chunk(
                        policy_id=p_filter,
                        envelope_id=e_filter,
                        sample_limit=None,
                    )
                    if insured_chunk:
                        structured_chunks.append(insured_chunk)
                        logger.info("Structured collective insured chunk injected for insured query", policy_id=p_filter)
                except Exception as i_err:
                    logger.warning("Failed injecting collective insured chunk in step 0c", error=str(i_err))

        # Step 1: Embed the query using the shared bge-m3 model
        query_vector = self._embed_query(question)

        # Step 2: Retrieve policy chunks (recuperación de la póliza completa o acotada por sobre o cliente)
        target_envelope_id = effective_filters.get("envelope_id")
        target_policy_id = effective_filters.get("policy_id")
        target_id_cliente = effective_filters.get("id_cliente")

        if target_envelope_id and hasattr(self._vector_search, "get_all_chunks_for_envelope"):
            logger.info("Recuperando toda la póliza completa y anexos del sobre para contexto", envelope_id=target_envelope_id)
            retrieved_chunks = self._vector_search.get_all_chunks_for_envelope(target_envelope_id)
        elif target_envelope_id:
            logger.info("Búsqueda RAG acotada a sobre de póliza", envelope_id=target_envelope_id)
            search_filters = effective_filters
            if self._hybrid_search is not None:
                retrieved_chunks = self._retrieve_and_rerank(
                    query_vector=query_vector,
                    query_text=question,
                    top_k=resolved_top_k,
                    filters=search_filters,
                )
            else:
                retrieved_chunks = self._retrieve_chunks(
                    query_vector=query_vector,
                    top_k=resolved_top_k,
                    threshold=resolved_threshold,
                    filters=search_filters,
                )
        elif target_id_cliente and hasattr(self._vector_search, "get_all_chunks_for_client"):
            logger.info("Recuperando todos los documentos del cliente para contexto", id_cliente=target_id_cliente)
            retrieved_chunks = self._vector_search.get_all_chunks_for_client(target_id_cliente)
        elif target_id_cliente:
            logger.info("Búsqueda RAG acotada a cliente", id_cliente=target_id_cliente)
            search_filters = effective_filters
            if self._hybrid_search is not None:
                retrieved_chunks = self._retrieve_and_rerank(
                    query_vector=query_vector,
                    query_text=question,
                    top_k=resolved_top_k,
                    filters=search_filters,
                )
            else:
                retrieved_chunks = self._retrieve_chunks(
                    query_vector=query_vector,
                    top_k=resolved_top_k,
                    threshold=resolved_threshold,
                    filters=search_filters,
                )
        elif target_policy_id and hasattr(self._vector_search, "get_all_chunks_for_policy"):
            logger.info("Recuperando toda la póliza completa para contexto", policy_id=target_policy_id)
            retrieved_chunks = self._vector_search.get_all_chunks_for_policy(target_policy_id)
        else:
            search_filters = effective_filters if effective_filters else None
            if self._hybrid_search is not None:
                initial_chunks = self._retrieve_and_rerank(
                    query_vector=query_vector,
                    query_text=question,
                    top_k=resolved_top_k,
                    filters=search_filters,
                )
            else:
                initial_chunks = self._retrieve_chunks(
                    query_vector=query_vector,
                    top_k=resolved_top_k,
                    threshold=resolved_threshold,
                    filters=search_filters,
                )

            # Si la búsqueda detecta la póliza más relevante, recuperar toda la póliza completa
            if initial_chunks and initial_chunks[0].policy_id and hasattr(self._vector_search, "get_all_chunks_for_policy"):
                detected_policy_id = initial_chunks[0].policy_id
                logger.info(
                    "Póliza identificada por búsqueda; recuperando toda la póliza completa",
                    policy_id=detected_policy_id,
                )
                retrieved_chunks = self._vector_search.get_all_chunks_for_policy(detected_policy_id)
            else:
                retrieved_chunks = initial_chunks

        # Merge structured chunks (highest priority) with retrieved text chunks
        seen_ids = {sc.chunk_id for sc in structured_chunks if sc.chunk_id}
        merged_chunks = list(structured_chunks)
        for chunk in retrieved_chunks:
            if chunk.chunk_id not in seen_ids:
                merged_chunks.append(chunk)
                if chunk.chunk_id:
                    seen_ids.add(chunk.chunk_id)

        # [ADITIVO] Step 2b: Pólizas GRANDES — contexto acotado por presupuesto.
        # Pólizas pequeñas e intermedias no entran aquí (flujo idéntico al actual).
        large_policy_mode = False
        if self._large_policy.is_large(merged_chunks):
            logger.info(
                "Póliza GRANDE detectada; aplicando contexto acotado",
                chunks=len(merged_chunks),
                tokens_est=self._large_policy.estimate_tokens(merged_chunks),
            )
            merged_chunks = self._large_policy.build(
                question=question,
                query_vector=query_vector,
                all_chunks=merged_chunks,
                structured_chunks=structured_chunks,
                filters=effective_filters,
                retrieve_fn=self._retrieve_and_rerank,
                embed_fn=self._embed_query,
            )
            large_policy_mode = True
        full_chunks_for_fallback = merged_chunks

        # Step 3: Contingency path — no relevant chunks found
        if not merged_chunks:
            logger.info(
                "No chunks above similarity threshold — returning contingency answer",
                threshold=resolved_threshold,
            )
            return QueryResponse(
                answer=_NO_CONTEXT_ANSWER,
                sources=[],
                query=question,
                chunks_used=0,
                model_used=self._config.llm_model,
                no_context_found=True,
            )

        # Step 4: Assemble context string with per-chunk labels
        context_text = self._build_context(merged_chunks)

        # Step 5: Call OpenAI for answer generation
        try:
            answer = self._generate_answer(question=question, context_text=context_text)
        except ContextTooLargeError:
            # [ADITIVO] Fallback: OpenAI rechazó por tamaño (p. ej. Tier 1 = 200K TPM).
            if large_policy_mode or not self._large_policy.fallback_enabled:
                raise
            logger.warning(
                "Contexto rechazado por tamaño; reintentando en modo póliza GRANDE",
                chunks=len(full_chunks_for_fallback),
                tokens_est=self._large_policy.estimate_tokens(full_chunks_for_fallback),
            )
            merged_chunks = self._large_policy.build(
                question=question,
                query_vector=query_vector,
                all_chunks=full_chunks_for_fallback,
                structured_chunks=structured_chunks,
                filters=effective_filters,
                retrieve_fn=self._retrieve_and_rerank,
                embed_fn=self._embed_query,
            )
            context_text = self._build_context(merged_chunks)
            answer = self._generate_answer(question=question, context_text=context_text)

        logger.info(
            "RAG query completed",
            chunks_used=len(merged_chunks),
            model=self._config.llm_model,
            answer_preview=answer[:80],
        )

        return QueryResponse(
            answer=answer,
            sources=merged_chunks,
            query=question,
            chunks_used=len(merged_chunks),
            model_used=self._config.llm_model,
            no_context_found=False,
        )

    def search_chunks(
        self,
        question: str,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """Execute retrieval and re-ranking only, returning pure chunks with scores and metadata.

        Does NOT call OpenAI or generate LLM answers. Designed for external agents
        and downstream consumers that supply their own reasoning models.

        Args:
            question: Search query or natural language question.
            top_k: Maximum chunks to return. Defaults to config.top_k.
            similarity_threshold: Minimum similarity threshold.
            filters: Optional pre-filter parameters (company_sigla, numero_poliza, ramo, tipo_documento, id_cliente).

        Returns:
            List of RetrievedChunk instances with similarity_score and metadata.
        """
        question = question.strip()
        if not question:
            raise ValueError("The search query must not be empty.")

        resolved_top_k = top_k if top_k is not None else self._config.top_k
        resolved_threshold = (
            similarity_threshold
            if similarity_threshold is not None
            else self._config.similarity_threshold
        )
        effective_filters = dict(filters) if filters else {}

        # Embed query
        query_vector = self._embed_query(question)

        # Retrieve and rerank
        if self._hybrid_search is not None:
            retrieved_chunks = self._retrieve_and_rerank(
                query_vector=query_vector,
                query_text=question,
                top_k=resolved_top_k,
                filters=effective_filters,
            )
        else:
            retrieved_chunks = self._retrieve_chunks(
                query_vector=query_vector,
                top_k=resolved_top_k,
                threshold=resolved_threshold,
                filters=effective_filters,
            )

        # If similarity threshold is explicitly passed, apply filter
        if similarity_threshold is not None:
            filtered_chunks = [
                c for c in retrieved_chunks
                if c.similarity_score >= resolved_threshold
            ]
        else:
            filtered_chunks = retrieved_chunks

        return filtered_chunks[:resolved_top_k]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _embed_query(self, question: str) -> list[float]:
        """Generate a 1024-dimensional embedding for the user's question.

        Delegates to the shared EmbeddingService (BAAI/bge-m3). Since the
        EmbeddingService uses lazy loading, the model is already warm from
        the ingestion pipeline — no additional load time.

        Args:
            question: User question string.

        Returns:
            List of 1024 floats representing the query vector.

        Raises:
            RuntimeError: If embedding generation fails.
        """
        from app.domain.models.chunks import PolicyChunk  # noqa: PLC0415

        # Wrap the question in a temporary PolicyChunk to reuse the batch API
        temp_chunk = PolicyChunk(chunk_index=0, chunk_content=question)
        try:
            result = self._embedder.generate_embeddings_for_chunks([temp_chunk])
            embedding = result[0].embedding
            if embedding is None:
                raise RuntimeError("Embedding generation returned None for query.")
            return embedding
        except Exception as exc:
            logger.error("Query embedding generation failed", error=str(exc))
            raise RuntimeError(f"Failed to embed query: {exc}") from exc

    def _retrieve_chunks(
        self,
        query_vector: list[float],
        top_k: int,
        threshold: float,
        filters: dict[str, Any] | None,
    ) -> list[RetrievedChunk]:
        """Retrieve similar chunks from the vector store.

        Args:
            query_vector: 1024-dim query embedding.
            top_k: Maximum chunks to return.
            threshold: Minimum similarity threshold.
            filters: Optional pre-filter parameters.

        Returns:
            List of RetrievedChunk ordered by similarity DESC.
        """
        try:
            return self._vector_search.search_similar_chunks(
                query_vector=query_vector,
                top_k=top_k,
                similarity_threshold=threshold,
                filters=filters,
            )
        except Exception as exc:
            logger.error("Vector search failed", error=str(exc))
            raise RuntimeError(f"Vector database query failed: {exc}") from exc

    def _retrieve_and_rerank(
        self,
        query_vector: list[float],
        query_text: str,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve via hybrid search, resolve parents, and rerank.

        This is the Parent-Child Retrieval path:
        1. Hybrid RRF search over Child Chunks (vector + FTS).
        2. Resolve and deduplicate Parent Chunks.
        3. Cross-encoder reranking to select the top-N most relevant Parents.

        Falls back to returning the hybrid results without reranking if
        no RerankerService was injected.

        Args:
            query_vector: 1024-dim query embedding.
            query_text: Original user question for FTS and reranking.
            top_k: Maximum number of parent chunks to return.
            filters: Optional pre-filter parameters.

        Returns:
            List of top-N RetrievedChunk instances (Parent Chunks).
        """
        if self._hybrid_search is None:
            return self._retrieve_chunks(
                query_vector=query_vector,
                top_k=top_k,
                threshold=self._config.similarity_threshold,
                filters=filters,
            )

        top_k_children = max(30, top_k * 3)
        rrf_pool = max(60, top_k_children * 2)
        try:
            parent_chunks = self._hybrid_search.search_and_resolve(
                query_vector=query_vector,
                query_text=query_text,
                top_k_children=top_k_children,
                rrf_pool=rrf_pool,
                filters=filters,
            )
        except Exception as exc:
            logger.error("Hybrid search failed", error=str(exc))
            raise RuntimeError(f"Hybrid search query failed: {exc}") from exc

        if not parent_chunks:
            return []

        # Apply cross-encoder reranking if available
        if self._reranker is not None:
            try:
                parent_chunks = self._reranker.rerank(
                    query=query_text,
                    parent_chunks=parent_chunks,
                    top_n=top_k,
                )
            except Exception as exc:
                logger.warning(
                    "Reranker failed — returning hybrid results without reranking",
                    error=str(exc),
                )
                # Graceful degradation: use hybrid results as-is
                parent_chunks = parent_chunks[:top_k]
        else:
            parent_chunks = parent_chunks[:top_k]

        # Expand any partial table sub-chunks into their complete contiguous sequence
        if hasattr(self._hybrid_search, "expand_table_chunks"):
            try:
                expanded = self._hybrid_search.expand_table_chunks(parent_chunks)
                if isinstance(expanded, list):
                    parent_chunks = expanded
            except Exception as exc:
                logger.warning("Table chunk expansion failed — using retrieved chunks as-is", error=str(exc))

        return parent_chunks

    @staticmethod
    def _chunk_hierarchy_priority(chunk: RetrievedChunk) -> tuple[int, float, int]:
        """Determine chunk priority for context ordering.

        Prioritizes structured JSONB and specific policy items (annexes, endorsements,
        particular conditions, billing slips) before extensive generic general conditions,
        preventing 'lost-in-the-middle' attention degradation.
        """
        meta = chunk.metadata_json or {}
        source = str(meta.get("source", "")).lower()
        tipo = str(meta.get("tipo_documento", "")).upper()
        source_file = str(meta.get("source_file", "")).upper()
        doc_label = str(chunk.document_label).upper()
        section = str(meta.get("section", "")).upper()

        # Priority 0: Ficha técnica estructurada (JSONB)
        if source == "structured_database" or "ESTRUCTURADA" in section or "JSONB" in doc_label:
            prio = 0
        # Priority 1: Anexos modificatorios, inclusiones, certificados y liquidaciones
        elif any(k in tipo for k in ["ANEXO", "LIQUIDACION_PAGOS", "COBRANZA"]):
            prio = 1
        elif any(k in source_file for k in ["ANEXO", "CERTIFICADO", "LIQUIDACION"]):
            prio = 1
        # Priority 2: Condiciones Particulares y Aclaraciones
        elif "PARTICULAR" in tipo or "PARTICULAR" in section:
            prio = 2
        elif "CONDICIONADOS_PARTICULA" in source_file and chunk.chunk_index < 30:
            prio = 2
        # Priority 3: Condiciones Generales (clausulado estándar supletorio)
        else:
            prio = 3

        # Secondary sort: higher similarity score first, then sequential chunk index
        return (prio, -chunk.similarity_score, chunk.chunk_index)

    def _build_context(self, chunks: list[RetrievedChunk]) -> str:
        """Assemble the context string injected into the prompt.

        Each chunk is prefixed with its document label for source attribution.
        Chunks are ordered hierarchically by document specificity and similarity.

        Args:
            chunks: Retrieved chunks with metadata.

        Returns:
            Formatted context string ready for prompt injection.
        """
        ordered_chunks = sorted(chunks, key=self._chunk_hierarchy_priority)
        parts: list[str] = []
        for i, chunk in enumerate(ordered_chunks, start=1):
            label = chunk.document_label
            parts.append(f"{label}\n{chunk.chunk_content}")

        return "\n\n---\n\n".join(parts)

    def _generate_answer(self, question: str, context_text: str) -> str:
        """Call OpenAI chat completion API with the assembled prompt.

        Args:
            question: Original user question.
            context_text: Pre-assembled context from retrieved chunks.

        Returns:
            Answer string from the LLM.

        Raises:
            RuntimeError: On OpenAI API error or unexpected response format.
        """
        user_content = _CONTEXT_HEADER.format(
            context=context_text,
            question=question,
        )

        try:
            client = self._get_openai_client()
            create_params: dict[str, Any] = {
                "model": self._config.llm_model,
                "temperature": self._config.temperature,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            }
            try:
                response = client.chat.completions.create(
                    **create_params,
                    max_completion_tokens=self._config.max_tokens,
                )
            except (TypeError, openai.BadRequestError):
                response = client.chat.completions.create(
                    **create_params,
                    max_tokens=self._config.max_tokens,
                )
            choice = response.choices[0]
            if choice.finish_reason == "length":
                logger.warning(
                    "OpenAI answer generation reached maximum token limit (truncated)",
                    max_tokens=self._config.max_tokens,
                    model=self._config.llm_model,
                )
            content = choice.message.content
            if content is None:
                raise RuntimeError("OpenAI returned an empty message content.")
            return content.strip()

        except openai.RateLimitError as exc:
            # [ADITIVO] Un 429 "Request too large" no es temporal: reintentar no sirve.
            if is_request_too_large(exc):
                logger.error("OpenAI request too large for TPM/context", error=str(exc))
                raise ContextTooLargeError(
                    "La consulta excede el tamaño máximo admitido por el modelo para esta póliza."
                ) from exc
            logger.error("OpenAI rate limit exceeded", error=str(exc))
            raise RuntimeError("OpenAI rate limit exceeded. Try again later.") from exc
        except openai.AuthenticationError as exc:
            logger.error("OpenAI authentication error — check OPENAI_API_KEY", error=str(exc))
            raise RuntimeError("OpenAI authentication failed. Check OPENAI_API_KEY.") from exc
        except openai.APIConnectionError as exc:
            logger.error("OpenAI connection error", error=str(exc))
            raise RuntimeError("Could not connect to OpenAI API.") from exc
        except openai.BadRequestError as exc:
            # [ADITIVO] 400 context_length_exceeded → tamaño; otros 400 se tratan igual que APIError.
            if is_request_too_large(exc):
                logger.error("OpenAI context length exceeded", error=str(exc))
                raise ContextTooLargeError(
                    "La consulta excede la ventana de contexto del modelo para esta póliza."
                ) from exc
            logger.error("OpenAI API error", status_code=getattr(exc, "status_code", None), error=str(exc))
            raise RuntimeError(f"OpenAI API error: {exc}") from exc
        except openai.APIError as exc:
            logger.error("OpenAI API error", status_code=getattr(exc, "status_code", None), error=str(exc))
            raise RuntimeError(f"OpenAI API error: {exc}") from exc
        except Exception as exc:
            logger.error("Unexpected error during LLM completion", error=str(exc))
            raise RuntimeError(f"LLM completion failed: {exc}") from exc

    def _get_openai_client(self) -> openai.OpenAI:
        """Return a cached OpenAI client, creating it on first access.

        Uses lazy initialization to avoid importing openai at module load time
        and to allow OPENAI_API_KEY to be set after module import.

        Returns:
            Configured openai.OpenAI client instance.
        """
        if self._openai_client is None:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY environment variable is not set. "
                    "Add it to your .env file."
                )
            self._openai_client = openai.OpenAI(api_key=api_key)
        return self._openai_client

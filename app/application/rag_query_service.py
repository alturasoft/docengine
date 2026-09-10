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
    ) -> None:
        self._embedder = embedding_service
        self._vector_search = vector_search
        self._config = config
        self._hybrid_search = hybrid_search
        self._reranker = reranker
        self._structured_search = structured_search
        self._openai_client: openai.OpenAI | None = None

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
            if policy_id_filter:
                record = self._structured_search.find_by_policy_id(policy_id_filter)
                if record:
                    structured_chunks.append(
                        self._structured_search.format_structured_chunk(record)
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
                    if len(matched_records) == 1 and not effective_filters.get("policy_id"):
                        effective_filters["policy_id"] = record["policy_id"]

        # Step 1: Embed the query using the shared bge-m3 model
        query_vector = self._embed_query(question)

        # Step 2: Retrieve policy chunks (recuperación de la póliza completa)
        target_policy_id = effective_filters.get("policy_id")
        if target_policy_id and hasattr(self._vector_search, "get_all_chunks_for_policy"):
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

    def _build_context(self, chunks: list[RetrievedChunk]) -> str:
        """Assemble the context string injected into the prompt.

        Each chunk is prefixed with its document label for source attribution.
        Chunks are already ordered by similarity score DESC.

        Args:
            chunks: Retrieved chunks with metadata.

        Returns:
            Formatted context string ready for prompt injection.
        """
        parts: list[str] = []
        for i, chunk in enumerate(chunks, start=1):
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
            response = client.chat.completions.create(
                model=self._config.llm_model,
                temperature=self._config.temperature,
                max_tokens=self._config.max_tokens,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            )
            content = response.choices[0].message.content
            if content is None:
                raise RuntimeError("OpenAI returned an empty message content.")
            return content.strip()

        except openai.RateLimitError as exc:
            logger.error("OpenAI rate limit exceeded", error=str(exc))
            raise RuntimeError("OpenAI rate limit exceeded. Try again later.") from exc
        except openai.AuthenticationError as exc:
            logger.error("OpenAI authentication error — check OPENAI_API_KEY", error=str(exc))
            raise RuntimeError("OpenAI authentication failed. Check OPENAI_API_KEY.") from exc
        except openai.APIConnectionError as exc:
            logger.error("OpenAI connection error", error=str(exc))
            raise RuntimeError("Could not connect to OpenAI API.") from exc
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

"""DocEngine — [ADITIVO FASE 1 & 2] Estrategia de contexto para pólizas GRANDES.

Este módulo es estrictamente aditivo. No altera el flujo de pólizas pequeñas
e intermedias: ``RAGQueryService`` solo delega aquí cuando el contexto
estimado de la póliza supera ``LargePolicyConfig.token_threshold`` o cuando
OpenAI rechaza una petición por tamaño ("Request too large" /
"context_length_exceeded").

Modo GRANDE (Fase 1 & 2) — contexto acotado por presupuesto de tokens:
1. Ficha técnica estructurada (JSONB) — siempre.
2. [Fase 2] Mapa temático y estructural de la póliza (Policy Map) — provee
   visión global de las 2000+ páginas sin consumir más de ~1500 tokens.
3. [Fase 2] Recuperación Multi-Query — expande preguntas compuestas en
   sub-consultas temáticas para abarcar todos los ángulos en pólizas extensas.
4. Fragmentos más relevantes a la pregunta (búsqueda híbrida + reranker,
   acotada a la póliza/sobre), con top-K amplio.
5. Vecinos inmediatos (chunk_index ±1) de los mejores fragmentos para no
   cortar cláusulas a la mitad.
6. Anexos, condiciones particulares y liquidaciones (prioridades 1–2 de la
   jerarquía existente) hasta completar el presupuesto.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING, Any, Callable

from app.config.settings import LargePolicyConfig
from app.domain.models.query_models import RetrievedChunk
from app.infrastructure.logging.logger import get_logger

if TYPE_CHECKING:
    from app.application.fleet_extractor_service import FleetExtractorService
    from app.application.policy_map_service import PolicyMapService

logger = get_logger(__name__)

# Overhead aproximado por fragmento (etiqueta + separadores) en caracteres
_PER_CHUNK_OVERHEAD_CHARS = 80


class ContextTooLargeError(RuntimeError):
    """La petición al LLM excede el tamaño permitido (TPM o ventana de contexto).

    Subclase de RuntimeError para mantener compatibilidad con los manejadores
    existentes de la API (que capturan RuntimeError).
    """


def is_request_too_large(exc: BaseException) -> bool:
    """Distingue un rechazo por TAMAÑO de un rate limit temporal real.

    - 429 "Request too large ... The input or output tokens must be reduced"
      → tamaño (reintentar nunca funcionará).
    - 400 code=context_length_exceeded → excede la ventana del modelo.
    - 429 "Rate limit reached ... Please try again in Xs" → temporal (False).
    """
    code = str(getattr(exc, "code", "") or "").lower()
    if code == "context_length_exceeded":
        return True
    msg = str(exc).lower()
    return (
        "request too large" in msg
        or "must be reduced" in msg
        or "context_length_exceeded" in msg
        or "maximum context length" in msg
    )


class LargePolicyContextStrategy:
    """Decide y construye el contexto para pólizas grandes.

    Args:
        config: LargePolicyConfig con umbral, presupuesto y parámetros.
        priority_fn: Función de prioridad jerárquica existente
            (``RAGQueryService._chunk_hierarchy_priority``); se reutiliza
            sin modificarla.
        map_service: Servicio opcional de mapa de póliza (Fase 2).
        fleet_service: Servicio opcional de extracción de flota de vehículos.
    """

    _FLEET_PATTERNS = [
        re.compile(
            r"\b(?:listado|n[oó]mina|relaci[oó]n|inventario|detalle|todos|cu[aá]ntos|cuantas|cuantos)\s+(?:de\s+)?(?:los\s+)?(?:veh[ií]culos|autos|automotores|camiones|unidades|flota|items?)\b",
            re.I,
        ),
        re.compile(r"\bflota\s+(?:de\s+)?(?:veh[ií]culos|asegurada)\b", re.I),
        re.compile(r"\bveh[ií]culos\s+asegurados\b", re.I),
        re.compile(r"\btotal\s+(?:de\s+)?(?:veh[ií]culos|unidades|flota)\b", re.I),
        re.compile(r"\bplacas?\s+aseguradas?\b", re.I),
    ]

    _INSURED_PATTERNS = [
        re.compile(
            r"\b(?:listado|n[oó]mina|relaci[oó]n|padr[oó]n|detalle|todos|todas|cu[aá]nt[ao]s)\s+(?:de\s+)?(?:las\s+|los\s+)?(?:asegurados|aseguradas|personas|titulares|dependientes|afiliados|empleados|empleadas|trabajadores|trabajadoras|miembros|vidas)\b",
            re.I,
        ),
        re.compile(r"\b(?:personas|asegurados|titulares|dependientes|empleados)\s+(?:est[aá]n\s+)?asegurad[ao]s?\b", re.I),
        re.compile(r"\btotal\s+(?:de\s+)?(?:asegurados|personas|afiliados|vidas|titulares)\b", re.I),
        re.compile(r"\bqui[eé]nes\s+est[aá]n\s+asegurados?\b", re.I),
        re.compile(r"\bfigura\b.*\basegurad[ao]\b", re.I),
    ]

    def __init__(
        self,
        config: LargePolicyConfig,
        priority_fn: Callable[[RetrievedChunk], tuple[int, float, int]],
        map_service: PolicyMapService | None = None,
        fleet_service: FleetExtractorService | None = None,
    ) -> None:
        self._cfg = config
        self._priority_fn = priority_fn
        self._map_service = map_service
        self._fleet_service = fleet_service

    def is_fleet_query(self, question: str) -> bool:
        """Determina si la consulta del usuario apunta a la nómina/lista de vehículos."""
        return any(p.search(question) for p in self._FLEET_PATTERNS)

    def is_insured_query(self, question: str) -> bool:
        """Determina si la consulta del usuario apunta a la nómina/lista de asegurados."""
        return any(p.search(question) for p in self._INSURED_PATTERNS)

    # ------------------------------------------------------------------
    # Estimación y decisión
    # ------------------------------------------------------------------

    def estimate_tokens(self, chunks: list[RetrievedChunk]) -> int:
        """Estima los tokens del contexto que se armaría con estos chunks."""
        total_chars = sum(len(c.chunk_content or "") + _PER_CHUNK_OVERHEAD_CHARS for c in chunks)
        return int(total_chars / self._cfg.chars_per_token)

    def _chunk_tokens(self, chunk: RetrievedChunk) -> int:
        return int((len(chunk.chunk_content or "") + _PER_CHUNK_OVERHEAD_CHARS) / self._cfg.chars_per_token)

    @property
    def fallback_enabled(self) -> bool:
        return self._cfg.enabled and self._cfg.fallback_on_too_large

    def is_large(self, chunks: list[RetrievedChunk]) -> bool:
        """True si el contexto estimado supera el umbral de póliza GRANDE."""
        if not self._cfg.enabled or not chunks:
            return False
        return self.estimate_tokens(chunks) > self._cfg.token_threshold

    # ------------------------------------------------------------------
    # Construcción del contexto acotado (Fases 1 y 2)
    # ------------------------------------------------------------------

    def build(
        self,
        question: str,
        query_vector: list[float],
        all_chunks: list[RetrievedChunk],
        structured_chunks: list[RetrievedChunk],
        filters: dict[str, Any],
        retrieve_fn: Callable[..., list[RetrievedChunk]],
        embed_fn: Callable[[str], list[float]] | None = None,
    ) -> list[RetrievedChunk]:
        """Selecciona un subconjunto de chunks dentro del presupuesto de tokens."""
        budget = self._cfg.context_budget_tokens
        selected: list[RetrievedChunk] = []
        seen: set[str] = set()
        used = 0

        def key_of(c: RetrievedChunk) -> str:
            return c.chunk_id or f"{c.policy_id}_{c.chunk_index}"

        def try_add(c: RetrievedChunk) -> bool:
            nonlocal used
            k = key_of(c)
            if k in seen:
                return True
            cost = self._chunk_tokens(c)
            if used + cost > budget:
                return False
            selected.append(c)
            seen.add(k)
            used += cost
            return True

        # 1. Ficha estructurada (siempre máxima prioridad)
        for sc in structured_chunks:
            try_add(sc)

        # 2. [Fase 2] Mapa temático y estructural de la póliza (si está disponible)
        scope = self._resolve_scope(all_chunks, filters)
        target_policy_id = scope.get("policy_id") or (all_chunks[0].policy_id if all_chunks else None)
        target_envelope_id = scope.get("envelope_id") or filters.get("envelope_id")

        if self._cfg.policy_map_enabled and self._map_service and target_policy_id:
            try:
                map_chunk = self._map_service.get_or_create_map_chunk(
                    policy_id=target_policy_id,
                    envelope_id=target_envelope_id,
                )
                if map_chunk:
                    try_add(map_chunk)
                    logger.info("Mapa de póliza incluido en contexto macro", policy_id=target_policy_id)
            except Exception as exc:
                logger.warning("No se pudo inyectar mapa de póliza", error=str(exc))

        # 2b. [ADITIVO] Nómina oficial y consolidada de flota (si la consulta refiere a vehículos/flota)
        if self._fleet_service and (target_policy_id or target_envelope_id) and self.is_fleet_query(question):
            try:
                fleet_chunk = self._fleet_service.format_fleet_summary_chunk(
                    policy_id=target_policy_id,
                    envelope_id=target_envelope_id,
                    sample_limit=None,
                )
                if fleet_chunk:
                    try_add(fleet_chunk)
                    logger.info("Nómina consolidada de flota inyectada en contexto", policy_id=target_policy_id)
            except Exception as f_exc:
                logger.warning("No se pudo inyectar resumen de flota", error=str(f_exc))

        # 3. [ADITIVO] Búsqueda dirigida de entidad específica (placa, chasis, motor, ítem)
        # Si el usuario pregunta por un vehículo/código particular, inyectar sus chunks y vecinos de inmediato
        entity_chunks = self._find_entity_chunks(question, all_chunks)
        for ec in entity_chunks:
            try_add(ec)

        # 4. Fragmentos relevantes a la pregunta principal (búsqueda híbrida)
        retrieved: list[RetrievedChunk] = []
        if scope:
            try:
                retrieved = retrieve_fn(
                    query_vector=query_vector,
                    query_text=question,
                    top_k=self._cfg.retrieval_top_k,
                    filters=scope,
                ) or []
            except Exception as exc:
                logger.warning("Large-policy retrieval failed; using priority fill only", error=str(exc))
                retrieved = []

        # 5. [Fase 2] Multi-Query: sub-consultas temáticas para preguntas compuestas
        if self._cfg.multi_query_enabled and embed_fn and scope:
            sub_queries = self._generate_subqueries(question, max_queries=self._cfg.multi_query_count)
            for sub_q in sub_queries:
                try:
                    sub_v = embed_fn(sub_q)
                    sub_chunks = retrieve_fn(
                        query_vector=sub_v,
                        query_text=sub_q,
                        top_k=max(10, self._cfg.retrieval_top_k // 2),
                        filters=scope,
                    ) or []
                    for sc in sub_chunks:
                        if key_of(sc) not in {key_of(r) for r in retrieved}:
                            retrieved.append(sc)
                except Exception as sub_exc:
                    logger.debug("Sub-query retrieval skipped", sub_query=sub_q, error=str(sub_exc))

        by_pos = {(c.policy_id, c.chunk_index): c for c in all_chunks}
        for c in retrieved:
            try_add(c)

        # 5. Vecinos inmediatos de los mejores fragmentos
        for c in retrieved[: self._cfg.neighbor_expansion_top]:
            for delta in (-1, 1):
                nb = by_pos.get((c.policy_id, c.chunk_index + delta))
                if nb is not None:
                    try_add(nb)

        # 6. Anexos / Condiciones Particulares / Liquidaciones (prioridad 1–2)
        priority_chunks = [c for c in all_chunks if self._priority_fn(c)[0] in (1, 2)]
        priority_chunks.sort(key=self._priority_fn)
        for c in priority_chunks:
            if not try_add(c) and used >= budget * 0.98:
                break

        # 7. Si no hubo recuperación útil, completar en orden jerárquico
        if not retrieved:
            for c in sorted(all_chunks, key=self._priority_fn):
                if not try_add(c) and used >= budget * 0.98:
                    break

        logger.info(
            "Large-policy context built (Phase 1 & 2)",
            total_chunks=len(all_chunks),
            total_tokens_est=self.estimate_tokens(all_chunks),
            selected_chunks=len(selected),
            selected_tokens_est=used,
            retrieved=len(retrieved),
            scope=scope,
        )
        return selected

    @staticmethod
    def _generate_subqueries(question: str, max_queries: int = 2) -> list[str]:
        """Descompone preguntas compuestas en sub-consultas temáticas."""
        # Detectar patrones de conjunción típicos: "¿X y Y?", "X además de Y", "X, también Y"
        subqueries: list[str] = []
        cleaned = re.sub(r"^[¿?\s]+|[¿?\s]+$", "", question)

        # Partir en partes lógicas si contiene conectores
        parts = re.split(r"\s+(?:y|adem[aá]s\s+de|as[ií]\s+como|o\s+bien)\s+|\s*;\s*", cleaned, flags=re.I)
        if len(parts) > 1:
            for p in parts:
                p = p.strip()
                if len(p) >= 10 and p.lower() != cleaned.lower():
                    subqueries.append(p)

        return subqueries[:max_queries]

    @staticmethod
    def _resolve_scope(all_chunks: list[RetrievedChunk], filters: dict[str, Any]) -> dict[str, Any]:
        """Determina el filtro de búsqueda híbrida para acotar a la póliza/sobre."""
        if filters.get("envelope_id"):
            return {"envelope_id": filters["envelope_id"]}
        if filters.get("policy_id"):
            return {"policy_id": filters["policy_id"]}
        counts = Counter(c.policy_id for c in all_chunks if c.policy_id and c.policy_id != "None")
        if counts:
            return {"policy_id": counts.most_common(1)[0][0]}
        return {}

    @classmethod
    def extract_target_entities(cls, query: str) -> list[str]:
        """Extrae placas, números de chasis, motor, ítems o códigos alfanuméricos."""
        entities: list[str] = []
        # 1. Patrón explícito: placa, chasis, motor, vin, item
        labeled = re.findall(
            r"(?:placa|chasis|motor|vin|item|[íi]tem)[:\s#]+([A-Za-z0-9\-]+)",
            query,
            flags=re.I,
        )
        for val in labeled:
            clean = val.strip().replace(":", "").replace("#", "")
            if len(clean) >= 3 and clean not in entities:
                entities.append(clean)

        # 2. Códigos alfanuméricos que combinan letras y números (ej. 2571EDF, 2571-EDF)
        tokens = re.findall(r"[a-zA-Z0-9\-]{4,18}", query)
        for t in tokens:
            t_clean = t.replace("-", "").upper()
            if any(c.isdigit() for c in t_clean) and any(c.isalpha() for c in t_clean):
                if t not in entities and t_clean not in [e.upper().replace("-", "") for e in entities]:
                    entities.append(t)

        return entities

    def _find_entity_chunks(
        self,
        question: str,
        all_chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """Localiza fragmentos que contengan exactamente la entidad consultada (placa, chasis, item...).

        Si encuentra coincidencias, expande a sus chunks contiguos (±3) para incluir
        toda la ficha particular del vehículo (objeto asegurado, coberturas, franquicias, prima).
        """
        entities = self.extract_target_entities(question)
        if not entities or not all_chunks:
            return []

        by_pos = {(c.policy_id, c.chunk_index): c for c in all_chunks}
        matched_chunks: list[RetrievedChunk] = []
        seen_keys: set[str] = set()

        for ent in entities:
            ent_upper = ent.upper()
            clean_digits = "".join(c for c in ent if c.isdigit())
            clean_letters = "".join(c for c in ent if c.isalpha()).upper()

            for c in all_chunks:
                content_upper = (c.chunk_content or "").upper()
                meta_str = str(c.metadata_json or "").upper()
                full_text = f"{content_upper} {meta_str}"

                direct_match = ent_upper in full_text
                plate_match = False
                if len(clean_digits) >= 3 and len(clean_letters) >= 2:
                    plate_match = clean_digits in full_text and clean_letters in full_text

                if direct_match or plate_match:
                    k = c.chunk_id or f"{c.policy_id}_{c.chunk_index}"
                    if k not in seen_keys:
                        matched_chunks.append(c)
                        seen_keys.add(k)

                    # Expandir a los vecinos (±3) para incluir la ficha completa
                    for delta in range(-3, 4):
                        if delta == 0:
                            continue
                        neighbor = by_pos.get((c.policy_id, c.chunk_index + delta))
                        if neighbor:
                            nk = neighbor.chunk_id or f"{neighbor.policy_id}_{neighbor.chunk_index}"
                            if nk not in seen_keys:
                                matched_chunks.append(neighbor)
                                seen_keys.add(nk)

        if matched_chunks:
            logger.info(
                "Entidad específica encontrada en fragmentos de póliza",
                entities=entities,
                matched_and_neighbors_count=len(matched_chunks),
            )

        return matched_chunks


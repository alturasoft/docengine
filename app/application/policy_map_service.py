"""DocEngine — Application Service: Policy Map Service.

[ADITIVO FASE 2] Genera y recupera el mapa temático y estructural (índice de secciones)
de una póliza o sobre para proveer visión macro al LLM sin requerir millones de tokens.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.models.query_models import RetrievedChunk
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_policy_map_repository import PgPolicyMapRepository
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

# Palabras clave bolivianas de seguros para etiquetado temático de secciones
_TOPIC_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Responsabilidad Civil", re.compile(r"responsabilidad\s+civil|extracontractual", re.I)),
    ("Deducibles y Franquicias", re.compile(r"franquicia|deducible", re.I)),
    ("Pérdida Total / Daño Propio", re.compile(r"p[eé]rdida\s+total|da[ññ]os\s+propios|destrucci[oó]n", re.I)),
    ("Robo y Asalto", re.compile(r"robo|asalto|hurto", re.I)),
    ("Accidentes Personales", re.compile(r"accidentes\s+personales|ocupantes|gastos\s+m[eé]dicos", re.I)),
    ("Extraterritorialidad", re.compile(r"extraterritorialidad|cono\s+sur|chile|argentina|peru|brasil", re.I)),
    ("Vigencia y Plazos", re.compile(r"vigencia|aviso\s+de\s+siniestro|plazo", re.I)),
    ("Exclusiones", re.compile(r"exclusi[oó]n|exclusiones|no\s+cubre", re.I)),
    ("Auxilio y Asistencia", re.compile(r"asistencia|gr[uú]a|remolque|auxilio", re.I)),
    ("Valores y Primas", re.compile(r"prima|forma\s+de\s+pago|suma\s+asegurada", re.I)),
]


class PolicyMapService:
    """Servicio para construir y consultar el mapa estructural de pólizas."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        map_repo: PgPolicyMapRepository | None = None,
    ) -> None:
        self._db = db_manager
        self._repo = map_repo or PgPolicyMapRepository(db_manager)

    def get_or_create_map_chunk(
        self,
        policy_id: str,
        envelope_id: str | None = None,
        auto_generate: bool = True,
    ) -> RetrievedChunk | None:
        """Obtiene el mapa de la póliza como un RetrievedChunk formateado.

        Si aún no está generado en la base de datos y `auto_generate=True`,
        lo construye dinámicamente, lo persiste y lo retorna.
        """
        # 1. Intentar por sobre primero si existe
        summaries: list[dict[str, Any]] = []
        if envelope_id:
            summaries = self._repo.get_summaries_for_envelope(envelope_id)

        # 2. Si no hay por sobre, intentar por policy_id
        if not summaries and policy_id:
            summaries = self._repo.get_summaries_for_policy(policy_id)

        # 3. Si no existe y auto_generate=True, generar ahora
        if not summaries and auto_generate and policy_id:
            try:
                summaries = self.generate_map_for_policy(policy_id, envelope_id)
            except Exception as exc:
                logger.warning("No se pudo generar mapa dinámico de póliza", policy_id=policy_id, error=str(exc))
                return None

        if not summaries:
            return None

        return self._repo.format_map_chunk(summaries, policy_id=policy_id or "envelope")

    def generate_map_for_policy(
        self,
        policy_id: str,
        envelope_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Analiza la estructura de chunks de la póliza y genera los resúmenes temáticos."""
        chunks = self._load_policy_chunks(policy_id)
        if not chunks:
            logger.info("Póliza no tiene chunks para generar mapa", policy_id=policy_id)
            return []

        # Obtener datos de la póliza si envelope_id no fue provisto
        if not envelope_id:
            envelope_id = self._lookup_envelope_id(policy_id)

        # Identificar secciones y agrupar chunks
        sections_data = self._cluster_sections(chunks)

        summaries: list[dict[str, Any]] = []
        for idx, sec in enumerate(sections_data, start=1):
            title = sec["title"]
            chunk_list = sec["chunks"]
            sample_text = "\n".join(c["content"] for c in chunk_list[:3])

            # Extraer temas clave
            topics: list[str] = []
            for name, pattern in _TOPIC_PATTERNS:
                if pattern.search(title) or pattern.search(sample_text):
                    topics.append(name)

            # Generar resumen estructurado y conciso
            summary_text = self._build_extractive_summary(title, chunk_list, sec.get("repeat_count", 1))

            summaries.append({
                "section_index": idx,
                "section_title": title,
                "tipo_documento": sec.get("tipo_documento"),
                "source_file": sec.get("source_file"),
                "chunk_start": chunk_list[0]["chunk_index"],
                "chunk_end": chunk_list[-1]["chunk_index"],
                "summary_text": summary_text,
                "key_topics": topics,
            })

        self._repo.save_summaries(policy_id, envelope_id, summaries)
        return summaries

    def _cluster_sections(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Agrupa chunks secuenciales por encabezados temáticos y colapsa ítems repetitivos de flotas."""
        clusters: list[dict[str, Any]] = []
        current_title: str | None = None
        current_chunks: list[dict[str, Any]] = []
        item_repeat_count = 0
        in_item_block = False

        for c in chunks:
            meta = c.get("metadata") or {}
            h2 = meta.get("Header 2") or meta.get("Header 1") or meta.get("section") or "Condiciones Generales"
            h2_clean = str(h2).strip()

            # Detectar si estamos en un ítem de flota (e.g. ITEM 1, ITEM 2...)
            item_match = re.search(r"ITEM\s+(\d+)", h2_clean, re.I)
            if item_match:
                item_repeat_count += 1
                if not in_item_block:
                    if current_title and current_chunks:
                        clusters.append({
                            "title": current_title,
                            "chunks": current_chunks,
                            "tipo_documento": current_chunks[0].get("tipo_documento"),
                            "source_file": current_chunks[0].get("source_file"),
                        })
                    in_item_block = True
                    current_title = "Nómina de Ítems / Vehículos Asegurados (Flota Colectiva)"
                    current_chunks = [c]
                else:
                    current_chunks.append(c)
                continue

            # Si salimos del bloque de ítems o cambia la sección
            if in_item_block and not any(k in h2_clean.upper() for k in ["VALOR", "OBJETO", "ITEM", "FRANQUICIA"]):
                # Cerrar bloque de flota
                clusters.append({
                    "title": f"Nómina de Ítems Asegurados ({item_repeat_count} vehículos)",
                    "chunks": current_chunks,
                    "repeat_count": item_repeat_count,
                    "tipo_documento": current_chunks[0].get("tipo_documento") if current_chunks else None,
                    "source_file": current_chunks[0].get("source_file") if current_chunks else None,
                })
                in_item_block = False
                current_title = h2_clean
                current_chunks = [c]
                continue

            if in_item_block:
                current_chunks.append(c)
                continue

            if current_title is None or h2_clean == current_title:
                current_title = h2_clean
                current_chunks.append(c)
            else:
                clusters.append({
                    "title": current_title,
                    "chunks": current_chunks,
                    "tipo_documento": current_chunks[0].get("tipo_documento"),
                    "source_file": current_chunks[0].get("source_file"),
                })
                current_title = h2_clean
                current_chunks = [c]

        if current_chunks and current_title:
            clusters.append({
                "title": current_title,
                "chunks": current_chunks,
                "repeat_count": item_repeat_count if in_item_block else 1,
                "tipo_documento": current_chunks[0].get("tipo_documento"),
                "source_file": current_chunks[0].get("source_file"),
            })

        # Deduplicar o consolidar clusters muy pequeños o idénticos
        return self._consolidate_clusters(clusters)

    @staticmethod
    def _consolidate_clusters(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
        consolidated: list[dict[str, Any]] = []
        seen_titles: set[str] = set()

        for c in clusters:
            title = c["title"]
            # Si el título ya fue visto de forma repetitiva (ej. notas que aparecen 100 veces)
            if title in seen_titles and len(c["chunks"]) < 5:
                continue
            seen_titles.add(title)
            consolidated.append(c)

        return consolidated

    @staticmethod
    def _build_extractive_summary(title: str, chunk_list: list[dict[str, Any]], repeat_count: int = 1) -> str:
        """Sintetiza una descripción breve y factual a partir del contenido de los chunks."""
        if repeat_count > 1:
            return (
                f"Contiene la nómina y especificaciones individuales de {repeat_count} vehículos asegurados, "
                "incluyendo datos del objeto asegurado, coberturas por ítem, franquicias y primas particulares."
            )

        # Buscar primeras líneas útiles evitando encabezados de metadata
        text_snippets: list[str] = []
        for c in chunk_list[:4]:
            content = c["content"]
            lines = [
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.startswith("[") and not line.startswith("<!--") and not line.startswith("#")
            ]
            if lines:
                text_snippets.extend(lines[:2])
            if len(text_snippets) >= 3:
                break

        if text_snippets:
            preview = " ".join(text_snippets)
            # Limpiar espacios múltiples y acotar a 300 chars
            preview = re.sub(r"\s+", " ", preview).strip()
            if len(preview) > 300:
                preview = preview[:297] + "..."
            return preview

        return f"Estipulaciones y cláusulas correspondientes a {title}."

    def _load_policy_chunks(self, policy_id: str) -> list[dict[str, Any]]:
        sql = """
            SELECT pc.chunk_index, pc.chunk_content, pc.metadata_json,
                   p.file_name, p.tipo_documento
            FROM policy_chunks pc
            JOIN policies p ON pc.policy_id = p.id
            WHERE pc.policy_id = %s::uuid
              AND (pc.chunk_type = 'parent' OR pc.parent_id IS NULL)
            ORDER BY pc.chunk_index ASC;
        """
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (policy_id,))
                rows = cur.fetchall()

        return [
            {
                "chunk_index": r[0],
                "content": r[1] or "",
                "metadata": r[2] if isinstance(r[2], dict) else {},
                "source_file": r[3],
                "tipo_documento": r[4],
            }
            for r in rows
        ]

    def _lookup_envelope_id(self, policy_id: str) -> str | None:
        sql = "SELECT envelope_id::text FROM policies WHERE id = %s::uuid;"
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (policy_id,))
                row = cur.fetchone()
                return row[0] if row else None

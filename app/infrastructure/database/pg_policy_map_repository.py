"""DocEngine — Infrastructure: PostgreSQL Policy Map (Section Summaries) Repository.

[ADITIVO] Gestiona la persistencia y consulta del mapa temático y resúmenes de secciones
para documentos de pólizas de seguros.
"""

from __future__ import annotations

import json
from typing import Any

from app.domain.models.query_models import RetrievedChunk
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class PgPolicyMapRepository:
    """Repositorio para almacenamiento y recuperación del mapa de secciones de pólizas."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    def save_summaries(
        self,
        policy_id: str,
        envelope_id: str | None,
        summaries: list[dict[str, Any]],
    ) -> None:
        """Guarda o actualiza la lista de resúmenes de sección para una póliza.

        Reemplaza atómicamente los resúmenes previos de esa póliza para evitar duplicados.
        """
        if not summaries:
            return

        delete_sql = "DELETE FROM policy_section_summaries WHERE policy_id = %s::uuid;"
        insert_sql = """
            INSERT INTO policy_section_summaries (
                policy_id, envelope_id, section_index, section_title,
                tipo_documento, source_file, chunk_start, chunk_end,
                summary_text, key_topics, updated_at
            ) VALUES (
                %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP
            );
        """

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(delete_sql, (policy_id,))
                for s in summaries:
                    cur.execute(
                        insert_sql,
                        (
                            policy_id,
                            envelope_id,
                            s.get("section_index", 0),
                            s.get("section_title", "Sección"),
                            s.get("tipo_documento"),
                            s.get("source_file"),
                            s.get("chunk_start", 0),
                            s.get("chunk_end", 0),
                            s.get("summary_text", ""),
                            json.dumps(s.get("key_topics", []), ensure_ascii=False),
                        ),
                    )
            conn.commit()

        logger.info(
            "Guardados resúmenes de mapa de póliza",
            policy_id=policy_id,
            envelope_id=envelope_id,
            sections_count=len(summaries),
        )

    def get_summaries_for_policy(self, policy_id: str) -> list[dict[str, Any]]:
        """Recupera los resúmenes de sección de una póliza en orden secuencial."""
        sql = """
            SELECT id, policy_id::text, envelope_id::text, section_index,
                   section_title, tipo_documento, source_file,
                   chunk_start, chunk_end, summary_text, key_topics
            FROM policy_section_summaries
            WHERE policy_id = %s::uuid
            ORDER BY section_index ASC;
        """
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (policy_id,))
                rows = cur.fetchall()

        return [self._row_to_dict(r) for r in rows]

    def get_summaries_for_envelope(self, envelope_id: str) -> list[dict[str, Any]]:
        """Recupera los resúmenes de sección de todas las pólizas del sobre."""
        sql = """
            SELECT id, policy_id::text, envelope_id::text, section_index,
                   section_title, tipo_documento, source_file,
                   chunk_start, chunk_end, summary_text, key_topics
            FROM policy_section_summaries
            WHERE envelope_id = %s::uuid
            ORDER BY created_at ASC, section_index ASC;
        """
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (envelope_id,))
                rows = cur.fetchall()

        return [self._row_to_dict(r) for r in rows]

    def format_map_chunk(
        self,
        summaries: list[dict[str, Any]],
        policy_id: str = "map",
    ) -> RetrievedChunk | None:
        """Formatea la lista de resúmenes de secciones como un RetrievedChunk de alta prioridad."""
        if not summaries:
            return None

        lines: list[str] = [
            "### MAPA TEMÁTICO Y ESTRUCTURA GENERAL DE LA PÓLIZA (ÍNDICE DE SECCIONES)",
            "A continuación se presenta el mapa consolidado de todas las secciones, anexos y cláusulas que componen esta póliza:",
            "",
        ]

        for s in summaries:
            title = s.get("section_title", "Sección")
            summary = s.get("summary_text", "").strip()
            tipo = s.get("tipo_documento") or ""
            source = s.get("source_file") or ""
            topics = s.get("key_topics") or []

            header_desc = f"- **{title}**"
            if tipo:
                header_desc += f" [{tipo}]"
            lines.append(header_desc)
            if summary:
                lines.append(f"  *Resumen:* {summary}")
            if topics and isinstance(topics, list):
                topics_str = ", ".join(str(t) for t in topics[:8])
                lines.append(f"  *Términos y coberturas clave:* {topics_str}")
            lines.append("")

        content = "\n".join(lines)
        return RetrievedChunk(
            chunk_id=f"policy_map_{policy_id}",
            policy_id=policy_id,
            chunk_index=-1,
            chunk_content=content,
            metadata_json={
                "source": "structured_database",
                "tipo_documento": "MAPA_POLIZA",
                "section": "MAPA_ESTRUCTURADO_POLIZA",
                "document_label": "[MAPA GLOBAL DE LA PÓLIZA]",
            },
            similarity_score=1.0,
        )

    @staticmethod
    def _row_to_dict(row: tuple) -> dict[str, Any]:
        return {
            "id": str(row[0]),
            "policy_id": row[1],
            "envelope_id": row[2],
            "section_index": row[3],
            "section_title": row[4],
            "tipo_documento": row[5],
            "source_file": row[6],
            "chunk_start": row[7],
            "chunk_end": row[8],
            "summary_text": row[9],
            "key_topics": row[10] if isinstance(row[10], (list, dict)) else [],
        }

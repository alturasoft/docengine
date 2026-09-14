"""DocEngine — Infrastructure: PostgreSQL Structured Search Repository.

Read-only repository for querying atomized policy data stored in the
`policy_structured_data` table (header metadata, coberturas, and
condiciones especiales).

This module performs NO write operations and does NOT modify any existing tables.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.models.query_models import RetrievedChunk
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

_FETCH_BY_ID_QUERY = """
    SELECT
        psd.policy_id::text AS policy_id,
        p.file_name,
        p.company_sigla,
        psd.data
    FROM policy_structured_data psd
    JOIN policies p ON psd.policy_id = p.id
    WHERE psd.policy_id = %s::uuid;
"""

_SEARCH_BY_CANDIDATES_QUERY = """
    SELECT
        psd.policy_id::text AS policy_id,
        p.file_name,
        p.company_sigla,
        psd.data
    FROM policy_structured_data psd
    JOIN policies p ON psd.policy_id = p.id
    WHERE
        LOWER(REGEXP_REPLACE(psd.data->'datos_cabecera'->>'numero_poliza', '[^a-zA-Z0-9]', '', 'g')) = ANY(%s)
        OR psd.data->'datos_cabecera'->>'numero_poliza' ILIKE ANY(%s)
    LIMIT %s;
"""

_RECENT_POLICIES_QUERY = """
    SELECT
        p.id::text AS policy_id,
        p.file_name,
        p.company_sigla,
        p.created_at::text,
        psd.data
    FROM policies p
    LEFT JOIN policy_structured_data psd ON p.id = psd.policy_id
    ORDER BY p.created_at DESC
    LIMIT %s;
"""

_FIND_BASIC_QUERY = """
    SELECT
        p.id::text AS policy_id,
        p.file_name,
        p.company_sigla,
        p.created_at::text,
        psd.data
    FROM policies p
    LEFT JOIN policy_structured_data psd ON p.id = psd.policy_id
    WHERE
        p.id::text = %s
        OR LOWER(REGEXP_REPLACE(COALESCE(psd.data->'datos_cabecera'->>'numero_poliza', ''), '[^a-zA-Z0-9]', '', 'g')) = %s
        OR psd.data->'datos_cabecera'->>'numero_poliza' ILIKE %s
        OR p.file_name ILIKE %s
        OR psd.data->'datos_cabecera'->>'asegurado' ILIKE %s
    ORDER BY p.created_at DESC
    LIMIT 1;
"""


def extract_basic_info(record: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize standard basic policy fields from a structured record.

    Fields extracted in the required order:
    1. numero_poliza
    2. ramo
    3. asegurado
    4. numero_documento
    5. vigencia
    6. prima_total
    """
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    cabecera = data.get("datos_cabecera") if isinstance(data.get("datos_cabecera"), dict) else {}
    objeto = data.get("objeto_asegurado") if isinstance(data.get("objeto_asegurado"), dict) else {}

    # 1. Número de la póliza
    num_poliza = (
        cabecera.get("numero_poliza")
        or record.get("file_name", "Desconocido")
    )

    # 2. Ramo (fallback: objeto_asegurado.tipo_bien -> actividad_economica -> 'No especificado')
    ramo = (
        cabecera.get("ramo")
        or (objeto.get("tipo_bien") if isinstance(objeto, dict) else None)
        or cabecera.get("actividad_economica")
        or "No especificado"
    )

    # 3. Asegurado
    asegurado = (
        cabecera.get("asegurado")
        or cabecera.get("tomador")
        or "No especificado"
    )

    # 4. Número de documento (CI o NIT)
    doc_identidad = cabecera.get("documento_identidad")
    nit = cabecera.get("nit")
    if doc_identidad and nit and doc_identidad != nit:
        numero_documento = f"CI: {doc_identidad} / NIT: {nit}"
    elif doc_identidad:
        numero_documento = str(doc_identidad)
    elif nit:
        numero_documento = f"NIT: {nit}"
    else:
        numero_documento = "No registrado"

    # 5. Vigencia
    v_desde = cabecera.get("vigencia_desde")
    v_hasta = cabecera.get("vigencia_hasta")
    if v_desde and v_hasta:
        vigencia = f"Desde {v_desde} hasta {v_hasta}"
    elif v_desde:
        vigencia = f"Desde {v_desde}"
    elif v_hasta:
        vigencia = f"Hasta {v_hasta}"
    else:
        vigencia = "No especificada"

    # 6. Prima total
    prima = cabecera.get("prima_total")
    moneda = cabecera.get("moneda")
    if prima and moneda:
        prima_total = f"{prima} {moneda}"
    elif prima:
        prima_total = str(prima)
    else:
        prima_total = "No especificada"

    return {
        "policy_id": record.get("policy_id", ""),
        "numero_poliza": num_poliza,
        "ramo": ramo,
        "asegurado": asegurado,
        "numero_documento": numero_documento,
        "vigencia": vigencia,
        "prima_total": prima_total,
        "company_sigla": record.get("company_sigla"),
        "file_name": record.get("file_name"),
        "created_at": str(record.get("created_at", "")) if record.get("created_at") else None,
    }


class PgStructuredSearchRepository:
    """Read-only repository for querying policy structured JSON data."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    def find_by_policy_id(self, policy_id: str) -> dict[str, Any] | None:
        """Fetch structured policy data by its UUID.

        Args:
            policy_id: UUID string of the policy.

        Returns:
            Dict containing policy_id, file_name, company_sigla, and data dict,
            or None if not found.
        """
        try:
            with self._db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(_FETCH_BY_ID_QUERY, (policy_id,))
                    row = cur.fetchone()
                    if row is None:
                        return None
                    return {
                        "policy_id": row[0],
                        "file_name": row[1],
                        "company_sigla": row[2],
                        "data": row[3] if isinstance(row[3], dict) else {},
                    }
        except Exception as exc:
            logger.error("Failed to fetch structured policy by ID", policy_id=policy_id, error=str(exc))
            return None

    def search_by_query_text(self, query_text: str, limit: int = 2) -> list[dict[str, Any]]:
        """Search structured policies by detecting policy numbers in the query text.

        Args:
            query_text: User question string.
            limit: Maximum matching policies to return.

        Returns:
            List of matching policy records with structured data.
        """
        if not query_text or not query_text.strip():
            return []

        # Extract potential policy numbers / alphanumeric tokens from query
        tokens = re.findall(r"[A-Za-z0-9\-_/]{4,}", query_text)
        if not tokens:
            return []

        normalized_tokens = [re.sub(r"[^a-zA-Z0-9]", "", t).lower() for t in tokens if len(re.sub(r"[^a-zA-Z0-9]", "", t)) >= 3]
        like_patterns = [f"%{t.strip()}%" for t in tokens if len(t.strip()) >= 3]

        if not normalized_tokens and not like_patterns:
            return []

        try:
            with self._db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        _SEARCH_BY_CANDIDATES_QUERY,
                        (normalized_tokens, like_patterns, limit),
                    )
                    rows = cur.fetchall()
                    results = []
                    for row in rows:
                        results.append({
                            "policy_id": row[0],
                            "file_name": row[1],
                            "company_sigla": row[2],
                            "data": row[3] if isinstance(row[3], dict) else {},
                        })
                    return results
        except Exception as exc:
            logger.error("Failed to search structured policies by text", query=query_text, error=str(exc))
            return []

    def format_structured_chunk(self, record: dict[str, Any]) -> RetrievedChunk:
        """Format a structured policy record into a high-priority RetrievedChunk.

        Args:
            record: Dict returned by find_by_policy_id or search_by_query_text.

        Returns:
            RetrievedChunk with similarity_score=1.0 containing the structured facts.
        """
        policy_id = record.get("policy_id", "")
        file_name = record.get("file_name", "Póliza")
        company_sigla = record.get("company_sigla", "")
        data = record.get("data", {})

        cabecera = data.get("datos_cabecera") if isinstance(data.get("datos_cabecera"), dict) else {}
        objeto = data.get("objeto_asegurado") if isinstance(data.get("objeto_asegurado"), dict) else {}
        coberturas = data.get("coberturas", []) if isinstance(data.get("coberturas"), list) else []
        condiciones = data.get("condiciones_especiales", []) if isinstance(data.get("condiciones_especiales"), list) else []

        lines: list[str] = [
            f"# DATOS ESTRUCTURADOS DE LA PÓLIZA (DOCUMENTO: {file_name})",
        ]

        if cabecera:
            lines.append("## DATOS GENERALES Y CABECERA:")
            if cabecera.get("numero_poliza"):
                lines.append(f"- **Número de Póliza**: {cabecera['numero_poliza']}")
            if cabecera.get("poliza_anterior"):
                lines.append(f"- **Póliza Anterior / Renovación**: {cabecera['poliza_anterior']}")
            if cabecera.get("asegurado"):
                lines.append(f"- **Asegurado**: {cabecera['asegurado']}")
            if cabecera.get("documento_identidad"):
                lines.append(f"- **Documento de Identidad (CI)**: {cabecera['documento_identidad']}")
            if cabecera.get("nit"):
                lines.append(f"- **NIT**: {cabecera['nit']}")
            if cabecera.get("direccion"):
                lines.append(f"- **Dirección**: {cabecera['direccion']}")
            if cabecera.get("zona"):
                lines.append(f"- **Zona**: {cabecera['zona']}")
            if cabecera.get("barrio_distrito") or cabecera.get("distrito_ciudad"):
                lines.append(f"- **Barrio / Distrito / Ciudad**: {cabecera.get('barrio_distrito') or cabecera.get('distrito_ciudad')}")
            if cabecera.get("telefono"):
                lines.append(f"- **Teléfono Fijo**: {cabecera['telefono']}")
            if cabecera.get("celular"):
                lines.append(f"- **Número de Celular**: {cabecera['celular']}")
            if cabecera.get("email"):
                lines.append(f"- **Correo Electrónico (E-mail)**: {cabecera['email']}")

            if cabecera.get("actividad_economica"):
                lines.append(f"- **Actividad Económica**: {cabecera['actividad_economica']}")
            if cabecera.get("tomador"):
                lines.append(f"- **Tomador**: {cabecera['tomador']}")
            if cabecera.get("aseguradora"):
                lines.append(f"- **Compañía Aseguradora**: {cabecera['aseguradora']}")
            if cabecera.get("sigla_empresa"):
                lines.append(f"- **Sigla**: {cabecera['sigla_empresa']}")
            if cabecera.get("vigencia_desde") or cabecera.get("vigencia_hasta"):
                lines.append(f"- **Vigencia**: Desde {cabecera.get('vigencia_desde', 'N/D')} hasta {cabecera.get('vigencia_hasta', 'N/D')}")
            if cabecera.get("moneda"):
                lines.append(f"- **Moneda**: {cabecera['moneda']}")
            if cabecera.get("prima_total"):
                lines.append(f"- **Prima Total**: {cabecera['prima_total']}")

        if objeto:
            lines.append("\n## OBJETO O BIEN ASEGURADO:")
            if objeto.get("tipo_bien"):
                lines.append(f"- **Tipo de Bien**: {objeto['tipo_bien']}")
            if objeto.get("marca"):
                lines.append(f"- **Marca**: {objeto['marca']}")
            if objeto.get("modelo"):
                lines.append(f"- **Modelo**: {objeto['modelo']}")
            if objeto.get("ano"):
                lines.append(f"- **Año**: {objeto['ano']}")
            if objeto.get("placa"):
                lines.append(f"- **Placa**: {objeto['placa']}")
            if objeto.get("motor"):
                lines.append(f"- **Motor**: {objeto['motor']}")
            if objeto.get("chasis"):
                lines.append(f"- **Chasis**: {objeto['chasis']}")
            if objeto.get("color"):
                lines.append(f"- **Color**: {objeto['color']}")
            if objeto.get("uso_servicio"):
                lines.append(f"- **Uso / Servicio**: {objeto['uso_servicio']}")
            if objeto.get("valor_declarado"):
                lines.append(f"- **Valor Declarado**: {objeto['valor_declarado']}")
            if objeto.get("alcance_territorial"):
                lines.append(f"- **Alcance Territorial**: {objeto['alcance_territorial']}")


        if coberturas:
            lines.append("\n## COBERTURAS CONTRATADAS:")
            for cob in coberturas:
                if isinstance(cob, dict):
                    nom = cob.get("nombre", "Cobertura")
                    sa = cob.get("suma_asegurada")
                    ded = cob.get("deducible")
                    lim = cob.get("limite")
                    details = []
                    if sa:
                        details.append(f"Suma Asegurada: {sa}")
                    if ded:
                        details.append(f"Deducible: {ded}")
                    if lim:
                        details.append(f"Límite: {lim}")
                    detail_str = f" ({' | '.join(details)})" if details else ""
                    lines.append(f"- **{nom}**{detail_str}")

        if condiciones:
            lines.append("\n## CONDICIONES ESPECIALES / CLÁUSULAS PARTICULARES:")
            for idx, cond in enumerate(condiciones, start=1):
                lines.append(f"{idx}. {cond}")

        chunk_content = "\n".join(lines)

        return RetrievedChunk(
            chunk_id=f"structured_{policy_id}",
            policy_id=policy_id,
            chunk_index=0,
            chunk_content=chunk_content,
            metadata_json={
                "file_name": file_name,
                "company_sigla": company_sigla,
                "source": "structured_database",
                "section": "Ficha Técnica Estructurada (JSONB)",
            },
            similarity_score=1.0,
        )

    def get_recent_policies(self, limit: int = 20) -> list[dict[str, Any]]:
        """Fetch the most recent policies with standard basic information.

        Args:
            limit: Maximum number of policies to return (default 20).

        Returns:
            List of dicts containing the 6 basic fields plus metadata.
        """
        try:
            with self._db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(_RECENT_POLICIES_QUERY, (limit,))
                    rows = cur.fetchall()
                    results: list[dict[str, Any]] = []
                    for row in rows:
                        record = {
                            "policy_id": row[0],
                            "file_name": row[1],
                            "company_sigla": row[2],
                            "created_at": row[3],
                            "data": row[4] if isinstance(row[4], dict) else {},
                        }
                        results.append(extract_basic_info(record))
                    return results
        except Exception as exc:
            logger.error("Failed to fetch recent policies", error=str(exc))
            return []

    def find_basic_by_policy_number_or_id(self, query_str: str) -> dict[str, Any] | None:
        """Find basic policy information by policy number, ID, or filename.

        Args:
            query_str: Policy number, UUID, or search term.

        Returns:
            Dict containing the 6 basic fields plus metadata, or None if not found.
        """
        if not query_str or not query_str.strip():
            return None

        raw_q = query_str.strip()
        norm_q = re.sub(r"[^a-zA-Z0-9]", "", raw_q).lower()
        like_q = f"%{raw_q}%"

        try:
            with self._db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        _FIND_BASIC_QUERY,
                        (raw_q, norm_q, like_q, like_q, like_q),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return None
                    record = {
                        "policy_id": row[0],
                        "file_name": row[1],
                        "company_sigla": row[2],
                        "created_at": row[3],
                        "data": row[4] if isinstance(row[4], dict) else {},
                    }
                    return extract_basic_info(record)
        except Exception as exc:
            logger.error("Failed to find basic policy info", query=query_str, error=str(exc))
            return None

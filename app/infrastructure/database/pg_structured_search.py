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
        OR p.id_cliente = ANY(%s)
        OR psd.data->'datos_cabecera'->>'documento_identidad' = ANY(%s)
        OR psd.data->'datos_cabecera'->>'nit' = ANY(%s)
    LIMIT %s;
"""

_RECENT_POLICIES_QUERY = """
    SELECT
        p.id::text AS policy_id,
        p.file_name,
        p.company_sigla,
        p.created_at::text,
        psd.data,
        p.id_cliente
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
        psd.data,
        p.id_cliente
    FROM policies p
    LEFT JOIN policy_structured_data psd ON p.id = psd.policy_id
    WHERE
        p.id::text = %s
        OR LOWER(REGEXP_REPLACE(COALESCE(psd.data->'datos_cabecera'->>'numero_poliza', ''), '[^a-zA-Z0-9]', '', 'g')) = %s
        OR psd.data->'datos_cabecera'->>'numero_poliza' ILIKE %s
        OR p.file_name ILIKE %s
        OR psd.data->'datos_cabecera'->>'asegurado' ILIKE %s
        OR p.nombre_cliente ILIKE %s
        OR p.id_cliente = %s
        OR psd.data->'datos_cabecera'->>'documento_identidad' = %s
        OR psd.data->'datos_cabecera'->>'nit' = %s
    ORDER BY p.created_at DESC
    LIMIT 1;
"""

_FIND_BY_CLIENT_QUERY = """
    SELECT
        p.id::text AS policy_id,
        p.file_name,
        p.company_sigla,
        p.created_at::text,
        psd.data,
        p.id_cliente,
        p.envelope_id::text AS envelope_id,
        p.tipo_documento,
        pe.numero_poliza AS envelope_numero_poliza,
        pe.ramo AS envelope_ramo,
        pe.nombre_cliente AS envelope_nombre_cliente
    FROM policies p
    LEFT JOIN policy_structured_data psd ON p.id = psd.policy_id
    LEFT JOIN policy_envelopes pe ON p.envelope_id = pe.id
    WHERE
        p.id_cliente = %s
        OR pe.id_cliente = %s
        OR psd.data->'datos_cabecera'->>'documento_identidad' = %s
        OR psd.data->'datos_cabecera'->>'nit' = %s
        OR LOWER(REGEXP_REPLACE(COALESCE(p.id_cliente, ''), '[^a-zA-Z0-9]', '', 'g')) = LOWER(REGEXP_REPLACE(%s, '[^a-zA-Z0-9]', '', 'g'))
        OR LOWER(REGEXP_REPLACE(COALESCE(pe.id_cliente, ''), '[^a-zA-Z0-9]', '', 'g')) = LOWER(REGEXP_REPLACE(%s, '[^a-zA-Z0-9]', '', 'g'))
        OR pe.nombre_cliente ILIKE %s
        OR psd.data->'datos_cabecera'->>'asegurado' ILIKE %s
        OR psd.data->'datos_cabecera'->>'tomador' ILIKE %s
    ORDER BY p.created_at DESC;
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

    id_cliente = record.get("id_cliente") or doc_identidad or nit

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
        "id_cliente": str(id_cliente) if id_cliente else None,
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

        raw_tokens = [t.strip() for t in tokens if len(t.strip()) >= 3]

        if not normalized_tokens and not like_patterns and not raw_tokens:
            return []

        try:
            with self._db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        _SEARCH_BY_CANDIDATES_QUERY,
                        (normalized_tokens, like_patterns, raw_tokens, raw_tokens, raw_tokens, limit),
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
                            "id_cliente": row[5] if len(row) > 5 else None,
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
                        (raw_q, norm_q, like_q, like_q, like_q, like_q, raw_q, raw_q, raw_q),
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
                        "id_cliente": row[5] if len(row) > 5 else None,
                    }
                    return extract_basic_info(record)
        except Exception as exc:
            logger.error("Failed to find basic policy info", query=query_str, error=str(exc))
            return None

    def find_by_client_id(self, id_cliente: str) -> list[dict[str, Any]]:
        """Fetch all structured policy records belonging to a client ID (CI or NIT).

        Args:
            id_cliente: Customer CI or NIT string.

        Returns:
            List of dicts containing policy_id, file_name, company_sigla, data, etc.
        """
        if not id_cliente or not id_cliente.strip():
            return []

        raw_id = id_cliente.strip()
        try:
            with self._db.get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        _FIND_BY_CLIENT_QUERY,
                        (raw_id, raw_id, raw_id, raw_id, raw_id, raw_id, f"%{raw_id}%", f"%{raw_id}%", f"%{raw_id}%"),
                    )
                    rows = cur.fetchall()
                    results: list[dict[str, Any]] = []
                    for row in rows:
                        results.append({
                            "policy_id": row[0],
                            "file_name": row[1],
                            "company_sigla": row[2],
                            "created_at": row[3],
                            "data": row[4] if isinstance(row[4], dict) else {},
                            "id_cliente": row[5] if len(row) > 5 else None,
                            "envelope_id": row[6] if len(row) > 6 else None,
                            "tipo_documento": row[7] if len(row) > 7 else None,
                            "envelope_numero_poliza": row[8] if len(row) > 8 else None,
                            "envelope_ramo": row[9] if len(row) > 9 else None,
                            "envelope_nombre_cliente": row[10] if len(row) > 10 else None,
                        })
                    return results
        except Exception as exc:
            logger.error("Failed to fetch structured policies by client ID", id_cliente=id_cliente, error=str(exc))
            return []

    def _doc_priority(self, rec: dict[str, Any]) -> int:
        """Calculate source priority for consolidating policy information."""
        fn = (rec.get("file_name") or "").lower()
        td = (rec.get("tipo_documento") or "").lower()
        data = rec.get("data") if isinstance(rec.get("data"), dict) else {}
        cab = data.get("datos_cabecera") if isinstance(data.get("datos_cabecera"), dict) else {}
        prio = 0
        if any(k in td or k in fn for k in ["particular", "caratula", "carátula", "poliza", "póliza"]):
            prio += 50
        elif any(k in td or k in fn for k in ["liquidacion", "liquidación", "cobranza"]):
            prio += 40
        elif any(k in td or k in fn for k in ["certificado", "anexo", "endoso"]):
            prio += 20
        elif any(k in td or k in fn for k in ["general"]):
            prio += 10

        if cab.get("vigencia_desde") and cab.get("vigencia_hasta"):
            prio += 15
        if cab.get("prima_total"):
            prio += 10
        if cab.get("numero_poliza"):
            prio += 5
        return prio

    def format_client_portfolio_chunk(
        self, records: list[dict[str, Any]], id_cliente: str
    ) -> RetrievedChunk:
        """Format multiple policy records belonging to a client into a structured portfolio summary chunk.

        Groups documents by unique commercial policy (envelope or policy number) to avoid repeating
        duplicate rows for endorsements, annexes, and multiple sub-documents of the same policy.

        Args:
            records: List of policy records for the client.
            id_cliente: Customer CI or NIT.

        Returns:
            RetrievedChunk with high priority containing the consolidated structured summary of the client's portfolio.
        """
        # Group records by unique policy
        grouped_policies: dict[str, list[dict[str, Any]]] = {}
        client_name = ""

        for rec in records:
            env_id = rec.get("envelope_id")
            if not client_name:
                client_name = rec.get("envelope_nombre_cliente") or ""
                if not client_name and isinstance(rec.get("data"), dict):
                    client_name = (rec["data"].get("datos_cabecera") or {}).get("asegurado") or ""

            if env_id:
                group_key = f"env_{env_id}"
            else:
                info = extract_basic_info(rec)
                company = rec.get("company_sigla") or ""
                norm_num = re.sub(r"[^a-zA-Z0-9]", "", info.get("numero_poliza") or rec.get("file_name") or "").lower()
                group_key = f"pol_{company}_{norm_num}" if norm_num else f"id_{rec.get('policy_id')}"

            grouped_policies.setdefault(group_key, []).append(rec)

        header_suffix = f" — CLIENTE: {client_name}" if client_name else ""
        lines = [
            f"[CARTERA DE PÓLIZAS DEL CLIENTE — CI/NIT: {id_cliente}{header_suffix}]",
            f"Total de pólizas registradas en cartera: {len(grouped_policies)}",
            "",
            "| N° | N° Póliza | Aseguradora | Ramo | Vigencia Contractual | Prima Total | Documentos Vinculados |",
            "|---|---|---|---|---|---|---|",
        ]

        for idx, (group_key, group_recs) in enumerate(grouped_policies.items(), 1):
            sorted_docs = sorted(group_recs, key=self._doc_priority, reverse=True)
            primary_rec = sorted_docs[0]
            primary_info = extract_basic_info(primary_rec)

            num_poliza = (
                primary_rec.get("envelope_numero_poliza")
                or primary_info.get("numero_poliza")
                or primary_rec.get("file_name", "Desconocido")
            )
            sigla = primary_rec.get("company_sigla") or primary_info.get("company_sigla") or "N/A"
            ramo = (
                primary_rec.get("envelope_ramo")
                or (primary_info.get("ramo") if primary_info.get("ramo") != "No especificado" else None)
            )

            # Find best vigencia dates from group
            fechas_str = ""
            for doc in sorted_docs:
                doc_data = doc.get("data") if isinstance(doc.get("data"), dict) else {}
                doc_cab = doc_data.get("datos_cabecera") if isinstance(doc_data.get("datos_cabecera"), dict) else {}
                v_d = doc_cab.get("vigencia_desde")
                v_h = doc_cab.get("vigencia_hasta")
                if v_d and v_h:
                    fechas_str = f"Desde: {v_d} | Hasta: {v_h}"
                    break
                elif v_d or v_h:
                    fechas_str = f"Desde: {v_d or 'N/E'} | Hasta: {v_h or 'N/E'}"
                    break

            if not fechas_str:
                fechas_str = primary_info.get("vigencia", "No especificada")

            # Find best prima from group if primary doesn't have it
            prima = primary_info.get("prima_total", "No especificada")
            if prima == "No especificada":
                for doc in sorted_docs:
                    doc_info = extract_basic_info(doc)
                    if doc_info.get("prima_total") and doc_info.get("prima_total") != "No especificada":
                        prima = doc_info["prima_total"]
                        break

            if not ramo or ramo == "No especificado":
                for doc in sorted_docs:
                    doc_info = extract_basic_info(doc)
                    if doc_info.get("ramo") and doc_info.get("ramo") != "No especificado":
                        ramo = doc_info["ramo"]
                        break
            ramo = ramo or "No especificado"

            doc_count = len(group_recs)
            doc_str = f"{doc_count} archivo{'s' if doc_count > 1 else ''}"

            lines.append(
                f"| {idx} | {num_poliza} | {sigla} | {ramo} | {fechas_str} | {prima} | {doc_str} |"
            )

        content = "\n".join(lines)
        return RetrievedChunk(
            chunk_id=f"client-portfolio-{id_cliente}",
            policy_id="client-portfolio",
            chunk_index=0,
            chunk_content=content,
            metadata_json={"source_file": "CARTERA_CLIENTE", "id_cliente": id_cliente},
            similarity_score=1.0,
        )

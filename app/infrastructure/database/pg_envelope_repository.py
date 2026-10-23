"""DocEngine — Infrastructure: PostgreSQL Policy Envelope Repository.

Handles all persistence and lookup operations for policy envelopes
and document associations in PostgreSQL.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from app.domain.models.envelope import normalize_document_type
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class PgEnvelopeRepository:
    """Repository for managing policy envelopes and their bound documents."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    def get_or_create_envelope(
        self,
        numero_poliza: str,
        company_sigla: str | None = None,
        ramo: str | None = None,
        id_cliente: str | None = None,
        nombre_cliente: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Find an existing policy envelope or create a new one.

        Args:
            numero_poliza: Policy number identifier.
            company_sigla: Optional 3-letter company code.
            ramo: Optional insurance line name.
            id_cliente: Optional customer identifier (Carnet or NIT).
            nombre_cliente: Optional customer name or business name.
            **kwargs: Extra parameters ignored safely for backward/forward compatibility.

        Returns:
            UUID string of the found or created policy envelope.
        """
        clean_num = (numero_poliza or "").strip()[:100]
        if not clean_num:
            fallback_sigla = company_sigla.strip().upper()[:20] if company_sigla else "GEN"
            fallback_client = id_cliente.strip()[:50] if id_cliente else "UNKNOWN"
            clean_num = f"POL-{fallback_sigla}-{fallback_client}"[:100]
        clean_sigla = company_sigla.strip().upper()[:20] if company_sigla else None
        clean_ramo = ramo.strip()[:200] if ramo else None
        clean_id_cliente = id_cliente.strip()[:50] if id_cliente else None
        clean_nombre_cliente = nombre_cliente.strip()[:255] if nombre_cliente else None

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Check if envelope already exists
                cur.execute(
                    """
                    SELECT id, ramo, id_cliente FROM policy_envelopes
                    WHERE numero_poliza = %s
                      AND (company_sigla = %s OR (%s IS NULL AND company_sigla IS NULL))
                    ORDER BY created_at DESC
                    LIMIT 1;
                    """,
                    (clean_num, clean_sigla, clean_sigla),
                )
                row = cur.fetchone()

                if row:
                    envelope_id = str(row[0])
                    existing_ramo = row[1] if len(row) > 1 else None
                    existing_id_cliente = row[2] if len(row) > 2 else None
                    updates = []
                    params: list[Any] = []

                    if clean_ramo and not existing_ramo:
                        updates.append("ramo = %s")
                        params.append(clean_ramo)
                    if clean_id_cliente and not existing_id_cliente:
                        updates.append("id_cliente = %s")
                        params.append(clean_id_cliente)

                    if updates:
                        updates.append("updated_at = CURRENT_TIMESTAMP")
                        params.append(envelope_id)
                        cur.execute(
                            f"UPDATE policy_envelopes SET {', '.join(updates)} WHERE id = %s;",
                            tuple(params),
                        )

                    if clean_nombre_cliente:
                        try:
                            cur.execute("SAVEPOINT check_nombre_cliente;")
                            cur.execute(
                                "UPDATE policy_envelopes SET nombre_cliente = %s WHERE id = %s AND (nombre_cliente IS NULL OR nombre_cliente = '');",
                                (clean_nombre_cliente, envelope_id),
                            )
                            cur.execute("RELEASE SAVEPOINT check_nombre_cliente;")
                        except Exception:
                            cur.execute("ROLLBACK TO SAVEPOINT check_nombre_cliente;")

                    conn.commit()
                    return envelope_id

                # 2. Create new envelope
                envelope_id = str(uuid.uuid4())
                if clean_nombre_cliente:
                    try:
                        cur.execute("SAVEPOINT insert_with_nombre;")
                        cur.execute(
                            """
                            INSERT INTO policy_envelopes (id, numero_poliza, company_sigla, ramo, id_cliente, nombre_cliente)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (numero_poliza, company_sigla) DO UPDATE
                            SET updated_at = CURRENT_TIMESTAMP,
                                id_cliente = COALESCE(policy_envelopes.id_cliente, EXCLUDED.id_cliente),
                                nombre_cliente = COALESCE(policy_envelopes.nombre_cliente, EXCLUDED.nombre_cliente)
                            RETURNING id;
                            """,
                            (envelope_id, clean_num, clean_sigla, clean_ramo, clean_id_cliente, clean_nombre_cliente),
                        )
                        res = cur.fetchone()
                        cur.execute("RELEASE SAVEPOINT insert_with_nombre;")
                        conn.commit()
                        return str(res[0]) if res else envelope_id
                    except Exception:
                        try:
                            cur.execute("ROLLBACK TO SAVEPOINT insert_with_nombre;")
                        except Exception:
                            pass

                cur.execute(
                    """
                    INSERT INTO policy_envelopes (id, numero_poliza, company_sigla, ramo, id_cliente)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (numero_poliza, company_sigla) DO UPDATE
                    SET updated_at = CURRENT_TIMESTAMP,
                        id_cliente = COALESCE(policy_envelopes.id_cliente, EXCLUDED.id_cliente)
                    RETURNING id;
                    """,
                    (envelope_id, clean_num, clean_sigla, clean_ramo, clean_id_cliente),
                )
                res = cur.fetchone()
                final_id = str(res[0]) if res else envelope_id

            conn.commit()
            return final_id

    def link_policy_to_envelope(
        self,
        policy_id: str,
        envelope_id: str,
        tipo_documento: str | None = None,
        id_cliente: str | None = None,
        nombre_cliente: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Link a document (policies table entry) to a policy envelope.

        Args:
            policy_id: UUID of the policy document record.
            envelope_id: UUID of the policy envelope.
            tipo_documento: Optional document classification (e.g. CONDICIONADO_GENERAL).
            id_cliente: Optional customer identifier to persist in policies record.
            nombre_cliente: Optional customer name or business name.
            **kwargs: Extra parameters ignored safely for backward/forward compatibility.
        """
        clean_type = normalize_document_type(tipo_documento)
        clean_id_cliente = id_cliente.strip()[:50] if id_cliente else None
        clean_nombre_cliente = nombre_cliente.strip()[:255] if nombre_cliente else None

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                if clean_id_cliente:
                    cur.execute(
                        """
                        UPDATE policies
                        SET envelope_id = %s,
                            tipo_documento = %s,
                            id_cliente = %s
                        WHERE id = %s;
                        """,
                        (envelope_id, clean_type, clean_id_cliente, policy_id),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE policies
                        SET envelope_id = %s,
                            tipo_documento = %s
                        WHERE id = %s;
                        """,
                        (envelope_id, clean_type, policy_id),
                    )

                if clean_nombre_cliente:
                    try:
                        cur.execute("SAVEPOINT link_nombre;")
                        cur.execute(
                            "UPDATE policies SET nombre_cliente = %s WHERE id = %s;",
                            (clean_nombre_cliente, policy_id),
                        )
                        cur.execute("RELEASE SAVEPOINT link_nombre;")
                    except Exception:
                        cur.execute("ROLLBACK TO SAVEPOINT link_nombre;")
            conn.commit()

    def get_envelope_by_id(self, envelope_id: str) -> dict[str, Any] | None:
        """Retrieve a policy envelope and its bound documents by envelope ID.

        Args:
            envelope_id: UUID string of the envelope.

        Returns:
            Dictionary with envelope details and document list, or None if not found.
        """
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pe.id::text, pe.numero_poliza, pe.company_sigla, pe.ramo,
                           pe.created_at::text, pe.updated_at::text, pe.id_cliente,
                           COALESCE(
                               pe.nombre_cliente,
                               (SELECT psd.data->'datos_cabecera'->>'asegurado'
                                FROM policies p
                                JOIN policy_structured_data psd ON p.id = psd.policy_id
                                WHERE p.envelope_id = pe.id AND psd.data->'datos_cabecera'->>'asegurado' IS NOT NULL
                                LIMIT 1)
                           ) AS nombre_cliente
                    FROM policy_envelopes pe
                    WHERE pe.id = %s::uuid;
                    """,
                    (envelope_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None

                env = {
                    "id": str(row[0]),
                    "numero_poliza": row[1],
                    "company_sigla": row[2],
                    "ramo": row[3],
                    "created_at": row[4],
                    "updated_at": row[5],
                    "id_cliente": row[6],
                    "nombre_cliente": row[7],
                    "documents": [],
                }

                # Retrieve bound documents
                cur.execute(
                    """
                    SELECT id::text, file_name, file_hash, company_sigla,
                           tipo_documento, total_pages, file_size_bytes,
                           created_at::text, id_cliente
                    FROM policies
                    WHERE envelope_id = %s::uuid
                    ORDER BY created_at ASC;
                    """,
                    (envelope_id,),
                )
                docs = cur.fetchall()
                for doc in docs:
                    env["documents"].append({
                        "policy_id": str(doc[0]),
                        "file_name": doc[1],
                        "file_hash": doc[2],
                        "company_sigla": doc[3],
                        "tipo_documento": doc[4],
                        "total_pages": doc[5],
                        "file_size_bytes": doc[6],
                        "created_at": doc[7],
                        "id_cliente": doc[8],
                    })

                env["documents_count"] = len(env["documents"])
                return env

    def get_envelope_by_policy_number(
        self,
        numero_poliza: str,
        company_sigla: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieve policy envelopes and their bound documents by policy number.

        Args:
            numero_poliza: Policy number or partial search.
            company_sigla: Optional company code filter.

        Returns:
            List of matching envelope dictionaries.
        """
        clean_num = numero_poliza.strip()
        clean_sigla = company_sigla.strip().upper() if company_sigla else None

        query = """
            SELECT pe.id::text, pe.numero_poliza, pe.company_sigla, pe.ramo,
                   pe.created_at::text, pe.updated_at::text, pe.id_cliente,
                   COALESCE(
                       pe.nombre_cliente,
                       (SELECT psd.data->'datos_cabecera'->>'asegurado'
                        FROM policies p
                        JOIN policy_structured_data psd ON p.id = psd.policy_id
                        WHERE p.envelope_id = pe.id AND psd.data->'datos_cabecera'->>'asegurado' IS NOT NULL
                        LIMIT 1)
                   ) AS nombre_cliente
            FROM policy_envelopes pe
            WHERE (
                pe.numero_poliza ILIKE %s
                OR LOWER(REGEXP_REPLACE(pe.numero_poliza, '[^a-zA-Z0-9]', '', 'g')) = LOWER(REGEXP_REPLACE(%s, '[^a-zA-Z0-9]', '', 'g'))
            )
        """
        params: list[Any] = [f"%{clean_num}%", clean_num]

        if clean_sigla:
            query += " AND pe.company_sigla = %s"
            params.append(clean_sigla)

        query += " ORDER BY pe.created_at DESC LIMIT 20;"

        envelopes = []
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()

                for row in rows:
                    env_id = str(row[0])
                    env = {
                        "id": env_id,
                        "numero_poliza": row[1],
                        "company_sigla": row[2],
                        "ramo": row[3],
                        "created_at": row[4],
                        "updated_at": row[5],
                        "id_cliente": row[6],
                        "nombre_cliente": row[7],
                        "documents": [],
                    }
                    envelopes.append(env)

                # Fetch documents for found envelopes
                for env in envelopes:
                    cur.execute(
                        """
                        SELECT id::text, file_name, file_hash, company_sigla,
                               tipo_documento, total_pages, file_size_bytes,
                               created_at::text, id_cliente
                        FROM policies
                        WHERE envelope_id = %s::uuid
                        ORDER BY created_at ASC;
                        """,
                        (env["id"],),
                    )
                    docs = cur.fetchall()
                    for doc in docs:
                        env["documents"].append({
                            "policy_id": str(doc[0]),
                            "file_name": doc[1],
                            "file_hash": doc[2],
                            "company_sigla": doc[3],
                            "tipo_documento": doc[4],
                            "total_pages": doc[5],
                            "file_size_bytes": doc[6],
                            "created_at": doc[7],
                            "id_cliente": doc[8],
                        })
                    env["documents_count"] = len(env["documents"])

        return envelopes

    def search_clients(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search distinct clients by CI, NIT, customer name, or business name.

        Args:
            query: Search string (Carnet, NIT, or name fragment).
            limit: Maximum client entries to return.

        Returns:
            List of unique client dicts with id_cliente, nombre_cliente, envelopes_count, and companies.
        """
        clean_q = query.strip()
        if not clean_q:
            return []

        clean_norm = re.sub(r"[^a-zA-Z0-9]", "", clean_q)
        sql = """
            WITH resolved_envelopes AS (
                SELECT
                    COALESCE(
                        pe.id_cliente,
                        (SELECT p.id_cliente FROM policies p WHERE p.envelope_id = pe.id AND p.id_cliente IS NOT NULL LIMIT 1)
                    ) AS id_cliente,
                    COALESCE(
                        pe.nombre_cliente,
                        (SELECT psd.data->'datos_cabecera'->>'asegurado'
                         FROM policies p
                         JOIN policy_structured_data psd ON p.id = psd.policy_id
                         WHERE p.envelope_id = pe.id AND psd.data->'datos_cabecera'->>'asegurado' IS NOT NULL
                         LIMIT 1)
                    ) AS nombre_cliente,
                    pe.company_sigla,
                    pe.id AS envelope_id
                FROM policy_envelopes pe
                WHERE (
                    pe.id_cliente ILIKE %s
                    OR (pe.id_cliente IS NOT NULL AND LOWER(REGEXP_REPLACE(pe.id_cliente, '[^a-zA-Z0-9]', '', 'g')) = LOWER(%s))
                    OR pe.nombre_cliente ILIKE %s
                    OR EXISTS (
                        SELECT 1 FROM policies p
                        JOIN policy_structured_data psd ON p.id = psd.policy_id
                        WHERE p.envelope_id = pe.id
                          AND (
                              psd.data->'datos_cabecera'->>'asegurado' ILIKE %s
                              OR psd.data->'datos_cabecera'->>'tomador' ILIKE %s
                          )
                    )
                )
            )
            SELECT
                id_cliente,
                MAX(nombre_cliente) AS nombre_cliente,
                COUNT(DISTINCT envelope_id) AS envelopes_count,
                ARRAY_AGG(DISTINCT company_sigla) FILTER (WHERE company_sigla IS NOT NULL) AS companies
            FROM resolved_envelopes
            WHERE id_cliente IS NOT NULL OR nombre_cliente IS NOT NULL
            GROUP BY id_cliente
            ORDER BY envelopes_count DESC, id_cliente ASC
            LIMIT %s;
        """
        params: list[Any] = [
            f"%{clean_q}%",
            clean_norm,
            f"%{clean_q}%",
            f"%{clean_q}%",
            f"%{clean_q}%",
            max(1, limit),
        ]

        clients = []
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
                for row in rows:
                    cid = str(row[0]) if row[0] else (row[1] or clean_q)
                    cname = row[1] or "No especificado"
                    clients.append({
                        "id_cliente": cid,
                        "nombre_cliente": cname,
                        "envelopes_count": int(row[2]),
                        "companies": list(row[3]) if row[3] else [],
                    })
        return clients

    def get_envelopes_by_client_id(
        self,
        id_cliente: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Retrieve policy envelopes and their bound documents for a specific client.

        Supports filtering by CI/NIT or customer name/business name.

        Args:
            id_cliente: Customer identifier (Carnet or NIT) or customer name.
            limit: Maximum envelopes to return (default 50).
            offset: Pagination offset.

        Returns:
            List of matching envelope dictionaries with documents.
        """
        clean_client = id_cliente.strip()
        clean_norm = re.sub(r"[^a-zA-Z0-9]", "", clean_client)
        query = """
            SELECT pe.id::text, pe.numero_poliza, pe.company_sigla, pe.ramo,
                   pe.created_at::text, pe.updated_at::text, pe.id_cliente,
                   COALESCE(
                       pe.nombre_cliente,
                       (SELECT psd.data->'datos_cabecera'->>'asegurado'
                        FROM policies p
                        JOIN policy_structured_data psd ON p.id = psd.policy_id
                        WHERE p.envelope_id = pe.id AND psd.data->'datos_cabecera'->>'asegurado' IS NOT NULL
                        LIMIT 1)
                   ) AS nombre_cliente
            FROM policy_envelopes pe
            WHERE (
                pe.id_cliente ILIKE %s
                OR (pe.id_cliente IS NOT NULL AND LOWER(REGEXP_REPLACE(pe.id_cliente, '[^a-zA-Z0-9]', '', 'g')) = LOWER(%s))
                OR pe.nombre_cliente ILIKE %s
                OR EXISTS (
                    SELECT 1 FROM policies p
                    JOIN policy_structured_data psd ON p.id = psd.policy_id
                    WHERE p.envelope_id = pe.id
                      AND (
                          psd.data->'datos_cabecera'->>'asegurado' ILIKE %s
                          OR psd.data->'datos_cabecera'->>'tomador' ILIKE %s
                      )
                )
            )
            ORDER BY pe.updated_at DESC, pe.created_at DESC
            LIMIT %s OFFSET %s;
        """
        params: list[Any] = [
            f"%{clean_client}%",
            clean_norm,
            f"%{clean_client}%",
            f"%{clean_client}%",
            f"%{clean_client}%",
            max(1, limit),
            max(0, offset),
        ]

        envelopes = []
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()

                for row in rows:
                    env_id = str(row[0])
                    env = {
                        "id": env_id,
                        "numero_poliza": row[1],
                        "company_sigla": row[2],
                        "ramo": row[3],
                        "created_at": row[4],
                        "updated_at": row[5],
                        "id_cliente": row[6],
                        "nombre_cliente": row[7],
                        "documents": [],
                    }
                    envelopes.append(env)

                for env in envelopes:
                    cur.execute(
                        """
                        SELECT id::text, file_name, file_hash, company_sigla,
                               tipo_documento, total_pages, file_size_bytes,
                               created_at::text, id_cliente
                        FROM policies
                        WHERE envelope_id = %s::uuid
                        ORDER BY created_at ASC;
                        """,
                        (env["id"],),
                    )
                    docs = cur.fetchall()
                    for doc in docs:
                        env["documents"].append({
                            "policy_id": str(doc[0]),
                            "file_name": doc[1],
                            "file_hash": doc[2],
                            "company_sigla": doc[3],
                            "tipo_documento": doc[4],
                            "total_pages": doc[5],
                            "file_size_bytes": doc[6],
                            "created_at": doc[7],
                            "id_cliente": doc[8],
                        })
                    env["documents_count"] = len(env["documents"])

        return envelopes

    def list_envelopes(
        self,
        limit: int = 50,
        offset: int = 0,
        company_sigla: str | None = None,
        id_cliente: str | None = None,
    ) -> list[dict[str, Any]]:
        """List policy envelopes ordered by most recently updated/created.

        Args:
            limit: Maximum envelopes to return (default 50).
            offset: Pagination offset.
            company_sigla: Optional company sigla filter.
            id_cliente: Optional customer identifier filter.

        Returns:
            List of envelope dictionaries with nested documents and counts.
        """
        query = """
            SELECT pe.id::text, pe.numero_poliza, pe.company_sigla, pe.ramo,
                   pe.created_at::text, pe.updated_at::text, pe.id_cliente,
                   COALESCE(
                       pe.nombre_cliente,
                       (SELECT psd.data->'datos_cabecera'->>'asegurado'
                        FROM policies p
                        JOIN policy_structured_data psd ON p.id = psd.policy_id
                        WHERE p.envelope_id = pe.id AND psd.data->'datos_cabecera'->>'asegurado' IS NOT NULL
                        LIMIT 1)
                   ) AS nombre_cliente
            FROM policy_envelopes pe
        """
        where_clauses: list[str] = []
        params: list[Any] = []

        if company_sigla:
            where_clauses.append("pe.company_sigla = %s")
            params.append(company_sigla.strip().upper())

        if id_cliente:
            clean_client = id_cliente.strip()
            where_clauses.append("(pe.id_cliente ILIKE %s OR LOWER(REGEXP_REPLACE(pe.id_cliente, '[^a-zA-Z0-9]', '', 'g')) = LOWER(REGEXP_REPLACE(%s, '[^a-zA-Z0-9]', '', 'g')))")
            params.extend([f"%{clean_client}%", clean_client])

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY pe.updated_at DESC, pe.created_at DESC LIMIT %s OFFSET %s;"
        params.extend([max(1, limit), max(0, offset)])

        envelopes = []
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                rows = cur.fetchall()

                for row in rows:
                    env_id = str(row[0])
                    env = {
                        "id": env_id,
                        "numero_poliza": row[1],
                        "company_sigla": row[2],
                        "ramo": row[3],
                        "created_at": row[4],
                        "updated_at": row[5],
                        "id_cliente": row[6],
                        "nombre_cliente": row[7],
                        "documents": [],
                    }
                    envelopes.append(env)

                # Fetch documents for each envelope
                for env in envelopes:
                    cur.execute(
                        """
                        SELECT id::text, file_name, file_hash, company_sigla,
                               tipo_documento, total_pages, file_size_bytes,
                               created_at::text, id_cliente
                        FROM policies
                        WHERE envelope_id = %s::uuid
                        ORDER BY created_at ASC;
                        """,
                        (env["id"],),
                    )
                    docs = cur.fetchall()
                    for doc in docs:
                        env["documents"].append({
                            "policy_id": str(doc[0]),
                            "file_name": doc[1],
                            "file_hash": doc[2],
                            "company_sigla": doc[3],
                            "tipo_documento": doc[4],
                            "total_pages": doc[5],
                            "file_size_bytes": doc[6],
                            "created_at": doc[7],
                            "id_cliente": doc[8],
                        })
                    env["documents_count"] = len(env["documents"])

        return envelopes

    def delete_envelope(self, envelope_id: str) -> dict[str, Any] | None:
        """Atomically delete a policy envelope and all bound documents from PostgreSQL.

        Due to ON DELETE CASCADE on:
        - policy_raw_md
        - policy_structured_data
        - policy_chunks
        - policy_processing_stats
        deleting records from `policies` automatically cleans up all associated
        content, vector embeddings, and telemetry.

        Args:
            envelope_id: UUID string of the envelope.

        Returns:
            Dictionary with deleted envelope info and deleted documents list,
            or None if the envelope does not exist.
        """
        with self._db.get_connection() as conn:
            try:
                with conn.cursor() as cur:
                    # 1. Verify existence and retrieve envelope details
                    cur.execute(
                        """
                        SELECT id::text, numero_poliza, company_sigla, ramo
                        FROM policy_envelopes
                        WHERE id = %s::uuid;
                        """,
                        (envelope_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None

                    envelope_info: dict[str, Any] = {
                        "id": str(row[0]),
                        "numero_poliza": row[1],
                        "company_sigla": row[2],
                        "ramo": row[3],
                        "deleted_documents": [],
                    }

                    # 2. Retrieve bound documents for audit and disk cleanup
                    cur.execute(
                        """
                        SELECT id::text, file_name, file_hash, company_sigla
                        FROM policies
                        WHERE envelope_id = %s::uuid;
                        """,
                        (envelope_id,),
                    )
                    docs = cur.fetchall()
                    for d in docs:
                        envelope_info["deleted_documents"].append({
                            "policy_id": str(d[0]),
                            "file_name": d[1],
                            "file_hash": d[2],
                            "company_sigla": d[3],
                        })

                    # 3. Delete bound documents from policies
                    # Cascade handles policy_raw_md, policy_structured_data,
                    # policy_chunks, and policy_processing_stats.
                    cur.execute(
                        """
                        DELETE FROM policies
                        WHERE envelope_id = %s::uuid;
                        """,
                        (envelope_id,),
                    )

                    # 4. Delete the envelope container
                    cur.execute(
                        """
                        DELETE FROM policy_envelopes
                        WHERE id = %s::uuid;
                        """,
                        (envelope_id,),
                    )

                conn.commit()
                return envelope_info
            except Exception:
                conn.rollback()
                raise

    def delete_document(self, policy_id: str) -> dict[str, Any] | None:
        """Atomically delete a single policy document from PostgreSQL.

        Due to ON DELETE CASCADE on associated tables (chunks, structured data,
        markdown, stats), deleting the document record from `policies` automatically
        removes all vector embeddings, atomized data, and cached files.

        Args:
            policy_id: UUID string of the document in the policies table.

        Returns:
            Dictionary with document details or None if not found.
        """
        with self._db.get_connection() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id::text, file_name, file_hash, company_sigla, envelope_id::text
                        FROM policies
                        WHERE id = %s::uuid;
                        """,
                        (policy_id,),
                    )
                    row = cur.fetchone()
                    if not row:
                        return None

                    doc_info: dict[str, Any] = {
                        "policy_id": str(row[0]),
                        "file_name": row[1],
                        "file_hash": row[2],
                        "company_sigla": row[3],
                        "envelope_id": str(row[4]) if row[4] else None,
                    }

                    cur.execute(
                        """
                        DELETE FROM policies
                        WHERE id = %s::uuid;
                        """,
                        (policy_id,),
                    )

                conn.commit()
                return doc_info
            except Exception:
                conn.rollback()
                raise


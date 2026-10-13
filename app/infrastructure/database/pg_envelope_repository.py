"""DocEngine — Infrastructure: PostgreSQL Policy Envelope Repository.

Handles all persistence and lookup operations for policy envelopes
and document associations in PostgreSQL.
"""

from __future__ import annotations

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
    ) -> str:
        """Find an existing policy envelope or create a new one.

        Args:
            numero_poliza: Policy number identifier.
            company_sigla: Optional 3-letter company code.
            ramo: Optional insurance line name.
            id_cliente: Optional customer identifier (Carnet or NIT).

        Returns:
            UUID string of the found or created policy envelope.
        """
        clean_num = numero_poliza.strip()
        clean_sigla = company_sigla.strip().upper() if company_sigla else None
        clean_ramo = ramo.strip() if ramo else None
        clean_id_cliente = id_cliente.strip() if id_cliente else None

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
                    conn.commit()
                    return envelope_id

                # 2. Create new envelope
                envelope_id = str(uuid.uuid4())
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
    ) -> None:
        """Link a document (policies table entry) to a policy envelope.

        Args:
            policy_id: UUID of the policy document record.
            envelope_id: UUID of the policy envelope.
            tipo_documento: Optional document classification (e.g. CONDICIONADO_GENERAL).
            id_cliente: Optional customer identifier to persist in policies record.
        """
        clean_type = normalize_document_type(tipo_documento)
        clean_id_cliente = id_cliente.strip() if id_cliente else None

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
                    SELECT id::text, numero_poliza, company_sigla, ramo,
                           created_at::text, updated_at::text, id_cliente
                    FROM policy_envelopes
                    WHERE id = %s::uuid;
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
            SELECT id::text, numero_poliza, company_sigla, ramo,
                   created_at::text, updated_at::text, id_cliente
            FROM policy_envelopes
            WHERE (
                numero_poliza ILIKE %s
                OR LOWER(REGEXP_REPLACE(numero_poliza, '[^a-zA-Z0-9]', '', 'g')) = LOWER(REGEXP_REPLACE(%s, '[^a-zA-Z0-9]', '', 'g'))
            )
        """
        params: list[Any] = [f"%{clean_num}%", clean_num]

        if clean_sigla:
            query += " AND company_sigla = %s"
            params.append(clean_sigla)

        query += " ORDER BY created_at DESC LIMIT 20;"

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

    def get_envelopes_by_client_id(
        self,
        id_cliente: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Retrieve policy envelopes and their bound documents for a specific client.

        Args:
            id_cliente: Customer identifier (Carnet or NIT).
            limit: Maximum envelopes to return (default 50).
            offset: Pagination offset.

        Returns:
            List of matching envelope dictionaries with documents.
        """
        clean_client = id_cliente.strip()
        query = """
            SELECT id::text, numero_poliza, company_sigla, ramo,
                   created_at::text, updated_at::text, id_cliente
            FROM policy_envelopes
            WHERE (
                id_cliente ILIKE %s
                OR LOWER(REGEXP_REPLACE(id_cliente, '[^a-zA-Z0-9]', '', 'g')) = LOWER(REGEXP_REPLACE(%s, '[^a-zA-Z0-9]', '', 'g'))
            )
            ORDER BY updated_at DESC, created_at DESC
            LIMIT %s OFFSET %s;
        """
        params: list[Any] = [f"%{clean_client}%", clean_client, max(1, limit), max(0, offset)]

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
            SELECT id::text, numero_poliza, company_sigla, ramo,
                   created_at::text, updated_at::text, id_cliente
            FROM policy_envelopes
        """
        where_clauses: list[str] = []
        params: list[Any] = []

        if company_sigla:
            where_clauses.append("company_sigla = %s")
            params.append(company_sigla.strip().upper())

        if id_cliente:
            clean_client = id_cliente.strip()
            where_clauses.append("(id_cliente ILIKE %s OR LOWER(REGEXP_REPLACE(id_cliente, '[^a-zA-Z0-9]', '', 'g')) = LOWER(REGEXP_REPLACE(%s, '[^a-zA-Z0-9]', '', 'g')))")
            params.extend([f"%{clean_client}%", clean_client])

        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)

        query += " ORDER BY updated_at DESC, created_at DESC LIMIT %s OFFSET %s;"
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

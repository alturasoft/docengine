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
    ) -> str:
        """Find an existing policy envelope or create a new one.

        Args:
            numero_poliza: Policy number identifier.
            company_sigla: Optional 3-letter company code.
            ramo: Optional insurance line name.

        Returns:
            UUID string of the found or created policy envelope.
        """
        clean_num = numero_poliza.strip()
        clean_sigla = company_sigla.strip().upper() if company_sigla else None
        clean_ramo = ramo.strip() if ramo else None

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Check if envelope already exists
                cur.execute(
                    """
                    SELECT id, ramo FROM policy_envelopes
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
                    existing_ramo = row[1]
                    # Update ramo if it was missing and is now provided
                    if clean_ramo and not existing_ramo:
                        cur.execute(
                            """
                            UPDATE policy_envelopes
                            SET ramo = %s, updated_at = CURRENT_TIMESTAMP
                            WHERE id = %s;
                            """,
                            (clean_ramo, envelope_id),
                        )
                    conn.commit()
                    return envelope_id

                # 2. Create new envelope
                envelope_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO policy_envelopes (id, numero_poliza, company_sigla, ramo)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (numero_poliza, company_sigla) DO UPDATE
                    SET updated_at = CURRENT_TIMESTAMP
                    RETURNING id;
                    """,
                    (envelope_id, clean_num, clean_sigla, clean_ramo),
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
    ) -> None:
        """Link a document (policies table entry) to a policy envelope.

        Args:
            policy_id: UUID of the policy document record.
            envelope_id: UUID of the policy envelope.
            tipo_documento: Optional document classification (e.g. CONDICIONADO_GENERAL).
        """
        clean_type = normalize_document_type(tipo_documento)

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
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
                           created_at::text, updated_at::text
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
                    "documents": [],
                }

                # Retrieve bound documents
                cur.execute(
                    """
                    SELECT id::text, file_name, file_hash, company_sigla,
                           tipo_documento, total_pages, file_size_bytes,
                           created_at::text
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
                   created_at::text, updated_at::text
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
                        "documents": [],
                    }
                    envelopes.append(env)

                # Fetch documents for found envelopes
                for env in envelopes:
                    cur.execute(
                        """
                        SELECT id::text, file_name, file_hash, company_sigla,
                               tipo_documento, total_pages, file_size_bytes,
                               created_at::text
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
                        })
                    env["documents_count"] = len(env["documents"])

        return envelopes

    def list_envelopes(
        self,
        limit: int = 50,
        offset: int = 0,
        company_sigla: str | None = None,
    ) -> list[dict[str, Any]]:
        """List policy envelopes ordered by most recently updated/created.

        Args:
            limit: Maximum envelopes to return (default 50).
            offset: Pagination offset.
            company_sigla: Optional company sigla filter.

        Returns:
            List of envelope dictionaries with nested documents and counts.
        """
        query = """
            SELECT id::text, numero_poliza, company_sigla, ramo,
                   created_at::text, updated_at::text
            FROM policy_envelopes
        """
        params: list[Any] = []
        if company_sigla:
            query += " WHERE company_sigla = %s"
            params.append(company_sigla.strip().upper())

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
                        "documents": [],
                    }
                    envelopes.append(env)

                # Fetch documents for each envelope
                for env in envelopes:
                    cur.execute(
                        """
                        SELECT id::text, file_name, file_hash, company_sigla,
                               tipo_documento, total_pages, file_size_bytes,
                               created_at::text
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
                        })
                    env["documents_count"] = len(env["documents"])

        return envelopes

"""DocEngine — Infrastructure: PostgreSQL Policy Insured Persons Repository.

[ADITIVO] Gestiona la persistencia, consulta, búsqueda y agregación estadística
de nóminas de personas aseguradas en pólizas colectivas en PostgreSQL.
"""

from __future__ import annotations

import json
from typing import Any

from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class PgInsuredPersonsRepository:
    """Repositorio para la gestión de personas aseguradas en pólizas colectivas."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    def save_insured_persons(
        self,
        policy_id: str,
        envelope_id: str | None,
        persons: list[dict[str, Any]],
    ) -> int:
        """Guarda o actualiza atómicamente la lista de asegurados de una póliza."""
        if not persons:
            return 0

        delete_sql = "DELETE FROM policy_insured_persons WHERE policy_id = %s::uuid;"
        insert_sql = """
            INSERT INTO policy_insured_persons (
                policy_id, envelope_id, item_number, nombre_completo,
                documento_identidad, fecha_nacimiento, edad, genero,
                parentesco_categoria, cargo_ocupacion, suma_asegurada_usd,
                prima_usd, raw_metadata, updated_at
            ) VALUES (
                %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (policy_id, item_number) DO UPDATE SET
                nombre_completo = EXCLUDED.nombre_completo,
                documento_identidad = EXCLUDED.documento_identidad,
                fecha_nacimiento = EXCLUDED.fecha_nacimiento,
                edad = EXCLUDED.edad,
                genero = EXCLUDED.genero,
                parentesco_categoria = EXCLUDED.parentesco_categoria,
                cargo_ocupacion = EXCLUDED.cargo_ocupacion,
                suma_asegurada_usd = EXCLUDED.suma_asegurada_usd,
                prima_usd = EXCLUDED.prima_usd,
                raw_metadata = EXCLUDED.raw_metadata,
                updated_at = CURRENT_TIMESTAMP;
        """

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(delete_sql, (policy_id,))
                for p in persons:
                    cur.execute(
                        insert_sql,
                        (
                            policy_id,
                            envelope_id,
                            p.get("item_number", 1),
                            p.get("nombre_completo", "ASEGURADO NOMINADO"),
                            p.get("documento_identidad"),
                            p.get("fecha_nacimiento"),
                            p.get("edad"),
                            p.get("genero"),
                            p.get("parentesco_categoria", "TITULAR"),
                            p.get("cargo_ocupacion"),
                            p.get("suma_asegurada_usd", 0.0),
                            p.get("prima_usd", 0.0),
                            json.dumps(p.get("raw_metadata", {}), ensure_ascii=False),
                        ),
                    )
            conn.commit()

        logger.info(
            "Personas aseguradas guardadas en base de datos",
            policy_id=policy_id,
            envelope_id=envelope_id,
            persons_count=len(persons),
        )
        return len(persons)

    def get_persons_for_policy(
        self,
        policy_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Recupera la lista de asegurados de una póliza específica."""
        query = """
            SELECT 
                id::text, policy_id::text, envelope_id::text, item_number,
                nombre_completo, documento_identidad, fecha_nacimiento, edad,
                genero, parentesco_categoria, cargo_ocupacion, suma_asegurada_usd,
                prima_usd, raw_metadata, created_at, updated_at
            FROM policy_insured_persons
            WHERE policy_id = %s::uuid
            ORDER BY item_number ASC
        """
        params: list[Any] = [policy_id]
        if limit is not None:
            query += " LIMIT %s OFFSET %s;"
            params.extend([limit, offset])
        else:
            query += ";"

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                cols = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                return [dict(zip(cols, row)) for row in rows]

    def get_persons_for_envelope(
        self,
        envelope_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Recupera los asegurados agrupados bajo un sobre de póliza."""
        query = """
            SELECT 
                id::text, policy_id::text, envelope_id::text, item_number,
                nombre_completo, documento_identidad, fecha_nacimiento, edad,
                genero, parentesco_categoria, cargo_ocupacion, suma_asegurada_usd,
                prima_usd, raw_metadata, created_at, updated_at
            FROM policy_insured_persons
            WHERE envelope_id = %s::uuid
            ORDER BY item_number ASC
        """
        params: list[Any] = [envelope_id]
        if limit is not None:
            query += " LIMIT %s OFFSET %s;"
            params.extend([limit, offset])
        else:
            query += ";"

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                cols = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                return [dict(zip(cols, row)) for row in rows]

    def search_persons(
        self,
        query_text: str,
        policy_id: str | None = None,
        envelope_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Busca asegurados por nombre o documento de identidad."""
        search_pattern = f"%{query_text.strip()}%"
        where_clauses = [
            "(nombre_completo ILIKE %s OR documento_identidad ILIKE %s OR cargo_ocupacion ILIKE %s)"
        ]
        params: list[Any] = [search_pattern, search_pattern, search_pattern]

        if policy_id:
            where_clauses.append("policy_id = %s::uuid")
            params.append(policy_id)
        elif envelope_id:
            where_clauses.append("envelope_id = %s::uuid")
            params.append(envelope_id)

        sql = f"""
            SELECT 
                id::text, policy_id::text, envelope_id::text, item_number,
                nombre_completo, documento_identidad, fecha_nacimiento, edad,
                genero, parentesco_categoria, cargo_ocupacion, suma_asegurada_usd,
                prima_usd, raw_metadata
            FROM policy_insured_persons
            WHERE {" AND ".join(where_clauses)}
            ORDER BY item_number ASC
            LIMIT %s;
        """
        params.append(limit)

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                cols = [desc[0] for desc in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

    def count_persons(
        self,
        policy_id: str | None = None,
        envelope_id: str | None = None,
    ) -> int:
        """Cuenta el total de asegurados en una póliza o sobre."""
        if policy_id:
            sql = "SELECT COUNT(*) FROM policy_insured_persons WHERE policy_id = %s::uuid;"
            params = (policy_id,)
        elif envelope_id:
            sql = "SELECT COUNT(*) FROM policy_insured_persons WHERE envelope_id = %s::uuid;"
            params = (envelope_id,)
        else:
            return 0

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return int(row[0]) if row else 0

    def get_insured_summary(
        self,
        policy_id: str | None = None,
        envelope_id: str | None = None,
        sample_limit: int | None = 20,
    ) -> dict[str, Any] | None:
        """Calcula el resumen agregado de la nómina de asegurados colectivos."""
        if policy_id:
            where_clause = "WHERE policy_id = %s::uuid"
            param = policy_id
        elif envelope_id:
            where_clause = "WHERE envelope_id = %s::uuid"
            param = envelope_id
        else:
            return None

        summary_sql = f"""
            SELECT 
                COUNT(*) AS total_asegurados,
                COALESCE(SUM(suma_asegurada_usd), 0.0) AS total_suma_asegurada_usd,
                COALESCE(SUM(prima_usd), 0.0) AS total_prima_usd,
                COALESCE(AVG(edad), 0.0) AS edad_promedio
            FROM policy_insured_persons
            {where_clause};
        """

        distrib_categoria_sql = f"""
            SELECT COALESCE(parentesco_categoria, 'TITULAR') AS cat, COUNT(*) AS cnt
            FROM policy_insured_persons
            {where_clause}
            GROUP BY COALESCE(parentesco_categoria, 'TITULAR')
            ORDER BY cnt DESC;
        """

        distrib_genero_sql = f"""
            SELECT COALESCE(genero, 'NO ESPECIFICADO') AS gen, COUNT(*) AS cnt
            FROM policy_insured_persons
            {where_clause}
            GROUP BY COALESCE(genero, 'NO ESPECIFICADO')
            ORDER BY cnt DESC;
        """

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(summary_sql, (param,))
                row = cur.fetchone()
                if not row or row[0] == 0:
                    return None

                total = int(row[0])
                val_total = float(row[1])
                prima_total = float(row[2])
                edad_prom = float(row[3])

                # Distribución por categoría / parentesco
                cur.execute(distrib_categoria_sql, (param,))
                distrib_cat = {r[0]: int(r[1]) for r in cur.fetchall()}

                # Distribución por género
                cur.execute(distrib_genero_sql, (param,))
                distrib_gen = {r[0]: int(r[1]) for r in cur.fetchall()}

        # Obtener muestra o lista completa
        sample_size = sample_limit if (sample_limit is not None and sample_limit < total) else total
        if policy_id:
            muestra = self.get_persons_for_policy(policy_id, limit=sample_size)
        else:
            muestra = self.get_persons_for_envelope(envelope_id, limit=sample_size)  # type: ignore

        return {
            "total_asegurados": total,
            "total_suma_asegurada_usd": val_total,
            "total_prima_usd": prima_total,
            "edad_promedio": round(edad_prom, 1) if edad_prom > 0 else None,
            "distribucion_categoria": distrib_cat,
            "distribucion_genero": distrib_gen,
            "muestra": muestra,
        }

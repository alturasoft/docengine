"""DocEngine — Infrastructure: PostgreSQL Policy Fleet Vehicles Repository.

[ADITIVO] Gestiona la persistencia, consulta y agregación estadística de nóminas
de vehículos de flotas aseguradas en PostgreSQL.
"""

from __future__ import annotations

import json
from typing import Any

from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class PgFleetRepository:
    """Repositorio para la gestión de vehículos de flota asegurados."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db = db_manager

    def save_vehicles(
        self,
        policy_id: str,
        envelope_id: str | None,
        vehicles: list[dict[str, Any]],
    ) -> int:
        """Guarda o actualiza atómicamente la lista de vehículos de una póliza."""
        if not vehicles:
            return 0

        delete_sql = "DELETE FROM policy_fleet_vehicles WHERE policy_id = %s::uuid;"
        insert_sql = """
            INSERT INTO policy_fleet_vehicles (
                policy_id, envelope_id, item_number, tipo_vehiculo,
                marca, modelo, anio, placa, chasis, motor, color,
                uso, plaza, valor_asegurado_usd, prima_usd, raw_metadata, updated_at
            ) VALUES (
                %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP
            )
            ON CONFLICT (policy_id, item_number) DO UPDATE SET
                tipo_vehiculo = EXCLUDED.tipo_vehiculo,
                marca = EXCLUDED.marca,
                modelo = EXCLUDED.modelo,
                anio = EXCLUDED.anio,
                placa = EXCLUDED.placa,
                chasis = EXCLUDED.chasis,
                motor = EXCLUDED.motor,
                color = EXCLUDED.color,
                uso = EXCLUDED.uso,
                plaza = EXCLUDED.plaza,
                valor_asegurado_usd = EXCLUDED.valor_asegurado_usd,
                prima_usd = EXCLUDED.prima_usd,
                raw_metadata = EXCLUDED.raw_metadata,
                updated_at = CURRENT_TIMESTAMP;
        """

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(delete_sql, (policy_id,))
                for v in vehicles:
                    cur.execute(
                        insert_sql,
                        (
                            policy_id,
                            envelope_id,
                            v.get("item_number", 1),
                            v.get("tipo_vehiculo"),
                            v.get("marca"),
                            v.get("modelo"),
                            v.get("anio"),
                            v.get("placa"),
                            v.get("chasis"),
                            v.get("motor"),
                            v.get("color"),
                            v.get("uso"),
                            v.get("plaza"),
                            v.get("valor_asegurado_usd", 0.0),
                            v.get("prima_usd", 0.0),
                            json.dumps(v.get("raw_metadata", {}), ensure_ascii=False),
                        ),
                    )
            conn.commit()

        logger.info(
            "Vehículos de flota guardados en base de datos",
            policy_id=policy_id,
            envelope_id=envelope_id,
            vehicles_count=len(vehicles),
        )
        return len(vehicles)

    def get_vehicles_for_policy(
        self,
        policy_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Recupera la nómina de vehículos de una póliza ordenada por ítem."""
        sql = """
            SELECT id, policy_id::text, envelope_id::text, item_number,
                   tipo_vehiculo, marca, modelo, anio, placa, chasis,
                   motor, color, uso, plaza, valor_asegurado_usd, prima_usd, raw_metadata
            FROM policy_fleet_vehicles
            WHERE policy_id = %s::uuid
            ORDER BY item_number ASC
        """
        params: list[Any] = [policy_id]
        if limit is not None:
            sql += " LIMIT %s OFFSET %s"
            params.extend([limit, offset])

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()

        return [self._row_to_dict(r) for r in rows]

    def get_vehicles_for_envelope(
        self,
        envelope_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Recupera todos los vehículos asociados a un sobre de póliza."""
        sql = """
            SELECT id, policy_id::text, envelope_id::text, item_number,
                   tipo_vehiculo, marca, modelo, anio, placa, chasis,
                   motor, color, uso, plaza, valor_asegurado_usd, prima_usd, raw_metadata
            FROM policy_fleet_vehicles
            WHERE envelope_id = %s::uuid
            ORDER BY item_number ASC
        """
        params: list[Any] = [envelope_id]
        if limit is not None:
            sql += " LIMIT %s OFFSET %s"
            params.extend([limit, offset])

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()

        return [self._row_to_dict(r) for r in rows]

    def count_vehicles(self, policy_id: str | None = None, envelope_id: str | None = None) -> int:
        """Retorna la cantidad total de vehículos registrados."""
        if envelope_id:
            sql = "SELECT COUNT(*) FROM policy_fleet_vehicles WHERE envelope_id = %s::uuid;"
            arg = envelope_id
        elif policy_id:
            sql = "SELECT COUNT(*) FROM policy_fleet_vehicles WHERE policy_id = %s::uuid;"
            arg = policy_id
        else:
            return 0

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (arg,))
                row = cur.fetchone()
                return row[0] if row else 0

    def search_vehicles(
        self,
        policy_id: str | None = None,
        envelope_id: str | None = None,
        query: str | None = None,
        tipo: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Busca y pagina vehículos con filtros opcionales de tipo o texto."""
        conditions: list[str] = []
        params: list[Any] = []

        if envelope_id:
            conditions.append("envelope_id = %s::uuid")
            params.append(envelope_id)
        elif policy_id:
            conditions.append("policy_id = %s::uuid")
            params.append(policy_id)
        else:
            return [], 0

        if tipo:
            conditions.append("tipo_vehiculo ILIKE %s")
            params.append(f"%{tipo.strip()}%")

        if query:
            q_clean = query.strip()
            conditions.append(
                "(placa ILIKE %s OR chasis ILIKE %s OR modelo ILIKE %s OR motor ILIKE %s OR marca ILIKE %s)"
            )
            params.extend([f"%{q_clean}%"] * 5)

        where_clause = " WHERE " + " AND ".join(conditions)

        count_sql = f"SELECT COUNT(*) FROM policy_fleet_vehicles{where_clause};"
        data_sql = f"""
            SELECT id, policy_id::text, envelope_id::text, item_number,
                   tipo_vehiculo, marca, modelo, anio, placa, chasis,
                   motor, color, uso, plaza, valor_asegurado_usd, prima_usd, raw_metadata
            FROM policy_fleet_vehicles
            {where_clause}
            ORDER BY item_number ASC
            LIMIT %s OFFSET %s;
        """

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(count_sql, tuple(params))
                total = cur.fetchone()[0]

                data_params = list(params) + [limit, offset]
                cur.execute(data_sql, tuple(data_params))
                rows = cur.fetchall()

        vehicles = [self._row_to_dict(r) for r in rows]
        return vehicles, total

    def get_fleet_summary(
        self,
        policy_id: str | None = None,
        envelope_id: str | None = None,
        sample_limit: int | None = None,
    ) -> dict[str, Any]:
        """Calcula el resumen estadístico y de distribución de la flota asegurada."""
        cond = "envelope_id = %s::uuid" if envelope_id else "policy_id = %s::uuid"
        arg = envelope_id if envelope_id else policy_id
        if not arg:
            return {}

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                # 1. Totales
                cur.execute(
                    f"""
                    SELECT COUNT(*),
                           COALESCE(SUM(valor_asegurado_usd), 0),
                           COALESCE(SUM(prima_usd), 0)
                    FROM policy_fleet_vehicles
                    WHERE {cond};
                    """,
                    (arg,),
                )
                total_cnt, total_val, total_prima = cur.fetchone() or (0, 0, 0)
                if total_cnt == 0:
                    return {}

                # 2. Distribución por tipo de vehículo
                cur.execute(
                    f"""
                    SELECT COALESCE(tipo_vehiculo, 'OTROS'), COUNT(*)
                    FROM policy_fleet_vehicles
                    WHERE {cond}
                    GROUP BY 1 ORDER BY 2 DESC;
                    """,
                    (arg,),
                )
                por_tipo = {r[0]: r[1] for r in cur.fetchall()}

                # 3. Distribución por marca
                cur.execute(
                    f"""
                    SELECT COALESCE(marca, 'OTROS'), COUNT(*)
                    FROM policy_fleet_vehicles
                    WHERE {cond}
                    GROUP BY 1 ORDER BY 2 DESC;
                    """,
                    (arg,),
                )
                por_marca = {r[0]: r[1] for r in cur.fetchall()}

                # 4. Muestra o lista completa de vehículos
                if sample_limit is not None:
                    limit_sql = f"LIMIT {int(sample_limit)}"
                else:
                    limit_sql = ""

                cur.execute(
                    f"""
                    SELECT id, policy_id::text, envelope_id::text, item_number,
                           tipo_vehiculo, marca, modelo, anio, placa, chasis,
                           motor, color, uso, plaza, valor_asegurado_usd, prima_usd, raw_metadata
                    FROM policy_fleet_vehicles
                    WHERE {cond}
                    ORDER BY item_number ASC
                    {limit_sql};
                    """,
                    (arg,),
                )
                sample = [self._row_to_dict(r) for r in cur.fetchall()]

        return {
            "total_vehiculos": total_cnt,
            "total_valor_asegurado_usd": float(total_val),
            "total_prima_usd": float(total_prima),
            "distribucion_tipo": por_tipo,
            "distribucion_marca": por_marca,
            "muestra": sample,
        }

    @staticmethod
    def _row_to_dict(row: tuple) -> dict[str, Any]:
        return {
            "id": str(row[0]),
            "policy_id": row[1],
            "envelope_id": row[2],
            "item_number": row[3],
            "tipo_vehiculo": row[4],
            "marca": row[5],
            "modelo": row[6],
            "anio": row[7],
            "placa": row[8],
            "chasis": row[9],
            "motor": row[10],
            "color": row[11],
            "uso": row[12],
            "plaza": row[13],
            "valor_asegurado_usd": float(row[14]) if row[14] is not None else 0.0,
            "prima_usd": float(row[15]) if row[15] is not None else 0.0,
            "raw_metadata": row[16] if isinstance(row[16], dict) else {},
        }

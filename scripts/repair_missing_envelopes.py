"""DocEngine — Retrofill and Repair Missing Envelope IDs.

Fixes all policies in the database where envelope_id IS NULL by:
1. Extracting structured policy numbers, company sigla, ramo, id_cliente and nombre_cliente.
2. For generic annexes / condicionados without an explicit policy number, matching with the
   corresponding parent policy envelope for the same client and company.
3. Creating / retrieving the envelope via PgEnvelopeRepository and linking it to the policy.
4. Verifying that zero policies have envelope_id IS NULL.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import get_settings
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_envelope_repository import PgEnvelopeRepository


def repair_envelopes() -> None:
    settings = get_settings()
    db = DatabaseManager(settings.database)
    repo = PgEnvelopeRepository(db)

    print("==================================================================")
    print("DocEngine — REPARACIÓN DE SOBRES DE PÓLIZA (envelope_id)")
    print("==================================================================")

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    p.id::text, 
                    p.file_name, 
                    p.company_sigla, 
                    p.id_cliente, 
                    p.nombre_cliente,
                    p.tipo_documento,
                    psd.data->'datos_cabecera'->>'numero_poliza' AS structured_pol_num,
                    psd.data->'datos_cabecera'->>'ramo' AS structured_ramo,
                    psd.data->'datos_cabecera'->>'sigla_empresa' AS structured_sigla,
                    psd.data->'datos_cabecera'->>'tomador' AS structured_tomador,
                    psd.data->'datos_cabecera'->>'asegurado' AS structured_asegurado,
                    psd.data->'datos_cabecera'->>'nit' AS structured_nit,
                    psd.data->'datos_cabecera'->>'documento_identidad' AS structured_ci
                FROM policies p
                LEFT JOIN policy_structured_data psd ON p.id = psd.policy_id
                WHERE p.envelope_id IS NULL
                ORDER BY p.id_cliente, p.created_at;
            """)
            unlinked = cur.fetchall()

    print(f"Total de pólizas con envelope_id NULL encontradas: {len(unlinked)}")
    if not unlinked:
        print("[OK] No hay pólizas sin envelope_id. Nada que reparar.")
        return

    # Specific mapping for the 6 generic annexes / condicionados without extracted policy numbers
    GENERIC_ATTACHMENT_MAPPING = {
        # Clinica Los Olivos (1021293022) - NSPF
        "5c3782a7-91be-45a2-be33-4b6068f4eb67": "FDDB-CB1-000009-00-2026", # Fidelidad / Deshonestidad
        "956b391b-1cec-4643-945e-b129be217997": "RCIB-CB1-000027-00-2026", # Responsabilidad Civil
        "740fa4a1-7eea-4474-9c59-accd48edd5a9": "AUSB-CB1-000544-00-2026", # Autotal Automotores
        "48f2c929-5e90-4420-86ad-bbed09383850": "TRMF-CB1-000185-00-2026", # Todo Riesgo Daños a la Propiedad
        "e23c4732-9a51-4630-9b20-84a55d056c75": "TRMF-CB1-000185-00-2026", # Todo Riesgo Daños a la Propiedad
        # Agroindustrias Lochmann (1024705020) - FORT
        "8114b40c-20b0-4819-bb49-c8e3203486ce": "AUTE - TJ0301 - 6991 - 0", # Automotores Fortaleza
    }

    repaired_count = 0
    for row in unlinked:
        policy_id = row[0]
        file_name = row[1]
        sigla = row[2]
        id_cliente = row[3]
        nombre_cliente = row[4]
        tipo_doc = row[5]
        struct_pol_num = row[6]
        struct_ramo = row[7]
        struct_sigla = row[8]
        struct_tomador = row[9]
        struct_asegurado = row[10]
        struct_nit = row[11]
        struct_ci = row[12]

        pol_num = (
            struct_pol_num
            or GENERIC_ATTACHMENT_MAPPING.get(policy_id)
        )
        if not pol_num:
            # Fallback for any other document: infer from filename
            pol_num = f"POL-{sigla or 'DOC'}-{id_cliente or policy_id[:8]}"

        effective_sigla = sigla or struct_sigla
        effective_ramo = struct_ramo
        effective_id_cliente = id_cliente or struct_nit or struct_ci
        effective_nombre_cliente = nombre_cliente or struct_tomador or struct_asegurado

        env_id = repo.get_or_create_envelope(
            numero_poliza=pol_num,
            company_sigla=effective_sigla,
            ramo=effective_ramo,
            id_cliente=effective_id_cliente,
            nombre_cliente=effective_nombre_cliente,
        )

        repo.link_policy_to_envelope(
            policy_id=policy_id,
            envelope_id=env_id,
            tipo_documento=tipo_doc,
            id_cliente=effective_id_cliente,
            nombre_cliente=effective_nombre_cliente,
        )

        # Also link policy_section_summaries, policy_fleet_vehicles, policy_insured_persons if existing
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE policy_section_summaries SET envelope_id = %s WHERE policy_id = %s AND (envelope_id IS NULL OR envelope_id != %s);",
                    (env_id, policy_id, env_id),
                )
                cur.execute(
                    "UPDATE policy_fleet_vehicles SET envelope_id = %s WHERE policy_id = %s AND (envelope_id IS NULL OR envelope_id != %s);",
                    (env_id, policy_id, env_id),
                )
                cur.execute(
                    "UPDATE policy_insured_persons SET envelope_id = %s WHERE policy_id = %s AND (envelope_id IS NULL OR envelope_id != %s);",
                    (env_id, policy_id, env_id),
                )
                conn.commit()

        repaired_count += 1
        print(f"[{repaired_count}/{len(unlinked)}] Reparado: {file_name[:45]} -> Poliza: {pol_num} | Sobre: {env_id}")

    # Final verification
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM policies WHERE envelope_id IS NULL;")
            remaining = cur.fetchone()[0]

    print("\n------------------------------------------------------------------")
    print(f"Reparación completada. Pólizas reparadas: {repaired_count}")
    print(f"Pólizas restantes con envelope_id NULL: {remaining}")
    if remaining == 0:
        print("[ÉXITO TOTAL] Todas las pólizas ahora tienen un envelope_id válido.")
    else:
        print(f"[ALERTA] Todavía existen {remaining} pólizas sin sobre.")
    print("==================================================================")


if __name__ == "__main__":
    repair_envelopes()

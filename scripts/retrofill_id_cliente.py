"""DocEngine — Retrofill id_cliente into policy_envelopes and policies.

Executes a staged retrofitting process:
1. Direct extraction from structured JSON cabecera (documento_identidad or nit).
2. Cross-matching by exact normalized Asegurado with already identified envelopes.
3. Regex extraction from raw Markdown, filtering out insurer corporate NITs.
4. Propagation of id_cliente from policy_envelopes to policies table.
5. Generates a CSV audit report for any remaining envelopes without id_cliente.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
import re
import psycopg2
from dotenv import load_dotenv

# Known corporate NITs of Bolivian insurance companies to prevent false attribution
INSURER_NITS_BLACKLIST = {
    "1020655027",  # BISA Seguros y Reaseguros S.A.
    "1020353028",  # Alianza Cía de Seguros y Reaseguros S.A.
    "1020613024",  # Credinform International S.A.
    "1016253021",  # La Boliviana Ciacruz de Seguros y Reaseguros S.A.
    "1020473026",  # Fortaleza de Seguros y Reaseguros S.A.
    "1015383020",  # Nacional Seguros Patrimoniales y Fianzas S.A.
    "1028525026",  # Unibienes Seguros Patrimoniales S.A.
    "1028723027",  # Latina Seguros Patrimoniales S.A.
}


def sanitize_id(raw_val: str | None) -> str | None:
    """Clean and validate an identity document or NIT string."""
    if not raw_val:
        return None
    val = raw_val.strip()
    if val.lower() in ("null", "none", "s/n", "sn", "n/a", "na", "-", "."):
        return None
    # Must contain at least 4 digits
    digits = re.sub(r"\D", "", val)
    if len(digits) < 4:
        return None
    # Check if blacklisted insurer NIT
    if digits in INSURER_NITS_BLACKLIST:
        return None
    # Return cleaned string (max 50 chars)
    return val[:50]


def run_retrofill() -> None:
    load_dotenv()
    conn = psycopg2.connect(
        host=os.getenv("DOCENGINE_DB_HOST", "localhost"),
        port=os.getenv("DOCENGINE_DB_PORT", 5432),
        dbname=os.getenv("DOCENGINE_DB_NAME", "docengine"),
        user=os.getenv("DOCENGINE_DB_USER", "postgres"),
        password=os.getenv("DOCENGINE_DB_PASSWORD", "postgres"),
    )
    cur = conn.cursor()

    print("==================================================")
    print("DOCENGINE — RETROLLENADO DE id_cliente")
    print("==================================================")

    # Total envelopes
    cur.execute("SELECT COUNT(*) FROM policy_envelopes;")
    total_envelopes = cur.fetchone()[0]
    print(f"Total de sobres (policy_envelopes): {total_envelopes}")

    # -------------------------------------------------------------------------
    # PASO 1: Extracción directa desde policy_structured_data
    # -------------------------------------------------------------------------
    print("\n[Paso 1] Extrayendo desde datos_cabecera (NIT / CI)...")
    cur.execute("""
        SELECT 
            p.envelope_id,
            psd.data->'datos_cabecera'->>'documento_identidad' AS doc_id,
            psd.data->'datos_cabecera'->>'nit' AS nit_val
        FROM policies p
        JOIN policy_structured_data psd ON p.id = psd.policy_id
        WHERE p.envelope_id IS NOT NULL;
    """)
    rows = cur.fetchall()

    envelope_candidates: dict[str, set[str]] = {}
    for env_id, doc_id, nit_val in rows:
        clean_ci = sanitize_id(doc_id)
        clean_nit = sanitize_id(nit_val)
        if env_id not in envelope_candidates:
            envelope_candidates[env_id] = set()
        if clean_nit:
            envelope_candidates[env_id].add(clean_nit)
        elif clean_ci:
            envelope_candidates[env_id].add(clean_ci)

    paso1_updated = 0
    for env_id, candidates in envelope_candidates.items():
        if candidates:
            # Pick the most specific (prefer NIT or longest representation)
            chosen_id = sorted(candidates, key=lambda x: (len(re.sub(r"\D", "", x)), len(x)), reverse=True)[0]
            cur.execute("""
                UPDATE policy_envelopes
                SET id_cliente = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND id_cliente IS NULL;
            """, (chosen_id, env_id))
            if cur.rowcount > 0:
                paso1_updated += 1

    conn.commit()
    print(f" -> Sobres actualizados en Paso 1: {paso1_updated}")

    # -------------------------------------------------------------------------
    # PASO 2: Cruce por Nombre / Razón Social de Asegurado en la misma base
    # -------------------------------------------------------------------------
    print("\n[Paso 2] Cruzando clientes recurrentes por nombre de Asegurado...")
    cur.execute("""
        SELECT 
            UPPER(TRIM(psd.data->'datos_cabecera'->>'asegurado')) AS asegurado,
            pe.id_cliente
        FROM policy_envelopes pe
        JOIN policies p ON p.envelope_id = pe.id
        JOIN policy_structured_data psd ON p.id = psd.policy_id
        WHERE pe.id_cliente IS NOT NULL
          AND psd.data->'datos_cabecera'->>'asegurado' IS NOT NULL
        GROUP BY UPPER(TRIM(psd.data->'datos_cabecera'->>'asegurado')), pe.id_cliente;
    """)
    known_clients = cur.fetchall()
    client_name_map: dict[str, str] = {}
    for name, id_c in known_clients:
        if name and len(name) > 4:
            client_name_map[name] = id_c

    # Find envelopes still without id_cliente
    cur.execute("""
        SELECT 
            pe.id,
            UPPER(TRIM(psd.data->'datos_cabecera'->>'asegurado')) AS asegurado
        FROM policy_envelopes pe
        JOIN policies p ON p.envelope_id = pe.id
        JOIN policy_structured_data psd ON p.id = psd.policy_id
        WHERE pe.id_cliente IS NULL
          AND psd.data->'datos_cabecera'->>'asegurado' IS NOT NULL;
    """)
    unknown_envelopes = cur.fetchall()
    paso2_updated = 0
    for env_id, name in unknown_envelopes:
        if name in client_name_map:
            assigned_id = client_name_map[name]
            cur.execute("""
                UPDATE policy_envelopes
                SET id_cliente = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND id_cliente IS NULL;
            """, (assigned_id, env_id))
            if cur.rowcount > 0:
                paso2_updated += 1

    conn.commit()
    print(f" -> Sobres actualizados en Paso 2: {paso2_updated}")

    # -------------------------------------------------------------------------
    # PASO 3: Rescate por Regex en policy_raw_md (Markdown crudo)
    # -------------------------------------------------------------------------
    print("\n[Paso 3] Escaneando texto crudo (Markdown) para sobres restantes...")
    cur.execute("""
        SELECT pe.id, prm.markdown_content
        FROM policy_envelopes pe
        JOIN policies p ON p.envelope_id = pe.id
        JOIN policy_raw_md prm ON p.id = prm.policy_id
        WHERE pe.id_cliente IS NULL;
    """)
    raw_pending = cur.fetchall()

    ci_pat = re.compile(
        r"(?:C\.?I\.?|CARNET|DOCUMENTO(?:\s+DE)?\s+IDENTIDAD|CEDULA)[\s\:\.\#-]*([0-9]{5,9}(?:\s*-[0-9A-Z]{1,3}|\s+[A-Z]{2,4})?)",
        re.IGNORECASE,
    )
    nit_pat = re.compile(r"\bNIT[\s\:\.\#-]*([0-9]{7,13})\b", re.IGNORECASE)

    paso3_updated = 0
    for env_id, md in raw_pending:
        if not md:
            continue
        nits = nit_pat.findall(md)
        valid_nits = [sanitize_id(n) for n in nits if sanitize_id(n)]
        cis = ci_pat.findall(md)
        valid_cis = [sanitize_id(c) for c in cis if sanitize_id(c)]

        chosen = None
        if valid_nits:
            chosen = valid_nits[0]
        elif valid_cis:
            chosen = valid_cis[0]

        if chosen:
            cur.execute("""
                UPDATE policy_envelopes
                SET id_cliente = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND id_cliente IS NULL;
            """, (chosen, env_id))
            if cur.rowcount > 0:
                paso3_updated += 1

    conn.commit()
    print(f" -> Sobres actualizados en Paso 3: {paso3_updated}")

    # -------------------------------------------------------------------------
    # PASO 4: Propagación hacia policies.id_cliente
    # -------------------------------------------------------------------------
    print("\n[Paso 4] Propagando id_cliente a la tabla policies...")
    cur.execute("""
        UPDATE policies p
        SET id_cliente = pe.id_cliente
        FROM policy_envelopes pe
        WHERE p.envelope_id = pe.id
          AND pe.id_cliente IS NOT NULL
          AND p.id_cliente IS NULL;
    """)
    docs_updated = cur.rowcount
    conn.commit()
    print(f" -> Documentos (policies) actualizados con id_cliente: {docs_updated}")

    # -------------------------------------------------------------------------
    # RESUMEN Y REPORTE DE EXCEPCIONES
    # -------------------------------------------------------------------------
    cur.execute("SELECT COUNT(*) FROM policy_envelopes WHERE id_cliente IS NOT NULL;")
    total_con_id = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM policy_envelopes WHERE id_cliente IS NULL;")
    total_sin_id = cur.fetchone()[0]

    pct = (total_con_id / total_envelopes) * 100 if total_envelopes else 0.0
    print("\n==================================================")
    print(f"RESULTADO FINAL:")
    print(f" - Sobres CON id_cliente: {total_con_id} ({pct:.1f}%)")
    print(f" - Sobres pendientes (sin dato en PDF): {total_sin_id}")
    print("==================================================")

    # Export exceptions CSV
    if total_sin_id > 0:
        out_dir = Path("outputs")
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / "polizas_pendientes_id_cliente.csv"

        cur.execute("""
            SELECT 
                pe.id AS envelope_id,
                pe.numero_poliza,
                pe.company_sigla,
                pe.ramo,
                COALESCE(psd.data->'datos_cabecera'->>'asegurado', 'DESCONOCIDO') AS asegurado
            FROM policy_envelopes pe
            LEFT JOIN policies p ON p.envelope_id = pe.id
            LEFT JOIN policy_structured_data psd ON p.id = psd.policy_id
            WHERE pe.id_cliente IS NULL
            GROUP BY pe.id, pe.numero_poliza, pe.company_sigla, pe.ramo, psd.data->'datos_cabecera'->>'asegurado';
        """)
        pending_rows = cur.fetchall()

        with open(csv_path, mode="w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["envelope_id", "numero_poliza", "company_sigla", "ramo", "asegurado", "id_cliente_a_asignar"])
            for r in pending_rows:
                writer.writerow([r[0], r[1], r[2], r[3], r[4], ""])

        print(f"\nReporte de excepciones exportado a: {csv_path.resolve()}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    run_retrofill()

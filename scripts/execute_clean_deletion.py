"""DocEngine — Clean Policy Deletion Script.

Safely and cleanly removes specified policies and all associated records across:
- PostgreSQL tables (policy_envelopes, policies, policy_chunks, policy_raw_md,
  policy_structured_data, policy_processing_stats, processing_jobs, policy_section_summaries,
  policy_fleet_vehicles, policy_insured_persons)
- SQLite batch checkpoint tracker (.batch_checkpoint.sqlite)
- Local filesystem output artifacts (outputs/ directory: markdown and json folders)

Ensures that re-ingestion will be completely pristine without conflicts or skips.
"""

import os
import sys
import shutil
import sqlite3
import psycopg2
from pathlib import Path

TARGET_POLICIES = [
    "DES-SC0101-282",
    "BDH-LP0201-58-5",
    "MUA-LP0201-3910-5",
    "RCD-LP0201-145-5",
    "ACCI-LP0201-2884-5",
    "AUTE-LP0201-3034-3",
    "SE3A-LP2-500038-02-2026",
    "SE3A-LP2-500037-02-2026",
    "AUTE - TJ0301 - 6991 - 0",
    "100520",
    "27239",
    "27111",
    "27325",
    "61825"
]

def execute_deletion():
    print("===================================================================")
    print("DocEngine — INICIANDO ELIMINACIÓN LIMPIA DE PÓLIZAS")
    print("===================================================================")

    conn = psycopg2.connect(
        host=os.getenv("DOCENGINE_DB_HOST", "localhost"),
        port=int(os.getenv("DOCENGINE_DB_PORT", "5432")),
        dbname=os.getenv("DOCENGINE_DB_NAME", "docengine"),
        user=os.getenv("DOCENGINE_DB_USER", "postgres"),
        password=os.getenv("DOCENGINE_DB_PASSWORD", "postgres")
    )
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # 1. Identificar policy_envelopes
        clean_targets = [p.replace(" ", "") for p in TARGET_POLICIES]
        cur.execute("""
            SELECT id, numero_poliza, company_sigla, ramo, id_cliente, nombre_cliente
            FROM policy_envelopes
            WHERE numero_poliza = ANY(%s)
               OR REPLACE(numero_poliza, ' ', '') = ANY(%s)
        """, (TARGET_POLICIES, clean_targets))
        envelopes = cur.fetchall()
        envelope_ids = [e[0] for e in envelopes]

        print(f"1. Sobres de póliza identificados: {len(envelopes)}")
        for e in envelopes:
            print(f"   - Sobre: {e[1]} | Aseguradora: {e[2]} | UUID: {e[0]}")

        # 2. Identificar policies (documentos)
        cur.execute("""
            SELECT p.id, p.file_name, p.file_hash, p.company_sigla, p.tipo_documento, pe.numero_poliza
            FROM policies p
            JOIN policy_envelopes pe ON p.envelope_id = pe.id
            WHERE pe.id = ANY(%s::uuid[])
        """, (envelope_ids,))
        policy_docs = cur.fetchall()
        policy_ids = [p[0] for p in policy_docs]
        file_hashes = [p[2] for p in policy_docs if p[2]]
        file_names = [p[1] for p in policy_docs if p[1]]

        print(f"\n2. Documentos asociados identificados: {len(policy_docs)}")
        for p in policy_docs:
            print(f"   - Documento: {p[1]} (Tipo: {p[4]}, Póliza: {p[5]})")

        # 3. Eliminar de tablas hijas en PostgreSQL
        print("\n3. Eliminando registros en PostgreSQL...")

        # processing_jobs
        cur.execute("""
            DELETE FROM processing_jobs 
            WHERE policy_id = ANY(%s::uuid[]) 
               OR file_name = ANY(%s)
        """, (policy_ids, file_names))
        deleted_jobs = cur.rowcount
        print(f"   - processing_jobs eliminados: {deleted_jobs}")

        # policy_section_summaries
        cur.execute("""
            DELETE FROM policy_section_summaries 
            WHERE policy_id = ANY(%s::uuid[]) 
               OR envelope_id = ANY(%s::uuid[])
        """, (policy_ids, envelope_ids))
        deleted_summaries = cur.rowcount
        print(f"   - policy_section_summaries eliminados: {deleted_summaries}")

        # policy_fleet_vehicles
        cur.execute("""
            DELETE FROM policy_fleet_vehicles 
            WHERE policy_id = ANY(%s::uuid[]) 
               OR envelope_id = ANY(%s::uuid[])
        """, (policy_ids, envelope_ids))
        deleted_vehicles = cur.rowcount
        print(f"   - policy_fleet_vehicles eliminados: {deleted_vehicles}")

        # policy_insured_persons
        cur.execute("""
            DELETE FROM policy_insured_persons 
            WHERE policy_id = ANY(%s::uuid[]) 
               OR envelope_id = ANY(%s::uuid[])
        """, (policy_ids, envelope_ids))
        deleted_persons = cur.rowcount
        print(f"   - policy_insured_persons eliminados: {deleted_persons}")

        # policy_chunks
        cur.execute("DELETE FROM policy_chunks WHERE policy_id = ANY(%s::uuid[])", (policy_ids,))
        deleted_chunks = cur.rowcount
        print(f"   - policy_chunks (vectores/embeddings) eliminados: {deleted_chunks}")

        # policy_raw_md
        cur.execute("DELETE FROM policy_raw_md WHERE policy_id = ANY(%s::uuid[])", (policy_ids,))
        deleted_raw_md = cur.rowcount
        print(f"   - policy_raw_md eliminados: {deleted_raw_md}")

        # policy_structured_data
        cur.execute("DELETE FROM policy_structured_data WHERE policy_id = ANY(%s::uuid[])", (policy_ids,))
        deleted_structured = cur.rowcount
        print(f"   - policy_structured_data eliminados: {deleted_structured}")

        # policy_processing_stats
        cur.execute("DELETE FROM policy_processing_stats WHERE policy_id = ANY(%s::uuid[])", (policy_ids,))
        deleted_stats = cur.rowcount
        print(f"   - policy_processing_stats eliminados: {deleted_stats}")

        # policies (documentos)
        cur.execute("DELETE FROM policies WHERE id = ANY(%s::uuid[])", (policy_ids,))
        deleted_policies = cur.rowcount
        print(f"   - policies (documentos principales) eliminados: {deleted_policies}")

        # policy_envelopes (sobres)
        cur.execute("DELETE FROM policy_envelopes WHERE id = ANY(%s::uuid[])", (envelope_ids,))
        deleted_envelopes = cur.rowcount
        print(f"   - policy_envelopes (sobres lógicos) eliminados: {deleted_envelopes}")

        # Confirmar transacción PostgreSQL
        conn.commit()
        print("   -> Transacción PostgreSQL confirmada con éxito (COMMIT).")

    except Exception as exc:
        conn.rollback()
        print(f"[ERROR] Error durante la eliminación en PostgreSQL: {exc}")
        conn.close()
        sys.exit(1)

    conn.close()

    # 4. Eliminar del checkpoint SQLite (.batch_checkpoint.sqlite)
    print("\n4. Limpiando puntos de control en SQLite...")
    sqlite_path = Path("/opt/docengine/carga_inicial/.batch_checkpoint.sqlite")
    deleted_chk = 0
    if sqlite_path.exists():
        sq_conn = sqlite3.connect(sqlite_path)
        sq_cur = sq_conn.cursor()

        # Por hash
        if file_hashes:
            placeholders = ",".join("?" for _ in file_hashes)
            sq_cur.execute(f"DELETE FROM batch_checkpoint WHERE file_hash IN ({placeholders})", file_hashes)
            deleted_chk += sq_cur.rowcount

        # Por número de póliza
        for pol in TARGET_POLICIES:
            clean = pol.replace(" ", "")
            sq_cur.execute("""
                DELETE FROM batch_checkpoint 
                WHERE numero_poliza = ? 
                   OR REPLACE(numero_poliza, ' ', '') = ?
                   OR numero_poliza LIKE ?
            """, (pol, clean, f"%{pol}%"))
            deleted_chk += sq_cur.rowcount

        sq_conn.commit()
        sq_conn.close()
        print(f"   - Registros de checkpoint eliminados en SQLite: {deleted_chk}")
    else:
        print("   - No se encontró archivo .batch_checkpoint.sqlite.")

    # 5. Eliminar artefactos de salida del filesystem (outputs/)
    print("\n5. Limpiando artefactos generados en outputs/...")
    outputs_dir = Path("/opt/docengine/outputs")
    deleted_dirs = 0
    deleted_files = 0

    deleted_paths_record = []
    for f_name in file_names:
        stem = Path(f_name).stem
        for p in list(outputs_dir.glob(f"**/*{stem}*")):
            if p.exists():
                deleted_paths_record.append(str(p))
                if p.is_dir():
                    shutil.rmtree(p)
                    deleted_dirs += 1
                else:
                    p.unlink()
                    deleted_files += 1

    print(f"   - Directorios de outputs eliminados: {deleted_dirs}")
    print(f"   - Archivos individuales de outputs eliminados: {deleted_files}")

    # 6. Verificación posterior de integridad
    print("\n6. Verificando que no queden rastros...")
    conn = psycopg2.connect(
        host=os.getenv("DOCENGINE_DB_HOST", "localhost"),
        port=int(os.getenv("DOCENGINE_DB_PORT", "5432")),
        dbname=os.getenv("DOCENGINE_DB_NAME", "docengine"),
        user=os.getenv("DOCENGINE_DB_USER", "postgres"),
        password=os.getenv("DOCENGINE_DB_PASSWORD", "postgres")
    )
    cur = conn.cursor()

    cur.execute("""
        SELECT count(*) FROM policy_envelopes 
        WHERE numero_poliza = ANY(%s) OR REPLACE(numero_poliza, ' ', '') = ANY(%s)
    """, (TARGET_POLICIES, clean_targets))
    remaining_envelopes = cur.fetchone()[0]

    cur.execute("""
        SELECT count(*) FROM policies 
        WHERE file_name = ANY(%s) OR file_hash = ANY(%s)
    """, (file_names, file_hashes))
    remaining_policies = cur.fetchone()[0]

    conn.close()

    print(f"   - Sobres restantes en DB: {remaining_envelopes}")
    print(f"   - Documentos restantes en DB: {remaining_policies}")

    if remaining_envelopes == 0 and remaining_policies == 0:
        print("\n===================================================================")
        print("ELIMINACIÓN LIMPIA COMPLETADA EXITOSAMENTE. SISTEMA LISTO PARA RECARGA.")
        print("===================================================================")
    else:
        print("\n[ALERTA] Aún se detectaron registros remanentes.")

if __name__ == "__main__":
    execute_deletion()

#!/usr/bin/env python3
"""DocEngine — Script de Vaciado de Ingestas Operativas.

Propósito:
    Vacía de forma limpia y segura todas las ingestas de pólizas y documentos
    procesados en la base de datos PostgreSQL, manteniendo intactas todas las
    tablas de métricas, estadísticas, auditoría histórica y catálogos maestros.

Tablas operativas vaciadas (Datos de Ingesta):
    - policy_chunks              (Embeddings vectoriales y fragmentos RAG)
    - policy_raw_md              (Contenido Markdown extraído por Docling)
    - policy_structured_data     (JSONB estructurado: coberturas, sumas, deducibles)
    - policy_section_summaries   (Resúmenes de secciones de póliza)
    - policy_fleet_vehicles      (Vehículos de flota extraídos)
    - policy_insured_persons     (Asegurados dependientes / personas)
    - policies                   (Documentos operativos procesados)
    - policy_envelopes           (Sobres lógicos de póliza)

Tablas PRESERVADAS (Métricas, Estadísticas, Auditoría y Maestros):
    - policy_processing_stats    (Métricas de rendimiento, tiempos, páginas, tokens, costos)
    - audit_metrics_ledger       (Libro mayor inmutable WORM de auditoría y KPIs)
    - processing_jobs            (Historial y seguimiento de trabajos de procesamiento)
    - cat_aseguradoras           (Catálogo maestro de compañías aseguradoras)
    - cat_ramos                  (Catálogo maestro de ramos APS)
    - cat_tipos_documento        (Catálogo maestro de clasificación documental)

Opciones adicionales:
    --dry-run                    Simula el vaciado sin aplicar cambios (ROLLBACK).
    --yes / -y                   Ejecuta sin pedir confirmación interactiva.
    --reset-checkpoints          Limpia el archivo SQLite de checkpoints (.batch_checkpoint.sqlite).
    --clean-outputs              Elimina archivos generados en outputs/ (markdown y json).
    --record-audit-events        Registra eventos DOCUMENT_DELETED y ENVELOPE_DELETED en audit_metrics_ledger.

Uso:
    python scripts/purge_ingestions.py --dry-run
    python scripts/purge_ingestions.py
    python scripts/purge_ingestions.py --yes --reset-checkpoints
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Asegurar que la raíz del proyecto esté en sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psycopg2
from psycopg2.extras import RealDictCursor

# Intentar cargar configuración desde DocEngine settings, con fallback seguro a .env/os.environ
try:
    from app.config.settings import get_settings
    _settings = get_settings()
    DEFAULT_DB_HOST = _settings.database.host
    DEFAULT_DB_PORT = _settings.database.port
    DEFAULT_DB_NAME = _settings.database.name
    DEFAULT_DB_USER = _settings.database.user
    DEFAULT_DB_PASSWORD = _settings.database.password
except Exception:
    DEFAULT_DB_HOST = os.getenv("DOCENGINE_DB_HOST", "localhost")
    DEFAULT_DB_PORT = int(os.getenv("DOCENGINE_DB_PORT", "5432"))
    DEFAULT_DB_NAME = os.getenv("DOCENGINE_DB_NAME", "docengine")
    DEFAULT_DB_USER = os.getenv("DOCENGINE_DB_USER", "postgres")
    DEFAULT_DB_PASSWORD = os.getenv("DOCENGINE_DB_PASSWORD", "postgres")

# Tablas operativas que se vacían (ordenadas de hijas a padres para respetar integridad referencial)
OPERATIONAL_TABLES = [
    "policy_chunks",
    "policy_raw_md",
    "policy_structured_data",
    "policy_section_summaries",
    "policy_fleet_vehicles",
    "policy_insured_persons",
    "policies",
    "policy_envelopes",
]

# Tablas críticas que se deben PRESERVAR y NUNCA vaciar
PRESERVED_TABLES = [
    "policy_processing_stats",
    "audit_metrics_ledger",
    "processing_jobs",
    "cat_aseguradoras",
    "cat_ramos",
    "cat_tipos_documento",
]


def get_table_counts(cur) -> Dict[str, int]:
    """Obtiene el número de registros actual de todas las tablas relevantes."""
    counts = {}
    for table in OPERATIONAL_TABLES + PRESERVED_TABLES:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table};")
            counts[table] = cur.fetchone()[0]
        except Exception:
            counts[table] = -1
    return counts


def print_table_report(title: str, counts: Dict[str, int]) -> None:
    """Imprime un reporte formateado del estado de las tablas."""
    print(f"\n{title}")
    print("=" * 70)
    print(f" {'Tipo':<15} | {'Tabla':<28} | {'Registros':>15}")
    print("-" * 70)
    
    print(" [OPERACIONAL - A VACIAR]")
    for tbl in OPERATIONAL_TABLES:
        cnt = counts.get(tbl, 0)
        cnt_str = f"{cnt:,}" if cnt >= 0 else "NO EXISTE"
        print(f" {'Ingesta':<15} | {tbl:<28} | {cnt_str:>15}")
    
    print("-" * 70)
    print(" [PRESERVADO - ESTADÍSTICAS / MÉTRICAS / MAESTROS]")
    for tbl in PRESERVED_TABLES:
        cnt = counts.get(tbl, 0)
        cnt_str = f"{cnt:,}" if cnt >= 0 else "NO EXISTE"
        desc = "Métricas" if "stat" in tbl or "ledger" in tbl else ("Jobs" if "job" in tbl else "Catálogo")
        print(f" {desc:<15} | {tbl:<28} | {cnt_str:>15}")
    print("=" * 70)


def record_audit_deletions(cur) -> Tuple[int, int]:
    """Registra eventos DOCUMENT_DELETED y ENVELOPE_DELETED en audit_metrics_ledger antes del borrado."""
    # 1. Obtener documentos operativos a eliminar
    cur.execute("""
        SELECT 
            p.id AS policy_id,
            p.envelope_id,
            p.file_name,
            p.file_hash,
            p.company_sigla,
            p.tipo_documento,
            pe.numero_poliza,
            pe.ramo,
            COALESCE(p.id_cliente, pe.id_cliente) AS id_cliente,
            COALESCE(p.nombre_cliente, pe.nombre_cliente) AS nombre_cliente
        FROM policies p
        LEFT JOIN policy_envelopes pe ON p.envelope_id = pe.id;
    """)
    policies = cur.fetchall()
    
    doc_events = 0
    for pol in policies:
        cur.execute("""
            INSERT INTO audit_metrics_ledger (
                event_type, policy_id, envelope_id, numero_poliza,
                company_sigla, ramo, tipo_documento, id_cliente,
                nombre_cliente, file_name, file_hash, metadata
            ) VALUES (
                'DOCUMENT_DELETED', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                jsonb_build_object('source', 'purge_ingestions_script')
            );
        """, (
            str(pol["policy_id"]),
            str(pol["envelope_id"]) if pol["envelope_id"] else None,
            pol["numero_poliza"],
            pol["company_sigla"],
            pol["ramo"],
            pol["tipo_documento"],
            pol["id_cliente"],
            pol["nombre_cliente"],
            pol["file_name"],
            pol["file_hash"],
        ))
        doc_events += 1

    # 2. Obtener sobres operativos a eliminar
    cur.execute("""
        SELECT id, numero_poliza, company_sigla, ramo, id_cliente, nombre_cliente
        FROM policy_envelopes;
    """)
    envelopes = cur.fetchall()

    env_events = 0
    for env in envelopes:
        cur.execute("""
            INSERT INTO audit_metrics_ledger (
                event_type, envelope_id, numero_poliza,
                company_sigla, ramo, id_cliente, nombre_cliente, metadata
            ) VALUES (
                'ENVELOPE_DELETED', %s, %s, %s, %s, %s, %s,
                jsonb_build_object('source', 'purge_ingestions_script')
            );
        """, (
            str(env["id"]),
            env["numero_poliza"],
            env["company_sigla"],
            env["ramo"],
            env["id_cliente"],
            env["nombre_cliente"],
        ))
        env_events += 1

    return doc_events, env_events


def clean_sqlite_checkpoint() -> int:
    """Vacía los registros de .batch_checkpoint.sqlite."""
    chk_path = PROJECT_ROOT / "carga_inicial" / ".batch_checkpoint.sqlite"
    if not chk_path.exists():
        print(f"   [INFO] No se encontró archivo SQLite de checkpoints en {chk_path}")
        return 0

    try:
        conn = sqlite3.connect(chk_path)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM batch_checkpoint;")
        count = cur.fetchone()[0]
        cur.execute("DELETE FROM batch_checkpoint;")
        conn.commit()
        conn.close()
        print(f"   [OK] Checkpoint SQLite vaciado exitosamente: {count:,} registros eliminados.")
        return count
    except Exception as exc:
        print(f"   [ERROR] No se pudo vaciar checkpoint SQLite: {exc}")
        return 0


def clean_outputs_directory() -> Tuple[int, int]:
    """Limpia los archivos de salida generados en outputs/ preservando el directorio raíz."""
    outputs_dir = PROJECT_ROOT / "outputs"
    if not outputs_dir.exists():
        print(f"   [INFO] El directorio de outputs no existe: {outputs_dir}")
        return 0, 0

    deleted_files = 0
    deleted_dirs = 0
    for item in outputs_dir.iterdir():
        if item.name.startswith("."):
            continue
        try:
            if item.is_dir():
                shutil.rmtree(item)
                deleted_dirs += 1
            else:
                item.unlink()
                deleted_files += 1
        except Exception as exc:
            print(f"   [ADVERTENCIA] Error eliminando {item.name}: {exc}")

    print(f"   [OK] outputs/ limpiado: {deleted_dirs} subdirectorios y {deleted_files} archivos eliminados.")
    return deleted_dirs, deleted_files


def purge_database(
    dry_run: bool = False,
    record_audit: bool = False,
    reset_checkpoints: bool = False,
    clean_outputs: bool = False,
) -> None:
    """Ejecuta el vaciado de las tablas de ingesta en PostgreSQL de forma transaccional."""
    print("=" * 70)
    print("DocEngine — VACIADO DE INGESTAS DE BASE DE DATOS")
    print(f"Modo: {'[DRY-RUN / SIMULACIÓN]' if dry_run else '[EJECUCIÓN REAL]'}")
    print(f"Host: {DEFAULT_DB_HOST}:{DEFAULT_DB_PORT} | Base de datos: {DEFAULT_DB_NAME}")
    print("=" * 70)

    try:
        conn = psycopg2.connect(
            host=DEFAULT_DB_HOST,
            port=DEFAULT_DB_PORT,
            dbname=DEFAULT_DB_NAME,
            user=DEFAULT_DB_USER,
            password=DEFAULT_DB_PASSWORD,
        )
    except Exception as exc:
        print(f"[FATAL] Error de conexión a PostgreSQL: {exc}")
        sys.exit(1)

    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            # 1. Reporte inicial de estado
            initial_counts = get_table_counts(cur)
            print_table_report("ESTADO PREVIO DE LAS TABLAS:", initial_counts)

            total_op_rows = sum(initial_counts.get(tbl, 0) for tbl in OPERATIONAL_TABLES if initial_counts.get(tbl, 0) > 0)
            if total_op_rows == 0:
                print("\n[INFO] Las tablas de ingesta ya están completamente vacías. Nada que eliminar.")
            else:
                print(f"\n[INFO] Total de registros operativos a eliminar: {total_op_rows:,}")

            # 2. Registrar eventos de auditoría si se solicitó
            if record_audit and not dry_run and total_op_rows > 0:
                print("\nRegistrando eventos de eliminación en audit_metrics_ledger...")
                with conn.cursor(cursor_factory=RealDictCursor) as dict_cur:
                    doc_evts, env_evts = record_audit_deletions(dict_cur)
                print(f"   - Eventos DOCUMENT_DELETED registrados: {doc_evts}")
                print(f"   - Eventos ENVELOPE_DELETED registrados: {env_evts}")

            # 3. Proceder al vaciado de tablas operativas
            if total_op_rows > 0:
                print("\nVaciando tablas operativas de ingesta...")
                deleted_summary = {}
                for table in OPERATIONAL_TABLES:
                    cur.execute(f"DELETE FROM {table};")
                    deleted_count = cur.rowcount
                    deleted_summary[table] = deleted_count
                    print(f"   - {table:<28} -> {deleted_count:>8,} filas eliminadas")

            # 4. Verificar integridad y permanencia de tablas protegidas
            post_counts = get_table_counts(cur)

            # Validar que NINGUNA tabla preservada haya sido vaciada
            for tbl in PRESERVED_TABLES:
                init_val = initial_counts.get(tbl, 0)
                post_val = post_counts.get(tbl, 0)
                # Si se registraron eventos de auditoría, audit_metrics_ledger pudo haber crecido
                if tbl == "audit_metrics_ledger" and record_audit:
                    if post_val < init_val:
                        raise RuntimeError(f"Violación de integridad: {tbl} perdió registros ({init_val} -> {post_val})")
                else:
                    if post_val != init_val:
                        raise RuntimeError(f"Violación de integridad: {tbl} cambió inesperadamente ({init_val} -> {post_val})")

            # 5. Confirmar o deshacer transacción según modo
            if dry_run:
                conn.rollback()
                print("\n" + "=" * 70)
                print("[SIMULACIÓN COMPLETADA] Transacción revertida (ROLLBACK). Ningún dato fue alterado.")
                print("=" * 70)
            else:
                conn.commit()
                print("\n" + "=" * 70)
                print("[ÉXITO] Transacción confirmada en PostgreSQL (COMMIT).")
                print("=" * 70)
                print_table_report("ESTADO FINAL DE LAS TABLAS TRAS EL VACIADO:", post_counts)

    except Exception as exc:
        conn.rollback()
        print(f"\n[ERROR CRÍTICO] La operación falló y fue revertida (ROLLBACK): {exc}")
        conn.close()
        sys.exit(1)

    conn.close()

    # Operaciones complementarias fuera de PostgreSQL (si se solicitaron y no es dry-run)
    if not dry_run:
        if reset_checkpoints:
            print("\nLimpiando checkpoints de ingesta por lote (SQLite)...")
            clean_sqlite_checkpoint()

        if clean_outputs:
            print("\nLimpiando directorio outputs/...")
            clean_outputs_directory()

    print("\nProceso finalizado.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Vacía todas las ingestas de pólizas en PostgreSQL preservando métricas, estadísticas y catálogos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula la ejecución en modo prueba sin alterar la base de datos (hace ROLLBACK automático).",
    )
    parser.add_argument(
        "-y", "--yes", "--force",
        dest="force",
        action="store_true",
        help="Omite la confirmación interactiva y ejecuta el vaciado directamente.",
    )
    parser.add_argument(
        "--reset-checkpoints",
        action="store_true",
        help="También vacía la tabla batch_checkpoint en .batch_checkpoint.sqlite para permitir reingesta completa.",
    )
    parser.add_argument(
        "--clean-outputs",
        action="store_true",
        help="También elimina los archivos generados en el directorio outputs/ (markdown y json).",
    )
    parser.add_argument(
        "--record-audit-events",
        action="store_true",
        help="Registra eventos DOCUMENT_DELETED y ENVELOPE_DELETED en audit_metrics_ledger antes de eliminar.",
    )

    args = parser.parse_args()

    if not args.dry_run and not args.force:
        print("\n" + "!" * 70)
        print(" ADVERTENCIA: Esta operación eliminará todas las pólizas, chunks,")
        print(" embeddings y datos estructurados de la base de datos PostgreSQL.")
        print(" Las tablas de métricas, estadísticas y auditoría se mantendrán.")
        print("!" * 70)
        confirm = input("\n¿Está seguro de que desea proceder con el vaciado? (escriba 'si' o 'yes'): ").strip().lower()
        if confirm not in ("si", "sí", "yes", "y"):
            print("[CANCELADO] Operación cancelada por el usuario.")
            sys.exit(0)

    purge_database(
        dry_run=args.dry_run,
        record_audit=args.record_audit_events,
        reset_checkpoints=args.reset_checkpoints,
        clean_outputs=args.clean_outputs,
    )


if __name__ == "__main__":
    main()


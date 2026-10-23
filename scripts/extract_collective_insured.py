"""DocEngine — [ADITIVO] Script de Extracción Determinista de Nóminas Colectivas de Personas.

Extrae la nómina estructurada de asegurados en pólizas colectivas de Salud,
Accidentes Personales y Vida en Grupo, y las almacena en la tabla `policy_insured_persons`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root directory to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from dotenv import load_dotenv

load_dotenv(root_dir / ".env")

from app.application.collective_insured_extractor_service import CollectiveInsuredExtractorService
from app.config.settings import get_settings
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


def run_collective_insured_extraction(specific_policy_id: str | None = None) -> None:
    """Ejecuta el escaneo y extracción de nóminas de personas en pólizas colectivas."""
    settings = get_settings()
    db = DatabaseManager(settings.database)
    db.initialize()
    insured_service = CollectiveInsuredExtractorService(db)

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            if specific_policy_id:
                cur.execute(
                    "SELECT id::text, file_name, total_pages, envelope_id::text FROM policies WHERE id = %s::uuid;",
                    (specific_policy_id,),
                )
            else:
                # Buscar pólizas de ramos colectivos o que contengan tablas de asegurados
                cur.execute(
                    """
                    SELECT DISTINCT p.id::text, p.file_name, p.total_pages, p.envelope_id::text
                    FROM policies p
                    LEFT JOIN policy_envelopes pe ON p.envelope_id = pe.id
                    LEFT JOIN policy_raw_md prm ON prm.policy_id = p.id
                    WHERE (
                        pe.ramo ILIKE '%accidente%' 
                        OR pe.ramo ILIKE '%salud%' 
                        OR pe.ramo ILIKE '%medica%' 
                        OR pe.ramo ILIKE '%enfermedad%'
                        OR pe.ramo ILIKE '%vida%'
                    )
                    AND (
                        pe.ramo ILIKE '%colectiv%'
                        OR pe.ramo ILIKE '%grupo%'
                        OR pe.ramo ILIKE '%corporativo%'
                        OR prm.markdown_content ~* '(?<![/0-9-])\y([1-9][0-9]{0,4})\s+(personas|asegurados|titulares|afiliados|empleados|trabajadores)\y'
                        OR prm.markdown_content ILIKE '%registro de asegurados%'
                        OR prm.markdown_content ILIKE '%nómina de asegurados%'
                        OR prm.markdown_content ILIKE '%nomina de asegurados%'
                    )
                    ORDER BY p.total_pages DESC;
                    """
                )
            policies = cur.fetchall()

    print(f"\n[COLLECTIVE INSURED EXTRACTOR] Encontradas {len(policies)} pólizas candidatas a nómina colectiva de personas:")
    total_persons_extracted = 0

    for pid, fname, pages, env_id in policies:
        print(f"\n -> Procesando póliza: {fname} (ID: {pid[:8]}..., Páginas: {pages})")
        persons = insured_service.extract_and_save_policy_insured(policy_id=pid, envelope_id=env_id)
        count = len(persons)
        total_persons_extracted += count
        print(f"    ✓ {count} personas aseguradas registradas.")

        if count > 0:
            summary = insured_service._repo.get_insured_summary(policy_id=pid)
            if summary:
                print(f"    - Total asegurados: {summary['total_asegurados']}")
                if summary["total_suma_asegurada_usd"] > 0:
                    print(f"    - Suma asegurada acumulada: $us. {summary['total_suma_asegurada_usd']:,.2f}")
                print(f"    - Distribución por categoría: {summary['distribucion_categoria']}")
                muestra = [p.get("nombre_completo") for p in summary["muestra"][:3]]
                print(f"    - Muestra nombres: {muestra}")

    db.close()
    print(f"\n[OK] Extracción finalizada. Total de asegurados extraídos: {total_persons_extracted}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extrae nóminas de personas aseguradas en pólizas colectivas.")
    parser.add_argument("--policy-id", type=str, default=None, help="UUID de póliza específica a procesar.")
    args = parser.parse_args()

    run_collective_insured_extraction(specific_policy_id=args.policy_id)

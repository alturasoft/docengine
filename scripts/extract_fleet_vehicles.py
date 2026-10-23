"""DocEngine — [ADITIVO] Script de Extracción Determinista de Nóminas de Flota.

Extrae fichas técnicas de vehículos de pólizas colectivas de automotores
y las almacena en la tabla `policy_fleet_vehicles`.
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

from app.application.fleet_extractor_service import FleetExtractorService
from app.config.settings import get_settings
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


def run_fleet_extraction(specific_policy_id: str | None = None) -> None:
    settings = get_settings()
    db = DatabaseManager(settings.database)
    db.initialize()
    fleet_service = FleetExtractorService(db)

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            if specific_policy_id:
                cur.execute(
                    "SELECT id::text, file_name, total_pages, envelope_id::text FROM policies WHERE id = %s::uuid;",
                    (specific_policy_id,),
                )
            else:
                # Buscar pólizas que contengan fragmentos de vehículos o ítems
                cur.execute(
                    """
                    SELECT DISTINCT p.id::text, p.file_name, p.total_pages, p.envelope_id::text
                    FROM policies p
                    JOIN policy_chunks pc ON pc.policy_id = p.id
                    WHERE pc.chunk_content ~* 'TIPO VEH[IÍ]CULO'
                       OR pc.chunk_content ~* 'ITEM [0-9]+.*PLACA'
                    ORDER BY p.total_pages DESC;
                    """
                )
            policies = cur.fetchall()

    print(f"\n[FLEET EXTRACTOR] Encontradas {len(policies)} pólizas candidatas a nómina de vehículos:")
    for pid, fname, pages, env_id in policies:
        print(f"\n -> Extrayendo flota para: {fname} (ID: {pid[:8]}..., Páginas: {pages})")
        vehicles = fleet_service.extract_and_save_policy_fleet(policy_id=pid, envelope_id=env_id)
        print(f"    ✓ {len(vehicles)} vehículos extraídos y guardados.")

        # Mostrar resumen si hay vehículos
        if vehicles:
            summary = fleet_service._repo.get_fleet_summary(policy_id=pid)
            if summary:
                print(f"    - Total unidades: {summary['total_vehiculos']}")
                print(f"    - Valor asegurado total: $us. {summary['total_valor_asegurado_usd']:,.2f}")
                print(f"    - Distribución por tipo: {summary['distribucion_tipo']}")
                print(f"    - Top 3 placas: {[v.get('placa') for v in summary['muestra'][:3]]}")

    db.close()
    print("\n[OK] Extracción de nóminas de flota finalizada con éxito.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extrae nóminas de vehículos asegurados.")
    parser.add_argument("--policy-id", type=str, default=None, help="UUID de póliza específica a procesar.")
    args = parser.parse_args()

    run_fleet_extraction(specific_policy_id=args.policy_id)

"""DocEngine — [ADITIVO FASE 2] Script de Generación de Mapas de Pólizas Grandes.

Genera de forma retroactiva o bajo demanda los mapas temáticos y de secciones
en la tabla `policy_section_summaries` para pólizas existentes.
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

from app.application.policy_map_service import PolicyMapService
from app.config.settings import get_settings
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


def run_map_generation(min_pages: int = 500, specific_policy_id: str | None = None) -> None:
    settings = get_settings()
    db = DatabaseManager(settings.database)
    db.initialize()
    map_service = PolicyMapService(db)

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            if specific_policy_id:
                cur.execute(
                    "SELECT id::text, file_name, total_pages, envelope_id::text FROM policies WHERE id = %s::uuid;",
                    (specific_policy_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT p.id::text, p.file_name, p.total_pages, p.envelope_id::text
                    FROM policies p
                    WHERE p.total_pages >= %s
                    ORDER BY p.total_pages DESC;
                    """,
                    (min_pages,),
                )
            policies = cur.fetchall()

    print(f"\n[MAP GEN] Encontradas {len(policies)} pólizas para generar mapa (min_pages={min_pages}):")
    for pid, fname, pages, env_id in policies:
        print(f" -> Procesando: {fname} (ID: {pid[:8]}..., Páginas: {pages})")
        summaries = map_service.generate_map_for_policy(policy_id=pid, envelope_id=env_id)
        print(f"    ✓ {len(summaries)} secciones identificadas y almacenadas.")

    db.close()
    print("\n[OK] Generación de mapas completada con éxito.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Genera mapas de secciones para pólizas grandes.")
    parser.add_argument("--min-pages", type=int, default=500, help="Páginas mínimas para calificar como grande.")
    parser.add_argument("--policy-id", type=str, default=None, help="UUID de póliza específica a procesar.")
    args = parser.parse_args()

    run_map_generation(min_pages=args.min_pages, specific_policy_id=args.policy_id)

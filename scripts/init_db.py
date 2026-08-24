"""DocEngine — Database Initialization Script.

Executes scripts/001_add_rag_tables.sql against PostgreSQL using application settings.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root directory to sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import psycopg2

from app.config.settings import get_settings
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


def init_db() -> None:
    settings = get_settings()
    db_config = settings.database

    sql_files = sorted(Path(__file__).parent.glob("*.sql"))
    if not sql_files:
        print("[ERROR] No SQL files found.")
        sys.exit(1)

    print(f"Connecting to PostgreSQL database '{db_config.name}' at {db_config.host}:{db_config.port}...")

    try:
        conn = psycopg2.connect(
            host=db_config.host,
            port=db_config.port,
            dbname=db_config.name,
            user=db_config.user,
            password=db_config.password,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            for sql_file in sql_files:
                print(f"Executing {sql_file.name}...")
                cur.execute(sql_file.read_text(encoding="utf-8"))
        conn.close()
        print("[OK] Database schema and migrations applied successfully!")

    except Exception as exc:
        print(f"[ERROR] Error initializing database: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    init_db()

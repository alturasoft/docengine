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

    sql_path = Path(__file__).parent / "001_add_rag_tables.sql"
    if not sql_path.exists():
        print(f"[ERROR] SQL file not found: {sql_path}")
        sys.exit(1)

    sql_content = sql_path.read_text(encoding="utf-8")

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
            print("Executing 001_add_rag_tables.sql...")
            cur.execute(sql_content)
        conn.close()
        print("[OK] Database tables and pgvector extension created/verified successfully!")

    except Exception as exc:
        print(f"[ERROR] Error initializing database: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    init_db()

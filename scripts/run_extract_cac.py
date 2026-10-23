import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
from app.config.settings import get_settings
from app.infrastructure.database.db_connection import DatabaseManager
from app.application.collective_insured_extractor_service import CollectiveInsuredExtractorService

settings = get_settings()
db = DatabaseManager(settings.database)
db.initialize()
service = CollectiveInsuredExtractorService(db)

# 1. Buscar todos los documentos pertenecientes a CAC-LPR0687876
conn = psycopg2.connect(
    host=os.getenv('DOCENGINE_DB_HOST', 'localhost'),
    port=os.getenv('DOCENGINE_DB_PORT', 5432),
    dbname=os.getenv('DOCENGINE_DB_NAME', 'docengine'),
    user=os.getenv('DOCENGINE_DB_USER', 'postgres'),
    password=os.getenv('DOCENGINE_DB_PASSWORD', 'postgres'),
)
cur = conn.cursor()
cur.execute("""
    SELECT p.id::text, p.file_name, p.envelope_id::text, pe.numero_poliza
    FROM policies p
    JOIN policy_envelopes pe ON p.envelope_id = pe.id
    WHERE pe.numero_poliza ILIKE '%CAC-LPR0687876%';
""")
docs = cur.fetchall()

print(f"Procesando {len(docs)} documentos para CAC-LPR0687876...")
total_saved = 0
for pid, fname, env_id, num in docs:
    print(f"\nExtrayendo para: {fname} (ID: {pid[:8]}...)")
    persons = service.extract_and_save_policy_insured(policy_id=pid, envelope_id=env_id)
    print(f" -> Extraídas: {len(persons)} personas")
    total_saved += len(persons)

# 2. Consultar el resumen guardado en la base de datos
print("\n" + "="*60)
print(f"TOTAL ASEGURADOS GUARDADOS EN policy_insured_persons: {total_saved}")
cur.execute("SELECT COUNT(*) FROM policy_insured_persons;")
print(f"Total registros en la tabla policy_insured_persons: {cur.fetchone()[0]}")

cur.execute("""
    SELECT item_number, nombre_completo, documento_identidad, suma_asegurada_usd, prima_usd
    FROM policy_insured_persons
    ORDER BY item_number ASC
    LIMIT 10;
""")
print("\nMuestra de los primeros 10 asegurados en la tabla:")
for r in cur.fetchall():
    print(f"  Ítem {r[0]}: {r[1]} | Doc: {r[2]} | Suma: ${r[3]:,.2f} | Prima: ${r[4]:,.2f}")

conn.close()
db.close()

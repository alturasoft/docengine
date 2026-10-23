import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

from app.config.settings import get_settings
from app.infrastructure.database.db_connection import DatabaseManager
from app.application.collective_insured_extractor_service import CollectiveInsuredExtractorService

conn = psycopg2.connect(
    host=os.getenv('DOCENGINE_DB_HOST', 'localhost'),
    port=os.getenv('DOCENGINE_DB_PORT', 5432),
    dbname=os.getenv('DOCENGINE_DB_NAME', 'docengine'),
    user=os.getenv('DOCENGINE_DB_USER', 'postgres'),
    password=os.getenv('DOCENGINE_DB_PASSWORD', 'postgres'),
)
cur = conn.cursor()

# Get documents of CAC-LPR0687876
cur.execute("""
    SELECT p.id::text, p.file_name, p.envelope_id::text, pe.numero_poliza
    FROM policies p
    JOIN policy_envelopes pe ON p.envelope_id = pe.id
    WHERE pe.numero_poliza ILIKE '%CAC-LPR0687876%';
""")
docs = cur.fetchall()

settings = get_settings()
db = DatabaseManager(settings.database)
service = CollectiveInsuredExtractorService(db)

print(f"=== Extrayendo asegurados para CAC-LPR0687876 ({len(docs)} documentos) ===")
total_extracted = 0

for pid, fname, env_id, num in docs:
    print(f"\nDocumento: {fname} (ID: {pid[:8]}...)")
    persons = service.extract_and_save_policy_insured(policy_id=pid, envelope_id=env_id)
    print(f" -> Guardados: {len(persons)} personas aseguradas")
    total_extracted += len(persons)

print("\n" + "="*60)
print(f"Total personas extraídas y guardadas en esta ejecución: {total_extracted}")

cur.execute("SELECT COUNT(*) FROM policy_insured_persons WHERE envelope_id = (SELECT id FROM policy_envelopes WHERE numero_poliza ILIKE '%CAC-LPR0687876%' LIMIT 1);")
count_in_envelope = cur.fetchone()[0]
print(f"Total en policy_insured_persons para el sobre CAC-LPR0687876: {count_in_envelope}")

cur.execute("""
    SELECT item_number, nombre_completo, documento_identidad, suma_asegurada_usd, prima_usd
    FROM policy_insured_persons
    WHERE envelope_id = (SELECT id FROM policy_envelopes WHERE numero_poliza ILIKE '%CAC-LPR0687876%' LIMIT 1)
    ORDER BY item_number ASC
    LIMIT 10;
""")
print("\nMuestra de los primeros 10 asegurados en la base de datos:")
for r in cur.fetchall():
    print(f"  Ítem #{r[0]}: {r[1]} | Doc: {r[2]} | Suma: Bs. {r[3]:,.2f} | Prima: Bs. {r[4]:,.2f}")

conn.close()

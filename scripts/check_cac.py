import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(
    host=os.getenv('DOCENGINE_DB_HOST', 'localhost'),
    port=os.getenv('DOCENGINE_DB_PORT', 5432),
    dbname=os.getenv('DOCENGINE_DB_NAME', 'docengine'),
    user=os.getenv('DOCENGINE_DB_USER', 'postgres'),
    password=os.getenv('DOCENGINE_DB_PASSWORD', 'postgres'),
)
conn.autocommit = True
cur = conn.cursor()

# 1. Check if table exists
cur.execute("""
    SELECT EXISTS (
        SELECT FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_name = 'policy_insured_persons'
    );
""")
table_exists = cur.fetchone()[0]
print(f"¿Existe la tabla policy_insured_persons? {table_exists}")

if not table_exists:
    print("Creando tabla policy_insured_persons desde 010_add_policy_insured_persons.sql...")
    sql_path = "/opt/docengine/scripts/010_add_policy_insured_persons.sql"
    with open(sql_path, "r", encoding="utf-8") as f:
        cur.execute(f.read())
    print("Tabla creada con éxito.")

# 2. Check documents for CAC-LPR0687876
cur.execute("""
    SELECT p.id::text, p.file_name, p.envelope_id::text, pe.numero_poliza, pe.ramo
    FROM policies p
    LEFT JOIN policy_envelopes pe ON p.envelope_id = pe.id
    WHERE pe.numero_poliza ILIKE '%CAC-LPR0687876%' OR p.file_name ILIKE '%CAC-LPR0687876%';
""")
docs = cur.fetchall()
print(f"\nDocumentos encontrados para CAC-LPR0687876: {len(docs)}")
for pid, fname, eid, num_pol, ramo in docs:
    print(f" - ID: {pid} | Archivo: {fname} | Sobre: {eid} | Ramo: {ramo}")

# 3. Check count in policy_insured_persons
cur.execute("SELECT COUNT(*) FROM policy_insured_persons;")
print(f"\nTotal registros actuales en policy_insured_persons: {cur.fetchone()[0]}")

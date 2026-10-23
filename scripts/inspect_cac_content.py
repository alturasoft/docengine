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
cur = conn.cursor()

cur.execute("""
    SELECT p.id::text, p.file_name, prm.markdown_content
    FROM policies p
    JOIN policy_raw_md prm ON p.id = prm.policy_id
    JOIN policy_envelopes pe ON p.envelope_id = pe.id
    WHERE pe.numero_poliza ILIKE '%CAC-LPR0687876%';
""")

rows = cur.fetchall()
for pid, fname, md in rows:
    print(f"\n=======================================================")
    print(f"ARCHIVO: {fname} (ID: {pid})")
    print(f"Longitud texto: {len(md)} caracteres")
    # Check for tables or mentions of personas/asegurados
    lines = md.splitlines()
    table_lines = [l for l in lines if "|" in l]
    print(f"Líneas de tabla encontradas: {len(table_lines)}")
    if table_lines:
        print("Muestra de tabla (primeras 15 líneas):")
        for tl in table_lines[:15]:
            print("  ", tl[:120])
    
    # Check for keywords
    for kw in ["asegurado", "nomina", "nómina", "personas", "materia del seguro"]:
        matches = [l for l in lines if kw in l.lower()]
        if matches:
            print(f"Coincidencias '{kw}' ({len(matches)}): {matches[0][:100]}")

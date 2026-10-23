import os
import psycopg2
import re
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

# Get markdown of Condicionados_Particula...
cur.execute("SELECT markdown_content FROM policy_raw_md WHERE policy_id = '4f93b696-4935-4ef9-8a89-3df06306b719';")
md = cur.fetchone()[0]

# Find the table
lines = [l.strip() for l in md.splitlines()]
tables = []
curr = []
for l in lines:
    if l.startswith("|") and l.endswith("|"):
        curr.append(l)
    else:
        if len(curr) >= 3:
            tables.append(curr)
        curr = []
if len(curr) >= 3:
    tables.append(curr)

print(f"Total tablas encontradas en Condicionados_Particulares: {len(tables)}")
for i, t in enumerate(tables):
    print(f"\n--- Tabla {i} ({len(t)} filas) ---")
    print("Header:", t[0])
    print("Fila 1:", t[2] if len(t) > 2 else "N/A")
    print("Fila 2:", t[3] if len(t) > 3 else "N/A")

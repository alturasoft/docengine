import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

from app.application.collective_insured_extractor_service import CollectiveInsuredExtractorService

conn = psycopg2.connect(
    host=os.getenv('DOCENGINE_DB_HOST', 'localhost'),
    port=os.getenv('DOCENGINE_DB_PORT', 5432),
    dbname=os.getenv('DOCENGINE_DB_NAME', 'docengine'),
    user=os.getenv('DOCENGINE_DB_USER', 'postgres'),
    password=os.getenv('DOCENGINE_DB_PASSWORD', 'postgres'),
)
cur = conn.cursor()

# Get markdown of Condicionados_Particulares
cur.execute("SELECT markdown_content FROM policy_raw_md WHERE policy_id = '4f93b696-4935-4ef9-8a89-3df06306b719';")
md1 = cur.fetchone()[0]

# Get markdown of Anexo
cur.execute("SELECT markdown_content FROM policy_raw_md WHERE policy_id = '5150597c-9cbb-4c9c-9930-f0264e12b42a';")
md2 = cur.fetchone()[0]

conn.close()

service = CollectiveInsuredExtractorService(None) # type: ignore

print("--- Extracción Condicionados_Particulares ---")
persons1 = service._parse_tables_from_markdown(md1)
print(f"Total personas extraídas: {len(persons1)}")
for p in persons1[:5]:
    print("  ", p["item_number"], p["nombre_completo"], p["documento_identidad"], p["suma_asegurada_usd"], p["prima_usd"])

print("\n--- Extracción Anexo ---")
persons2 = service._parse_tables_from_markdown(md2)
print(f"Total personas extraídas: {len(persons2)}")
for p in persons2[:5]:
    print("  ", p["item_number"], p["nombre_completo"], p["documento_identidad"], p["suma_asegurada_usd"], p["prima_usd"])

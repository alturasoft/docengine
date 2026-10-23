import os
from dotenv import load_dotenv

load_dotenv()
from app.config.settings import get_settings
from app.infrastructure.database.db_connection import DatabaseManager
from app.application.collective_insured_extractor_service import CollectiveInsuredExtractorService

settings = get_settings()
db = DatabaseManager(settings.database)
db.initialize()

service = CollectiveInsuredExtractorService(db)

# Run on CAC-LPR0687876
policy_id = "4f93b696-4935-4ef9-8a89-3df06306b719" # Condicionados_Particula...
envelope_id = "89a95248-cf1b-430a-8a65-ec4b45cf8f09"

print(f"Probando extracción para póliza {policy_id}...")
persons = service.extract_and_save_policy_insured(policy_id=policy_id, envelope_id=envelope_id)
print(f"Total personas extraídas: {len(persons)}")
if persons:
    print("Muestra primeras 5:")
    for p in persons[:5]:
        print("  ", p)

# Test also the other document
policy_id2 = "5150597c-9cbb-4c9c-9930-f0264e12b42a" # Anexo con 658...
print(f"\nProbando extracción para anexo {policy_id2}...")
persons2 = service.extract_and_save_policy_insured(policy_id=policy_id2, envelope_id=envelope_id)
print(f"Total personas extraídas: {len(persons2)}")
if persons2:
    print("Muestra primeras 5:")
    for p in persons2[:5]:
        print("  ", p)

db.close()

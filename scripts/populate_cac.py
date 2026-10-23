import os
import re
import json
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

def parse_amount(raw_val: str | None) -> float:
    if not raw_val:
        return 0.0
    s = str(raw_val).strip()
    if "." in s and "," in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts[-1]) == 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    clean = re.sub(r"[^\d.]", "", s)
    try:
        return float(clean)
    except ValueError:
        return 0.0

def parse_tables(raw_md: str) -> list[dict]:
    if not raw_md or "|" not in raw_md:
        return []

    lines = [line.strip() for line in raw_md.splitlines()]
    tables: list[list[str]] = []
    current_table: list[str] = []

    for line in lines:
        if line.startswith("|"):
            current_table.append(line)
        else:
            if len(current_table) >= 3:
                tables.append(current_table)
            current_table = []
    if len(current_table) >= 3:
        tables.append(current_table)

    persons = []
    item_counter = 1

    for table_lines in tables:
        header_line = table_lines[0]
        header_cells = [c.strip().upper() for c in header_line.strip().strip("|").split("|")]

        name_idx = None
        ci_idx = None
        val_idx = None
        prima_idx = None

        for i, h in enumerate(header_cells):
            if any(w in h for w in ["NOMBRE", "ASEGURADO", "BENEFICIARIO", "EMPLEADO", "AFILIADO"]) and name_idx is None:
                name_idx = i
            elif any(w in h for w in ["C.I", "CI", "DOC", "DOCUMENTO", "CARNET", "IDENTIDAD", "DNI", "PASAPORTE"]) and ci_idx is None:
                ci_idx = i
            elif any(w in h for w in ["SUMA", "VALOR", "CAPITAL", "COBERTURA", "MONTO", "M. ACC", "M.ACC", "MUERTE"]) and val_idx is None:
                val_idx = i
            elif any(w in h for w in ["PRIMA", "PRIMA T", "PRIMA TOTAL"]) and prima_idx is None:
                prima_idx = i

        if name_idx is None and ci_idx is None:
            continue

        for row_line in table_lines[2:]:
            cells = [c.strip() for c in row_line.strip().strip("|").split("|")]
            if not cells:
                continue

            nombre = cells[name_idx] if (name_idx is not None and name_idx < len(cells)) else ""
            ci = cells[ci_idx] if (ci_idx is not None and ci_idx < len(cells)) else None
            val_raw = cells[val_idx] if (val_idx is not None and val_idx < len(cells)) else "0"
            prima_raw = cells[prima_idx] if (prima_idx is not None and prima_idx < len(cells)) else "0"

            if not nombre or nombre.upper() in ["TOTAL", "SUBTOTAL", "NOMBRE", "---", "-"]:
                continue
            if len(nombre) < 3 or nombre.replace(".", "").isdigit():
                continue

            effective_item = item_counter
            item_prefix_match = re.match(r"^\s*(\d+)\s*[\.\-\)]+\s*(.*)$", nombre)
            if item_prefix_match:
                try:
                    detected_num = int(item_prefix_match.group(1))
                    if detected_num > 0:
                        effective_item = detected_num
                    nombre = item_prefix_match.group(2).strip()
                except ValueError:
                    pass

            suma_usd = parse_amount(val_raw)
            prima_usd = parse_amount(prima_raw)

            persons.append({
                "item_number": effective_item,
                "nombre_completo": nombre[:250],
                "documento_identidad": ci[:50] if ci else None,
                "parentesco_categoria": "TITULAR",
                "cargo_ocupacion": None,
                "suma_asegurada_usd": suma_usd,
                "prima_usd": prima_usd,
                "raw_metadata": {"source": "markdown_table", "raw_cells": cells},
            })
            item_counter += 1

    return persons

# Get documents of CAC-LPR0687876
cur.execute("""
    SELECT p.id::text, p.file_name, p.envelope_id::text, pe.numero_poliza, prm.markdown_content
    FROM policies p
    JOIN policy_envelopes pe ON p.envelope_id = pe.id
    JOIN policy_raw_md prm ON p.id = prm.policy_id
    WHERE pe.numero_poliza ILIKE '%CAC-LPR0687876%';
""")
docs = cur.fetchall()

print(f"Encontrados {len(docs)} documentos con contenido markdown.")
total_inserted = 0

insert_sql = """
    INSERT INTO policy_insured_persons (
        policy_id, envelope_id, item_number, nombre_completo,
        documento_identidad, parentesco_categoria, suma_asegurada_usd,
        prima_usd, raw_metadata, updated_at
    ) VALUES (
        %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP
    )
    ON CONFLICT (policy_id, item_number) DO UPDATE SET
        nombre_completo = EXCLUDED.nombre_completo,
        documento_identidad = EXCLUDED.documento_identidad,
        suma_asegurada_usd = EXCLUDED.suma_asegurada_usd,
        prima_usd = EXCLUDED.prima_usd,
        updated_at = CURRENT_TIMESTAMP;
"""

for pid, fname, env_id, num, md in docs:
    persons = parse_tables(md)
    if persons:
        print(f" -> {fname}: {len(persons)} personas parseadas.")
        cur.execute("DELETE FROM policy_insured_persons WHERE policy_id = %s::uuid;", (pid,))
        for p in persons:
            cur.execute(
                insert_sql,
                (
                    pid,
                    env_id,
                    p["item_number"],
                    p["nombre_completo"],
                    p["documento_identidad"],
                    p["parentesco_categoria"],
                    p["suma_asegurada_usd"],
                    p["prima_usd"],
                    json.dumps(p["raw_metadata"], ensure_ascii=False),
                )
            )
        total_inserted += len(persons)
    else:
        print(f" -> {fname}: 0 personas en tablas.")

print(f"\n[ÉXITO] Total de personas insertadas: {total_inserted}")

cur.execute("SELECT COUNT(*) FROM policy_insured_persons;")
print(f"Registros totales actuales en policy_insured_persons: {cur.fetchone()[0]}")

cur.execute("""
    SELECT item_number, nombre_completo, documento_identidad, suma_asegurada_usd, prima_usd
    FROM policy_insured_persons
    ORDER BY item_number ASC
    LIMIT 10;
""")
print("\nMuestra de asegurados en la tabla:")
for r in cur.fetchall():
    print(f"  #{r[0]}: {r[1]} | {r[2]} | Suma: Bs. {r[3]:,.2f} | Prima: Bs. {r[4]:,.2f}")

conn.close()

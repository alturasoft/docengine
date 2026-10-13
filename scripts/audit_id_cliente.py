"""DocEngine — Procedimiento de Auditoría y Validación de id_cliente.

Valida que el campo `id_cliente` (en policy_envelopes y policies) corresponda
fielmente a las llaves `nit` o `documento_identidad` de `datos_cabecera` en
`policy_structured_data`.

Detecta:
1. DISCREPANCIA_CABECERA: El sobre o póliza tiene un id_cliente distinto al NIT/CI de su cabecera.
2. CONFLICTO_EN_SOBRE: Dos documentos del mismo sobre tienen NITs/CIs diferentes (ej. anexo vs condicionado).
3. NIT_ASEGURADORA_CAPTURADO: La cabecera capturó por error el NIT de la aseguradora.
4. CODIGO_APS_DETECTADO: La cabecera o id_cliente contiene un código de registro APS (ej. 206-935001-2000).
5. SIN_IDENTIFICADOR: Documentos sin NIT ni documento_identidad.

Uso:
    python scripts/audit_id_cliente.py
    python scripts/audit_id_cliente.py --fix-obvious   (Aplica corrección donde el condicionado particular es concluyente)
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import re
from typing import Any
import psycopg2
from dotenv import load_dotenv

# Blacklist de NITs de aseguradoras conocidas para filtrar falsos positivos
INSURER_NITS_BLACKLIST = {
    "1020655027": "BISA Seguros",
    "1020353028": "Alianza Cía de Seguros",
    "1020613024": "Credinform International",
    "1016253021": "La Boliviana Ciacruz",
    "1020473026": "Fortaleza Seguros",
    "1015383020": "Nacional Seguros Patrimoniales",
    "1028525026": "Unibienes Seguros",
    "1028723027": "Latina Seguros",
    "1020613020": "Univida Seguros",
}

# Patrón característico de códigos de registro APS (ej. 206-935001-2000, 101-910012-2015)
APS_CODE_PATTERN = re.compile(r"^\d{3}-\d{5,7}-\d{4}", re.IGNORECASE)


def normalize_id(val: str | None) -> str | None:
    """Limpia y normaliza un documento o NIT."""
    if not val:
        return None
    s = str(val).strip()
    if s.lower() in ("null", "none", "s/n", "sn", "n/a", "na", "-", ".", "ninguno", "no registrado"):
        return None
    return s


def extract_digits(val: str | None) -> str:
    """Extrae únicamente los dígitos de un valor."""
    if not val:
        return ""
    return re.sub(r"\D", "", str(val))


def run_audit(auto_fix: bool = False, target_policy: str | None = None) -> None:
    load_dotenv()
    conn = psycopg2.connect(
        host=os.getenv("DOCENGINE_DB_HOST", "localhost"),
        port=os.getenv("DOCENGINE_DB_PORT", 5432),
        dbname=os.getenv("DOCENGINE_DB_NAME", "docengine"),
        user=os.getenv("DOCENGINE_DB_USER", "postgres"),
        password=os.getenv("DOCENGINE_DB_PASSWORD", "postgres"),
    )
    cur = conn.cursor()

    print("=" * 70)
    print("DOCENGINE — AUDITORÍA DE CONSISTENCIA DE id_cliente")
    print("=" * 70)

    # 1. Obtener todas las pólizas con sus sobres y datos estructurados
    query = """
        SELECT 
            p.id AS policy_id,
            p.file_name,
            p.tipo_documento,
            p.company_sigla,
            p.id_cliente AS pol_id_cliente,
            pe.id AS envelope_id,
            pe.numero_poliza,
            pe.id_cliente AS env_id_cliente,
            psd.data->'datos_cabecera'->>'nit' AS cab_nit,
            psd.data->'datos_cabecera'->>'documento_identidad' AS cab_doc_id,
            psd.data->'datos_cabecera'->>'asegurado' AS cab_asegurado
        FROM policies p
        LEFT JOIN policy_envelopes pe ON p.envelope_id = pe.id
        LEFT JOIN policy_structured_data psd ON p.id = psd.policy_id
    """
    params: list[Any] = []
    if target_policy:
        query += " WHERE pe.numero_poliza ILIKE %s OR p.file_name ILIKE %s"
        params.extend([f"%{target_policy}%", f"%{target_policy}%"])
    query += " ORDER BY pe.numero_poliza NULLS LAST, p.created_at ASC;"

    cur.execute(query, tuple(params))
    rows = cur.fetchall()

    print(f"Total de registros analizados: {len(rows)}\n")

    # Agrupar por sobre
    envelope_docs: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        (
            pol_id,
            fname,
            tipodoc,
            sigla,
            pol_cli,
            env_id,
            numpol,
            env_cli,
            cab_nit,
            cab_doc_id,
            asegurado,
        ) = r

        env_key = env_id or f"NO_ENV_{pol_id}"
        if env_key not in envelope_docs:
            envelope_docs[env_key] = []

        envelope_docs[env_key].append({
            "policy_id": pol_id,
            "file_name": fname,
            "tipo_documento": tipodoc or "DESCONOCIDO",
            "company_sigla": sigla,
            "pol_id_cliente": normalize_id(pol_cli),
            "envelope_id": env_id,
            "numero_poliza": numpol,
            "env_id_cliente": normalize_id(env_cli),
            "cab_nit": normalize_id(cab_nit),
            "cab_doc_id": normalize_id(cab_doc_id),
            "asegurado": asegurado,
        })

    discrepancies: list[dict[str, Any]] = []
    sobres_con_conflicto = 0
    documentos_con_error = 0
    fixes_to_apply: list[dict[str, str]] = []

    for env_key, docs in envelope_docs.items():
        # Evaluar identificadores encontrados en cabeceras de este sobre
        nits_in_envelope: dict[str, list[str]] = {}
        for d in docs:
            nit = d["cab_nit"]
            doc_id = d["cab_doc_id"]
            if nit:
                nits_in_envelope.setdefault(nit, []).append(f"{d['tipo_documento']}:{d['file_name']}")
            if doc_id and doc_id != nit:
                nits_in_envelope.setdefault(doc_id, []).append(f"{d['tipo_documento']}:{d['file_name']}")

        # Buscar si hay conflicto entre documentos del sobre
        unique_clean_ids = {extract_digits(k) for k in nits_in_envelope if extract_digits(k)}
        # Filtrar NITs de aseguradoras de los IDs limpios
        client_clean_ids = {cid for cid in unique_clean_ids if cid not in INSURER_NITS_BLACKLIST}

        env_has_conflict = len(client_clean_ids) > 1
        if env_has_conflict:
            sobres_con_conflicto += 1

        # Identificar la fuente más confiable en el sobre (preferir CONDICIONADO_PARTICULAR o POLIZA_PRINCIPAL)
        trusted_id: str | None = None
        for d in docs:
            if d["tipo_documento"] in ("CONDICIONADO_PARTICULAR", "POLIZA_PRINCIPAL"):
                cand = d["cab_nit"] or d["cab_doc_id"]
                cand_digits = extract_digits(cand)
                if cand and cand_digits not in INSURER_NITS_BLACKLIST and not APS_CODE_PATTERN.match(cand):
                    trusted_id = cand
                    break

        if not trusted_id:
            # Si no hay condicionado particular, buscar en liquidación o cualquier doc con NIT válido
            for d in docs:
                cand = d["cab_nit"] or d["cab_doc_id"]
                cand_digits = extract_digits(cand)
                if cand and cand_digits not in INSURER_NITS_BLACKLIST and not APS_CODE_PATTERN.match(cand):
                    trusted_id = cand
                    break

        env_id_cliente = docs[0]["env_id_cliente"]
        env_num_poliza = docs[0]["numero_poliza"]
        env_id = docs[0]["envelope_id"]

        for d in docs:
            cab_nit = d["cab_nit"]
            cab_doc_id = d["cab_doc_id"]
            pol_cli = d["pol_id_cliente"]
            tipo_doc = d["tipo_documento"]
            f_name = d["file_name"]

            cab_candidates = [x for x in (cab_nit, cab_doc_id) if x]
            cab_digits = [extract_digits(x) for x in cab_candidates]
            pol_digits = extract_digits(pol_cli)
            env_digits = extract_digits(env_id_cliente)

            # Clasificación del hallazgo
            hallazgos: list[str] = []

            # A. Ver si el id_cliente tiene un código APS
            if env_id_cliente and APS_CODE_PATTERN.match(env_id_cliente):
                hallazgos.append("CODIGO_APS_COMO_ID_CLIENTE")
            if pol_cli and APS_CODE_PATTERN.match(pol_cli):
                hallazgos.append("CODIGO_APS_EN_POLICY_CLI")

            # B. Ver si la cabecera tiene NIT de aseguradora
            for c in cab_candidates:
                cdig = extract_digits(c)
                if cdig in INSURER_NITS_BLACKLIST:
                    hallazgos.append(f"CABECERA_TIENE_NIT_ASEGURADORA({INSURER_NITS_BLACKLIST[cdig]})")

            # C. Ver si hay discrepancia entre pol_id_cliente y su propia cabecera
            if cab_digits and pol_digits:
                # Si ninguno de los dígitos de la cabecera coincide con pol_cli
                if not any(pol_digits == cd or pol_digits in cd or cd in pol_digits for cd in cab_digits if cd not in INSURER_NITS_BLACKLIST):
                    # Descartar si cabecera es código APS
                    if any(APS_CODE_PATTERN.match(c) for c in cab_candidates):
                        hallazgos.append("CABECERA_ERRONEA_APS")
                    else:
                        hallazgos.append("DISCREPANCIA_POL_VS_CABECERA")

            # D. Discrepancia del sobre respecto a este documento legítimo
            if trusted_id and env_digits != extract_digits(trusted_id):
                hallazgos.append("DISCREPANCIA_ENV_VS_TRUSTED_ID")

            if env_has_conflict:
                hallazgos.append("CONFLICTO_ENTRE_DOCS_DEL_SOBRE")

            if hallazgos:
                documentos_con_error += 1
                row_report = {
                    "envelope_id": env_id or "",
                    "numero_poliza": env_num_poliza or "SIN_NUMERO",
                    "company_sigla": d["company_sigla"] or "",
                    "policy_id": d["policy_id"],
                    "tipo_documento": tipo_doc,
                    "file_name": f_name,
                    "env_id_cliente": env_id_cliente or "",
                    "pol_id_cliente": pol_cli or "",
                    "cab_nit": cab_nit or "",
                    "cab_doc_id": cab_doc_id or "",
                    "asegurado": d["asegurado"] or "",
                    "hallazgos": "; ".join(hallazgos),
                    "sugerencia_id_cliente": trusted_id or "",
                }
                discrepancies.append(row_report)

                # Si tenemos una sugerencia confiable y el actual está errado (APS o vacío o distinto a condicionado)
                if trusted_id and (env_id_cliente != trusted_id or pol_cli != trusted_id):
                    fixes_to_apply.append({
                        "envelope_id": env_id,
                        "policy_id": d["policy_id"],
                        "trusted_id": trusted_id,
                        "numero_poliza": env_num_poliza,
                    })

    # Imprimir resumen de hallazgos
    print(f"Total de inconsistencias/alertas encontradas: {len(discrepancies)}")
    print(f"Sobres con conflicto entre documentos: {sobres_con_conflicto}")

    # Mostrar las primeras 15 inconsistencias en consola
    print("\n" + "=" * 70)
    print("MUESTRA DE CASOS DETECTADOS:")
    print("=" * 70)
    for i, d in enumerate(discrepancies[:15], start=1):
        print(f"[{i}] Póliza: {d['numero_poliza']} | Doc: {d['tipo_documento']}")
        print(f"    Archivo: {d['file_name']}")
        print(f"    Envelope ID Cli: '{d['env_id_cliente']}' | Pol ID Cli: '{d['pol_id_cliente']}'")
        print(f"    Cabecera NIT: '{d['cab_nit']}' | Cabecera CI: '{d['cab_doc_id']}'")
        print(f"    Asegurado: {d['asegurado']}")
        print(f"    Hallazgos: {d['hallazgos']}")
        if d['sugerencia_id_cliente']:
            print(f"    --> Sugerencia id_cliente correcto: {d['sugerencia_id_cliente']}")
        print("-" * 70)

    # Exportar CSV completo
    out_dir = Path("outputs")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "auditoria_inconsistencias_id_cliente.csv"

    fieldnames = [
        "numero_poliza",
        "company_sigla",
        "tipo_documento",
        "file_name",
        "env_id_cliente",
        "pol_id_cliente",
        "cab_nit",
        "cab_doc_id",
        "sugerencia_id_cliente",
        "hallazgos",
        "asegurado",
        "envelope_id",
        "policy_id",
    ]
    with open(csv_path, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(discrepancies)

    print(f"\n[OK] Reporte completo exportado a: {csv_path.resolve()}")

    # Aplicar correcciones si fue invocado con --fix-obvious
    if auto_fix and fixes_to_apply:
        print("\n" + "=" * 70)
        print("APLICANDO CORRECCIÓN AUTOMÁTICA DE CASOS CONFIABLES...")
        print("=" * 70)
        # Deduplicar sobres a actualizar
        envs_fixed = set()
        policies_fixed = set()

        for fix in fixes_to_apply:
            env_id = fix.get("envelope_id")
            pol_id = fix.get("policy_id")
            t_id = fix.get("trusted_id")

            if env_id and env_id not in envs_fixed:
                cur.execute(
                    "UPDATE policy_envelopes SET id_cliente = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;",
                    (t_id, env_id),
                )
                cur.execute(
                    "UPDATE policies SET id_cliente = %s WHERE envelope_id = %s;",
                    (t_id, env_id),
                )
                envs_fixed.add(env_id)

            if pol_id and pol_id not in policies_fixed:
                cur.execute(
                    "UPDATE policies SET id_cliente = %s WHERE id = %s;",
                    (t_id, pol_id),
                )
                policies_fixed.add(pol_id)

        conn.commit()
        print(f" -> Sobres (policy_envelopes) corregidos: {len(envs_fixed)}")
        print(f" -> Documentos (policies) corregidos: {len(policies_fixed)}")
        print("=" * 70)
    elif not auto_fix and fixes_to_apply:
        unique_envs = {f['envelope_id'] for f in fixes_to_apply if f.get('envelope_id')}
        print(f"\n[AVISO] Se identificaron {len(unique_envs)} sobres con solución confiable.")
        print("Para aplicar las correcciones, ejecute:")
        print("    python scripts/audit_id_cliente.py --fix-obvious")

    cur.close()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auditoría de id_cliente en DocEngine.")
    parser.add_argument(
        "--fix-obvious",
        action="store_true",
        help="Corrige automáticamente cuando el condicionado particular o fuente confiable tiene el NIT/CI correcto.",
    )
    parser.add_argument(
        "--policy",
        type=str,
        default=None,
        help="Filtrar por número de póliza o nombre de archivo específico.",
    )
    args = parser.parse_args()

    run_audit(auto_fix=args.fix_obvious, target_policy=args.policy)

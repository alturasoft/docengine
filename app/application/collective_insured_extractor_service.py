"""DocEngine — Application Service: Collective Insured Extractor Service.

[ADITIVO] Extrae de forma determinista y de alta velocidad (0% alucinación, 0 costo)
la nómina estructurada de personas en pólizas colectivas (Salud, Accidentes Personales,
Vida en Grupo) a partir de los fragmentos textuales y tablas ya indexados en la base de datos.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.models.query_models import RetrievedChunk
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_insured_persons_repository import PgInsuredPersonsRepository
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class CollectiveInsuredExtractorService:
    """Servicio de extracción determinista y consulta de nóminas de personas aseguradas."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        insured_repo: PgInsuredPersonsRepository | None = None,
    ) -> None:
        self._db = db_manager
        self._repo = insured_repo or PgInsuredPersonsRepository(db_manager)

    def extract_and_save_policy_insured(
        self,
        policy_id: str,
        envelope_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Analiza el contenido de la póliza, extrae todos los asegurados y los guarda en la BD."""
        chunks = self._load_policy_chunks(policy_id)
        raw_md = self._load_raw_markdown(policy_id)

        if not chunks and not raw_md:
            return []

        if not envelope_id:
            envelope_id = self._lookup_envelope_id(policy_id)

        persons = self._parse_persons_from_content(chunks, raw_md)
        if persons:
            self._repo.save_insured_persons(
                policy_id=policy_id,
                envelope_id=envelope_id,
                persons=persons,
            )
            logger.info(
                "Nómina de asegurados extraída y guardada exitosamente",
                policy_id=policy_id,
                total_asegurados=len(persons),
            )
        return persons

    def get_or_extract_insured(
        self,
        policy_id: str,
        envelope_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Recupera la nómina de asegurados desde la BD, o la extrae al vuelo si no existe."""
        persons = self._repo.get_persons_for_policy(policy_id)
        if not persons and envelope_id:
            persons = self._repo.get_persons_for_envelope(envelope_id)

        if not persons:
            persons = self.extract_and_save_policy_insured(policy_id, envelope_id)

        return persons

    def format_insured_summary_chunk(
        self,
        policy_id: str | None = None,
        envelope_id: str | None = None,
        sample_limit: int | None = None,
    ) -> RetrievedChunk | None:
        """Genera un fragmento estructurado enriquecido con el resumen y la nómina de asegurados."""
        summary = self._repo.get_insured_summary(
            policy_id=policy_id,
            envelope_id=envelope_id,
            sample_limit=sample_limit,
        )

        # Si aún no estaba extraída, intentar extraerla
        if not summary and policy_id:
            self.extract_and_save_policy_insured(policy_id, envelope_id)
            summary = self._repo.get_insured_summary(
                policy_id=policy_id,
                envelope_id=envelope_id,
                sample_limit=sample_limit,
            )

        if not summary or summary.get("total_asegurados", 0) == 0:
            return None

        total = summary["total_asegurados"]
        val_total = summary["total_suma_asegurada_usd"]
        prima_total = summary["total_prima_usd"]
        edad_prom = summary.get("edad_promedio")
        categorias = summary["distribucion_categoria"]
        generos = summary["distribucion_genero"]
        muestra = summary["muestra"]

        lines: list[str] = [
            f"### NÓMINA OFICIAL Y COMPLETA DE ASEGURADOS (PÓLIZA COLECTIVA - {total} PERSONAS)",
            f"- **Total de Personas Aseguradas:** {total} personas.",
        ]
        if val_total > 0:
            lines.append(f"- **Capital / Suma Asegurada Total Acumulada:** $us. {val_total:,.2f}")
        if prima_total > 0:
            lines.append(f"- **Prima Total Emitida (Asegurados):** $us. {prima_total:,.2f}")
        if edad_prom:
            lines.append(f"- **Edad Promedio:** {edad_prom} años.")

        # Desglose por categoría / parentesco
        if categorias:
            cat_str = ", ".join(f"{c}: {cnt}" for c, cnt in list(categorias.items())[:6])
            lines.append(f"- **Distribución por Categoría:** {cat_str}")

        # Desglose por género
        if generos and len(generos) > 1:
            gen_str = ", ".join(f"{g}: {cnt}" for g, cnt in list(generos.items())[:4])
            lines.append(f"- **Distribución por Género:** {gen_str}")

        # Enlace para exportar
        target_pid = policy_id
        target_eid = envelope_id
        if target_pid:
            lines.append(
                f"- **Descarga en Excel / CSV:** [Descargar Nómina Completa en Excel (CSV)](/api/v1/policies/{target_pid}/insured-persons/export)"
            )
        elif target_eid:
            lines.append(
                f"- **Descarga en Excel / CSV:** [Descargar Nómina Completa en Excel (CSV)](/api/v1/envelopes/{target_eid}/insured-persons/export)"
            )

        if len(muestra) >= total:
            lines.append(f"\n#### NÓMINA COMPLETA DE LOS {total} ASEGURADOS:")
            lines.append(
                "[INSTRUCCIÓN CRÍTICA: A continuación se detalla la nómina completa de todos los asegurados. "
                "Presenta esta nómina completa en formato de tabla o lista ordenada para el usuario, sin omitir datos ni recortarla a una muestra.]"
            )
        else:
            lines.append(f"\n#### Muestra de la nómina de asegurados ({len(muestra)} de {total} personas):")

        lines.append("| Ítem | Nombre Completo | C.I. / Documento | Categoría / Parentesco | Edad | Cargo / Actividad | Suma Asegurada ($us.) |")
        lines.append("|------|-----------------|------------------|------------------------|------|-------------------|------------------------|")

        for p in muestra:
            it = p.get("item_number", "-")
            nm = p.get("nombre_completo") or "ASEGURADO NOMINADO"
            ci = p.get("documento_identidad") or "-"
            cat = p.get("parentesco_categoria") or "TITULAR"
            ed = str(p.get("edad")) if p.get("edad") is not None else "-"
            cg = p.get("cargo_ocupacion") or "-"
            sa = f"{p.get('suma_asegurada_usd', 0.0):,.2f}" if p.get("suma_asegurada_usd", 0.0) > 0 else "-"
            lines.append(f"| {it} | {nm} | {ci} | {cat} | {ed} | {cg} | {sa} |")

        if total > len(muestra):
            lines.append(
                f"\n*Nota: La póliza registra un total de {total} asegurados. La nómina completa con todos los registros puede descargarse desde el enlace de exportación CSV.*"
            )

        content = "\n".join(lines)
        return RetrievedChunk(
            chunk_id=f"insured_summary_{policy_id or envelope_id}",
            policy_id=policy_id or "insured",
            chunk_index=-3,
            chunk_content=content,
            metadata_json={
                "source": "structured_database",
                "tipo_documento": "NOMINA_ASEGURADOS",
                "section": "NOMINA_COLECTIVA_PERSONAS",
                "document_label": f"[NÓMINA COLECTIVA: {total} ASEGURADOS]",
            },
            similarity_score=1.0,
        )

    # -----------------------------------------------------------------------
    # Parseo determinista de personas
    # -----------------------------------------------------------------------

    def _parse_persons_from_content(
        self,
        chunks: list[dict[str, Any]],
        raw_md: str,
    ) -> list[dict[str, Any]]:
        """Intenta extraer asegurados mediante tablas Markdown o fichas de anexos."""
        # Estrategia 1: Tablas Markdown de asegurados
        persons = self._parse_tables_from_markdown(raw_md)
        if persons:
            return persons

        # Estrategia 2: Fichas individuales por ítems o bloques en chunks
        persons = self._parse_blocks_from_chunks(chunks)
        if persons:
            return persons

        # Estrategia 3: Pólizas con declaración global de colectivo (ej. "709 Personas según planilla adjunta")
        global_person = self._parse_global_collective_declaration(raw_md)
        if global_person:
            return [global_person]

        return []

    def _parse_tables_from_markdown(self, raw_md: str) -> list[dict[str, Any]]:
        """Detecta y parsea tablas de nómina de asegurados en Markdown."""
        if not raw_md or "|" not in raw_md:
            return []

        # Extraer bloques de tablas basados en líneas consecutivas que inicien con pipe '|'
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

        persons: list[dict[str, Any]] = []
        item_counter = 1

        for table_lines in tables:
            header_line = table_lines[0]
            header_cells = [c.strip().upper() for c in header_line.strip().strip("|").split("|")]

            # Verificar si parece tabla de personas
            name_idx: int | None = None
            ci_idx: int | None = None
            cat_idx: int | None = None
            age_idx: int | None = None
            cargo_idx: int | None = None
            val_idx: int | None = None
            prima_idx: int | None = None

            for i, h in enumerate(header_cells):
                if any(w in h for w in ["NOMBRE", "ASEGURADO", "BENEFICIARIO", "EMPLEADO", "AFILIADO"]) and name_idx is None:
                    name_idx = i
                elif any(w in h for w in ["C.I", "CI", "DOC", "DOCUMENTO", "CARNET", "IDENTIDAD", "DNI", "PASAPORTE"]) and ci_idx is None:
                    ci_idx = i
                elif any(w in h for w in ["PARENTESCO", "CATEGORIA", "TIPO", "RELACION", "FIGURA"]) and cat_idx is None:
                    cat_idx = i
                elif any(w in h for w in ["EDAD", "NACIMIENTO", "FEC. NAC"]) and age_idx is None:
                    age_idx = i
                elif any(w in h for w in ["CARGO", "OCUPACION", "PUESTO", "PROFESION"]) and cargo_idx is None:
                    cargo_idx = i
                elif any(w in h for w in ["SUMA", "VALOR", "CAPITAL", "COBERTURA", "MONTO", "M. ACC", "M.ACC", "MUERTE"]) and val_idx is None:
                    val_idx = i
                elif any(w in h for w in ["PRIMA", "PRIMA T", "PRIMA TOTAL"]) and prima_idx is None:
                    prima_idx = i

            # Debe haber al menos una columna de nombre o de CI/Asegurado
            if name_idx is None and ci_idx is None:
                continue

            # Parsear filas de datos (a partir de la línea 2, omitiendo separador)
            for row_line in table_lines[2:]:
                cells = [c.strip() for c in row_line.strip().strip("|").split("|")]
                if not cells:
                    continue

                nombre = cells[name_idx] if (name_idx is not None and name_idx < len(cells)) else ""
                ci = cells[ci_idx] if (ci_idx is not None and ci_idx < len(cells)) else None
                cat = cells[cat_idx] if (cat_idx is not None and cat_idx < len(cells)) else "TITULAR"
                edad_raw = cells[age_idx] if (age_idx is not None and age_idx < len(cells)) else None
                cargo = cells[cargo_idx] if (cargo_idx is not None and cargo_idx < len(cells)) else None
                val_raw = cells[val_idx] if (val_idx is not None and val_idx < len(cells)) else "0"
                prima_raw = cells[prima_idx] if (prima_idx is not None and prima_idx < len(cells)) else "0"

                # Filtrar encabezados repetidos o líneas vacías
                if not nombre or nombre.upper() in ["TOTAL", "SUBTOTAL", "NOMBRE", "---", "-"]:
                    continue
                if len(nombre) < 3 or nombre.replace(".", "").isdigit():
                    continue

                # Extraer número de ítem si viene como prefijo en el nombre (ej. "1 .- FLORES...")
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

                # Extraer edad si es numérica
                edad: int | None = None
                fec_nac: str | None = None
                if edad_raw:
                    if edad_raw.isdigit() and 0 < int(edad_raw) < 120:
                        edad = int(edad_raw)
                    elif re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", edad_raw):
                        fec_nac = edad_raw

                # Normalizar suma asegurada y prima
                suma_usd = self._parse_amount(val_raw)
                prima_usd = self._parse_amount(prima_raw)

                persons.append({
                    "item_number": effective_item,
                    "nombre_completo": nombre[:250],
                    "documento_identidad": ci[:50] if ci else None,
                    "fecha_nacimiento": fec_nac,
                    "edad": edad,
                    "genero": None,
                    "parentesco_categoria": cat[:100] if cat else "TITULAR",
                    "cargo_ocupacion": cargo[:150] if cargo else None,
                    "suma_asegurada_usd": suma_usd,
                    "prima_usd": prima_usd,
                    "raw_metadata": {"source": "markdown_table", "raw_cells": cells},
                })
                item_counter += 1

        return persons

    def _parse_blocks_from_chunks(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Extrae personas a partir de fichas técnicas o certificados repetitivos."""
        persons: list[dict[str, Any]] = []
        item_counter = 1

        for c in chunks:
            content = c.get("content", "")
            # Buscar patrones como "ASEGURADO: <Nombre>", "C.I.: <Doc>"
            asegurado_match = re.search(r"(?:NOMBRE\s+DEL\s+)?ASEGURADO(?:\s+TITULAR)?[:\s]+([^\n\r|#]+)", content, re.I)
            if not asegurado_match:
                continue

            nombre = asegurado_match.group(1).strip()
            # Descartar empresas o tomadores jurídicos si es un encabezado global
            if any(term in nombre.upper() for term in ["S.A.", "S.R.L.", "LTDA.", "COMPAÑIA", "BANCO", "EMPRESA"]):
                continue
            if len(nombre) < 4:
                continue

            ci_match = re.search(r"(?:C\.?I\.?|CARNET|DOCUMENTO(?:\s+DE)?\s+IDENTIDAD)[:\s#]+([A-Za-z0-9\-]+)", content, re.I)
            ci = ci_match.group(1).strip() if ci_match else None

            fec_match = re.search(r"(?:FECHA\s+DE\s+NACIMIENTO|FEC\.?\s*NAC\.?)[:\s]+(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", content, re.I)
            fec = fec_match.group(1).strip() if fec_match else None

            parentesco_match = re.search(r"(?:PARENTESCO|CATEGORIA|CONDICION)[:\s]+([^\n\r|#]+)", content, re.I)
            parentesco = parentesco_match.group(1).strip() if parentesco_match else "TITULAR"

            val_match = re.search(r"(?:VALOR\s+ASEGURADO|SUMA\s+ASEGURADA)[:\s]+\$us\.?\s*([\d,]+(?:\.\d+)?)", content, re.I)
            val_usd = 0.0
            if val_match:
                try:
                    val_usd = float(val_match.group(1).replace(",", ""))
                except ValueError:
                    val_usd = 0.0

            # Evitar duplicados por nombre y CI
            if any(p["nombre_completo"] == nombre and p["documento_identidad"] == ci for p in persons):
                continue

            persons.append({
                "item_number": item_counter,
                "nombre_completo": nombre[:250],
                "documento_identidad": ci[:50] if ci else None,
                "fecha_nacimiento": fec,
                "edad": None,
                "genero": None,
                "parentesco_categoria": parentesco[:100],
                "cargo_ocupacion": None,
                "suma_asegurada_usd": val_usd,
                "prima_usd": 0.0,
                "raw_metadata": {"source": "chunk_certificate_block"},
            })
            item_counter += 1

        return persons

    def _parse_global_collective_declaration(self, raw_md: str) -> dict[str, Any] | None:
        """Detecta pólizas colectivas declaradas como grupo/planilla global (innominadas o adjuntas)."""
        if not raw_md:
            return None

        m = re.search(
            r"MATERIA\s+DEL\s+SEGURO[:\s]+([0-9]{1,4})\s+(?:personas|asegurados|titulares|afiliados|empleados|trabajadores)[^\n\r.]*",
            raw_md,
            re.I,
        )
        if not m:
            m = re.search(
                r"([0-9]{1,4})\s+(?:personas|asegurados|titulares|afiliados|empleados|trabajadores)\s+(?:seg[uú]n\s+detalle|seg[uú]n\s+planilla|dependientes)",
                raw_md,
                re.I,
            )

        if m:
            full_text = m.group(0).strip()
            cant_match = re.search(r"\b(\d+)\b", full_text)
            cant = int(cant_match.group(1)) if cant_match else 1
            if cant >= 1:
                return {
                    "item_number": 1,
                    "nombre_completo": f"COLECTIVIDAD DE {cant} PERSONAS CUBIERTAS (SEGÚN PLANILLA/NÓMINA)",
                    "documento_identidad": "NÓMINA ADJUNTA",
                    "fecha_nacimiento": None,
                    "edad": None,
                    "genero": None,
                    "parentesco_categoria": "COLECTIVO / PLANILLA",
                    "cargo_ocupacion": full_text[:150],
                    "suma_asegurada_usd": 0.0,
                    "prima_usd": 0.0,
                    "raw_metadata": {"source": "global_collective_declaration", "declaration": full_text, "total_declarado": cant},
                }

        return None

    @staticmethod
    def _parse_amount(raw_val: str | None) -> float:
        """Parsea montos monetarios soportando formatos 100,000.00 y 100.000,00."""
        if not raw_val:
            return 0.0
        s = str(raw_val).strip()
        if "." in s and "," in s:
            if s.rfind(",") > s.rfind("."):
                # Formato boliviano/latam: 100.000,00
                s = s.replace(".", "").replace(",", ".")
            else:
                # Formato US: 100,000.00
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

    # -----------------------------------------------------------------------
    # Carga auxiliar de datos
    # -----------------------------------------------------------------------

    def _load_policy_chunks(self, policy_id: str) -> list[dict[str, Any]]:
        """Carga los fragmentos textuales de la póliza ordenados por chunk_index."""
        sql = """
            SELECT chunk_index, chunk_content, metadata_json
            FROM policy_chunks
            WHERE policy_id = %s::uuid
            ORDER BY chunk_index ASC;
        """
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (policy_id,))
                return [
                    {
                        "index": row[0],
                        "content": row[1],
                        "metadata": row[2] or {},
                    }
                    for row in cur.fetchall()
                ]

    def _load_raw_markdown(self, policy_id: str) -> str:
        """Carga el texto Markdown completo extraído por Docling."""
        sql = "SELECT markdown_content FROM policy_raw_md WHERE policy_id = %s::uuid;"
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (policy_id,))
                row = cur.fetchone()
                return str(row[0]) if row and row[0] else ""

    def _lookup_envelope_id(self, policy_id: str) -> str | None:
        """Obtiene el envelope_id correspondiente a una póliza."""
        sql = "SELECT envelope_id::text FROM policies WHERE id = %s::uuid;"
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (policy_id,))
                row = cur.fetchone()
                return str(row[0]) if row and row[0] else None

"""DocEngine — Application Service: Fleet Extractor Service.

[ADITIVO] Extrae de forma determinista y de alta velocidad (0% alucinación, 0 costo)
la nómina estructurada de vehículos en pólizas colectivas de flotas a partir
de los fragmentos textuales ya indexados en la base de datos.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.models.query_models import RetrievedChunk
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_fleet_repository import PgFleetRepository
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class FleetExtractorService:
    """Servicio de extracción determinista y consulta de nóminas de flotas de vehículos."""

    def __init__(
        self,
        db_manager: DatabaseManager,
        fleet_repo: PgFleetRepository | None = None,
    ) -> None:
        self._db = db_manager
        self._repo = fleet_repo or PgFleetRepository(db_manager)

    def extract_and_save_policy_fleet(
        self,
        policy_id: str,
        envelope_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Analiza los fragmentos de la póliza, extrae todos los vehículos y los guarda en la BD."""
        chunks = self._load_policy_chunks(policy_id)
        if not chunks:
            return []

        if not envelope_id:
            envelope_id = self._lookup_envelope_id(policy_id)

        vehicles = self._parse_vehicles_from_chunks(chunks)
        if vehicles:
            self._repo.save_vehicles(
                policy_id=policy_id,
                envelope_id=envelope_id,
                vehicles=vehicles,
            )
            logger.info(
                "Nómina de flota extraída y guardada exitosamente",
                policy_id=policy_id,
                total_vehiculos=len(vehicles),
            )
        return vehicles

    def get_or_extract_fleet(
        self,
        policy_id: str,
        envelope_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Recupera la nómina de vehículos desde la BD, o la extrae al vuelo si no existe."""
        vehicles = self._repo.get_vehicles_for_policy(policy_id)
        if not vehicles and envelope_id:
            vehicles = self._repo.get_vehicles_for_envelope(envelope_id)

        if not vehicles:
            vehicles = self.extract_and_save_policy_fleet(policy_id, envelope_id)

        return vehicles

    def format_fleet_summary_chunk(
        self,
        policy_id: str | None = None,
        envelope_id: str | None = None,
        sample_limit: int | None = None,
    ) -> RetrievedChunk | None:
        """Genera un fragmento estructurado enriquecido con el resumen y la nómina de vehículos."""
        summary = self._repo.get_fleet_summary(
            policy_id=policy_id,
            envelope_id=envelope_id,
            sample_limit=sample_limit,
        )

        # Si aún no estaba extraída, intentar extraerla
        if not summary and policy_id:
            self.extract_and_save_policy_fleet(policy_id, envelope_id)
            summary = self._repo.get_fleet_summary(
                policy_id=policy_id,
                envelope_id=envelope_id,
                sample_limit=sample_limit,
            )

        if not summary or summary.get("total_vehiculos", 0) == 0:
            return None

        total = summary["total_vehiculos"]
        val_total = summary["total_valor_asegurado_usd"]
        prima_total = summary["total_prima_usd"]
        tipos = summary["distribucion_tipo"]
        marcas = summary["distribucion_marca"]
        muestra = summary["muestra"]

        lines: list[str] = [
            f"### NÓMINA OFICIAL Y COMPLETA DE VEHÍCULOS ASEGURADOS (FLOTA - {total} UNIDADES)",
            f"- **Total de Vehículos / Ítems Asegurados:** {total} unidades.",
            f"- **Valor Asegurado Total de la Flota:** $us. {val_total:,.2f}",
        ]
        if prima_total > 0:
            lines.append(f"- **Prima Total Emitida (Vehículos):** $us. {prima_total:,.2f}")

        # Desglose por tipo
        tipos_str = ", ".join(f"{t}: {cnt}" for t, cnt in list(tipos.items())[:6])
        lines.append(f"- **Distribución por Tipo:** {tipos_str}")

        # Desglose por marca
        marcas_str = ", ".join(f"{m}: {cnt}" for m, cnt in list(marcas.items())[:6])
        lines.append(f"- **Distribución por Marca:** {marcas_str}")

        # Enlace para exportar
        target_pid = policy_id
        target_eid = envelope_id
        if target_pid:
            lines.append(f"- **Descarga en Excel / CSV:** [Descargar Nómina Completa en Excel (CSV)](/api/v1/policies/{target_pid}/fleet/export)")
        elif target_eid:
            lines.append(f"- **Descarga en Excel / CSV:** [Descargar Nómina Completa en Excel (CSV)](/api/v1/envelopes/{target_eid}/fleet/export)")

        if len(muestra) >= total:
            lines.append(f"\n#### NÓMINA COMPLETA DE TODOS LOS {total} VEHÍCULOS ASEGURADOS:")
            lines.append("[INSTRUCCIÓN CRÍTICA: A continuación se detalla la nómina completa de todos los vehículos asegurados. Presenta esta nómina completa en formato de tabla o lista ordenada para el usuario, sin recortarla a una muestra.]")
        else:
            lines.append(f"\n#### Muestra de la nómina de vehículos ({len(muestra)} de {total} unidades):")

        lines.append("| Ítem | Tipo | Marca | Modelo | Año | Placa | Chasis | Valor Asegurado ($us.) |")
        lines.append("|------|------|-------|--------|-----|-------|--------|------------------------|")

        for v in muestra:
            it = v.get("item_number", "-")
            tp = v.get("tipo_vehiculo") or "-"
            mk = v.get("marca") or "-"
            md = v.get("modelo") or "-"
            yr = v.get("anio") or "-"
            pl = v.get("placa") or "S/P"
            ch = (v.get("chasis") or "-")[:12]
            va = f"{v.get('valor_asegurado_usd', 0.0):,.2f}"
            lines.append(f"| {it} | {tp} | {mk} | {md} | {yr} | {pl} | {ch} | {va} |")

        if total > len(muestra):
            lines.append(
                f"\n*Nota: La nómina contiene en total {total} vehículos registrados. Puede descargarse completa desde el enlace de exportación CSV.*"
            )

        content = "\n".join(lines)
        return RetrievedChunk(
            chunk_id=f"fleet_summary_{policy_id or envelope_id}",
            policy_id=policy_id or "fleet",
            chunk_index=-2,
            chunk_content=content,
            metadata_json={
                "source": "structured_database",
                "tipo_documento": "NOMINA_FLOTA",
                "section": "NOMINA_VEHICULOS_FLOTA",
                "document_label": f"[NÓMINA DE FLOTA: {total} VEHÍCULOS]",
            },
            similarity_score=1.0,
        )

    def _parse_vehicles_from_chunks(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Parsea deterministamente las fichas técnicas individuales de vehículos."""
        # Agrupar texto contiguo por ítem
        # Los ítems inician con "ITEM <num>" o "## ITEM <num>"
        item_blocks: dict[int, list[str]] = {}
        current_item = 0

        for c in chunks:
            content = c.get("content", "")
            meta = c.get("metadata", {})
            h2 = meta.get("Header 2") or meta.get("Header 1") or ""

            # Buscar inicio de ítem en encabezado o en contenido
            item_match = re.search(r"\bITEM\s+(\d+)\b", f"{h2} {content[:120]}", re.I)
            if item_match:
                current_item = int(item_match.group(1))
                if current_item not in item_blocks:
                    item_blocks[current_item] = []

            if current_item > 0:
                item_blocks[current_item].append(content)

        # Si no encontramos con "ITEM <num>", buscar por "Ítem: <num>"
        if not item_blocks:
            for c in chunks:
                content = c.get("content", "")
                m = re.search(r"[íi]tem[:\s]+(\d+)", content, re.I)
                if m:
                    current_item = int(m.group(1))
                    if current_item not in item_blocks:
                        item_blocks[current_item] = []
                if current_item > 0:
                    item_blocks[current_item].append(content)

        vehicles: list[dict[str, Any]] = []
        for item_num, text_list in sorted(item_blocks.items()):
            block_text = "\n".join(text_list)
            v = self._parse_single_vehicle(item_num, block_text)
            if v:
                vehicles.append(v)

        return vehicles

    @staticmethod
    def _parse_single_vehicle(item_num: int, text: str) -> dict[str, Any] | None:
        """Extrae los atributos individuales de un bloque de texto de ítem."""
        # Limpiar caracteres repetidos para facilitar matching
        clean_text = re.sub(r"[ \t]+", " ", text)

        def extract_field(pattern: str) -> str | None:
            m = re.search(pattern, clean_text, re.I)
            if m:
                val = m.group(1).strip()
                # Filtrar valores vacíos o de plantilla
                if val.upper() not in ["NO ASIGNADO", "NO TIENE", "S/N", "NONE", "NULL", "-"]:
                    return val
            return None

        tipo = extract_field(r"TIPO\s+VEH[IÍ]CULO[:\s]+([^\n\r|#]+)")
        marca = extract_field(r"MARCA[:\s]+([^\n\r|#]+)")
        modelo = extract_field(r"MODELO[:\s]+([^\n\r|#]+)")
        anio_str = extract_field(r"A[ÑN]O[:\s]+(\d{4})")
        placa = extract_field(r"PLACA[:\s]+([A-Za-z0-9\-]+)")
        chasis = extract_field(r"CHASIS[:\s]+([A-Za-z0-9\-]+)")
        motor = extract_field(r"MOTOR[:\s]+([A-Za-z0-9\-]+)")
        color = extract_field(r"COLOR[:\s]+([^\n\r|#]+)")
        uso = extract_field(r"USO[:\s]+([^\n\r|#]+)")
        plaza = extract_field(r"PLAZA(?:\s+DE\s+CIRCULACI[OÓ]N)?[:\s]+([^\n\r|#]+)")

        # Valor Asegurado
        val_usd = 0.0
        val_match = re.search(r"VALOR\s+DEL\s+VEH[IÍ]CULO[:\s]+\$us\.?\s*([\d,]+(?:\.\d+)?)", clean_text, re.I)
        if not val_match:
            val_match = re.search(r"Valor\s+Asegurado(?:\s*\(\$us\.?\))?[:\s|]+([\d,]+(?:\.\d+)?)", clean_text, re.I)
        if val_match:
            try:
                val_usd = float(val_match.group(1).replace(",", ""))
            except ValueError:
                val_usd = 0.0

        # Prima individual
        prima_usd = 0.0
        prima_match = re.search(r"Prima\s+Individual\s+Emitida\s*[:\s]+\$us\.?\s*\*+([\d,]+(?:\.\d+)?)", clean_text, re.I)
        if prima_match:
            try:
                prima_usd = float(prima_match.group(1).replace(",", ""))
            except ValueError:
                prima_usd = 0.0

        # Si no encontramos ni placa, ni tipo, ni chasis, es un bloque espurio
        if not any([tipo, marca, modelo, placa, chasis, val_usd > 0]):
            return None

        # Limpiezas adicionales
        if tipo:
            tipo = tipo.split()[0].upper() if len(tipo.split()) > 0 else tipo.upper()
        if marca:
            marca = marca.split()[0].upper() if len(marca.split()) > 0 else marca.upper()
        if modelo:
            # Cortar si incluye texto subsiguiente
            modelo = re.split(r"A[ÑN]O|PLACA|COLOR|CHASIS", modelo, flags=re.I)[0].strip()

        anio = int(anio_str) if anio_str and anio_str.isdigit() else None

        return {
            "item_number": item_num,
            "tipo_vehiculo": tipo,
            "marca": marca,
            "modelo": modelo,
            "anio": anio,
            "placa": placa.upper() if placa else None,
            "chasis": chasis.upper() if chasis else None,
            "motor": motor.upper() if motor else None,
            "color": color.upper() if color else None,
            "uso": uso.upper() if uso else None,
            "plaza": plaza.upper() if plaza else None,
            "valor_asegurado_usd": val_usd,
            "prima_usd": prima_usd,
            "raw_metadata": {
                "item_number": item_num,
            },
        }

    def _load_policy_chunks(self, policy_id: str) -> list[dict[str, Any]]:
        sql = """
            SELECT chunk_index, chunk_content, metadata_json
            FROM policy_chunks
            WHERE policy_id = %s::uuid
              AND (chunk_type = 'parent' OR parent_id IS NULL)
            ORDER BY chunk_index ASC;
        """
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (policy_id,))
                rows = cur.fetchall()

        return [
            {
                "chunk_index": r[0],
                "content": r[1] or "",
                "metadata": r[2] if isinstance(r[2], dict) else {},
            }
            for r in rows
        ]

    def _lookup_envelope_id(self, policy_id: str) -> str | None:
        sql = "SELECT envelope_id::text FROM policies WHERE id = %s::uuid;"
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (policy_id,))
                row = cur.fetchone()
                return row[0] if row else None

"""DocEngine — Application: Master Catalogs Service.

Centralized service for managing and querying insurance domain catalogs:
- Insurance Companies (Aseguradoras)
- Insurance Lines (Ramos APS)
- Document Types (Tipos de Documento)

Supports instant in-memory lookup, alias resolution for backward compatibility,
and optional database synchronisation.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

CATALOGS_DIR = Path(__file__).resolve().parents[1] / "config" / "catalogs"


def _normalize_text(text: str) -> str:
    """Normalize text by stripping accents, uppercase conversion, and punctuation removal."""
    nfkd = unicodedata.normalize("NFKD", text)
    clean = "".join([c for c in nfkd if not unicodedata.combining(c)])
    return re.sub(r"[^A-Z0-9 ]+", " ", clean.upper()).strip()


@dataclass(frozen=True)
class CompanyItem:
    """Insurance company catalog entity."""

    id: int
    nombre: str
    sigla: str
    sigla_anterior: str | None = None


@dataclass(frozen=True)
class DocumentTypeItem:
    """Document type catalog entity."""

    id: int
    documento: str
    codigo_normalizado: str | None = None


@dataclass(frozen=True)
class RamoItem:
    """Insurance line catalog entity according to Bolivian APS code."""

    codigo: int
    tipo: str
    ramo: str


class CatalogService:
    """Service providing fast cached access to all reference catalogs."""

    def __init__(self, catalogs_dir: Path | None = None) -> None:
        self.catalogs_dir = catalogs_dir or CATALOGS_DIR
        self._companies: dict[str, CompanyItem] = {}  # sigla_canonica -> CompanyItem
        self._companies_by_id: dict[int, CompanyItem] = {}
        self._companies_by_norm_name: dict[str, CompanyItem] = {}
        self._sigla_aliases: dict[str, str] = {}  # alias (upper) -> sigla_canonica (upper)
        self._document_types: dict[int, DocumentTypeItem] = {}
        self._ramos: dict[int, RamoItem] = {}
        self._ramos_by_tipo: dict[str, list[RamoItem]] = {}
        self._ramos_by_norm_name: dict[str, int] = {}
        self._load_catalogs()

    def _load_catalogs(self) -> None:
        """Load catalogs from CSV files into memory."""
        self._load_companies()
        self._load_document_types()
        self._load_ramos()

    def _load_companies(self) -> None:
        csv_path = self.catalogs_dir / "companias.csv"
        if not csv_path.exists():
            logger.warning("Companies catalog file not found", path=str(csv_path))
            return

        # Known mapping of previous 3-letter siglas to the new standard
        historical_aliases: dict[str, str] = {
            "CRI": "CRE",
            "BIS": "BISA",
            "ALI": "ALI-SEG",
            "ALV": "ALI-VIDA",
            "FOR": "FORT",
            "FOV": "FORT-P",
            "FORTV": "FORT-P",
            "NPF": "NSPF",
            "LBP": "LBC-P",
            "NVS": "NAL-VIDA",
            "CRP": "CRESEG",
            "UNI": "UNIVIDA",
            "UBI": "UNIBIENES",
            "CRG": "CRDI-G",
            "LBC": "LBC",
            "VIT": "VIT",
            "MSC": "MSC",
        }

        try:
            with open(csv_path, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    cid = int(row["id_aseguradora"].strip())
                    nombre = row["aseguradora"].strip()
                    sigla = row["abreviatura"].strip().upper()

                    # Find if there was a historical sigla for this company
                    sigla_ant = None
                    for old_sig, new_sig in historical_aliases.items():
                        if new_sig == sigla and old_sig != sigla:
                            sigla_ant = old_sig
                            break

                    item = CompanyItem(
                        id=cid,
                        nombre=nombre,
                        sigla=sigla,
                        sigla_anterior=sigla_ant,
                    )
                    self._companies[sigla] = item
                    self._companies_by_id[cid] = item
                    norm_co = _normalize_text(nombre)
                    if norm_co:
                        self._companies_by_norm_name[norm_co] = item

                    # Register canonical sigla in alias table
                    self._sigla_aliases[sigla] = sigla

            # Register backward compatibility aliases
            for old_sigla, new_sigla in historical_aliases.items():
                self._sigla_aliases[old_sigla] = new_sigla

            logger.info("Loaded companies catalog", total=len(self._companies))
        except Exception as exc:
            logger.error("Failed to load companies catalog", error=str(exc))

    def _load_document_types(self) -> None:
        csv_path = self.catalogs_dir / "documentos.csv"
        if not csv_path.exists():
            return

        norm_map = {
            1: "CONDICIONADO_GENERAL",
            2: "CONDICIONADO_PARTICULAR",
            3: "LIQUIDACION_PAGOS",
            4: "ANEXO",
            5: "CERTIFICADO",
            6: "ANEXO_LIQUIDACION",
        }

        try:
            with open(csv_path, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    did = int(row["id_documento"].strip())
                    doc_nombre = row["documento"].strip()
                    item = DocumentTypeItem(
                        id=did,
                        documento=doc_nombre,
                        codigo_normalizado=norm_map.get(did),
                    )
                    self._document_types[did] = item
            logger.info("Loaded document types catalog", total=len(self._document_types))
        except Exception as exc:
            logger.error("Failed to load document types catalog", error=str(exc))

    def _load_ramos(self) -> None:
        csv_path = self.catalogs_dir / "ramos.csv"
        if not csv_path.exists():
            return

        try:
            with open(csv_path, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    codigo = int(row["codigo"].strip())
                    tipo = row["tipo"].strip()
                    ramo = row["ramo"].strip()
                    item = RamoItem(codigo=codigo, tipo=tipo, ramo=ramo)
                    self._ramos[codigo] = item
                    self._ramos_by_tipo.setdefault(tipo, []).append(item)
                    norm_name = _normalize_text(ramo)
                    if norm_name:
                        self._ramos_by_norm_name[norm_name] = codigo
            logger.info("Loaded ramos catalog", total=len(self._ramos))
        except Exception as exc:
            logger.error("Failed to load ramos catalog", error=str(exc))

    # --- Public Query Methods ---

    def resolve_sigla(self, sigla_or_alias: str | None) -> str | None:
        """Resolve any given sigla or historical alias to the new canonical sigla.

        Examples:
            'CRI' -> 'CRE'
            'cre' -> 'CRE'
            'BIS' -> 'BISA'
            'FORT' -> 'FORT'
            'FOV' -> 'FORT-P'
            'FORTV' -> 'FORT-P'
        """
        if not sigla_or_alias:
            return None
        norm = sigla_or_alias.strip().upper()
        return self._sigla_aliases.get(norm, norm)

    def get_company_by_sigla(self, sigla_or_alias: str) -> CompanyItem | None:
        """Fetch CompanyItem resolving aliases automatically."""
        canonical = self.resolve_sigla(sigla_or_alias)
        if canonical and canonical in self._companies:
            return self._companies[canonical]
        # Fallback: check normalized company name
        norm_name = _normalize_text(sigla_or_alias)
        if norm_name in self._companies_by_norm_name:
            return self._companies_by_norm_name[norm_name]
        for co_name, item in self._companies_by_norm_name.items():
            if len(co_name) >= 6 and (co_name in norm_name or norm_name in co_name):
                return item
        return None

    def get_company_by_id(self, company_id: int) -> CompanyItem | None:
        """Fetch CompanyItem by integer primary ID."""
        return self._companies_by_id.get(company_id)

    def get_all_companies(self) -> list[CompanyItem]:
        """Return list of all registered companies sorted by ID."""
        return sorted(self._companies.values(), key=lambda c: c.id)

    def get_companies_dict(self) -> dict[str, str]:
        """Return dictionary of canonical SIGLA -> Full Name."""
        return {item.sigla: item.nombre for item in self.get_all_companies()}

    def get_all_document_types(self) -> list[DocumentTypeItem]:
        """Return list of all document types sorted by ID."""
        return sorted(self._document_types.values(), key=lambda d: d.id)

    def get_all_ramos(self) -> list[RamoItem]:
        """Return list of all ramos sorted by APS code."""
        return sorted(self._ramos.values(), key=lambda r: r.codigo)

    def get_ramos_by_tipo(self) -> dict[str, list[dict[str, Any]]]:
        """Return ramos grouped by category/tipo."""
        result: dict[str, list[dict[str, Any]]] = {}
        for tipo, items in self._ramos_by_tipo.items():
            result[tipo] = [
                {"codigo": item.codigo, "ramo": item.ramo}
                for item in sorted(items, key=lambda x: x.codigo)
            ]
        return result

    def resolve_company_id(self, sigla_or_alias: str | None) -> int | None:
        """Resolve company sigla or historical alias to its integer primary key (id_aseguradora).

        Examples:
            'CRI' -> 2 (CREDINFORM)
            'CRE' -> 2
            'BISA' -> 5 (BISA SEGUROS)
            'LBC' -> 1 (LA BOLIVIANA CIACRUZ)
        """
        if not sigla_or_alias:
            return None
        company = self.get_company_by_sigla(sigla_or_alias)
        return company.id if company else None

    def resolve_ramo_codigo(self, ramo_input: str | int | None) -> int | None:
        """Resolve insurance line text, APS code or common alias to cat_ramos primary key (codigo_ramo).

        Supports:
            - Direct integers or numeric strings ('9105', 9105)
            - SPVS / APS registration code ('209-935031-2016 08 024' -> 9350)
            - Normalized exact names ('AUTOMOTORES', 'INCENDIO Y ALIADOS')
            - Standard Bolivian market aliases ('AUTOMOTOR', 'VIDA EN GRUPO', 'DESGRAVAMEN')
            - Substring fuzzy containment matching safely bounded to valid codes.

        Returns:
            APS codigo integer if resolved, or None if unknown.
        """
        if ramo_input is None:
            return None

        # 1. Direct code check (int or string digits)
        raw_str = str(ramo_input).strip()
        if raw_str.isdigit():
            code = int(raw_str)
            if code in self._ramos:
                return code

        # 1.1 SPVS / APS code check (e.g. 209-935031-2016 08 024 -> 9350)
        spvs_match = re.search(r"\b\d{3}-(\d{4})\d{2}-", raw_str)
        if spvs_match:
            code = int(spvs_match.group(1))
            if code in self._ramos:
                return code

        norm = _normalize_text(raw_str)
        if not norm:
            return None

        # 2. Exact match against catalog official names
        if norm in self._ramos_by_norm_name:
            return self._ramos_by_norm_name[norm]

        # 3. Standard Bolivian insurance synonyms mapping
        if norm in RAMO_SYNONYMS:
            return RAMO_SYNONYMS[norm]

        # 4. Containment matching (check longest synonym matches first)
        for syn, syn_code in sorted(RAMO_SYNONYMS.items(), key=lambda kv: len(kv[0]), reverse=True):
            if len(syn) >= 4 and syn in norm:
                return syn_code

        for official_norm, off_code in sorted(self._ramos_by_norm_name.items(), key=lambda kv: len(kv[0]), reverse=True):
            if len(official_norm) >= 4 and (official_norm in norm or norm in official_norm):
                return off_code

        return None

    def resolve_ramo_nombre(self, ramo_input: str | int | None) -> str | None:
        """Resolve canonical ramo name from code, text, synonym or SPVS code.

        Returns:
            Official ramo name (e.g. 'Accidentes personales', 'Automotores') or None.
        """
        code = self.resolve_ramo_codigo(ramo_input)
        if code and code in self._ramos:
            return self._ramos[code].ramo
        return None


# Standard Bolivian insurance market synonyms for APS line resolution
RAMO_SYNONYMS: dict[str, int] = {
    # Automotores (9105)
    "AUTOMOTOR": 9105,
    "AUTOMOTORES": 9105,
    "AUTOS": 9105,
    "AUTOMOTRIZ": 9105,
    "VEHICULOS": 9105,
    "VEHICULAR": 9105,
    "AUTOMOVIL": 9105,
    "AUTOMOVILES": 9105,
    # Incendio y Aliados (9101)
    "INCENDIO": 9101,
    "INCENDIO Y ALIADOS": 9101,
    "INCENDIOS": 9101,
    "LINEAS ALIADAS": 9101,
    # Robo (9102)
    "ROBO": 9102,
    "ROBO Y ASALTO": 9102,
    # Transportes (9103)
    "TRANSPORTE": 9103,
    "TRANSPORTES": 9103,
    "TRANSPORTE DE CARGA": 9103,
    "CARGA": 9103,
    # Naves o Embarcaciones (9104)
    "NAVES": 9104,
    "EMBARCACIONES": 9104,
    # Aeronavegación (9106)
    "AERONAVEGACION": 9106,
    "AEREO": 9106,
    "AVIACION": 9106,
    # Ramos Técnicos (9107)
    "RAMOS TECNICOS": 9107,
    "RAMO TECNICO": 9107,
    "TECNICO": 9107,
    "TODO RIESGO CONTRATISTA": 9107,
    "ROTURA DE MAQUINARIA": 9107,
    "EQUIPO DE CONTRATISTA": 9107,
    "EQUIPO ELECTRONICO": 9107,
    "MONTAJE": 9107,
    # Responsabilidad Civil (9108)
    "RESPONSABILIDAD CIVIL": 9108,
    "RC": 9108,
    # Riesgos varios y misceláneos (9109)
    "RIESGOS VARIOS": 9109,
    "MISCELANEOS": 9109,
    "RIESGOS VARIOS Y MISCELANEOS": 9109,
    # Agropecuarios (9110)
    "AGROPECUARIO": 9110,
    "AGROPECUARIOS": 9110,
    "AGRICOLA": 9110,
    "GANADERO": 9110,
    # Salud o enfermedad (9111)
    "SALUD": 9111,
    "ENFERMEDAD": 9111,
    "SALUD O ENFERMEDAD": 9111,
    "ASISTENCIA MEDICA": 9111,
    "SEGURO MEDICO": 9111,
    # Accidentes personales (9112 / 9350)
    "ACCIDENTES": 9112,
    "ACCIDENTES PERSONALES": 9112,
    "ACCIDENTE PERSONAL": 9112,
    "APES": 9350,
    "AP": 9112,
    "ACCIDENTES ESCOLARES": 9350,
    "ACCIDENTES PERSONALES ESCOLARES": 9350,
    # 3-D (9127)
    "3-D": 9127,
    "3D": 9127,
    "DESHONESTIDAD": 9127,
    "DESHONESTIDAD DESTRUCCION Y DESAPARICION": 9127,
    # Fianzas (9221 - 9231)
    "SERIEDAD DE PROPUESTA": 9221,
    "CUMPLIMIENTO DE OBRA": 9222,
    "BUENA EJECUCION DE OBRA": 9223,
    "CUMPLIMIENTO DE SERVICIOS": 9224,
    "CUMPLIMIENTO DE SUMINISTROS": 9225,
    "INVERSION DE ANTICIPOS": 9226,
    "ANTICIPOS": 9226,
    "FIDELIDAD DE EMPLEADOS": 9227,
    "CREDITOS": 9228,
    "CREDITO": 9228,
    "ADUANERAS": 9229,
    "ADUANERA": 9229,
    "OBLIGACIONES ADUANERAS": 9229,
    "TELECOMUNICACIONES": 9220,
    "FIANZA": 9222,
    "FIANZAS": 9222,
    "GARANTIA": 9222,
    # Vida (9341 - 9346)
    "VIDA": 9341,
    "VIDA INDIVIDUAL": 9341,
    "VIDA LARGO PLAZO": 9341,
    "VIDA INDIVIDUAL LARGO PLAZO": 9341,
    "VIDA INDIVIDUAL CORTO PLAZO": 9342,
    "VIDA CORTO PLAZO": 9342,
    "RENTAS": 9343,
    "SEPELIO": 9344,
    "DEFUNCION": 9344,
    "DEFUNCION O SEPELIO": 9344,
    "SEPELIO LARGO PLAZO": 9344,
    "VIDA EN GRUPO": 9346,
    "VIDA GRUPO": 9346,
    "VIDA COLECTIVO": 9346,
    "VIDA EN GRUPO CORTO PLAZO": 9346,
    "DESGRAVAMEN": 9348,
    "DESGRAVAMEN HIPOTECARIO": 9348,
    "DESGRAVAMEN HIPOTECARIO LARGO PLAZO": 9348,
    "DESGRAVAMEN HIPOTECARIO CORTO PLAZO": 9349,
    # Obligatorios (9455, 9456)
    "SOAT": 9455,
    "ACCIDENTES DE TRANSITO": 9455,
    "ACCIDENTES DEL TRABAJADOR": 9456,
}


# Singleton instance for system-wide consumption
catalog_service = CatalogService()


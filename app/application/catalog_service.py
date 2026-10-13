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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

CATALOGS_DIR = Path(__file__).resolve().parents[1] / "config" / "catalogs"


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
        self._sigla_aliases: dict[str, str] = {}  # alias (upper) -> sigla_canonica (upper)
        self._document_types: dict[int, DocumentTypeItem] = {}
        self._ramos: dict[int, RamoItem] = {}
        self._ramos_by_tipo: dict[str, list[RamoItem]] = {}
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
        if not canonical:
            return None
        return self._companies.get(canonical)

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


# Singleton instance for system-wide consumption
catalog_service = CatalogService()

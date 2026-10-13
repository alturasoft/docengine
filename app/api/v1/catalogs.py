"""DocEngine — API v1: Catalogs Router.

Endpoints for retrieving reference catalogs:
- Insurance Companies (Aseguradoras)
- Document Types (Tipos de Documento)
- Insurance Lines (Ramos APS)
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.application.catalog_service import catalog_service

router = APIRouter(prefix="/catalogs", tags=["Catálogos"])


class CompanyCatalogResponse(BaseModel):
    id: int = Field(description="ID oficial de la aseguradora")
    nombre: str = Field(description="Razón social completa")
    sigla: str = Field(description="Sigla oficial actual")
    sigla_anterior: str | None = Field(default=None, description="Sigla histórica previa (si aplica)")


class DocumentTypeCatalogResponse(BaseModel):
    id: int = Field(description="ID normativo del tipo de documento")
    documento: str = Field(description="Descripción normativa")
    codigo_normalizado: str | None = Field(default=None, description="Identificador en mayúsculas")


class RamoCatalogResponse(BaseModel):
    codigo: int = Field(description="Código oficial APS")
    tipo: str = Field(description="Categoría o tipo de seguro")
    ramo: str = Field(description="Nombre del ramo")


@router.get(
    "/companies",
    response_model=list[CompanyCatalogResponse],
    summary="Listar catálogo de empresas aseguradoras",
    description="Retorna el catálogo completo con IDs oficiales, nombres y siglas vigentes.",
)
def get_companies_catalog() -> list[dict[str, Any]]:
    """Return full list of insurance companies with ID, name and sigla."""
    return [
        {
            "id": c.id,
            "nombre": c.nombre,
            "sigla": c.sigla,
            "sigla_anterior": c.sigla_anterior,
        }
        for c in catalog_service.get_all_companies()
    ]


@router.get(
    "/document-types",
    response_model=list[DocumentTypeCatalogResponse],
    summary="Listar catálogo de tipos de documento",
    description="Retorna la clasificación normativa de tipos de documento de pólizas.",
)
def get_document_types_catalog() -> list[dict[str, Any]]:
    """Return document types catalog."""
    return [
        {
            "id": d.id,
            "documento": d.documento,
            "codigo_normalizado": d.codigo_normalizado,
        }
        for d in catalog_service.get_all_document_types()
    ]


@router.get(
    "/ramos",
    response_model=list[RamoCatalogResponse],
    summary="Listar catálogo plano de ramos de seguros (APS)",
    description="Retorna todos los ramos codificados según la normativa de la APS.",
)
def get_ramos_catalog() -> list[dict[str, Any]]:
    """Return all ramos sorted by code."""
    return [
        {
            "codigo": r.codigo,
            "tipo": r.tipo,
            "ramo": r.ramo,
        }
        for r in catalog_service.get_all_ramos()
    ]


@router.get(
    "/ramos/grouped",
    summary="Listar ramos agrupados por tipo de seguro",
    description="Retorna los ramos estructurados jerárquicamente por categoría (Generales, Personas, Fianzas, etc.).",
)
def get_ramos_grouped() -> dict[str, list[dict[str, Any]]]:
    """Return ramos grouped by category."""
    return catalog_service.get_ramos_by_tipo()

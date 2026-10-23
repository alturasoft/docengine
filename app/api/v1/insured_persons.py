"""DocEngine — Collective Insured Persons API Endpoints (v1).

[ADITIVO] Endpoints dedicados para la consulta, búsqueda y exportación tabular (CSV)
de nóminas de personas aseguradas en pólizas colectivas.

GET /api/v1/policies/{policy_id}/insured-persons         — Consulta y paginación con resumen estadístico.
GET /api/v1/policies/{policy_id}/insured-persons/export  — Descarga de la nómina completa en formato CSV.
GET /api/v1/envelopes/{envelope_id}/insured-persons        — Consulta por sobre de póliza.
GET /api/v1/envelopes/{envelope_id}/insured-persons/export — Descarga por sobre en formato CSV.
GET /api/v1/insured-persons/search                         — Búsqueda por nombre o documento de identidad.
"""

from __future__ import annotations

import csv
import io
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.application.collective_insured_extractor_service import CollectiveInsuredExtractorService
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_insured_persons_repository import PgInsuredPersonsRepository
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["CollectiveInsured"])


def get_insured_repo(request: Request) -> PgInsuredPersonsRepository:
    """Dependency para inyectar PgInsuredPersonsRepository."""
    rag_query = getattr(request.app.state, "rag_query_service", None)
    if rag_query and getattr(rag_query, "_insured_service", None) is not None:
        return rag_query._insured_service._repo

    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from app.config.settings import get_settings
        settings = get_settings()

    db_manager = DatabaseManager(settings.database)
    return PgInsuredPersonsRepository(db_manager)


InsuredRepoDep = Annotated[PgInsuredPersonsRepository, Depends(get_insured_repo)]


def get_insured_service(request: Request) -> CollectiveInsuredExtractorService:
    """Dependency para inyectar CollectiveInsuredExtractorService."""
    rag_query = getattr(request.app.state, "rag_query_service", None)
    if rag_query and getattr(rag_query, "_insured_service", None) is not None:
        return rag_query._insured_service

    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from app.config.settings import get_settings
        settings = get_settings()

    db_manager = DatabaseManager(settings.database)
    return CollectiveInsuredExtractorService(db_manager)


InsuredServiceDep = Annotated[CollectiveInsuredExtractorService, Depends(get_insured_service)]


# ---------------------------------------------------------------------------
# Endpoints por Póliza (Documento)
# ---------------------------------------------------------------------------

@router.get(
    "/policies/{policy_id}/insured-persons",
    summary="Consultar nómina de asegurados de una póliza",
    response_description="Resumen y lista paginada de personas aseguradas.",
)
async def get_policy_insured_persons(
    policy_id: str,
    repo: InsuredRepoDep,
    service: InsuredServiceDep,
    limit: Annotated[int, Query(ge=1, le=1000, description="Límite de registros a retornar")] = 50,
    offset: Annotated[int, Query(ge=0, description="Desplazamiento / paginación")] = 0,
) -> dict[str, Any]:
    """Retorna la lista de asegurados de la póliza con resumen y métricas demográficas."""
    summary = repo.get_insured_summary(policy_id=policy_id, sample_limit=None)
    if not summary or summary.get("total_asegurados", 0) == 0:
        # Intentar extracción al vuelo
        service.extract_and_save_policy_insured(policy_id)
        summary = repo.get_insured_summary(policy_id=policy_id, sample_limit=None)

    if not summary or summary.get("total_asegurados", 0) == 0:
        return {
            "policy_id": policy_id,
            "total_asegurados": 0,
            "resumen": None,
            "items": [],
            "limit": limit,
            "offset": offset,
        }

    items = repo.get_persons_for_policy(policy_id=policy_id, limit=limit, offset=offset)

    return {
        "policy_id": policy_id,
        "total_asegurados": summary["total_asegurados"],
        "resumen": {
            "total_suma_asegurada_usd": summary["total_suma_asegurada_usd"],
            "total_prima_usd": summary["total_prima_usd"],
            "edad_promedio": summary.get("edad_promedio"),
            "distribucion_categoria": summary["distribucion_categoria"],
            "distribucion_genero": summary["distribucion_genero"],
        },
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get(
    "/policies/{policy_id}/insured-persons/export",
    summary="Descargar nómina de asegurados en Excel (CSV)",
    response_description="Archivo CSV descargable con la nómina completa de asegurados.",
)
async def export_policy_insured_persons_csv(
    policy_id: str,
    repo: InsuredRepoDep,
    service: InsuredServiceDep,
) -> Response:
    """Genera y descarga un archivo CSV con la nómina completa de asegurados de la póliza."""
    persons = repo.get_persons_for_policy(policy_id=policy_id)
    if not persons:
        service.extract_and_save_policy_insured(policy_id)
        persons = repo.get_persons_for_policy(policy_id=policy_id)

    if not persons:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró nómina de asegurados para la póliza '{policy_id}'.",
        )

    output = io.StringIO()
    # Escribir BOM para apertura correcta en Microsoft Excel (UTF-8)
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    writer.writerow([
        "Item",
        "Nombre Completo",
        "Documento Identidad",
        "Fecha Nacimiento",
        "Edad",
        "Genero",
        "Parentesco / Categoria",
        "Cargo / Ocupacion",
        "Suma Asegurada ($us.)",
        "Prima ($us.)",
    ])

    for p in persons:
        writer.writerow([
            p.get("item_number", ""),
            p.get("nombre_completo", ""),
            p.get("documento_identidad", ""),
            p.get("fecha_nacimiento", ""),
            p.get("edad", ""),
            p.get("genero", ""),
            p.get("parentesco_categoria", "TITULAR"),
            p.get("cargo_ocupacion", ""),
            f"{p.get('suma_asegurada_usd', 0.0):.2f}",
            f"{p.get('prima_usd', 0.0):.2f}",
        ])

    csv_data = output.getvalue()
    filename = f"nomina_asegurados_poliza_{policy_id[:8]}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Endpoints por Sobre de Póliza (Envelope)
# ---------------------------------------------------------------------------

@router.get(
    "/envelopes/{envelope_id}/insured-persons",
    summary="Consultar nómina de asegurados de un sobre",
    response_description="Resumen y lista paginada de personas aseguradas en el sobre.",
)
async def get_envelope_insured_persons(
    envelope_id: str,
    repo: InsuredRepoDep,
    limit: Annotated[int, Query(ge=1, le=1000, description="Límite de registros a retornar")] = 50,
    offset: Annotated[int, Query(ge=0, description="Desplazamiento / paginación")] = 0,
) -> dict[str, Any]:
    """Retorna la lista de asegurados de todas las pólizas pertenecientes a un sobre."""
    summary = repo.get_insured_summary(envelope_id=envelope_id, sample_limit=None)
    if not summary or summary.get("total_asegurados", 0) == 0:
        return {
            "envelope_id": envelope_id,
            "total_asegurados": 0,
            "resumen": None,
            "items": [],
            "limit": limit,
            "offset": offset,
        }

    items = repo.get_persons_for_envelope(envelope_id=envelope_id, limit=limit, offset=offset)

    return {
        "envelope_id": envelope_id,
        "total_asegurados": summary["total_asegurados"],
        "resumen": {
            "total_suma_asegurada_usd": summary["total_suma_asegurada_usd"],
            "total_prima_usd": summary["total_prima_usd"],
            "edad_promedio": summary.get("edad_promedio"),
            "distribucion_categoria": summary["distribucion_categoria"],
            "distribucion_genero": summary["distribucion_genero"],
        },
        "limit": limit,
        "offset": offset,
        "items": items,
    }


@router.get(
    "/envelopes/{envelope_id}/insured-persons/export",
    summary="Descargar nómina de asegurados del sobre en Excel (CSV)",
    response_description="Archivo CSV descargable con la nómina de asegurados del sobre.",
)
async def export_envelope_insured_persons_csv(
    envelope_id: str,
    repo: InsuredRepoDep,
) -> Response:
    """Genera y descarga un archivo CSV con la nómina completa de asegurados en el sobre."""
    persons = repo.get_persons_for_envelope(envelope_id=envelope_id)
    if not persons:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró nómina de asegurados para el sobre '{envelope_id}'.",
        )

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    writer.writerow([
        "Item",
        "Nombre Completo",
        "Documento Identidad",
        "Fecha Nacimiento",
        "Edad",
        "Genero",
        "Parentesco / Categoria",
        "Cargo / Ocupacion",
        "Suma Asegurada ($us.)",
        "Prima ($us.)",
    ])

    for p in persons:
        writer.writerow([
            p.get("item_number", ""),
            p.get("nombre_completo", ""),
            p.get("documento_identidad", ""),
            p.get("fecha_nacimiento", ""),
            p.get("edad", ""),
            p.get("genero", ""),
            p.get("parentesco_categoria", "TITULAR"),
            p.get("cargo_ocupacion", ""),
            f"{p.get('suma_asegurada_usd', 0.0):.2f}",
            f"{p.get('prima_usd', 0.0):.2f}",
        ])

    csv_data = output.getvalue()
    filename = f"nomina_asegurados_sobre_{envelope_id[:8]}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Endpoint de Búsqueda de Personas
# ---------------------------------------------------------------------------

@router.get(
    "/insured-persons/search",
    summary="Buscar personas aseguradas por nombre o C.I.",
    response_description="Lista de personas que coinciden con el término de búsqueda.",
)
async def search_insured_persons(
    q: Annotated[str, Query(min_length=2, description="Término de búsqueda (Nombre, C.I., Cargo)")],
    repo: InsuredRepoDep,
    policy_id: Annotated[str | None, Query(description="Filtrar por UUID de póliza")] = None,
    envelope_id: Annotated[str | None, Query(description="Filtrar por UUID de sobre")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="Límite de resultados")] = 50,
) -> dict[str, Any]:
    """Permite buscar rápidamente si una persona o cédula está amparada en una póliza o en el sistema."""
    results = repo.search_persons(
        query_text=q,
        policy_id=policy_id,
        envelope_id=envelope_id,
        limit=limit,
    )
    return {
        "query": q,
        "policy_id": policy_id,
        "envelope_id": envelope_id,
        "total_encontrados": len(results),
        "items": results,
    }

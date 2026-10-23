"""DocEngine — Fleet API Endpoints (v1).

[ADITIVO] Endpoints dedicados para la consulta y exportación tabular (CSV)
de nóminas de flotas de vehículos asegurados.

GET /api/v1/policies/{policy_id}/fleet         — Consulta y paginación de vehículos con resumen estadístico.
GET /api/v1/policies/{policy_id}/fleet/export  — Descarga de la nómina completa en formato CSV.
GET /api/v1/envelopes/{envelope_id}/fleet        — Consulta por sobre de póliza.
GET /api/v1/envelopes/{envelope_id}/fleet/export — Descarga por sobre en formato CSV.
"""

from __future__ import annotations

import csv
import io
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.application.fleet_extractor_service import FleetExtractorService
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_fleet_repository import PgFleetRepository
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Fleet"])


def get_fleet_repo(request: Request) -> PgFleetRepository:
    """Dependency para inyectar PgFleetRepository."""
    rag_query = getattr(request.app.state, "rag_query_service", None)
    if rag_query and getattr(rag_query, "_fleet_service", None) is not None:
        return rag_query._fleet_service._repo

    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from app.config.settings import get_settings
        settings = get_settings()

    db_manager = DatabaseManager(settings.database)
    return PgFleetRepository(db_manager)


FleetRepoDep = Annotated[PgFleetRepository, Depends(get_fleet_repo)]


def get_fleet_service(request: Request) -> FleetExtractorService:
    """Dependency para inyectar FleetExtractorService."""
    rag_query = getattr(request.app.state, "rag_query_service", None)
    if rag_query and getattr(rag_query, "_fleet_service", None) is not None:
        return rag_query._fleet_service

    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from app.config.settings import get_settings
        settings = get_settings()

    db_manager = DatabaseManager(settings.database)
    return FleetExtractorService(db_manager)


FleetServiceDep = Annotated[FleetExtractorService, Depends(get_fleet_service)]


# ----------------------------------------------------------------------
# Endpoints por Póliza
# ----------------------------------------------------------------------

@router.get(
    "/policies/{policy_id}/fleet",
    summary="Consultar nómina de vehículos de una póliza",
    response_description="Resumen y lista paginada de vehículos asegurados.",
)
async def get_policy_fleet(
    policy_id: str,
    fleet_service: FleetServiceDep,
    page: int = Query(default=1, ge=1, description="Número de página"),
    limit: int = Query(default=50, ge=1, le=200, description="Registros por página"),
    tipo: str | None = Query(default=None, description="Filtrar por tipo (ej. CAMIONETA, BUS)"),
    search: str | None = Query(default=None, description="Búsqueda por placa, chasis, modelo o marca"),
) -> dict[str, Any]:
    """Retorna la nómina estructurada de vehículos para una póliza, extrayéndola al vuelo si aún no existe."""
    # Verificar si existen registros o extraerlos al vuelo
    total_existing = fleet_service._repo.count_vehicles(policy_id=policy_id)
    if total_existing == 0:
        fleet_service.extract_and_save_policy_fleet(policy_id=policy_id)

    offset = (page - 1) * limit
    vehicles, total = fleet_service._repo.search_vehicles(
        policy_id=policy_id,
        query=search,
        tipo=tipo,
        limit=limit,
        offset=offset,
    )
    summary = fleet_service._repo.get_fleet_summary(policy_id=policy_id)

    return {
        "policy_id": policy_id,
        "total": total,
        "page": page,
        "limit": limit,
        "summary": summary,
        "vehicles": vehicles,
    }


@router.get(
    "/policies/{policy_id}/fleet/export",
    summary="Exportar nómina de vehículos de una póliza en CSV",
    response_description="Archivo CSV descargable con todos los vehículos de la póliza.",
)
async def export_policy_fleet_csv(
    policy_id: str,
    fleet_service: FleetServiceDep,
) -> Response:
    """Descarga la nómina completa de vehículos de una póliza en formato CSV."""
    vehicles = fleet_service.get_or_extract_fleet(policy_id=policy_id)
    if not vehicles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontraron vehículos de flota registrados para esta póliza.",
        )

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Encabezados
    writer.writerow([
        "Item",
        "Tipo Vehiculo",
        "Marca",
        "Modelo",
        "Año",
        "Placa",
        "Chasis",
        "Motor",
        "Color",
        "Uso",
        "Plaza",
        "Valor Asegurado ($us.)",
        "Prima ($us.)",
    ])

    for v in vehicles:
        writer.writerow([
            v.get("item_number", ""),
            v.get("tipo_vehiculo", ""),
            v.get("marca", ""),
            v.get("modelo", ""),
            v.get("anio", ""),
            v.get("placa", ""),
            v.get("chasis", ""),
            v.get("motor", ""),
            v.get("color", ""),
            v.get("uso", ""),
            v.get("plaza", ""),
            f"{v.get('valor_asegurado_usd', 0.0):.2f}",
            f"{v.get('prima_usd', 0.0):.2f}",
        ])

    csv_data = output.getvalue()
    filename = f"flota_poliza_{policy_id[:8]}.csv"

    return Response(
        content=csv_data.encode("utf-8-sig"),  # utf-8 con BOM para correcta apertura en Excel
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8",
        },
    )


# ----------------------------------------------------------------------
# Endpoints por Sobre (Envelope)
# ----------------------------------------------------------------------

@router.get(
    "/envelopes/{envelope_id}/fleet",
    summary="Consultar nómina de vehículos de un sobre de póliza",
    response_description="Resumen y lista paginada de vehículos asegurados en el sobre.",
)
async def get_envelope_fleet(
    envelope_id: str,
    fleet_repo: FleetRepoDep,
    page: int = Query(default=1, ge=1, description="Número de página"),
    limit: int = Query(default=50, ge=1, le=200, description="Registros por página"),
    tipo: str | None = Query(default=None, description="Filtrar por tipo (ej. CAMIONETA, BUS)"),
    search: str | None = Query(default=None, description="Búsqueda por placa, chasis, modelo o marca"),
) -> dict[str, Any]:
    offset = (page - 1) * limit
    vehicles, total = fleet_repo.search_vehicles(
        envelope_id=envelope_id,
        query=search,
        tipo=tipo,
        limit=limit,
        offset=offset,
    )
    summary = fleet_repo.get_fleet_summary(envelope_id=envelope_id)

    return {
        "envelope_id": envelope_id,
        "total": total,
        "page": page,
        "limit": limit,
        "summary": summary,
        "vehicles": vehicles,
    }


@router.get(
    "/envelopes/{envelope_id}/fleet/export",
    summary="Exportar nómina de vehículos de un sobre en CSV",
    response_description="Archivo CSV descargable con todos los vehículos del sobre.",
)
async def export_envelope_fleet_csv(
    envelope_id: str,
    fleet_repo: FleetRepoDep,
) -> Response:
    vehicles = fleet_repo.get_vehicles_for_envelope(envelope_id=envelope_id)
    if not vehicles:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontraron vehículos de flota registrados para este sobre.",
        )

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    writer.writerow([
        "Item",
        "Tipo Vehiculo",
        "Marca",
        "Modelo",
        "Año",
        "Placa",
        "Chasis",
        "Motor",
        "Color",
        "Uso",
        "Plaza",
        "Valor Asegurado ($us.)",
        "Prima ($us.)",
    ])

    for v in vehicles:
        writer.writerow([
            v.get("item_number", ""),
            v.get("tipo_vehiculo", ""),
            v.get("marca", ""),
            v.get("modelo", ""),
            v.get("anio", ""),
            v.get("placa", ""),
            v.get("chasis", ""),
            v.get("motor", ""),
            v.get("color", ""),
            v.get("uso", ""),
            v.get("plaza", ""),
            f"{v.get('valor_asegurado_usd', 0.0):.2f}",
            f"{v.get('prima_usd', 0.0):.2f}",
        ])

    csv_data = output.getvalue()
    filename = f"flota_sobre_{envelope_id[:8]}.csv"

    return Response(
        content=csv_data.encode("utf-8-sig"),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8",
        },
    )

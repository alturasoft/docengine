"""DocEngine — Policies API Endpoints (v1).

GET /api/v1/policies/recent  — List recent digitized policies with basic info.
GET /api/v1/policies/search  — Search a policy by policy number, ID, or keyword.
GET /api/v1/policies/{id}    — Get basic policy info by UUID.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.schemas import (
    DeleteEnvelopeResponseSchema,
    DeletedDocumentInfoSchema,
    PolicyBasicInfoSchema,
    PolicyEnvelopeSchema,
    PolicyEnvelopeSearchResponse,
    PolicySearchResponseSchema,
    RecentPoliciesResponseSchema,
)
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_envelope_repository import PgEnvelopeRepository
from app.infrastructure.database.pg_structured_search import (
    PgStructuredSearchRepository,
)
from app.infrastructure.logging.logger import get_logger
from app.infrastructure.storage.local_storage import LocalStorageService

logger = get_logger(__name__)
router = APIRouter(prefix="/policies", tags=["Policies"])


def get_structured_search_repo(request: Request) -> PgStructuredSearchRepository:
    """Dependency to retrieve or instantiate PgStructuredSearchRepository."""
    rag_query = getattr(request.app.state, "rag_query_service", None)
    if rag_query and getattr(rag_query, "_structured_search", None) is not None:
        return rag_query._structured_search

    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from app.config.settings import get_settings
        settings = get_settings()

    db_manager = DatabaseManager(settings.database)
    return PgStructuredSearchRepository(db_manager)


StructuredSearchDep = Annotated[PgStructuredSearchRepository, Depends(get_structured_search_repo)]


def get_envelope_repo(request: Request) -> PgEnvelopeRepository:
    """Dependency to retrieve or instantiate PgEnvelopeRepository."""
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from app.config.settings import get_settings
        settings = get_settings()

    db_manager = DatabaseManager(settings.database)
    return PgEnvelopeRepository(db_manager)


EnvelopeRepoDep = Annotated[PgEnvelopeRepository, Depends(get_envelope_repo)]


def get_storage_service(request: Request) -> LocalStorageService:
    """Dependency to retrieve or instantiate LocalStorageService."""
    extraction_svc = getattr(request.app.state, "extraction_service", None)
    if extraction_svc and hasattr(extraction_svc, "_storage") and extraction_svc._storage is not None:
        return extraction_svc._storage

    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        from app.config.settings import get_settings
        settings = get_settings()

    return LocalStorageService(settings)


StorageServiceDep = Annotated[LocalStorageService, Depends(get_storage_service)]



@router.get(
    "/recent",
    response_model=RecentPoliciesResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Listar pólizas digitalizadas recientes",
    description="Retorna las pólizas digitalizadas más recientes almacenadas e indexadas en la base de datos con su información básica.",
)
def get_recent_policies(
    repo: StructuredSearchDep,
    limit: int = Query(default=20, ge=1, le=50, description="Cantidad máxima de pólizas a retornar (por defecto 20, máximo 50)"),
) -> RecentPoliciesResponseSchema:
    """Retrieve the most recent policies from the database."""
    try:
        items = repo.get_recent_policies(limit=limit)
        policy_schemas = [PolicyBasicInfoSchema(**item) for item in items]
        return RecentPoliciesResponseSchema(
            total=len(policy_schemas),
            policies=policy_schemas,
        )
    except Exception as exc:
        logger.error("Failed to fetch recent policies", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch recent policies: {exc}",
        ) from exc


@router.get(
    "/search",
    response_model=PolicySearchResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Buscar póliza por número o palabra clave",
    description="Busca una póliza en la base de datos por su número de póliza, identificador UUID o palabra clave, y retorna su información básica.",
)
def search_policy(
    repo: StructuredSearchDep,
    q: str = Query(..., min_length=1, description="Número de póliza, identificador UUID o palabra clave a buscar"),
) -> PolicySearchResponseSchema:
    """Search policy by number, ID, or text."""
    try:
        item = repo.find_basic_by_policy_number_or_id(q)
        if item:
            return PolicySearchResponseSchema(
                found=True,
                policy=PolicyBasicInfoSchema(**item),
            )
        return PolicySearchResponseSchema(
            found=False,
            policy=None,
        )
    except Exception as exc:
        logger.error("Error searching policy", query=q, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching policy: {exc}",
        ) from exc


@router.get(
    "/envelopes",
    response_model=PolicyEnvelopeSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Listar sobres de póliza digitalizados",
    description="Retorna el listado de pólizas (sobres) indexadas, incluyendo la cantidad y detalles de documentos vinculados.",
)
def list_envelopes(
    repo: EnvelopeRepoDep,
    limit: int = Query(default=50, ge=1, le=100, description="Cantidad máxima de pólizas a retornar"),
    offset: int = Query(default=0, ge=0, description="Offset para paginación"),
    company_sigla: str | None = Query(default=None, description="Filtro opcional por sigla de compañía"),
    id_cliente: str | None = Query(default=None, description="Filtro opcional por identificador de cliente (Carnet o NIT)"),
) -> PolicyEnvelopeSearchResponse:
    """List policy envelopes with bound documents."""
    try:
        envelopes = repo.list_envelopes(
            limit=limit,
            offset=offset,
            company_sigla=company_sigla,
            id_cliente=id_cliente,
        )
        return PolicyEnvelopeSearchResponse(
            total=len(envelopes),
            envelopes=[PolicyEnvelopeSchema(**e) for e in envelopes],
        )
    except Exception as exc:
        logger.error("Error listing policy envelopes", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing envelopes: {exc}",
        ) from exc


@router.get(
    "/envelopes/by-client/{id_cliente}",
    response_model=PolicyEnvelopeSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Buscar sobres de póliza por cliente (Carnet o NIT)",
    description="Retorna todas las pólizas (sobres) y documentos vinculados pertenecientes a un cliente específico.",
)
def get_envelopes_by_client(
    id_cliente: str,
    repo: EnvelopeRepoDep,
    limit: int = Query(default=50, ge=1, le=100, description="Cantidad máxima de pólizas a retornar"),
    offset: int = Query(default=0, ge=0, description="Offset para paginación"),
) -> PolicyEnvelopeSearchResponse:
    """Find policy envelopes and bound documents for a specific client."""
    try:
        envelopes = repo.get_envelopes_by_client_id(
            id_cliente=id_cliente,
            limit=limit,
            offset=offset,
        )
        return PolicyEnvelopeSearchResponse(
            total=len(envelopes),
            envelopes=[PolicyEnvelopeSchema(**e) for e in envelopes],
        )
    except Exception as exc:
        logger.error("Error searching envelopes by client ID", id_cliente=id_cliente, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching envelopes by client: {exc}",
        ) from exc


@router.get(
    "/envelopes/by-number/{numero_poliza}",
    response_model=PolicyEnvelopeSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Buscar sobres de póliza por número de póliza",
    description="Busca y retorna los contenedores de póliza que coincidan con el número proporcionado, junto con todos los documentos asociados a cada uno.",
)
def get_envelopes_by_number(
    numero_poliza: str,
    repo: EnvelopeRepoDep,
    company_sigla: str | None = Query(default=None, description="Filtro opcional por sigla de compañía aseguradora"),
) -> PolicyEnvelopeSearchResponse:
    """Find policy envelopes and bound documents by policy number."""
    try:
        envelopes = repo.get_envelope_by_policy_number(
            numero_poliza=numero_poliza,
            company_sigla=company_sigla,
        )
        return PolicyEnvelopeSearchResponse(
            total=len(envelopes),
            envelopes=[PolicyEnvelopeSchema(**e) for e in envelopes],
        )
    except Exception as exc:
        logger.error("Error searching envelopes by number", numero_poliza=numero_poliza, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching envelopes: {exc}",
        ) from exc


@router.get(
    "/envelopes/{envelope_id}",
    response_model=PolicyEnvelopeSchema,
    status_code=status.HTTP_200_OK,
    summary="Obtener sobre de póliza y sus documentos por ID",
    description="Retorna el contenedor o sobre de póliza con todos los documentos vinculados.",
)
def get_envelope_by_id(
    envelope_id: str,
    repo: EnvelopeRepoDep,
) -> PolicyEnvelopeSchema:
    """Retrieve policy envelope by its UUID."""
    try:
        env = repo.get_envelope_by_id(envelope_id)
        if not env:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Envelope with ID '{envelope_id}' not found.",
            )
        return PolicyEnvelopeSchema(**env)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to retrieve envelope by ID", envelope_id=envelope_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve envelope: {exc}",
        ) from exc


@router.get(
    "/{policy_id}",
    response_model=PolicyBasicInfoSchema,
    status_code=status.HTTP_200_OK,
    summary="Obtener información básica de póliza por ID",
    description="Retorna los detalles estándar básicos de una póliza registrada a partir de su identificador único UUID.",
)
def get_policy_by_id(
    policy_id: str,
    repo: StructuredSearchDep,
) -> PolicyBasicInfoSchema:
    """Retrieve policy basic information by its UUID."""
    try:
        item = repo.find_basic_by_policy_number_or_id(policy_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Policy with ID '{policy_id}' not found.",
            )
        return PolicyBasicInfoSchema(**item)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to retrieve policy by ID", policy_id=policy_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve policy: {exc}",
        ) from exc


@router.delete(
    "/envelopes/{envelope_id}",
    response_model=DeleteEnvelopeResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Eliminar sobre de póliza completo y todos sus documentos",
    description=(
        "Elimina de forma atómica y completa un sobre de póliza (envelope) junto con todos los "
        "documentos asociados a él en PostgreSQL (incluyendo chunks vectoriales, datos estructurados, "
        "markdown y estadísticas). Opcionalmente elimina las carpetas de salida en disco."
    ),
)
def delete_envelope(
    envelope_id: str,
    repo: EnvelopeRepoDep,
    storage: StorageServiceDep,
    delete_files: bool = Query(
        default=True,
        description="Si es True, elimina también del sistema de archivos las carpetas generadas en outputs/",
    ),
) -> DeleteEnvelopeResponseSchema:
    """Delete a policy envelope and all associated documents."""
    try:
        deleted_data = repo.delete_envelope(envelope_id)
        if not deleted_data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Sobre de póliza (envelope) con ID '{envelope_id}' no encontrado.",
            )

        deleted_disk_dirs: list[str] = []
        if delete_files:
            for doc in deleted_data.get("deleted_documents", []):
                dirs = storage.delete_result_files(
                    document_id=doc.get("policy_id"),
                    company_sigla=doc.get("company_sigla"),
                    filename=doc.get("file_name"),
                )
                deleted_disk_dirs.extend(dirs)

        deleted_docs_schema = [
            DeletedDocumentInfoSchema(
                policy_id=d["policy_id"],
                file_name=d["file_name"],
                file_hash=d.get("file_hash"),
                company_sigla=d.get("company_sigla"),
            )
            for d in deleted_data.get("deleted_documents", [])
        ]

        logger.info(
            "Envelope y documentos eliminados exitosamente",
            envelope_id=envelope_id,
            numero_poliza=deleted_data.get("numero_poliza"),
            deleted_docs_count=len(deleted_docs_schema),
            deleted_disk_dirs_count=len(deleted_disk_dirs),
        )

        return DeleteEnvelopeResponseSchema(
            envelope_id=deleted_data["id"],
            numero_poliza=deleted_data["numero_poliza"],
            company_sigla=deleted_data.get("company_sigla"),
            ramo=deleted_data.get("ramo"),
            deleted_documents_count=len(deleted_docs_schema),
            deleted_documents=deleted_docs_schema,
            deleted_disk_dirs=deleted_disk_dirs,
            message="Sobre de póliza y todos sus documentos asociados fueron eliminados exitosamente.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error al eliminar el sobre de póliza", envelope_id=envelope_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al eliminar el sobre de póliza: {exc}",
        ) from exc

"""DocEngine — Policies API Endpoints (v1).

GET /api/v1/policies/recent  — List recent digitized policies with basic info.
GET /api/v1/policies/search  — Search a policy by policy number, ID, or keyword.
GET /api/v1/policies/{id}    — Get basic policy info by UUID.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.schemas import (
    ClientItemSchema,
    ClientSearchResponseSchema,
    CoberturaItemResponseSchema,
    DatosCabeceraResponseSchema,
    DeleteDocumentResponseSchema,
    DeleteEnvelopeResponseSchema,
    DeletedDocumentInfoSchema,
    ObjetoAseguradoResponseSchema,
    PolicyBasicInfoSchema,
    PolicyEnvelopeSchema,
    PolicyEnvelopeSearchResponse,
    PolicySearchResponseSchema,
    PolicyStructuredDataResponseSchema,
    RecentPoliciesResponseSchema,
)
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_envelope_repository import PgEnvelopeRepository
from app.infrastructure.database.pg_structured_search import (
    PgStructuredSearchRepository,
)
from app.infrastructure.logging.logger import get_logger
from app.infrastructure.storage.local_storage import LocalStorageService
from app.api.security import require_role

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
    dependencies=[Depends(require_role("readonly"))],
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
    dependencies=[Depends(require_role("readonly"))],
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
    dependencies=[Depends(require_role("readonly"))],
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
    "/clients/search",
    response_model=ClientSearchResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Buscar clientes por Nombre, Razón Social, CI o NIT",
    description="Retorna la lista de clientes registrados que coincidan con el término de búsqueda para autocompletado y selección.",
    dependencies=[Depends(require_role("readonly"))],
)
def search_clients(
    repo: EnvelopeRepoDep,
    q: str = Query(..., min_length=1, description="Nombre de cliente, razón social, carnet o NIT a buscar"),
    limit: int = Query(default=20, ge=1, le=50, description="Cantidad máxima de clientes a retornar"),
) -> ClientSearchResponseSchema:
    """Search unique clients by CI, NIT, or name fragment."""
    try:
        clients = repo.search_clients(query=q, limit=limit)
        return ClientSearchResponseSchema(
            total=len(clients),
            clients=[ClientItemSchema(**c) for c in clients],
        )
    except Exception as exc:
        logger.error("Error searching clients", query=q, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching clients: {exc}",
        ) from exc


@router.get(
    "/envelopes/by-client/{id_cliente}",
    response_model=PolicyEnvelopeSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Buscar sobres de póliza por cliente (Nombre, Carnet o NIT)",
    description="Retorna todas las pólizas (sobres) y documentos vinculados pertenecientes a un cliente específico (buscando por CI/NIT o Nombre/Razón Social).",
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
        logger.error("Error searching envelopes by client ID or name", id_cliente=id_cliente, error=str(exc))
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
    dependencies=[Depends(require_role("readonly"))],
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


@router.get(
    "/{policy_id}/structured",
    response_model=PolicyStructuredDataResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Obtener datos estructurados completos de póliza (Coberturas, límites, deducibles, vigencias)",
    description=(
        "Retorna la representación estructurada y atomizada completa de la póliza de seguros: "
        "datos contractuales de cabecera, especificaciones del objeto/vehículo asegurado, catálogo de coberturas con sumas, deducibles y límites, "
        "y cláusulas o condiciones especiales."
    ),
    dependencies=[Depends(require_role("readonly"))],
)
def get_policy_structured(
    policy_id: str,
    repo: StructuredSearchDep,
) -> PolicyStructuredDataResponseSchema:
    """Retrieve full structured policy JSON by policy ID or policy number."""
    try:
        # 1. Attempt direct UUID lookup
        record = repo.find_by_policy_id(policy_id)

        # 2. If not found by direct UUID, fallback to lookup by policy number
        resolved_id = policy_id
        if not record:
            basic = repo.find_basic_by_policy_number_or_id(policy_id)
            if basic and basic.get("policy_id"):
                resolved_id = basic["policy_id"]
                record = repo.find_by_policy_id(resolved_id)

        if not record or not record.get("data"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Datos estructurados para la póliza '{policy_id}' no encontrados.",
            )

        data = record.get("data", {})
        cabecera_raw = data.get("datos_cabecera") if isinstance(data.get("datos_cabecera"), dict) else {}
        objeto_raw = data.get("objeto_asegurado") if isinstance(data.get("objeto_asegurado"), dict) else None
        coberturas_raw = data.get("coberturas") if isinstance(data.get("coberturas"), list) else []
        condiciones_raw = data.get("condiciones_especiales") if isinstance(data.get("condiciones_especiales"), list) else []

        # Map cabecera
        cabecera = DatosCabeceraResponseSchema(
            numero_poliza=cabecera_raw.get("numero_poliza"),
            poliza_anterior=cabecera_raw.get("poliza_anterior"),
            asegurado=cabecera_raw.get("asegurado"),
            documento_identidad=cabecera_raw.get("documento_identidad"),
            nit=cabecera_raw.get("nit"),
            codigo_spvs=cabecera_raw.get("codigo_spvs"),
            direccion=cabecera_raw.get("direccion"),
            zona=cabecera_raw.get("zona"),
            barrio_distrito=cabecera_raw.get("barrio_distrito"),
            telefono=cabecera_raw.get("telefono"),
            celular=cabecera_raw.get("celular"),
            email=cabecera_raw.get("email"),
            actividad_economica=cabecera_raw.get("actividad_economica"),
            tomador=cabecera_raw.get("tomador"),
            aseguradora=cabecera_raw.get("aseguradora"),
            sigla_empresa=cabecera_raw.get("sigla_empresa") or record.get("company_sigla"),
            vigencia_desde=cabecera_raw.get("vigencia_desde"),
            vigencia_hasta=cabecera_raw.get("vigencia_hasta"),
            moneda=cabecera_raw.get("moneda"),
            prima_total=cabecera_raw.get("prima_total"),
        )

        # Map objeto asegurado
        objeto = (
            ObjetoAseguradoResponseSchema(
                tipo_bien=objeto_raw.get("tipo_bien"),
                marca=objeto_raw.get("marca"),
                modelo=objeto_raw.get("modelo"),
                ano=objeto_raw.get("ano"),
                placa=objeto_raw.get("placa"),
                motor=objeto_raw.get("motor"),
                chasis=objeto_raw.get("chasis"),
                color=objeto_raw.get("color"),
                uso_servicio=objeto_raw.get("uso_servicio"),
                valor_declarado=objeto_raw.get("valor_declarado"),
                alcance_territorial=objeto_raw.get("alcance_territorial"),
            )
            if objeto_raw
            else None
        )

        # Map coberturas
        coberturas = [
            CoberturaItemResponseSchema(
                nombre=c.get("nombre", "Cobertura"),
                suma_asegurada=c.get("suma_asegurada"),
                deducible=c.get("deducible"),
                limite=c.get("limite"),
            )
            for c in coberturas_raw
            if isinstance(c, dict)
        ]

        condiciones = [str(cond) for cond in condiciones_raw]
        id_cliente = cabecera.documento_identidad or cabecera.nit

        return PolicyStructuredDataResponseSchema(
            policy_id=record.get("policy_id", resolved_id),
            file_name=record.get("file_name"),
            company_sigla=record.get("company_sigla"),
            id_cliente=id_cliente,
            datos_cabecera=cabecera,
            objeto_asegurado=objeto,
            coberturas=coberturas,
            condiciones_especiales=condiciones,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error retrieving structured policy data", policy_id=policy_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving structured policy data: {exc}",
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
    dependencies=[Depends(require_role("admin"))],
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


@router.delete(
    "/{policy_id}",
    response_model=DeleteDocumentResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Eliminar documento individual de póliza (Reemplazo de documento)",
    description=(
        "Elimina de forma atómica un documento específico de la base de datos a partir de su UUID en la tabla policies "
        "(incluyendo sus fragmentos vectoriales, datos estructurados, markdown y estadísticas). "
        "Permite volver a subir una versión corregida del documento sin duplicidad ni inconsistencias. "
        "Opcionalmente elimina sus carpetas de salida en disco."
    ),
    dependencies=[Depends(require_role("admin"))],
)
def delete_single_document(
    policy_id: str,
    repo: EnvelopeRepoDep,
    storage: StorageServiceDep,
    delete_files: bool = Query(
        default=True,
        description="Si es True, elimina también del sistema de archivos las carpetas generadas en outputs/",
    ),
) -> DeleteDocumentResponseSchema:
    """Delete a single policy document and its associated storage."""
    try:
        deleted_doc = repo.delete_document(policy_id)
        if not deleted_doc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Documento con ID '{policy_id}' no encontrado.",
            )

        deleted_disk_dirs: list[str] = []
        if delete_files:
            dirs = storage.delete_result_files(
                document_id=deleted_doc.get("policy_id"),
                company_sigla=deleted_doc.get("company_sigla"),
                filename=deleted_doc.get("file_name"),
            )
            deleted_disk_dirs.extend(dirs)

        logger.info(
            "Documento eliminado exitosamente",
            policy_id=policy_id,
            filename=deleted_doc.get("file_name"),
            envelope_id=deleted_doc.get("envelope_id"),
        )

        return DeleteDocumentResponseSchema(
            policy_id=deleted_doc["policy_id"],
            file_name=deleted_doc["file_name"],
            envelope_id=deleted_doc.get("envelope_id"),
            company_sigla=deleted_doc.get("company_sigla"),
            deleted_disk_dirs=deleted_disk_dirs,
            message="Documento eliminado exitosamente. Ya puede cargar la versión corregida sin duplicidad.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error al eliminar documento individual", policy_id=policy_id, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al eliminar documento: {exc}",
        ) from exc


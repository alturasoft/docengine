"""DocEngine — API Pydantic Schemas.

Request and response models for the FastAPI layer.
These schemas are decoupled from domain models to allow independent evolution.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


# ---------------------------------------------------------------------------
# Metadata Schemas
# ---------------------------------------------------------------------------


class MetadataSchema(BaseModel):
    """Metadatos técnicos y estadísticas del documento extraído para respuestas de la API."""

    filename: str = Field(description="Nombre del archivo original procesado")
    sha256: str = Field(description="Hash SHA-256 del contenido del archivo original")
    page_count: int = Field(description="Cantidad total de páginas procesadas del documento")
    extraction_time_seconds: float = Field(description="Tiempo total empleado en la extracción (segundos)")
    docling_version: str = Field(description="Versión del motor Docling utilizada")
    tables_detected: int = Field(description="Cantidad total de tablas estructuradas detectadas")
    figures_detected: int = Field(description="Cantidad de figuras o imágenes detectadas")
    headers_removed: int = Field(description="Cantidad de encabezados repetitivos eliminados")
    footers_removed: int = Field(description="Cantidad de pies de página repetitivos eliminados")
    ocr_used: bool = Field(description="Indica si se aplicó reconocimiento óptico de caracteres (OCR)")
    has_multi_column: bool = Field(description="Indica si se detectó un diseño de múltiples columnas")
    markdown_size_bytes: int = Field(description="Tamaño del contenido Markdown generado en bytes")
    errors: list[str] = Field(default_factory=list, description="Lista de errores no críticos ocurridos durante la extracción")
    warnings: list[str] = Field(default_factory=list, description="Lista de advertencias generadas durante el procesamiento")
    extracted_at: datetime = Field(description="Fecha y hora de finalización de la extracción")
    company_sigla: str | None = Field(default=None, description="Sigla de la empresa aseguradora")
    # PDF type detection fields (Phase 2: auto-OCR)
    pdf_type: str | None = Field(
        default=None,
        description="Tipo de PDF detectado: 'digital' | 'scanned' | 'hybrid' | 'unknown'",
    )
    scanned_page_ratio: float | None = Field(
        default=None,
        description="Fracción de páginas escaneadas detectadas (0.0–1.0)",
    )
    pdf_detection_time_seconds: float | None = Field(
        default=None,
        description="Tiempo empleado en la clasificación previa del PDF (segundos)",
    )
    # Policy Envelope fields
    envelope_id: str | None = Field(
        default=None,
        description="UUID del sobre de póliza (envelope) al que se vinculó el documento",
    )
    tipo_documento: str | None = Field(
        default=None,
        description="Clasificación del tipo de documento (ej. 'CONDICIONADO_GENERAL', 'CONDICIONADO_PARTICULAR')",
    )
    id_cliente: str | None = Field(
        default=None,
        description="Identificador del cliente (Carnet de Identidad o NIT)",
    )


# ---------------------------------------------------------------------------
# Extraction Response Schemas
# ---------------------------------------------------------------------------


class RagReportSchema(BaseModel):
    """Reporte de persistencia e indexación del pipeline RAG en PostgreSQL."""

    policy_id: str | None = Field(default=None, description="UUID asignado a la póliza en la base de datos")
    job_id: str | None = Field(default=None, description="UUID del trabajo de procesamiento")
    skipped_duplicate: bool = Field(default=False, description="Indica si se omitió por ser un documento duplicado ya existente")
    chunks_created: int = Field(default=0, description="Cantidad de fragmentos semánticos creados e indexados")
    errors: list[str] = Field(default_factory=list, description="Lista de errores ocurridos durante el proceso RAG")
    envelope_id: str | None = Field(default=None, description="UUID del sobre de póliza vinculado en PostgreSQL")
    tipo_documento: str | None = Field(default=None, description="Tipo de documento asignado")


class ExtractionResultSchema(BaseModel):
    """Respuesta de la API para la extracción de un documento individual."""

    document_id: str = Field(description="Identificador único de la extracción")
    status: str = Field(description="Estado de la extracción: 'success' | 'partial' | 'failed'")
    markdown_preview: str = Field(
        description="Primeros 500 caracteres de previsualización del Markdown generado"
    )
    metadata: MetadataSchema = Field(description="Metadatos técnicos y estadísticas del documento extraído")
    output_paths: dict[str, str] = Field(
        description="Diccionario de formatos generados y sus rutas de almacenamiento en el servidor"
    )
    rag_report: RagReportSchema | None = Field(default=None, description="Resultado de persistencia RAG en PostgreSQL")
    created_at: datetime = Field(description="Fecha y hora de registro de la extracción")

    model_config = {"from_attributes": True}



class BatchExtractionResultSchema(BaseModel):
    """Respuesta de la API para la extracción por lote de una carpeta de documentos."""

    total_documents: int = Field(description="Cantidad total de documentos PDF procesados")
    successful: int = Field(description="Cantidad de extracciones exitosas")
    failed: int = Field(description="Cantidad de extracciones fallidas")
    results: list[ExtractionResultSchema] = Field(description="Lista de resultados detallados de cada documento procesado")


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class UrlExtractionRequest(BaseModel):
    """Cuerpo de la petición para extracción basada en URL remota."""

    url: str = Field(description="URL pública que apunta al documento PDF a procesar")
    id_cliente: str = Field(description="Identificador del cliente (Carnet de Identidad o NIT) (REQUERIDO)")
    output_formats: list[str] = Field(
        default=["all"],
        description="Formatos de salida a generar: 'md', 'json', 'all'",
    )
    company_sigla: str | None = Field(
        default=None, description="Sigla de la empresa aseguradora (ej. CRI, LBC, ALI)"
    )


class FolderExtractionRequest(BaseModel):
    """Cuerpo de la petición para extracción por lote de carpetas en el servidor."""

    folder_path: str = Field(description="Ruta del directorio en el servidor que contiene los archivos PDF")
    output_formats: list[str] = Field(default=["all"], description="Formatos de salida a generar: 'md', 'json', 'all'")
    company_sigla: str | None = Field(
        default=None, description="Sigla de la empresa aseguradora (ej. CRI, LBC, ALI)"
    )
    id_cliente: str | None = Field(
        default=None,
        description="Identificador del cliente (Carnet o NIT) para la carpeta, o inferible por prefijo de archivo/subcarpeta",
    )
    numero_poliza: str | None = Field(
        default=None,
        description="Número de póliza opcional para vincular todos los documentos del lote a un Sobre Digital",
    )
    ramo: str | None = Field(
        default=None,
        description="Línea o ramo de seguro opcional para el Sobre Digital (ej. AUTOMOTORES, VIDA)",
    )


# ---------------------------------------------------------------------------
# Health & System Schemas
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Cuerpo de respuesta para la verificación de salud del servicio (GET /health)."""

    status: str = Field(default="ok", description="Estado operativo del servicio ('ok')")
    environment: str = Field(description="Entorno de ejecución actual (ej. 'development', 'production')")
    uptime_seconds: float = Field(description="Segundos transcurridos desde el inicio del servidor")


class VersionResponse(BaseModel):
    """Cuerpo de respuesta para la consulta de versiones del servicio (GET /version)."""

    app_version: str = Field(description="Versión instalada de la aplicación DocEngine")
    docling_version: str = Field(description="Versión del motor Docling instalada")
    python_version: str = Field(description="Versión del entorno Python en ejecución")


class MetricsResponse(BaseModel):
    """Cuerpo de respuesta para las métricas acumuladas del servicio (GET /metrics)."""

    total_extractions: int = Field(description="Total acumulado de extracciones solicitadas")
    successful_extractions: int = Field(description="Cantidad de extracciones finalizadas exitosamente")
    failed_extractions: int = Field(description="Cantidad de extracciones que resultaron en fallo")
    total_pages_processed: int = Field(description="Total acumulado de páginas PDF procesadas")
    total_tables_detected: int = Field(description="Total acumulado de tablas detectadas y estructuradas")
    avg_extraction_time_seconds: float = Field(description="Tiempo promedio de procesamiento por documento en segundos")
    memory_usage_mb: float = Field(description="Consumo de memoria RAM del proceso del servidor en megabytes (MB)")


# ---------------------------------------------------------------------------
# RAG Query Schemas
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    """Cuerpo de la petición para consulta semántica con lenguaje natural (POST /api/v1/query)."""

    question: str = Field(
        description="Pregunta en lenguaje natural a responder a partir del contexto documental indexado.",
        min_length=3,
        max_length=2000,
    )
    top_k: int | None = Field(
        default=None,
        description="Cantidad máxima de fragmentos relevantes a recuperar (1–50). Por defecto toma el valor configurado en el servicio.",
        ge=1,
        le=50,
    )
    similarity_threshold: float | None = Field(
        default=None,
        description="Puntuación mínima de similitud de coseno para incluir un fragmento (0.0–1.0). Por defecto toma el valor configurado en el servicio.",
        ge=0.0,
        le=1.0,
    )
    filters: dict | None = Field(
        default=None,
        description=(
            "Filtros opcionales de metadatos. Claves soportadas: "
            "'policy_id' (str UUID), 'envelope_id' (str UUID), 'company_sigla' (str, ej. 'CRI'), 'id_cliente' (str, ej. '10203040')."
        ),
    )


class SourceChunkSchema(BaseModel):
    """Representación de un fragmento de texto recuperado utilizado como fuente de la respuesta."""

    chunk_id: str | None = Field(default=None, description="UUID de clave primaria en la tabla policy_chunks")
    policy_id: str = Field(description="UUID de la póliza principal a la que pertenece el fragmento")
    chunk_index: int = Field(description="Posición del fragmento dentro del documento original")
    similarity_score: float = Field(description="Puntuación de similitud de coseno calculada (0.0–1.0)")
    document_label: str = Field(description="Etiqueta legible del documento citado como fuente")
    chunk_content: str = Field(description="Contenido textual sin procesar del fragmento recuperado")
    metadata_json: dict = Field(default_factory=dict, description="Metadatos adicionales del fragmento (sección, página, etc.)")
    numero_poliza: str | None = Field(default=None, description="Número de póliza comercial contractual asociada al fragmento")
    company_sigla: str | None = Field(default=None, description="Sigla oficial de la aseguradora (ej. BISA, CRE, LBC)")


class QueryResponseSchema(BaseModel):
    """Cuerpo de respuesta para la consulta semántica con lenguaje natural (POST /api/v1/query)."""

    answer: str = Field(
        description=(
            "Respuesta generada por el LLM basada exclusivamente en los fragmentos de documentos recuperados. "
            "Retorna la frase de contingencia si no se encontró contexto relevante."
        )
    )
    query: str = Field(description="La pregunta formulada originalmente por el usuario")
    chunks_used: int = Field(description="Cantidad de fragmentos de documento incluidos en el contexto del prompt")
    model_used: str = Field(description="Identificador del modelo OpenAI utilizado para generar la respuesta")
    no_context_found: bool = Field(
        default=False,
        description="True cuando ningún fragmento superó el umbral mínimo de similitud requerido.",
    )
    sources: list[SourceChunkSchema] = Field(
        default_factory=list,
        description="Lista ordenada de fragmentos fuente utilizados (del más relevante al menor).",
    )
    created_at: datetime = Field(description="Marca de tiempo UTC de generación de la respuesta")


# ---------------------------------------------------------------------------
# Policy Basic Info & Search Schemas
# ---------------------------------------------------------------------------


class PolicyBasicInfoSchema(BaseModel):
    """Información básica estructurada de una póliza de seguro."""

    policy_id: str = Field(description="UUID del documento de póliza.")
    numero_poliza: str = Field(description="Número de póliza.")
    ramo: str = Field(description="Ramo de la póliza.")
    asegurado: str = Field(description="Nombre del asegurado o tomador.")
    numero_documento: str = Field(description="Documento de identidad (CI / NIT).")
    vigencia: str = Field(description="Período de vigencia (Desde - Hasta).")
    prima_total: str = Field(description="Prima total y moneda.")
    company_sigla: str | None = Field(default=None, description="Sigla de la aseguradora.")
    file_name: str | None = Field(default=None, description="Nombre del archivo original.")
    id_cliente: str | None = Field(default=None, description="Identificador del cliente (Carnet o NIT).")
    created_at: str | None = Field(default=None, description="Fecha de registro en la base de datos.")


class RecentPoliciesResponseSchema(BaseModel):
    """Cuerpo de respuesta para la consulta de pólizas recientes (GET /api/v1/policies/recent)."""

    total: int = Field(description="Cantidad de pólizas retornadas.")
    policies: list[PolicyBasicInfoSchema] = Field(description="Listado de pólizas recientes.")


class PolicySearchResponseSchema(BaseModel):
    """Cuerpo de respuesta para la búsqueda de pólizas (GET /api/v1/policies/search)."""

    found: bool = Field(description="Indica si se encontró la póliza.")
    policy: PolicyBasicInfoSchema | None = Field(default=None, description="Datos básicos de la póliza encontrada.")


# ---------------------------------------------------------------------------
# Policy Envelope Schemas
# ---------------------------------------------------------------------------


class DocumentSummarySchema(BaseModel):
    """Resumen de un documento adjunto a un sobre de póliza."""

    policy_id: str = Field(description="UUID de la fila en la tabla policies")
    file_name: str = Field(description="Nombre del archivo original")
    file_hash: str = Field(description="Hash SHA-256 del archivo")
    company_sigla: str | None = Field(default=None, description="Sigla de la aseguradora")
    tipo_documento: str | None = Field(default=None, description="Tipo de documento")
    total_pages: int | None = Field(default=None, description="Total de páginas")
    file_size_bytes: int | None = Field(default=None, description="Tamaño del archivo en bytes")
    id_cliente: str | None = Field(default=None, description="Identificador del cliente (Carnet o NIT)")
    created_at: str | None = Field(default=None, description="Fecha de creación")


class PolicyEnvelopeSchema(BaseModel):
    """Sobre o contenedor lógico que agrupa todos los documentos de una misma póliza."""

    id: str = Field(description="UUID único del envelope")
    numero_poliza: str = Field(description="Número de póliza")
    company_sigla: str | None = Field(default=None, description="Sigla de la aseguradora")
    ramo: str | None = Field(default=None, description="Ramo de la póliza")
    id_cliente: str | None = Field(default=None, description="Identificador del cliente (Carnet o NIT)")
    created_at: str | None = Field(default=None, description="Fecha de registro")
    updated_at: str | None = Field(default=None, description="Última actualización")
    documents_count: int = Field(default=0, description="Cantidad de documentos vinculados")
    documents: list[DocumentSummarySchema] = Field(default_factory=list, description="Listado de documentos vinculados")


class PolicyEnvelopeSearchResponse(BaseModel):
    """Respuesta a la búsqueda de envelopes de póliza."""

    total: int = Field(description="Cantidad de envelopes encontrados")
    envelopes: list[PolicyEnvelopeSchema] = Field(default_factory=list, description="Lista de envelopes")


class DeletedDocumentInfoSchema(BaseModel):
    """Información básica de un documento eliminado del sobre."""

    policy_id: str = Field(description="UUID del documento en la tabla policies")
    file_name: str = Field(description="Nombre del archivo original")
    file_hash: str | None = Field(default=None, description="Hash SHA-256 del documento")
    company_sigla: str | None = Field(default=None, description="Sigla de la aseguradora")


class DeleteEnvelopeResponseSchema(BaseModel):
    """Respuesta a la eliminación de un sobre de póliza completo."""

    envelope_id: str = Field(description="UUID del sobre de póliza eliminado")
    numero_poliza: str = Field(description="Número de póliza del sobre")
    company_sigla: str | None = Field(default=None, description="Sigla de la compañía aseguradora")
    ramo: str | None = Field(default=None, description="Ramo del seguro")
    deleted_documents_count: int = Field(description="Cantidad de documentos eliminados")
    deleted_documents: list[DeletedDocumentInfoSchema] = Field(
        default_factory=list, description="Lista de documentos asociados que fueron eliminados"
    )
    deleted_disk_dirs: list[str] = Field(
        default_factory=list, description="Directorios de salida en disco eliminados"
    )
    message: str = Field(description="Mensaje informativo del resultado")


# ---------------------------------------------------------------------------
# Nuevos Esquemas Aditivos (Fases 1 y 2)
# ---------------------------------------------------------------------------


class SearchFiltersSchema(BaseModel):
    """Filtros tipados para consultas y búsquedas RAG."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    company_sigla: str | None = Field(default=None, description="Sigla oficial de la aseguradora (ej. LBC, CRE, BISA)")
    sigla_aseguradora: str | None = Field(default=None, description="Alias retrocompatible para company_sigla")
    numero_poliza: str | None = Field(default=None, description="Número de póliza")
    ramo: str | None = Field(default=None, description="Ramo del seguro (ej. AUTOMOTOR, INCENDIO, SALUD)")
    tipo_documento: str | None = Field(default=None, description="Tipo de documento (ej. CONDICIONADO_GENERAL, CONDICIONADO_PARTICULAR)")
    vigencia_fecha: str | None = Field(default=None, description="Fecha de vigencia a comprobar (YYYY-MM-DD o DD/MM/YYYY)")
    id_cliente: str | None = Field(default=None, description="Identificador del cliente (Carnet de Identidad o NIT)")
    policy_id: str | None = Field(default=None, description="UUID del documento de póliza")
    envelope_id: str | None = Field(default=None, description="UUID del sobre de póliza")

    @model_validator(mode="before")
    @classmethod
    def unify_sigla_alias(cls, data: Any) -> Any:
        """Soporta tanto company_sigla como sigla_aseguradora o aseguradora de forma transparente."""
        if isinstance(data, dict):
            sigla = data.get("company_sigla") or data.get("sigla_aseguradora") or data.get("aseguradora")
            if sigla:
                data["company_sigla"] = sigla
                data["sigla_aseguradora"] = sigla
        return data


class QuerySearchRequest(BaseModel):
    """Cuerpo de la petición para búsqueda vectorial/híbrida pura sin generación LLM (POST /api/v1/query/search)."""

    question: str = Field(
        description="Consulta o pregunta en lenguaje natural para recuperar fragmentos relevantes.",
        min_length=3,
        max_length=2000,
    )
    top_k: int | None = Field(
        default=None,
        description="Cantidad máxima de fragmentos relevantes a recuperar (1–50).",
        ge=1,
        le=50,
    )
    similarity_threshold: float | None = Field(
        default=None,
        description="Puntuación mínima de similitud de coseno (0.0–1.0).",
        ge=0.0,
        le=1.0,
    )
    filters: dict | None = Field(
        default=None,
        description="Filtros de metadatos (company_sigla, numero_poliza, ramo, tipo_documento, id_cliente, vigencia_fecha).",
    )


class QuerySearchResponseSchema(BaseModel):
    """Respuesta a la búsqueda pura de fragmentos (POST /api/v1/query/search)."""

    query: str = Field(description="Pregunta o texto de consulta ejecutado")
    total_results: int = Field(description="Cantidad de fragmentos relevantes recuperados")
    results: list[SourceChunkSchema] = Field(
        default_factory=list,
        description="Listado de fragmentos con su puntaje de similitud, contenido y metadatos",
    )


class DatosCabeceraResponseSchema(BaseModel):
    """Datos de cabecera contractual de la póliza."""

    numero_poliza: str | None = None
    poliza_anterior: str | None = None
    asegurado: str | None = None
    documento_identidad: str | None = None
    nit: str | None = None
    codigo_spvs: str | None = None
    direccion: str | None = None
    zona: str | None = None
    barrio_distrito: str | None = None
    telefono: str | None = None
    celular: str | None = None
    email: str | None = None
    actividad_economica: str | None = None
    tomador: str | None = None
    aseguradora: str | None = None
    sigla_empresa: str | None = None
    vigencia_desde: str | None = None
    vigencia_hasta: str | None = None
    moneda: str | None = None
    prima_total: str | None = None


class ObjetoAseguradoResponseSchema(BaseModel):
    """Datos del bien o vehículo asegurado."""

    tipo_bien: str | None = None
    marca: str | None = None
    modelo: str | None = None
    ano: str | None = None
    placa: str | None = None
    motor: str | None = None
    chasis: str | None = None
    color: str | None = None
    uso_servicio: str | None = None
    valor_declarado: str | None = None
    alcance_territorial: str | None = None


class CoberturaItemResponseSchema(BaseModel):
    """Detalle de una cobertura individual."""

    nombre: str = Field(description="Nombre o descripción de la cobertura")
    suma_asegurada: str | None = Field(default=None, description="Monto asegurado")
    deducible: str | None = Field(default=None, description="Condiciones del deducible o franquicia")
    limite: str | None = Field(default=None, description="Límite indemnizatorio o sublímite")


class PolicyStructuredDataResponseSchema(BaseModel):
    """Datos estructurados completos de una póliza (GET /api/v1/policies/{policy_id}/structured)."""

    policy_id: str = Field(description="UUID de la póliza")
    file_name: str | None = Field(default=None, description="Nombre del archivo original")
    company_sigla: str | None = Field(default=None, description="Sigla de la compañía aseguradora")
    id_cliente: str | None = Field(default=None, description="Identificador del cliente (Carnet o NIT)")
    datos_cabecera: DatosCabeceraResponseSchema = Field(
        default_factory=DatosCabeceraResponseSchema,
        description="Metadatos de cabecera contractual (número, asegurado, vigencias, prima)",
    )
    objeto_asegurado: ObjetoAseguradoResponseSchema | None = Field(
        default=None, description="Datos del bien o vehículo asegurado"
    )
    coberturas: list[CoberturaItemResponseSchema] = Field(
        default_factory=list, description="Lista de coberturas, sumas aseguradas, deducibles y límites"
    )
    condiciones_especiales: list[str] = Field(
        default_factory=list, description="Lista de condiciones o cláusulas especiales"
    )


class JobStatusResponseSchema(BaseModel):
    """Estado de un trabajo de procesamiento en segundo plano (GET /api/v1/extract/jobs/{job_id})."""

    job_id: str = Field(description="UUID del trabajo de extracción")
    status: str = Field(description="Estado del trabajo: PROCESSING, COMPLETED, FAILED, SKIPPED")
    file_name: str = Field(description="Nombre del archivo procesado")
    policy_id: str | None = Field(default=None, description="UUID de la póliza resultante si completó")
    error_message: str | None = Field(default=None, description="Detalle del error en caso de fallo")
    created_at: str | None = Field(default=None, description="Fecha de creación del trabajo")
    updated_at: str | None = Field(default=None, description="Fecha de última actualización")


class AsyncExtractResponseSchema(BaseModel):
    """Respuesta a la solicitud de carga asíncrona (202 Accepted)."""

    job_id: str = Field(description="UUID del trabajo encolado")
    status: str = Field(default="PROCESSING", description="Estado inicial del trabajo")
    message: str = Field(description="Mensaje indicativo del procesamiento en segundo plano")


class DeleteDocumentResponseSchema(BaseModel):
    """Respuesta a la eliminación de un documento individual."""

    policy_id: str = Field(description="UUID del documento eliminado")
    file_name: str = Field(description="Nombre del archivo del documento")
    envelope_id: str | None = Field(default=None, description="UUID del sobre al que pertenecía")
    company_sigla: str | None = Field(default=None, description="Sigla de la aseguradora")
    deleted_disk_dirs: list[str] = Field(default_factory=list, description="Directorios de disco eliminados")
    message: str = Field(description="Mensaje confirmando la eliminación")


class ErrorDetailSchema(BaseModel):
    """Detalle de error estándar para documentación OpenAPI."""

    detail: str = Field(description="Descripción del error")



"""DocEngine — API Pydantic Schemas.

Request and response models for the FastAPI layer.
These schemas are decoupled from domain models to allow independent evolution.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, HttpUrl


# ---------------------------------------------------------------------------
# Metadata Schemas
# ---------------------------------------------------------------------------


class MetadataSchema(BaseModel):
    """Serialized DocumentMetadata for API responses."""

    filename: str
    sha256: str
    page_count: int
    extraction_time_seconds: float
    docling_version: str
    tables_detected: int
    figures_detected: int
    headers_removed: int
    footers_removed: int
    ocr_used: bool
    has_multi_column: bool
    markdown_size_bytes: int
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    extracted_at: datetime
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


# ---------------------------------------------------------------------------
# Extraction Response Schemas
# ---------------------------------------------------------------------------


class RagReportSchema(BaseModel):
    """Report of RAG pipeline persistence into PostgreSQL."""

    policy_id: str | None = None
    job_id: str | None = None
    skipped_duplicate: bool = False
    chunks_created: int = 0
    errors: list[str] = Field(default_factory=list)


class ExtractionResultSchema(BaseModel):
    """API response for a single document extraction."""

    document_id: str = Field(description="Unique extraction identifier")
    status: str = Field(description="success | partial | failed")
    markdown_preview: str = Field(
        description="First 500 characters of Markdown output"
    )
    metadata: MetadataSchema
    output_paths: dict[str, str] = Field(
        description="Map of format name to file path on server"
    )
    rag_report: RagReportSchema | None = Field(default=None, description="Resultado de persistencia RAG en PostgreSQL")
    created_at: datetime

    model_config = {"from_attributes": True}



class BatchExtractionResultSchema(BaseModel):
    """API response for a batch (folder) extraction."""

    total_documents: int
    successful: int
    failed: int
    results: list[ExtractionResultSchema]


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class UrlExtractionRequest(BaseModel):
    """Request body for URL-based extraction."""

    url: str = Field(description="URL pointing to a PDF document")
    output_formats: list[str] = Field(
        default=["all"],
        description="Output formats: md, json, all",
    )
    company_sigla: str | None = Field(
        default=None, description="Sigla de la empresa aseguradora (ej. CRI, LBC, ALI)"
    )


class FolderExtractionRequest(BaseModel):
    """Request body for folder-based extraction."""

    folder_path: str = Field(description="Server-side folder path containing PDFs")
    output_formats: list[str] = Field(default=["all"])
    company_sigla: str | None = Field(
        default=None, description="Sigla de la empresa aseguradora (ej. CRI, LBC, ALI)"
    )


# ---------------------------------------------------------------------------
# Health & System Schemas
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    status: str = Field(default="ok")
    environment: str
    uptime_seconds: float


class VersionResponse(BaseModel):
    """Response body for GET /version."""

    app_version: str
    docling_version: str
    python_version: str


class MetricsResponse(BaseModel):
    """Response body for GET /metrics."""

    total_extractions: int
    successful_extractions: int
    failed_extractions: int
    total_pages_processed: int
    total_tables_detected: int
    avg_extraction_time_seconds: float
    memory_usage_mb: float


# ---------------------------------------------------------------------------
# RAG Query Schemas
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    """Request body for POST /api/v1/query."""

    question: str = Field(
        description="Natural language question to answer from document context.",
        min_length=3,
        max_length=2000,
    )
    top_k: int = Field(
        default=5,
        description="Maximum number of document chunks to retrieve (1–20).",
        ge=1,
        le=20,
    )
    similarity_threshold: float = Field(
        default=0.3,
        description="Minimum cosine similarity score for a chunk to be included (0.0–1.0).",
        ge=0.0,
        le=1.0,
    )
    filters: dict | None = Field(
        default=None,
        description=(
            "Optional pre-filter parameters. Supported keys: "
            "'policy_id' (str UUID), 'company_sigla' (str, e.g. 'CRI')."
        ),
    )


class SourceChunkSchema(BaseModel):
    """Serialized representation of a retrieved chunk used as answer source."""

    chunk_id: str | None = Field(default=None, description="Primary key UUID in policy_chunks table.")
    policy_id: str = Field(description="UUID of the parent policy document.")
    chunk_index: int = Field(description="Position of the chunk within the document.")
    similarity_score: float = Field(description="Cosine similarity score (0.0–1.0).")
    document_label: str = Field(description="Human-readable citation label for the chunk.")
    chunk_content: str = Field(description="Raw text content of the chunk.")
    metadata_json: dict = Field(default_factory=dict, description="Chunk metadata (section, page, etc.).")


class QueryResponseSchema(BaseModel):
    """Response body for POST /api/v1/query."""

    answer: str = Field(
        description=(
            "LLM-generated answer based exclusively on retrieved document context. "
            "Returns the contingency phrase if no relevant context was found."
        )
    )
    query: str = Field(description="The original user question (verbatim).")
    chunks_used: int = Field(description="Number of document chunks included in the prompt context.")
    model_used: str = Field(description="OpenAI model identifier used for the completion.")
    no_context_found: bool = Field(
        default=False,
        description="True when no chunks passed the similarity threshold.",
    )
    sources: list[SourceChunkSchema] = Field(
        default_factory=list,
        description="Ordered list of source chunks (most relevant first).",
    )
    created_at: datetime = Field(description="UTC timestamp of the response.")

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


# ---------------------------------------------------------------------------
# Extraction Response Schemas
# ---------------------------------------------------------------------------


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

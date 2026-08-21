"""DocEngine — Application Configuration.

All configuration classes use Pydantic v2 BaseSettings.
Values can be overridden via environment variables prefixed with DOCENGINE_.
Example: DOCENGINE_LOG_LEVEL=DEBUG overrides LoggingConfig.level.

Never import application or infrastructure modules here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

import sys

# Load .env file into environment variables if present (except during pytest execution)
if "pytest" not in sys.modules and os.getenv("PYTEST_CURRENT_TEST") is None:
    load_dotenv()

# Guarantee a valid, writable cache directory for HuggingFace / Docling / PyTorch
# when running under system users with HOME=/nonexistent (e.g. Docker containers)
try:
    _home_path = Path.home()
    if str(_home_path) == "/nonexistent" or not _home_path.exists():
        import tempfile

        _hf_fallback = Path(tempfile.gettempdir()) / "huggingface"
        _hf_fallback.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("HF_HOME", str(_hf_fallback))
        os.environ.setdefault("TRANSFORMERS_CACHE", str(_hf_fallback))
        os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(_hf_fallback))
        os.environ.setdefault("TORCH_HOME", str(_hf_fallback))
except Exception:
    pass


# ---------------------------------------------------------------------------
# Sub-configurations (nested)
# ---------------------------------------------------------------------------


class ExtractionConfig(BaseSettings):
    """Controls what Docling extracts and how it handles document elements.

    Attributes:
        do_ocr: Enable OCR pipeline. MUST remain False for Phase 1.
            All infrastructure is prepared for Phase 2 activation.
        do_table_structure: Enable table detection and reconstruction.
        table_mode: TableFormer mode. ACCURATE for maximum fidelity.
            Options: 'ACCURATE' | 'FAST'
        do_cell_matching: Match PDF cells to table structure (improves accuracy).
        generate_picture_images: Extract image binaries from PDF (unused in Phase 1).
        page_range_start: First page to extract (1-indexed). None = beginning.
        page_range_end: Last page to extract (1-indexed). None = end.
        fix_spaced_text: Post-process Markdown to collapse letter-spaced text
            (e.g. "E n V i r t u d" → "En Virtud"). Caused by non-standard
            embedded font glyph maps in some insurance PDFs.
        spaced_text_min_ratio: Fraction of single-char tokens in a line that
            triggers spaced-text detection. Default 0.4 (40%).
        split_merged_tables: Post-process Markdown to detect and split tables
            that were incorrectly merged by TableFormer due to visual proximity.
    """

    model_config = SettingsConfigDict(env_prefix="DOCENGINE_EXTRACTION_", extra="ignore")

    do_ocr: bool = Field(default=False, description="Enable OCR pipeline (Phase 2 only)")
    do_table_structure: bool = Field(default=True, description="Enable table detection")
    table_mode: Literal["ACCURATE", "FAST"] = Field(
        default="ACCURATE", description="TableFormer mode"
    )
    do_cell_matching: bool = Field(default=True, description="Cell matching for tables")
    generate_picture_images: bool = Field(
        default=False, description="Extract image binaries"
    )
    page_range_start: int | None = Field(
        default=None, description="First page (1-indexed)", ge=1
    )
    page_range_end: int | None = Field(
        default=None, description="Last page (1-indexed)", ge=1
    )
    fix_spaced_text: bool = Field(
        default=True,
        description="Collapse letter-spaced text caused by non-standard font maps",
    )
    spaced_text_min_ratio: float = Field(
        default=0.4,
        description="Min ratio of single-char tokens to trigger spaced-text fix",
        ge=0.1,
        le=1.0,
    )
    split_merged_tables: bool = Field(
        default=True,
        description="Detect and split Markdown tables incorrectly merged by TableFormer",
    )

    # --- Auto-OCR Detection (Phase 2 activation) ---
    # These fields control the dynamic PDF type detection introduced in Phase 2.
    # All default to safe values: detection enabled, 50% threshold, 15 chars/page.
    auto_detect_pdf_type: bool = Field(
        default=True,
        description=(
            "Automatically detect if a PDF is scanned or digital before extraction. "
            "When True and a scanned/hybrid PDF is detected, Docling OCR is enabled "
            "dynamically regardless of the do_ocr setting."
        ),
    )
    scanned_page_ratio_threshold: float = Field(
        default=0.5,
        description=(
            "Minimum ratio of scanned pages (0.0–1.0) required to classify a PDF as "
            "SCANNED (and trigger force_full_page_ocr). Values below the threshold but "
            "above 0 produce a HYBRID classification (OCR without force_full_page_ocr)."
        ),
        ge=0.0,
        le=1.0,
    )
    min_chars_per_page: int = Field(
        default=50,
        description=(
            "Minimum character count on a sampled page to classify it as having "
            "embedded text (not scanned). Pages with fewer characters than this value "
            "are treated as scanned image pages."
        ),
        ge=1,
        le=500,
    )
    max_sample_pages: int = Field(
        default=10,
        description=(
            "Maximum number of pages to inspect during PDF type auto-detection. "
            "For documents larger than this, a proportional sample from the beginning, "
            "middle, and end of the document is used."
        ),
        ge=3,
        le=50,
    )


class PipelineConfig(BaseSettings):
    """Controls Docling pipeline behaviour and model loading.

    Attributes:
        pdf_backend: PDF parsing backend.
            'pypdfium2' (default — robust memory streaming using C++ PDFium,
            prevents std::bad_alloc errors on multi-page complex PDFs).
            'docling_parse' (native parser backend).
        artifacts_path: Path to pre-downloaded Docling model artifacts.
            Set this for air-gapped environments. None = auto-download.
        num_threads: Number of CPU threads for parallel page processing.
            0 = use all available cores.
        accelerator_device: Hardware accelerator. 'cpu' | 'cuda' | 'mps'.
        images_scale: Scale factor for internal page image rendering used by
            layout analysis. 1.0 is standard (prevents RAM exhaustion).
    """

    model_config = SettingsConfigDict(env_prefix="DOCENGINE_PIPELINE_", extra="ignore")

    pdf_backend: Literal["pypdfium2", "docling_parse", "docling_parse_v2"] = Field(
        default="pypdfium2",
        description=(
            "PDF parsing backend. 'pypdfium2' (default, robust memory for multi-page docs) "
            "or 'docling_parse'."
        ),
    )
    images_scale: float = Field(
        default=1.0,
        description="Page image scale factor for layout analysis (1.0–4.0)",
        ge=1.0,
        le=4.0,
    )
    artifacts_path: Path | None = Field(
        default=None, description="Local Docling model artifacts path"
    )
    num_threads: int = Field(
        default=4, description="CPU threads for pipeline", ge=1, le=64
    )
    accelerator_device: Literal["cpu", "cuda", "mps", "auto"] = Field(
        default="cpu", description="Hardware accelerator device"
    )


class OutputConfig(BaseSettings):
    """Controls where and how extraction results are stored.

    Attributes:
        output_dir: Base directory for all extraction outputs.
        formats: Which output formats to generate.
        include_metadata: Whether to save a metadata.json file.
        include_report: Whether to save an extraction_report.json file.
        markdown_preview_chars: Characters to include in API preview responses.
    """

    model_config = SettingsConfigDict(env_prefix="DOCENGINE_OUTPUT_", extra="ignore")

    output_dir: Path = Field(
        default=Path("outputs"), description="Base directory for outputs"
    )
    formats: list[str] = Field(
        default=["md", "json"], description="Output formats to generate"
    )
    include_metadata: bool = Field(default=True, description="Save metadata.json")
    include_report: bool = Field(default=True, description="Save extraction_report.json")
    markdown_preview_chars: int = Field(
        default=500, description="Preview chars for API responses"
    )

    @field_validator("output_dir", mode="before")
    @classmethod
    def resolve_output_dir(cls, v: str | Path) -> Path:
        """Ensure output_dir is always an absolute Path."""
        return Path(v).resolve()


LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class LoggingConfig(BaseSettings):
    """Controls application logging behaviour.

    Attributes:
        level: Log level. DEBUG | INFO | WARNING | ERROR | CRITICAL.
        format: Output format. 'json' for production, 'console' for development.
        log_file: Optional path to write logs to disk. None = stdout only.
        include_memory: Include memory consumption in log entries.
        include_timing: Include duration_ms in log entries.
    """

    model_config = SettingsConfigDict(env_prefix="DOCENGINE_LOG_", extra="ignore")

    level: LogLevel = Field(
        default=cast(LogLevel, "INFO"), description="Log level"
    )
    format: Literal["json", "console"] = Field(
        default="console", description="Log output format"
    )
    log_file: Path | None = Field(default=None, description="Path to log file")
    include_memory: bool = Field(default=True, description="Log memory consumption")
    include_timing: bool = Field(default=True, description="Log timing information")

    @field_validator("level", mode="before")
    @classmethod
    def normalize_level(cls, v: Any) -> Any:
        """Ensure log level string is uppercase."""
        if isinstance(v, str):
            return cast(LogLevel, v.upper())
        return v



class OCRConfig(BaseSettings):
    """OCR configuration stub — Phase 2 activation ready.

    This configuration class is fully implemented so that enabling OCR
    in Phase 2 only requires changing do_ocr=True in ExtractionConfig
    and selecting an engine here. No core code needs to change.

    Attributes:
        engine: OCR engine to use. 'tesseract' | 'easyocr' | 'rapidocr'.
        languages: List of language codes for OCR recognition.
        force_full_page_ocr: Force OCR on entire page (not just detected regions).
        tessdata_prefix: Path to Tesseract language data files.
    """

    model_config = SettingsConfigDict(env_prefix="DOCENGINE_OCR_", extra="ignore")

    engine: Literal["tesseract", "easyocr", "rapidocr"] = Field(
        default="easyocr", description="OCR engine"
    )
    languages: list[str] = Field(
        default=["es", "en"], description="OCR language codes"
    )
    force_full_page_ocr: bool = Field(
        default=False, description="Force full-page OCR"
    )
    tessdata_prefix: Path | None = Field(
        default=None, description="Tesseract data directory"
    )


class PerformanceConfig(BaseSettings):
    """Controls memory and performance trade-offs.

    Attributes:
        batch_size: Number of documents to process concurrently in batch mode.
        max_upload_size_mb: Maximum file size accepted by the API.
        request_timeout_seconds: Timeout for individual extraction operations.
        memory_warning_threshold_mb: Log a warning if memory exceeds this value.
    """

    model_config = SettingsConfigDict(env_prefix="DOCENGINE_PERF_", extra="ignore")

    batch_size: int = Field(default=4, description="Documents per batch", ge=1, le=32)
    max_upload_size_mb: int = Field(
        default=200, description="Max upload size in MB", ge=1, le=2048
    )
    request_timeout_seconds: int = Field(
        default=300, description="Extraction timeout in seconds", ge=30
    )
    memory_warning_threshold_mb: int = Field(
        default=2048, description="Memory warning threshold in MB"
    )


class MarkdownConfig(BaseSettings):
    """Controls Markdown post-processing behaviour.

    Attributes:
        remove_repeated_headers: Auto-detect and remove repeated page headers.
        remove_repeated_footers: Auto-detect and remove repeated page footers.
        repetition_threshold: Fraction of pages a text must appear in to be
            considered repetitive (0.0–1.0). Default 0.7 = 70% of pages.
        preserve_page_breaks: Include page break markers when structurally valuable.
        normalize_whitespace: Collapse excessive blank lines.
        max_consecutive_blank_lines: Maximum blank lines between sections.
    """

    model_config = SettingsConfigDict(env_prefix="DOCENGINE_MD_", extra="ignore")

    remove_repeated_headers: bool = Field(
        default=True, description="Remove repeated page headers"
    )
    remove_repeated_footers: bool = Field(
        default=True, description="Remove repeated page footers"
    )
    repetition_threshold: float = Field(
        default=0.7, description="Fraction of pages to consider text repetitive",
        ge=0.0, le=1.0,
    )
    preserve_page_breaks: bool = Field(
        default=False, description="Include page break markers"
    )
    normalize_whitespace: bool = Field(
        default=True, description="Collapse excessive blank lines"
    )
    max_consecutive_blank_lines: int = Field(
        default=2, description="Max blank lines between sections", ge=1, le=10
    )


class DatabaseConfig(BaseSettings):
    """Controls PostgreSQL connection and pool parameters.

    Attributes:
        host: Database host name or IP address.
        port: Database port number.
        name: Database name.
        user: Database user.
        password: Database password.
        pool_min: Minimum connections in connection pool.
        pool_max: Maximum connections in connection pool.
    """

    model_config = SettingsConfigDict(env_prefix="DOCENGINE_DB_", extra="ignore")

    host: str = Field(default="localhost", description="PostgreSQL host")
    port: int = Field(default=5432, description="PostgreSQL port")
    name: str = Field(default="docengine", description="Database name")
    user: str = Field(default="postgres", description="Database user")
    password: str = Field(default="postgres", description="Database password")
    pool_min: int = Field(default=2, description="Min pool connections")
    pool_max: int = Field(default=10, description="Max pool connections")

    @property
    def connection_uri(self) -> str:
        """Construct PostgreSQL connection URI."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class EmbeddingConfig(BaseSettings):
    """Controls local embedding generation and chunking parameters.

    Attributes:
        model_name: SentenceTransformers model identifier. Default "BAAI/bge-m3".
        batch_size: Batch size for vector encoding.
        device: Computation device ('cpu', 'cuda', 'mps', etc.).
        chunk_size_chars: Target max character length for chunks.
        chunk_overlap_chars: Overlap character length between chunks.
    """

    model_config = SettingsConfigDict(env_prefix="DOCENGINE_EMBED_", extra="ignore")

    model_name: str = Field(default="BAAI/bge-m3", description="Local embedding model name")
    batch_size: int = Field(default=32, description="Encoding batch size", ge=1, le=256)
    device: str = Field(default="cpu", description="Hardware device for embeddings")
    chunk_size_chars: int = Field(default=1800, description="Target chunk size in characters", ge=200, le=10000)
    chunk_overlap_chars: int = Field(default=200, description="Chunk overlap in characters", ge=0, le=1000)
    child_chunk_size_chars: int = Field(default=800, description="Child chunk size for Parent-Child retrieval", ge=100, le=2000)
    child_chunk_overlap_chars: int = Field(default=100, description="Child chunk overlap for Parent-Child retrieval", ge=0, le=500)
    cache_folder: Path | None = Field(
        default=None,
        description="Optional custom directory path for storing/loading embedding models",
    )


class RAGQueryConfig(BaseSettings):
    """Controls the RAG Query & Retrieval service (read path).

    This configuration is used exclusively by RAGQueryService and
    PgVectorSearchRepository. It has no effect on the ingestion pipeline.

    Attributes:
        top_k: Default number of chunks to retrieve per query (1–20).
        similarity_threshold: Minimum cosine similarity for a chunk to be
            included in the context (0.0–1.0). Lower values increase recall
            at the cost of noise; higher values increase precision.
        llm_model: OpenAI chat completion model to use for answer generation.
            'gpt-4o-mini' (fast, cost-effective) or 'gpt-4o' (higher quality).
        max_tokens: Maximum tokens in the LLM completion response.
        temperature: Sampling temperature. Fixed at 0.0 for maximum factual
            fidelity — do NOT change unless explicitly required.
    """

    model_config = SettingsConfigDict(env_prefix="DOCENGINE_RAG_", extra="ignore")

    top_k: int = Field(default=5, description="Default top-K chunks per query", ge=1, le=20)
    similarity_threshold: float = Field(
        default=0.3,
        description="Minimum cosine similarity threshold (0.0–1.0)",
        ge=0.0,
        le=1.0,
    )
    llm_model: str = Field(default="gpt-4o-mini", description="OpenAI chat completion model")
    max_tokens: int = Field(default=2048, description="Max tokens for LLM response", ge=128, le=8192)
    temperature: float = Field(default=0.0, description="Sampling temperature (0.0 = deterministic)", ge=0.0, le=2.0)


class RerankerConfig(BaseSettings):
    """Controls the cross-encoder reranking step in the RAG query path.

    When enabled, retrieved Parent Chunks are re-scored against the user query
    using a cross-encoder model (BAAI/bge-reranker-v2-m3) for higher-quality
    ranking before LLM context injection.

    Set DOCENGINE_RERANKER_ENABLED=False in .env for lightweight development
    environments (e.g., Windows with limited RAM). The mock fallback returns
    the first top_n chunks with synthetic scores, preserving data structure
    compatibility for the rest of the pipeline.

    Attributes:
        enabled: Toggle cross-encoder reranking on/off. Default True (production).
        model_name: HuggingFace cross-encoder model identifier.
        top_n: Number of parent chunks to return after reranking.
        device: Computation device ('cpu', 'cuda', 'directml').
        cache_folder: Optional custom model cache directory.
    """

    model_config = SettingsConfigDict(env_prefix="DOCENGINE_RERANKER_", extra="ignore")

    enabled: bool = Field(default=True, description="Enable cross-encoder reranking (False for dev mock)")
    model_name: str = Field(default="BAAI/bge-reranker-v2-m3", description="Cross-encoder model")
    top_n: int = Field(default=3, description="Number of parent chunks after reranking", ge=1, le=10)
    device: str = Field(default="cpu", description="Hardware device for reranker")
    cache_folder: Path | None = Field(
        default=None,
        description="Optional custom directory path for storing/loading reranker models",
    )


# ---------------------------------------------------------------------------
# Root application settings
# ---------------------------------------------------------------------------


class AppSettings(BaseSettings):
    """Root application settings — aggregates all sub-configurations.

    Environment variables are read from .env file and system environment.
    Sub-configurations use their own prefixes (e.g. DOCENGINE_LOG_LEVEL).

    Attributes:
        environment: Runtime environment. 'development' | 'production' | 'test'.
        app_name: Application name used in API metadata and logs.
        app_version: Application version string.
        extraction: Extraction pipeline configuration.
        pipeline: Docling pipeline technical configuration.
        output: Output storage configuration.
        logging: Logging configuration.
        ocr: OCR engine configuration (Phase 2).
        performance: Performance and memory configuration.
        markdown: Markdown post-processing configuration.
        database: PostgreSQL + pgvector configuration.
        embedding: Local embeddings and chunking configuration.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DOCENGINE_",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "production", "test"] = Field(
        default="development", description="Runtime environment"
    )
    app_name: str = Field(
        default="DocEngine", description="Application name"
    )
    app_version: str = Field(
        default="1.0.0", description="Application version"
    )

    # Sub-configurations — each reads its own env vars independently
    # They are instantiated via default_factory to avoid sharing state
    extraction: ExtractionConfig = Field(default_factory=lambda: ExtractionConfig())
    pipeline: PipelineConfig = Field(default_factory=lambda: PipelineConfig())
    output: OutputConfig = Field(default_factory=lambda: OutputConfig())
    logging: LoggingConfig = Field(default_factory=lambda: LoggingConfig())
    ocr: OCRConfig = Field(default_factory=lambda: OCRConfig())
    performance: PerformanceConfig = Field(default_factory=lambda: PerformanceConfig())
    markdown: MarkdownConfig = Field(default_factory=lambda: MarkdownConfig())
    database: DatabaseConfig = Field(default_factory=lambda: DatabaseConfig())
    embedding: EmbeddingConfig = Field(default_factory=lambda: EmbeddingConfig())
    rag_query: RAGQueryConfig = Field(default_factory=lambda: RAGQueryConfig())
    reranker: RerankerConfig = Field(default_factory=lambda: RerankerConfig())


    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, v: object) -> str:
        """Accept common aliases for environment names."""
        v_str = str(v).lower() if v is not None else ""
        mapping = {"dev": "development", "prod": "production"}
        return mapping.get(v_str, v_str)

    def is_development(self) -> bool:
        """Return True if running in development mode."""
        return self.environment == "development"

    def is_production(self) -> bool:
        """Return True if running in production mode."""
        return self.environment == "production"

    def is_test(self) -> bool:
        """Return True if running in test mode."""
        return self.environment == "test"


# ---------------------------------------------------------------------------
# Module-level singleton (lazy)
# ---------------------------------------------------------------------------

_settings_instance: AppSettings | None = None


def get_settings() -> AppSettings:
    """Return the application settings singleton.

    Creates the instance on first call, then caches it.
    In tests, call reset_settings() to force re-creation.

    Returns:
        The global AppSettings instance.
    """
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = AppSettings()
    return _settings_instance


def reset_settings() -> None:
    """Reset the settings singleton (use in tests only)."""
    global _settings_instance
    _settings_instance = None

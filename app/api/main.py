"""DocEngine — FastAPI Application Factory.

The create_app() function builds and configures the FastAPI application.
The DocumentConverter (Docling) is initialised ONCE in the lifespan
context manager and stored in app.state.extraction_service.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router as v1_router
from app.application.extraction_service import ExtractionService
from app.application.markdown_service import MarkdownService
from app.application.metadata_service import MetadataService
from app.application.validation_service import ValidationService
from app.config.settings import AppSettings, get_settings
from app.infrastructure.adapters.docling_adapter import DoclingAdapter
from app.infrastructure.logging.logger import configure_logging, get_logger
from app.infrastructure.storage.local_storage import LocalStorageService

logger = get_logger(__name__)


def _build_extraction_service(settings: AppSettings) -> ExtractionService:
    """Wire and return a fully configured ExtractionService.

    This is the composition root — the only place where concrete
    implementations are instantiated and injected.

    Args:
        settings: Application configuration.

    Returns:
        Configured ExtractionService ready for use.
    """
    extractor = DoclingAdapter(config=settings)
    storage = LocalStorageService(config=settings)
    markdown_service = MarkdownService(config=settings)
    metadata_service = MetadataService()
    validation_service = ValidationService(config=settings)

    return ExtractionService(
        extractor=extractor,
        markdown_service=markdown_service,
        metadata_service=metadata_service,
        validation_service=validation_service,
        storage=storage,
        config=settings,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan: startup and shutdown logic.

    On startup: initialise logging, build ExtractionService (loads Docling models).
    On shutdown: log graceful shutdown.
    """
    settings: AppSettings = app.state.settings

    # Initialise logging
    configure_logging(
        level=settings.logging.level,
        format_=settings.logging.format,
        log_file=str(settings.logging.log_file) if settings.logging.log_file else None,
    )

    logger.info(
        "DocEngine starting",
        version=settings.app_version,
        environment=settings.environment,
        table_mode=settings.extraction.table_mode,
        ocr_enabled=settings.extraction.do_ocr,
    )

    # Build and cache ExtractionService (expensive — loads Docling ML models)
    logger.info("Loading Docling models (this may take a moment)...")
    app.state.extraction_service = _build_extraction_service(settings)
    logger.info("Docling models loaded. Service ready.")

    # Build RAG Pipeline Service (ingestion path — existing, do not modify)
    try:
        from app.cli.rag_factory import create_rag_pipeline_service  # noqa: PLC0415
        app.state.rag_service = create_rag_pipeline_service()
        logger.info("RAG Pipeline Service initialized and ready.")
    except Exception as exc:
        logger.error("Could not initialize RAG Pipeline Service", error=str(exc))
        app.state.rag_service = None

    # Build RAG Query Service (read/query path — new, independent service)
    # Reuse the EmbeddingService from rag_service._embedder to share the
    # already-loaded bge-m3 model in memory (avoids a second ~1GB model load).
    try:
        from app.cli.rag_query_factory import create_rag_query_service  # noqa: PLC0415
        shared_embedder = getattr(app.state.rag_service, "_embedder", None)
        app.state.rag_query_service = create_rag_query_service(
            embedding_service=shared_embedder,
        )
        reuse_note = "shared" if shared_embedder is not None else "new instance"
        logger.info(
            "RAG Query Service initialized and ready.",
            embedding_service=reuse_note,
        )
    except Exception as exc:
        logger.error("Could not initialize RAG Query Service", error=str(exc))
        app.state.rag_query_service = None

    yield  # Application is running

    logger.info("DocEngine shutting down gracefully.")


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional settings override. Uses get_settings() if None.

    Returns:
        Configured FastAPI application instance.
    """
    resolved_settings = settings or get_settings()

    app = FastAPI(
        title="DocEngine — Motor de Extracción Documental",
        description=(
            "Motor de extracción de alta fidelidad para PDFs de pólizas de seguros. "
            "Basado en Docling (IBM Research). Produce Markdown optimizado para RAG."
        ),
        version=resolved_settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Store settings in app state for lifespan access
    app.state.settings = resolved_settings

    # CORS middleware (permissive for internal use — tighten for production)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(v1_router, prefix="/api/v1")

    # Mount Web UI if available
    webui_dir = (Path(__file__).resolve().parents[2] / "webui").resolve()
    if webui_dir.exists():
        app.mount("/ui", StaticFiles(directory=webui_dir, html=True), name="ui")

        @app.get("/", include_in_schema=False)
        @app.get("/index.html", include_in_schema=False)
        async def root_to_ui() -> FileResponse:
            return FileResponse(webui_dir / "index.html")

        @app.get("/chat", include_in_schema=False)
        @app.get("/chat.html", include_in_schema=False)
        async def root_to_chat() -> FileResponse:
            return FileResponse(webui_dir / "chat.html")

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception", path=str(request.url), error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error. Check logs for details."},
        )

    return app

"""DocEngine — Dependency Injection for FastAPI.

All application-layer services are wired here and provided
as FastAPI dependencies. The DocumentConverter (Docling) is
initialised once at startup via lifespan and stored in app.state.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request

from app.application.extraction_service import ExtractionService
from app.config.settings import AppSettings, get_settings


def get_app_settings() -> AppSettings:
    """FastAPI dependency: return the application settings singleton.

    Returns:
        AppSettings instance.
    """
    return get_settings()


SettingsDep = Annotated[AppSettings, Depends(get_app_settings)]


def get_extraction_service(request: Request) -> ExtractionService:
    """FastAPI dependency: return the ExtractionService from app state.

    The ExtractionService (and the underlying DoclingAdapter) is created
    once at startup in the lifespan context manager and stored in
    app.state.extraction_service. This avoids expensive model reloading
    on every request.

    Args:
        request: The FastAPI Request object (provides access to app.state).

    Returns:
        The ExtractionService singleton.
    """
    return request.app.state.extraction_service


ExtractionServiceDep = Annotated[ExtractionService, Depends(get_extraction_service)]


def get_rag_pipeline_service(request: Request):
    """FastAPI dependency: return RagPipelineService from app state."""
    return getattr(request.app.state, "rag_service", None)


RagPipelineServiceDep = Annotated[Any, Depends(get_rag_pipeline_service)]


def get_rag_query_service(request: Request):
    """FastAPI dependency: return RAGQueryService from app state.

    The service is initialized once in the lifespan context manager.
    Returns None if the service failed to initialize (degraded mode).

    Args:
        request: The FastAPI Request object (provides access to app.state).

    Returns:
        The RAGQueryService singleton, or None if unavailable.
    """
    return getattr(request.app.state, "rag_query_service", None)


RagQueryServiceDep = Annotated[Any, Depends(get_rag_query_service)]


"""DocEngine — Policies API Endpoints (v1).

GET /api/v1/policies/recent  — List recent digitized policies with basic info.
GET /api/v1/policies/search  — Search a policy by policy number, ID, or keyword.
GET /api/v1/policies/{id}    — Get basic policy info by UUID.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.api.v1.schemas import (
    PolicyBasicInfoSchema,
    PolicySearchResponseSchema,
    RecentPoliciesResponseSchema,
)
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_structured_search import (
    PgStructuredSearchRepository,
)
from app.infrastructure.logging.logger import get_logger

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


@router.get(
    "/recent",
    response_model=RecentPoliciesResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="List recent digitized policies",
    description="Returns the most recent digitized policies stored in the database with their basic information.",
)
def get_recent_policies(
    repo: StructuredSearchDep,
    limit: int = Query(default=20, ge=1, le=50, description="Max policies to return (default 20)"),
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
    summary="Search policy by number or keyword",
    description="Searches for a policy by its policy number, UUID, or keyword, and returns its basic information.",
)
def search_policy(
    repo: StructuredSearchDep,
    q: str = Query(..., min_length=1, description="Policy number, ID or keyword to search"),
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
    "/{policy_id}",
    response_model=PolicyBasicInfoSchema,
    status_code=status.HTTP_200_OK,
    summary="Get basic policy information by UUID",
    description="Returns standard basic policy details for a given policy ID.",
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

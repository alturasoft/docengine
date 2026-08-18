"""DocEngine — RAG Query API Endpoints (v1).

POST /api/v1/query   — Submit a natural language question and receive an
                       LLM-generated answer sourced exclusively from indexed
                       policy documents.
GET  /api/v1/query/health — Check RAGQueryService availability.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import RagQueryServiceDep
from app.api.v1.schemas import QueryRequest, QueryResponseSchema, SourceChunkSchema
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/query", tags=["RAG Query"])


@router.post(
    "",
    response_model=QueryResponseSchema,
    status_code=status.HTTP_200_OK,
    summary="Query documents with natural language",
    description=(
        "Submit a natural language question. DocEngine retrieves the most relevant "
        "document chunks from the vector store and generates a precise, "
        "source-grounded answer using OpenAI. "
        "The answer is based exclusively on indexed documents — no hallucination."
    ),
)
def query_documents(
    body: QueryRequest,
    rag_query_service: RagQueryServiceDep,
) -> QueryResponseSchema:
    """Answer a user question using the RAG pipeline.

    Args:
        body: QueryRequest containing the question, optional top_k,
              similarity_threshold, and metadata filters.
        rag_query_service: Injected RAGQueryService (from app.state).

    Returns:
        QueryResponseSchema with the LLM answer and source chunk references.

    Raises:
        HTTPException 503: If the RAG Query Service is not initialized.
        HTTPException 400: If the question fails validation.
        HTTPException 500: If an unexpected error occurs during retrieval or generation.
    """
    if rag_query_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "RAG Query Service is not available. "
                "Check server logs for initialization errors."
            ),
        )

    try:
        response = rag_query_service.query(
            question=body.question,
            top_k=body.top_k,
            similarity_threshold=body.similarity_threshold,
            filters=body.filters,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        logger.error("RAG query service error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("Unexpected error in RAG query endpoint", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query failed: {exc}",
        ) from exc

    return _to_response_schema(response)


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="RAG Query Service health check",
    description="Returns the operational status of the RAG Query Service.",
)
def query_health(rag_query_service: RagQueryServiceDep) -> dict[str, Any]:
    """Check if the RAGQueryService is initialized and ready.

    Args:
        rag_query_service: Injected service (may be None if initialization failed).

    Returns:
        Dict with 'status' key: 'ok' | 'unavailable'.
    """
    if rag_query_service is None:
        return {
            "status": "unavailable",
            "detail": "RAG Query Service failed to initialize. Check server logs.",
        }
    return {
        "status": "ok",
        "detail": "RAG Query Service is operational.",
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _to_response_schema(response: Any) -> QueryResponseSchema:
    """Convert a domain QueryResponse to the API QueryResponseSchema.

    Args:
        response: QueryResponse domain object.

    Returns:
        QueryResponseSchema suitable for JSON serialization.
    """
    sources = [
        SourceChunkSchema(
            chunk_id=chunk.chunk_id,
            policy_id=chunk.policy_id,
            chunk_index=chunk.chunk_index,
            similarity_score=round(chunk.similarity_score, 4),
            document_label=chunk.document_label,
            chunk_content=chunk.chunk_content,
            metadata_json=chunk.metadata_json,
        )
        for chunk in response.sources
    ]

    return QueryResponseSchema(
        answer=response.answer,
        query=response.query,
        chunks_used=response.chunks_used,
        model_used=response.model_used,
        no_context_found=response.no_context_found,
        sources=sources,
        created_at=response.created_at,
    )

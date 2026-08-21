"""DocEngine — RAG Query Factory.

Factory module to assemble and return a RAGQueryService with all dependencies.
The EmbeddingService instance is injected from outside (passed as parameter)
to enable reuse of the already-loaded bge-m3 model — avoiding a second
SentenceTransformer load in memory.
"""

from __future__ import annotations

from app.application.embedding_service import EmbeddingService
from app.application.rag_query_service import RAGQueryService
from app.application.reranker_service import RerankerService
from app.config.settings import get_settings
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_hybrid_search import PgHybridSearchRepository
from app.infrastructure.database.pg_vector_search import PgVectorSearchRepository


def create_rag_query_service(
    embedding_service: EmbeddingService | None = None,
) -> RAGQueryService:
    """Build and wire a RAGQueryService instance.

    The EmbeddingService is accepted as an optional parameter to allow the
    caller (lifespan in main.py) to inject the already-initialized instance
    from app.state, avoiding duplicate model loading.

    If no embedding_service is provided, a new instance is created using the
    application settings. This fallback ensures the factory is self-contained
    and usable in isolation (e.g., CLI scripts, tests).

    Hybrid search and reranker are always wired in. The reranker respects
    the DOCENGINE_RERANKER_ENABLED flag — when False, it operates in mock
    mode returning the first top_n chunks without loading the cross-encoder
    model (safe for Windows dev environments with limited RAM).

    Args:
        embedding_service: Optional pre-initialized EmbeddingService (bge-m3).
            Pass app.state.rag_service._embedder from the lifespan context
            to reuse the warm model instance.

    Returns:
        Fully configured RAGQueryService ready to handle queries.
    """
    settings = get_settings()

    # Database setup — read-only repositories, separate connection scope
    db_manager = DatabaseManager(settings.database)
    vector_search = PgVectorSearchRepository(db_manager)
    hybrid_search = PgHybridSearchRepository(db_manager)

    # Reranker — lazy model loading; mock mode when enabled=False
    reranker = RerankerService(settings.reranker)

    # Reuse the provided embedding_service, or create a new one as fallback
    if embedding_service is None:
        embedding_service = EmbeddingService(settings.embedding)

    return RAGQueryService(
        embedding_service=embedding_service,
        vector_search=vector_search,
        config=settings.rag_query,
        hybrid_search=hybrid_search,
        reranker=reranker,
    )


"""DocEngine — RAG Factory.

Factory module to assemble and instantiate RagPipelineService with all dependencies.
"""

from __future__ import annotations

from app.application.chunking_service import ChunkingService
from app.application.embedding_service import EmbeddingService
from app.application.openai_structured_extractor import OpenAIStructuredExtractor
from app.application.rag_pipeline_service import RagPipelineService
from app.config.settings import get_settings
from app.infrastructure.database.db_connection import DatabaseManager
from app.infrastructure.database.pg_rag_repository import PgRagRepository


def create_rag_pipeline_service() -> RagPipelineService:
    """Build and wire RagPipelineService instance using application settings.

    Returns:
        Fully configured RagPipelineService instance.
    """
    settings = get_settings()

    # Database setup
    db_manager = DatabaseManager(settings.database)
    repository = PgRagRepository(db_manager)

    # RAG Services
    chunking_service = ChunkingService(settings.embedding)
    embedding_service = EmbeddingService(settings.embedding)
    structured_extractor = OpenAIStructuredExtractor()

    return RagPipelineService(
        chunking_service=chunking_service,
        embedding_service=embedding_service,
        structured_extractor=structured_extractor,
        repository=repository,
    )

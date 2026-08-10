"""DocEngine — Application Service: EmbeddingService.

Generates dense vector embeddings locally using SentenceTransformers (BAAI/bge-m3).
Outputs exactly 1024-dimensional vectors via batched encoding.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.config.settings import EmbeddingConfig
from app.domain.models.chunks import PolicyChunk
from app.infrastructure.logging.logger import get_logger

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

logger = get_logger(__name__)


class EmbeddingService:
    """Service for local vector embedding generation using BAAI/bge-m3.

    - Lazy-initializes the SentenceTransformer model on first usage.
    - Performs batch encoding for optimal CPU/GPU throughput.
    - Ensures each output vector has exactly 1024 dimensions.
    """

    EXPECTED_DIMENSION = 1024

    def __init__(self, config: EmbeddingConfig) -> None:
        self._config = config
        self._model: SentenceTransformer | None = None

    def _get_model(self) -> SentenceTransformer:
        """Lazy-load the SentenceTransformer model."""
        if self._model is None:
            logger.info(
                "Loading local embedding model",
                model_name=self._config.model_name,
                device=self._config.device,
            )
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._model = SentenceTransformer(
                self._config.model_name,
                device=self._config.device,
            )
            logger.info(
                "Embedding model successfully loaded",
                model_name=self._config.model_name,
            )
        return self._model

    def generate_embeddings_for_chunks(self, chunks: list[PolicyChunk]) -> list[PolicyChunk]:
        """Generate 1024-dimensional embeddings for a list of PolicyChunk instances.

        Modifies the chunks in-place by assigning chunk.embedding.

        Args:
            chunks: List of PolicyChunk instances.

        Returns:
            The same list of PolicyChunk instances with embeddings assigned.
        """
        if not chunks:
            return chunks

        texts = [chunk.chunk_content for chunk in chunks]
        model = self._get_model()

        logger.info(
            "Generating local embeddings",
            chunk_count=len(texts),
            batch_size=self._config.batch_size,
        )

        # Generate vectors using batch encoding
        embeddings_matrix = model.encode(
            texts,
            batch_size=self._config.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

        for chunk, emb in zip(chunks, embeddings_matrix):
            emb_list = emb.tolist()
            if len(emb_list) != self.EXPECTED_DIMENSION:
                raise ValueError(
                    f"Unexpected embedding dimension: got {len(emb_list)}, "
                    f"expected {self.EXPECTED_DIMENSION}"
                )
            chunk.embedding = emb_list

        logger.info(
            "Local embedding generation complete",
            total_vectors=len(chunks),
            dimension=self.EXPECTED_DIMENSION,
        )

        return chunks

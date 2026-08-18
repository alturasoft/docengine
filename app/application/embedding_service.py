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

    def _resolve_cache_folder(self) -> str | None:
        """Resolve a valid, writable cache directory for HuggingFace / SentenceTransformers."""
        if self._config.cache_folder is not None:
            return str(self._config.cache_folder)

        import os
        if os.environ.get("HF_HOME") or os.environ.get("SENTENCE_TRANSFORMERS_HOME"):
            return None

        from pathlib import Path
        import tempfile

        try:
            home = Path.home()
            if str(home) == "/nonexistent" or not home.exists():
                fallback = Path(tempfile.gettempdir()) / "huggingface"
                fallback.mkdir(parents=True, exist_ok=True)
                return str(fallback)
        except Exception as exc:
            logger.warning("Could not access home directory, using temp fallback cache", error=str(exc))
            fallback = Path(tempfile.gettempdir()) / "huggingface"
            fallback.mkdir(parents=True, exist_ok=True)
            return str(fallback)

        return None

    def _get_model(self) -> SentenceTransformer:
        """Lazy-load the SentenceTransformer model.

        Supports the following devices:
        - 'cpu'       : Standard CPU inference (always available).
        - 'directml'  : AMD/Intel GPU acceleration on Windows via torch-directml.
                        Falls back to CPU automatically if torch-directml is not installed.
        - 'cuda'      : NVIDIA GPU (requires CUDA toolkit).
        - 'mps'       : Apple Silicon GPU.
        """
        if self._model is None:
            device = self._config.device

            # DirectML support — AMD Radeon 780M on Windows
            if device == "directml":
                try:
                    import torch_directml  # noqa: PLC0415
                    device = torch_directml.device()
                    logger.info(
                        "DirectML device initialised for AMD GPU acceleration",
                        device=str(device),
                    )
                except ImportError:
                    logger.warning(
                        "torch-directml not installed. Falling back to CPU. "
                        "Install with: pip install torch-directml",
                    )
                    device = "cpu"

            logger.info(
                "Loading local embedding model",
                model_name=self._config.model_name,
                device=str(device),
            )
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            cache_folder = self._resolve_cache_folder()
            kwargs: dict[str, str] = {}
            if cache_folder:
                kwargs["cache_folder"] = cache_folder

            self._model = SentenceTransformer(
                self._config.model_name,
                device=device,
                **kwargs,
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

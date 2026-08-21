"""DocEngine — Application Service: RerankerService.

Provides cross-encoder reranking of retrieved Parent Chunks using
BAAI/bge-reranker-v2-m3 for higher-quality ranking before LLM context
injection.

When disabled (DOCENGINE_RERANKER_ENABLED=False), the service operates in
mock mode: it returns the first top_n chunks unchanged, preserving the
data structure contract so the rest of the pipeline functions correctly.

Usage:
    - Production (Linux): DOCENGINE_RERANKER_ENABLED=True → real cross-encoder
    - Development (Windows): DOCENGINE_RERANKER_ENABLED=False → lightweight mock
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.domain.models.query_models import RetrievedChunk
from app.infrastructure.logging.logger import get_logger

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

    from app.config.settings import RerankerConfig

logger = get_logger(__name__)


class RerankerService:
    """Service for cross-encoder reranking of Parent Chunks.

    Lazy-loads the cross-encoder model on first usage to avoid memory
    consumption until actually needed. When disabled via config, no model
    is loaded and the mock fallback is used instead.

    The cross-encoder scores (query, document) pairs directly, producing
    a relevance score that is more accurate than bi-encoder cosine similarity
    for final-stage ranking.

    Args:
        config: RerankerConfig controlling model, device, and enabled flag.
    """

    def __init__(self, config: RerankerConfig) -> None:
        self._config = config
        self._model: CrossEncoder | None = None

    def rerank(
        self,
        query: str,
        parent_chunks: list[RetrievedChunk],
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        """Score each Parent Chunk against the query and return the top-N.

        When the reranker is disabled (mock mode), returns the first top_n
        chunks from the input list unchanged, preserving their existing
        similarity_score values for pipeline compatibility.

        Args:
            query: The original user question.
            parent_chunks: List of Parent Chunks to rerank. These should
                already be pre-filtered by the hybrid search step.
            top_n: Number of top chunks to return. Defaults to config.top_n.

        Returns:
            List of the top-N RetrievedChunk instances, ordered by reranker
            score (highest first). Each chunk's similarity_score is updated
            to reflect the cross-encoder score (normalized to 0.0–1.0 range).
        """
        resolved_top_n = top_n if top_n is not None else self._config.top_n

        if not parent_chunks:
            return []

        # If fewer chunks than requested, return all
        if len(parent_chunks) <= resolved_top_n:
            logger.debug(
                "Fewer parent chunks than top_n — returning all",
                chunk_count=len(parent_chunks),
                top_n=resolved_top_n,
            )
            return parent_chunks

        # --- MOCK MODE: return first top_n with original scores ---
        if not self._config.enabled:
            logger.info(
                "Reranker disabled (mock mode) — returning first top_n chunks as-is",
                top_n=resolved_top_n,
                total_chunks=len(parent_chunks),
            )
            return parent_chunks[:resolved_top_n]

        # --- REAL MODE: cross-encoder scoring ---
        model = self._get_model()

        pairs = [(query, chunk.chunk_content) for chunk in parent_chunks]

        logger.info(
            "Running cross-encoder reranking",
            model=self._config.model_name,
            pairs=len(pairs),
            top_n=resolved_top_n,
        )

        scores = model.predict(pairs)

        # Pair chunks with scores and sort descending
        scored_chunks = list(zip(parent_chunks, scores))
        scored_chunks.sort(key=lambda x: float(x[1]), reverse=True)

        # Update similarity_score on the returned chunks with the reranker score
        # Normalize to 0.0-1.0 range using sigmoid if scores are raw logits
        results: list[RetrievedChunk] = []
        for chunk, score in scored_chunks[:resolved_top_n]:
            chunk.similarity_score = float(score)
            results.append(chunk)

        logger.info(
            "Cross-encoder reranking complete",
            top_n=resolved_top_n,
            best_score=round(float(scored_chunks[0][1]), 4) if scored_chunks else 0.0,
            worst_included_score=round(float(results[-1].similarity_score), 4) if results else 0.0,
        )

        return results

    def _get_model(self) -> CrossEncoder:
        """Lazy-load the CrossEncoder model.

        Supports the same device options as EmbeddingService:
        - 'cpu': Standard CPU inference.
        - 'directml': AMD/Intel GPU on Windows (falls back to CPU).
        - 'cuda': NVIDIA GPU.
        - 'mps': Apple Silicon GPU.

        Returns:
            Configured CrossEncoder instance.
        """
        if self._model is None:
            device = self._config.device

            # DirectML support — AMD Radeon 780M on Windows
            if device == "directml":
                try:
                    import torch_directml  # noqa: PLC0415
                    device = str(torch_directml.device())
                    logger.info(
                        "DirectML device initialised for reranker",
                        device=device,
                    )
                except ImportError:
                    logger.warning(
                        "torch-directml not installed for reranker. Falling back to CPU.",
                    )
                    device = "cpu"

            logger.info(
                "Loading cross-encoder reranker model",
                model_name=self._config.model_name,
                device=device,
            )

            from sentence_transformers import CrossEncoder  # noqa: PLC0415

            kwargs: dict[str, str] = {}
            cache_folder = self._resolve_cache_folder()
            if cache_folder:
                kwargs["cache_folder"] = cache_folder

            self._model = CrossEncoder(
                self._config.model_name,
                device=device,
                **kwargs,
            )

            logger.info(
                "Cross-encoder reranker model loaded",
                model_name=self._config.model_name,
            )

        return self._model

    def _resolve_cache_folder(self) -> str | None:
        """Resolve a valid, writable cache directory for HuggingFace models."""
        if self._config.cache_folder is not None:
            return str(self._config.cache_folder)

        import os  # noqa: PLC0415

        if os.environ.get("HF_HOME") or os.environ.get("SENTENCE_TRANSFORMERS_HOME"):
            return None

        from pathlib import Path  # noqa: PLC0415
        import tempfile  # noqa: PLC0415

        try:
            home = Path.home()
            if str(home) == "/nonexistent" or not home.exists():
                fallback = Path(tempfile.gettempdir()) / "huggingface"
                fallback.mkdir(parents=True, exist_ok=True)
                return str(fallback)
        except Exception as exc:
            logger.warning(
                "Could not access home directory for reranker cache, using temp fallback",
                error=str(exc),
            )
            fallback = Path(tempfile.gettempdir()) / "huggingface"
            fallback.mkdir(parents=True, exist_ok=True)
            return str(fallback)

        return None

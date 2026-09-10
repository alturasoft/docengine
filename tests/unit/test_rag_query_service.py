"""Unit tests for RAGQueryService and QueryRequest schema."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.api.v1.schemas import QueryRequest
from app.application.rag_query_service import _SYSTEM_PROMPT, RAGQueryService
from app.config.settings import RAGQueryConfig
from app.domain.models.query_models import RetrievedChunk


class TestQueryRequestSchema:
    """Verify QueryRequest schema defaults and validation."""

    def test_default_values_are_none(self) -> None:
        """When not provided, top_k and similarity_threshold should default to None."""
        req = QueryRequest(question="¿Cuál es la prima total?")
        assert req.top_k is None
        assert req.similarity_threshold is None

    def test_custom_values_allowed_up_to_limit(self) -> None:
        """Explicit top_k up to 50 and similarity_threshold up to 1.0 are accepted."""
        req = QueryRequest(question="¿Tiene cobertura?", top_k=30, similarity_threshold=0.15)
        assert req.top_k == 30
        assert req.similarity_threshold == 0.15


class TestRAGQueryServicePipeline:
    """Verify retrieval and prompt configuration in RAGQueryService."""

    def test_system_prompt_is_constructive(self) -> None:
        """Verify prompt configuration."""
        assert "TERMINANTEMENTE PROHIBIDO" not in _SYSTEM_PROMPT
        assert "Exhaustividad y Enfoque Constructivo" in _SYSTEM_PROMPT
        assert "deducible / franquicia" in _SYSTEM_PROMPT

    def test_retrieve_and_rerank_propagates_top_k(self) -> None:
        """Ensure _retrieve_and_rerank calls hybrid_search with scaled children and rerank with top_n=top_k."""
        mock_embedder = MagicMock()
        mock_vector = MagicMock()
        mock_hybrid = MagicMock()
        mock_reranker = MagicMock()
        mock_config = RAGQueryConfig(top_k=12, similarity_threshold=0.20)

        service = RAGQueryService(
            embedding_service=mock_embedder,
            vector_search=mock_vector,
            config=mock_config,
            hybrid_search=mock_hybrid,
            reranker=mock_reranker,
        )

        dummy_chunk = RetrievedChunk(
            chunk_id="test-1",
            policy_id="pol-1",
            chunk_index=0,
            chunk_content="Contenido de prueba",
            metadata_json={},
            similarity_score=0.85,
        )
        mock_hybrid.search_and_resolve.return_value = [dummy_chunk]
        mock_reranker.rerank.return_value = [dummy_chunk]

        chunks = service._retrieve_and_rerank(
            query_vector=[0.1] * 1024,
            query_text="pregunta de prueba",
            top_k=15,
            filters=None,
        )

        # Verify hybrid search was called with top_k_children = max(30, 15 * 3) = 45
        mock_hybrid.search_and_resolve.assert_called_once()
        call_kwargs = mock_hybrid.search_and_resolve.call_args[1]
        assert call_kwargs["top_k_children"] == 45
        assert call_kwargs["rrf_pool"] == 90

        # Verify reranker received top_n=15
        mock_reranker.rerank.assert_called_once_with(
            query="pregunta de prueba",
            parent_chunks=[dummy_chunk],
            top_n=15,
        )
        assert chunks == [dummy_chunk]

    def test_query_retrieves_entire_policy_when_policy_id_filtered(self) -> None:
        """Ensure full policy retrieval is triggered when policy_id filter is provided."""
        mock_embedder = MagicMock()
        mock_embedder.embed_query.return_value = [0.1] * 1024
        mock_vector = MagicMock()
        mock_config = RAGQueryConfig(top_k=5, similarity_threshold=0.20)

        all_policy_chunks = [
            RetrievedChunk(
                chunk_id=f"chunk-{i}",
                policy_id="test-pol-uuid",
                chunk_index=i,
                chunk_content=f"Cláusula {i}",
                metadata_json={},
                similarity_score=1.0,
            )
            for i in range(10)
        ]
        mock_vector.get_all_chunks_for_policy.return_value = all_policy_chunks

        service = RAGQueryService(
            embedding_service=mock_embedder,
            vector_search=mock_vector,
            config=mock_config,
        )

        with patch.object(service, "_generate_answer", return_value="Respuesta de prueba"):
            response = service.query(
                question="¿Qué coberturas tiene?",
                filters={"policy_id": "test-pol-uuid"},
            )

        mock_vector.get_all_chunks_for_policy.assert_called_once_with("test-pol-uuid")
        assert len(response.sources) == 10
        assert response.chunks_used == 10
        assert response.answer == "Respuesta de prueba"

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

    def test_query_retrieves_entire_envelope_when_envelope_id_filtered(self):
        """When envelope_id is in filters, RAGQueryService fetches ALL chunks of the envelope."""
        mock_embedder = MagicMock()
        mock_embedder.generate_embeddings_for_chunks.return_value = [
            MagicMock(embedding=[0.1] * 1024)
        ]
        mock_config = RAGQueryConfig()
        mock_vector = MagicMock()

        all_envelope_chunks = [
            RetrievedChunk(
                chunk_id=f"chunk-{i}",
                policy_id=f"pol-{i % 2}",
                chunk_index=i,
                chunk_content=f"Anexo o Cláusula {i}",
                metadata_json={},
                similarity_score=1.0,
            )
            for i in range(12)
        ]
        mock_vector.get_all_chunks_for_envelope.return_value = all_envelope_chunks

        service = RAGQueryService(
            embedding_service=mock_embedder,
            vector_search=mock_vector,
            config=mock_config,
        )

        with patch.object(service, "_generate_answer", return_value="Respuesta sobre sobre completo"):
            response = service.query(
                question="¿Cuáles son los bienes asegurados?",
                filters={"envelope_id": "test-env-uuid"},
            )

        mock_vector.get_all_chunks_for_envelope.assert_called_once_with("test-env-uuid")
        assert len(response.sources) == 12
        assert response.chunks_used == 12
        assert response.answer == "Respuesta sobre sobre completo"

    def test_query_retrieves_entire_client_when_id_cliente_filtered(self):
        """When id_cliente is in filters, RAGQueryService fetches ALL chunks of the client."""
        mock_embedder = MagicMock()
        mock_embedder.generate_embeddings_for_chunks.return_value = [
            MagicMock(embedding=[0.1] * 1024)
        ]
        mock_config = RAGQueryConfig()
        mock_vector = MagicMock()

        all_client_chunks = [
            RetrievedChunk(
                chunk_id=f"chunk-{i}",
                policy_id=f"pol-cli-{i % 2}",
                chunk_index=i,
                chunk_content=f"Documento de cliente {i}",
                metadata_json={"id_cliente": "10203040"},
                similarity_score=1.0,
            )
            for i in range(8)
        ]
        mock_vector.get_all_chunks_for_client.return_value = all_client_chunks

        service = RAGQueryService(
            embedding_service=mock_embedder,
            vector_search=mock_vector,
            config=mock_config,
        )

        with patch.object(service, "_generate_answer", return_value="Respuesta para cliente"):
            response = service.query(
                question="¿Cuáles pólizas tiene el cliente 10203040?",
                filters={"id_cliente": "10203040"},
            )

        mock_vector.get_all_chunks_for_client.assert_called_once_with("10203040")
        assert len(response.sources) == 8
        assert response.chunks_used == 8
        assert response.answer == "Respuesta para cliente"

    def test_query_injects_structured_client_portfolio_chunk_when_id_cliente_filtered(self):
        """When id_cliente filter is provided, structured portfolio chunk should be injected."""
        mock_embedder = MagicMock()
        mock_embedder.embed_query.return_value = [0.1] * 1024
        mock_config = RAGQueryConfig()
        mock_vector = MagicMock()
        mock_structured = MagicMock()

        sample_records = [
            {
                "policy_id": "pol-1",
                "file_name": "auto.pdf",
                "company_sigla": "BISA",
                "created_at": "2026-01-01",
                "data": {
                    "datos_cabecera": {
                        "numero_poliza": "12345",
                        "ramo": "Automotores",
                        "vigencia_desde": "2026-01-01",
                        "vigencia_hasta": "2026-12-31",
                    }
                },
                "id_cliente": "10203040",
            }
        ]
        portfolio_chunk = RetrievedChunk(
            chunk_id="client-portfolio-10203040",
            policy_id="client-portfolio",
            chunk_index=0,
            chunk_content="[CARTERA DE PÓLIZAS DEL CLIENTE — CI/NIT: 10203040]",
            metadata_json={"id_cliente": "10203040"},
            similarity_score=1.0,
        )

        mock_structured.find_by_client_id.return_value = sample_records
        mock_structured.format_client_portfolio_chunk.return_value = portfolio_chunk
        mock_vector.get_all_chunks_for_client.return_value = []

        service = RAGQueryService(
            embedding_service=mock_embedder,
            vector_search=mock_vector,
            config=mock_config,
            structured_search=mock_structured,
        )

        with patch.object(service, "_generate_answer", return_value="Cartera analizada"):
            response = service.query(
                question="¿Cuáles son los ramos del cliente?",
                filters={"id_cliente": "10203040"},
            )

        mock_structured.find_by_client_id.assert_called_once_with("10203040")
        mock_structured.format_client_portfolio_chunk.assert_called_once_with(sample_records, "10203040")
        assert any(c.chunk_id == "client-portfolio-10203040" for c in response.sources)
        assert response.answer == "Cartera analizada"



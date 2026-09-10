"""DocEngine — Unit Tests: Structured Search & RAG Integration.

Tests verifying:
1. Formatting of structured JSON (cabecera, coberturas, condiciones especiales) to context chunks.
2. Integration of PgStructuredSearchRepository into RAGQueryService.
3. Auto-injection of policy conditions into the LLM context when querying by policy number.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from app.config.settings import RAGQueryConfig
from app.application.rag_query_service import RAGQueryService
from app.infrastructure.database.pg_structured_search import PgStructuredSearchRepository
from app.domain.models.chunks import PolicyChunk


class TestPgStructuredSearchFormatting:
    """Tests for format_structured_chunk."""

    def test_format_structured_chunk_complete_payload(self) -> None:
        db_mock = MagicMock()
        repo = PgStructuredSearchRepository(db_mock)

        record = {
            "policy_id": "11111111-2222-3333-4444-555555555555",
            "file_name": "poliza_credinform_SCR0667473.pdf",
            "company_sigla": "CRI",
            "data": {
                "datos_cabecera": {
                    "numero_poliza": "SCR0667473",
                    "asegurado": "Empresa Boliviana S.A.",
                    "tomador": "Empresa Boliviana S.A.",
                    "aseguradora": "CREDINFORM INTERNATIONAL",
                    "sigla_empresa": "CRI",
                    "vigencia_desde": "01/01/2026",
                    "vigencia_hasta": "31/12/2026",
                    "moneda": "USD",
                    "prima_total": "1,500.00",
                },
                "coberturas": [
                    {
                        "nombre": "Responsabilidad Civil",
                        "suma_asegurada": "100,000 USD",
                        "deducible": "10% mínimo 100 USD",
                        "limite": "100,000 USD por evento",
                    },
                    {
                        "nombre": "Daños Materiales",
                        "suma_asegurada": "50,000 USD",
                        "deducible": "5% del siniestro",
                        "limite": None,
                    },
                ],
                "condiciones_especiales": [
                    "Cláusula de notificación de siniestro dentro de los 5 días hábiles.",
                    "Cobertura ampliada para eventos de fuerza mayor o caso fortuito.",
                ],
            },
        }

        chunk = repo.format_structured_chunk(record)

        assert chunk.policy_id == "11111111-2222-3333-4444-555555555555"
        assert chunk.similarity_score == 1.0
        assert "SCR0667473" in chunk.chunk_content
        assert "Empresa Boliviana S.A." in chunk.chunk_content
        assert "Responsabilidad Civil" in chunk.chunk_content
        assert "Cláusula de notificación de siniestro" in chunk.chunk_content
        assert "Cobertura ampliada para eventos de fuerza mayor" in chunk.chunk_content
        assert chunk.metadata_json["section"] == "Ficha Técnica Estructurada (JSONB)"


class TestRAGQueryWithStructuredSearch:
    """Tests verifying RAGQueryService with structured search enabled."""

    @patch.dict("os.environ", {"OPENAI_API_KEY": "test-key-1234"})
    @patch("openai.OpenAI")
    def test_query_by_policy_number_injects_structured_chunk(self, mock_openai_cls: MagicMock) -> None:
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(message=MagicMock(content="Las condiciones especiales son: 1. Notificación de siniestro en 5 días."))
        ]
        mock_client.chat.completions.create.return_value = mock_completion

        mock_embedder = MagicMock()
        mock_embedder.generate_embeddings_for_chunks.return_value = [
            PolicyChunk(chunk_index=0, chunk_content="query", embedding=[0.1] * 1024)
        ]

        mock_vector_search = MagicMock()
        mock_vector_search.search_similar_chunks.return_value = []

        mock_structured_search = MagicMock()
        mock_structured_search.search_by_query_text.return_value = [
            {
                "policy_id": "uuid-1234",
                "file_name": "SCR0667473.pdf",
                "company_sigla": "CRI",
                "data": {
                    "datos_cabecera": {"numero_poliza": "SCR0667473"},
                    "coberturas": [],
                    "condiciones_especiales": ["Notificación de siniestro en 5 días."],
                },
            }
        ]

        repo = PgStructuredSearchRepository(MagicMock())
        structured_chunk = repo.format_structured_chunk(
            mock_structured_search.search_by_query_text.return_value[0]
        )
        mock_structured_search.format_structured_chunk.return_value = structured_chunk

        config = RAGQueryConfig(openai_api_key="test-key")
        service = RAGQueryService(
            embedding_service=mock_embedder,
            vector_search=mock_vector_search,
            config=config,
            structured_search=mock_structured_search,
        )

        response = service.query("cuales son las condiciones especiales de lapoliza SCR0667473")

        assert not response.no_context_found
        assert response.chunks_used >= 1
        assert "Las condiciones especiales son" in response.answer

        # Verify OpenAI was called with the structured conditions in the prompt
        call_args = mock_client.chat.completions.create.call_args[1]
        user_message = call_args["messages"][1]["content"]
        assert "SCR0667473" in user_message
        assert "Notificación de siniestro en 5 días" in user_message


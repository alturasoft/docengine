"""DocEngine — Unit Tests: Policy Processing Stats & Telemetry.

Tests for:
1. PolicyProcessingStats domain model serialization
2. OpenAIStructuredExtractor usage capture
3. RagPipelineService stats compilation and persistence
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.application.chunking_service import ChunkingService
from app.application.embedding_service import EmbeddingService
from app.application.openai_structured_extractor import OpenAIStructuredExtractor
from app.application.rag_pipeline_service import RagPipelineService
from app.domain.models.chunks import PolicyChunk
from app.domain.models.document import DocumentMetadata, ExtractionResult
from app.domain.models.rag_models import PolicyProcessingStats, RagProcessingReport
from app.infrastructure.database.pg_rag_repository import PgRagRepository, _normalize_file_type


class TestPolicyProcessingStatsModel:
    """Tests for PolicyProcessingStats domain model."""

    def test_stats_model_defaults_and_serialization(self) -> None:
        stats = PolicyProcessingStats(
            policy_id="test-uuid-1234",
            job_id="job-uuid-5678",
            policy_number="POL-998877",
            company_sigla="CRI",
            file_type="HYBRID",
            ocr_applied=True,
            scanned_page_ratio=0.5,
            total_pages=10,
            extraction_time_seconds=5.25,
            time_per_page_seconds=0.525,
            chunking_time_seconds=0.12,
            embedding_time_seconds=1.45,
            openai_time_seconds=2.30,
            total_pipeline_time_seconds=9.12,
            total_chunks=15,
            parent_chunks=5,
            child_chunks=10,
            openai_prompt_tokens=1500,
            openai_completion_tokens=350,
            openai_total_tokens=1850,
            openai_estimated_cost_usd=0.00725,
            coberturas_extracted_count=4,
            tables_detected=2,
            memory_peak_mb=128.5,
        )

        d = stats.to_dict()
        assert d["policy_id"] == "test-uuid-1234"
        assert d["job_id"] == "job-uuid-5678"
        assert d["policy_number"] == "POL-998877"
        assert d["company_sigla"] == "CRI"
        assert d["file_type"] == "HYBRID"
        assert d["ocr_applied"] is True
        assert d["total_pages"] == 10
        assert d["extraction_time_seconds"] == 5.25
        assert d["time_per_page_seconds"] == 0.525
        assert d["openai_prompt_tokens"] == 1500
        assert d["openai_completion_tokens"] == 350
        assert d["openai_total_tokens"] == 1850
        assert d["openai_estimated_cost_usd"] == 0.00725
        assert d["coberturas_extracted_count"] == 4
        assert d["tables_detected"] == 2
        assert d["memory_peak_mb"] == 128.5


class TestOpenAIUsageCapture:
    """Tests for OpenAIStructuredExtractor usage statistics and prompt generation."""

    def test_fallback_dict_when_no_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        extractor = OpenAIStructuredExtractor()
        res = extractor.extract_structured_json(markdown="# Test", company_sigla="CRI")
        assert res["datos_cabecera"]["sigla_empresa"] == "CRI"
        assert res["sigla_empresa"] == "CRI"
        assert res["extraction_source"] == "fallback"
        assert "coberturas" in res
        assert "condiciones_especiales" in res

    def test_build_system_prompt_without_sigla(self) -> None:
        extractor = OpenAIStructuredExtractor()
        prompt = extractor._build_system_prompt()
        assert "INSTRUCCIONES CRÍTICAS:" in prompt
        assert "numero_poliza" in prompt
        assert "asegurado" in prompt
        assert "datos_cabecera" in prompt
        assert "coberturas" in prompt
        assert "condiciones_especiales" in prompt

    def test_build_system_prompt_with_sigla(self) -> None:
        extractor = OpenAIStructuredExtractor()
        prompt = extractor._build_system_prompt(company_sigla="BIS")
        assert "INSTRUCCIONES CRÍTICAS:" in prompt
        assert "BIS" in prompt
        assert "sigla_empresa" in prompt


class TestRagPipelineStatsIntegration:
    """Tests for stats calculation within RagPipelineService."""

    def test_pipeline_computes_and_passes_stats(self) -> None:
        mock_chunker = MagicMock(spec=ChunkingService)
        mock_embedder = MagicMock(spec=EmbeddingService)
        mock_extractor = MagicMock(spec=OpenAIStructuredExtractor)
        mock_repo = MagicMock(spec=PgRagRepository)

        mock_repo.policy_exists_by_hash.return_value = None
        mock_repo.create_job.return_value = "job-111"
        mock_repo.save_rag_policy_transactional.return_value = "pol-222"

        chunk1 = PolicyChunk(
            chunk_index=0,
            chunk_content="parent text",
            metadata_json={},
            chunk_id="c1",
            parent_id=None,
            chunk_type="parent",
        )
        chunk2 = PolicyChunk(
            chunk_index=1,
            chunk_content="child text",
            metadata_json={},
            chunk_id="c2",
            parent_id="c1",
            chunk_type="child",
        )
        mock_chunker.chunk_markdown.return_value = [chunk1, chunk2]
        mock_embedder.generate_embeddings_for_chunks.return_value = [chunk1, chunk2]
        mock_extractor.extract_structured_json.return_value = {
            "datos_cabecera": {
                "numero_poliza": "POL-12345",
                "asegurado": "Empresa Boliviana S.A.",
                "tomador": None,
                "aseguradora": "Bisa Seguros",
                "sigla_empresa": "BIS",
                "vigencia_desde": "01/01/2026",
                "vigencia_hasta": "01/01/2027",
                "moneda": "USD",
                "prima_total": "1500.00",
            },
            "coberturas": [{"nombre": "Cobertura 1"}],
            "condiciones_especiales": ["Clausula 1"],
            "_usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 200,
                "total_tokens": 1200,
                "estimated_cost_usd": 0.0045,
                "duration_seconds": 1.2,
            },
        }

        meta = DocumentMetadata(
            filename="poliza_test.pdf",
            source_path=Path("poliza_test.pdf"),
            sha256="aabbcc112233",
            page_count=4,
            extraction_time_seconds=2.0,
            docling_version="2.0",
            tables_detected=1,
            figures_detected=0,
            headers_removed=0,
            footers_removed=0,
            ocr_used=False,
            has_multi_column=False,
            markdown_size_bytes=500,
            company_sigla="CRI",
            pdf_type="digital",
        )
        from app.domain.models.extraction import ExtractionStatus

        result = ExtractionResult(
            document_id="doc-123",
            status=ExtractionStatus.SUCCESS,
            markdown="# Póliza Test",
            json_data={},
            metadata=meta,
        )

        service = RagPipelineService(
            chunking_service=mock_chunker,
            embedding_service=mock_embedder,
            structured_extractor=mock_extractor,
            repository=mock_repo,
        )

        report = service.process_extraction_result(result)

        assert report.policy_id == "pol-222"
        assert report.skipped_duplicate is False
        assert mock_repo.save_rag_policy_transactional.called

        _, kwargs = mock_repo.save_rag_policy_transactional.call_args
        stats_passed: PolicyProcessingStats = kwargs.get("stats")
        assert stats_passed is not None
        assert stats_passed.policy_number == "POL-12345"
        assert stats_passed.company_sigla == "CRI"
        assert stats_passed.file_type == "DIGITAL"
        assert stats_passed.total_pages == 4
        assert stats_passed.time_per_page_seconds == 0.5
        assert stats_passed.total_chunks == 2
        assert stats_passed.parent_chunks == 1
        assert stats_passed.child_chunks == 1
        assert stats_passed.openai_total_tokens == 1200
        assert stats_passed.openai_prompt_tokens == 1000
        assert stats_passed.openai_completion_tokens == 200
        assert stats_passed.openai_estimated_cost_usd == 0.0045
        assert stats_passed.coberturas_extracted_count == 1
        assert stats_passed.tables_detected == 1

    def test_pipeline_maps_native_pdf_type_to_digital(self) -> None:
        """Verify that a document marked as 'native' gets persisted with file_type='DIGITAL'."""
        mock_chunker = MagicMock(spec=ChunkingService)
        mock_embedder = MagicMock(spec=EmbeddingService)
        mock_extractor = MagicMock(spec=OpenAIStructuredExtractor)
        mock_repo = MagicMock(spec=PgRagRepository)

        mock_repo.policy_exists_by_hash.return_value = None
        mock_repo.create_job.return_value = "job-999"
        mock_repo.save_rag_policy_transactional.return_value = "pol-999"

        chunk = PolicyChunk(
            chunk_index=0,
            chunk_content="Native doc text",
            metadata_json={},
            chunk_id="chk-1",
            parent_id=None,
            chunk_type="parent",
        )

        mock_chunker.chunk_markdown.return_value = [chunk]
        mock_embedder.generate_embeddings_for_chunks.return_value = [chunk]
        mock_extractor.extract_structured_json.return_value = {
            "datos_cabecera": {"numero_poliza": "POL-999"},
            "_usage": {"total_tokens": 100},
        }

        meta = DocumentMetadata(
            filename="native_sample.pdf",
            source_path=Path("native_sample.pdf"),
            sha256="hash999",
            page_count=2,
            extraction_time_seconds=1.0,
            docling_version="PdfExtractAdapter v1.0.0",
            tables_detected=0,
            figures_detected=0,
            headers_removed=0,
            footers_removed=0,
            ocr_used=True,
            has_multi_column=False,
            markdown_size_bytes=200,
            errors=[],
            pdf_type="native",  # Input as native
        )
        result = ExtractionResult(
            document_id="doc-999",
            status=MagicMock(value="success"),
            markdown="Native doc text",
            json_data={},
            metadata=meta,
        )

        service = RagPipelineService(
            chunking_service=mock_chunker,
            embedding_service=mock_embedder,
            structured_extractor=mock_extractor,
            repository=mock_repo,
        )

        report = service.process_extraction_result(result)
        assert report.policy_id == "pol-999"

        _, kwargs = mock_repo.save_rag_policy_transactional.call_args
        stats: PolicyProcessingStats = kwargs.get("stats")
        assert stats.file_type == "DIGITAL"


class TestFileTypeNormalizer:
    """Tests for repository file_type normalizer constraint guard."""

    def test_normalize_file_type(self) -> None:
        assert _normalize_file_type("DIGITAL") == "DIGITAL"
        assert _normalize_file_type("digital") == "DIGITAL"
        assert _normalize_file_type("NATIVE") == "DIGITAL"
        assert _normalize_file_type("native") == "DIGITAL"
        assert _normalize_file_type("SCANNED") == "SCANNED"
        assert _normalize_file_type("scanned") == "SCANNED"
        assert _normalize_file_type("HYBRID") == "HYBRID"
        assert _normalize_file_type("hybrid") == "HYBRID"
        assert _normalize_file_type("UNKNOWN") == "UNKNOWN"
        assert _normalize_file_type(None) == "UNKNOWN"
        assert _normalize_file_type("INVALID_VAL") == "UNKNOWN"


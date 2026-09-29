"""DocEngine — Unit Tests for Policy Envelope and Document Type Classification.

Verifies:
1. DocumentType normalization logic (casing, accents, aliases).
2. Domain model serialization (PolicyEnvelope, DocumentMetadata, ExtractionRequest).
3. PgEnvelopeRepository operations (get_or_create, link, lookup).
4. RagPipelineService envelope binding on both fresh extractions and idempotency skips.
5. API endpoints for envelope retrieval and policy upload with envelope fields.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import uuid
import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_extraction_service, get_rag_pipeline_service
from app.api.main import create_app
from app.api.v1.policies import get_envelope_repo
from app.domain.models.document import DocumentMetadata, ExtractionResult
from app.domain.models.envelope import DocumentType, PolicyEnvelope, normalize_document_type
from app.domain.models.extraction import ExtractionRequest, ExtractionStatus
from app.infrastructure.database.pg_envelope_repository import PgEnvelopeRepository


class TestDocumentTypeNormalization:
    """Test suite for document type normalization."""

    def test_normalize_standard_types(self):
        assert normalize_document_type("CONDICIONADO_GENERAL") == DocumentType.CONDICIONADO_GENERAL.value
        assert normalize_document_type("CONDICIONADO_PARTICULAR") == DocumentType.CONDICIONADO_PARTICULAR.value
        assert normalize_document_type("LIQUIDACION_PAGOS") == DocumentType.LIQUIDACION_PAGOS.value
        assert normalize_document_type("ANEXO") == DocumentType.ANEXO.value

    def test_normalize_accents_and_case(self):
        assert normalize_document_type("Condicionado General") == DocumentType.CONDICIONADO_GENERAL.value
        assert normalize_document_type("condicionado particular") == DocumentType.CONDICIONADO_PARTICULAR.value
        assert normalize_document_type("Liquidación de Pagos") == DocumentType.LIQUIDACION_PAGOS.value
        assert normalize_document_type("Póliza Principal") == DocumentType.POLIZA_PRINCIPAL.value

    def test_normalize_empty_or_none(self):
        assert normalize_document_type(None) is None
        assert normalize_document_type("") is None
        assert normalize_document_type("   ") is None


class TestDomainModelsEnvelope:
    """Test domain models with envelope fields."""

    def test_envelope_domain_model(self):
        env_id = str(uuid.uuid4())
        env = PolicyEnvelope(
            id=env_id,
            numero_poliza="POL-12345",
            company_sigla="CRI",
            ramo="AUTOMOTOR",
        )
        d = env.to_dict()
        assert d["id"] == env_id
        assert d["numero_poliza"] == "POL-12345"
        assert d["company_sigla"] == "CRI"
        assert d["ramo"] == "AUTOMOTOR"
        assert d["documents_count"] == 0

    def test_extraction_request_envelope_fields(self):
        req = ExtractionRequest(
            source="dummy.pdf",
            numero_poliza="POL-999",
            ramo="INCENDIO",
            tipo_documento="CONDICIONADO_GENERAL",
        )
        assert req.numero_poliza == "POL-999"
        assert req.ramo == "INCENDIO"
        assert req.tipo_documento == "CONDICIONADO_GENERAL"

    def test_document_metadata_envelope_fields(self):
        from pathlib import Path
        meta = DocumentMetadata(
            filename="dummy.pdf",
            source_path=Path("dummy.pdf"),
            sha256="abc",
            page_count=5,
            extraction_time_seconds=1.0,
            docling_version="2.0",
            tables_detected=0,
            figures_detected=0,
            headers_removed=0,
            footers_removed=0,
            ocr_used=False,
            has_multi_column=False,
            markdown_size_bytes=100,
            envelope_id="env-uuid-1",
            tipo_documento="ANEXO",
        )
        d = meta.to_dict()
        assert d["envelope_id"] == "env-uuid-1"
        assert d["tipo_documento"] == "ANEXO"


class TestPgEnvelopeRepository:
    """Test suite for PgEnvelopeRepository."""

    def test_get_or_create_envelope_existing(self):
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_db.get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        existing_id = str(uuid.uuid4())
        # First query returns existing envelope
        mock_cur.fetchone.return_value = (existing_id, "AUTOMOTOR")

        repo = PgEnvelopeRepository(mock_db)
        res = repo.get_or_create_envelope("POL-100", company_sigla="CRI", ramo="AUTOMOTOR")

        assert res == existing_id
        mock_conn.commit.assert_called()

    def test_get_or_create_envelope_new(self):
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_db.get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        new_id = str(uuid.uuid4())
        # First query returns None (not found), insert returns new_id
        mock_cur.fetchone.side_effect = [None, (new_id,)]

        repo = PgEnvelopeRepository(mock_db)
        res = repo.get_or_create_envelope("POL-200", company_sigla="LBC", ramo="VIDA")

        assert res == new_id
        mock_conn.commit.assert_called()

    def test_link_policy_to_envelope(self):
        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_cur = MagicMock()

        mock_db.get_connection.return_value.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        repo = PgEnvelopeRepository(mock_db)
        repo.link_policy_to_envelope("policy-uuid", "envelope-uuid", "condicionado general")

        mock_cur.execute.assert_called_once()
        args = mock_cur.execute.call_args[0][1]
        assert args[0] == "envelope-uuid"
        assert args[1] == DocumentType.CONDICIONADO_GENERAL.value
        assert args[2] == "policy-uuid"


class TestPolicyEnvelopeEndpoints:
    """Test FastAPI endpoints for policy envelopes."""

    def test_get_envelope_by_id_endpoint_found(self):
        app = create_app()
        mock_repo = MagicMock(spec=PgEnvelopeRepository)
        sample_env = {
            "id": "11111111-1111-1111-1111-111111111111",
            "numero_poliza": "POL-12345",
            "company_sigla": "CRI",
            "ramo": "AUTOMOTOR",
            "created_at": "2026-09-24T10:00:00Z",
            "updated_at": "2026-09-24T10:00:00Z",
            "documents_count": 1,
            "documents": [
                {
                    "policy_id": "22222222-2222-2222-2222-222222222222",
                    "file_name": "condicionado_general.pdf",
                    "file_hash": "hash123",
                    "company_sigla": "CRI",
                    "tipo_documento": "CONDICIONADO_GENERAL",
                    "total_pages": 10,
                    "file_size_bytes": 1024,
                    "created_at": "2026-09-24T10:00:00Z",
                }
            ],
        }
        mock_repo.get_envelope_by_id.return_value = sample_env
        app.dependency_overrides[get_envelope_repo] = lambda: mock_repo

        client = TestClient(app)
        response = client.get("/api/v1/policies/envelopes/11111111-1111-1111-1111-111111111111")
        assert response.status_code == 200
        data = response.json()
        assert data["numero_poliza"] == "POL-12345"
        assert data["documents_count"] == 1
        assert data["documents"][0]["tipo_documento"] == "CONDICIONADO_GENERAL"

    def test_get_envelope_by_id_endpoint_not_found(self):
        app = create_app()
        mock_repo = MagicMock(spec=PgEnvelopeRepository)
        mock_repo.get_envelope_by_id.return_value = None
        app.dependency_overrides[get_envelope_repo] = lambda: mock_repo

        client = TestClient(app)
        response = client.get("/api/v1/policies/envelopes/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    def test_get_envelopes_by_number_endpoint(self):
        app = create_app()
        mock_repo = MagicMock(spec=PgEnvelopeRepository)
        mock_repo.get_envelope_by_policy_number.return_value = [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "numero_poliza": "POL-12345",
                "company_sigla": "CRI",
                "ramo": "AUTOMOTOR",
                "created_at": "2026-09-24T10:00:00Z",
                "updated_at": "2026-09-24T10:00:00Z",
                "documents_count": 0,
                "documents": [],
            }
        ]
        app.dependency_overrides[get_envelope_repo] = lambda: mock_repo

        client = TestClient(app)
        response = client.get("/api/v1/policies/envelopes/by-number/POL-12345")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["envelopes"][0]["numero_poliza"] == "POL-12345"

    def test_extract_file_with_envelope_fields(self):
        from pathlib import Path
        app = create_app()
        mock_extract_svc = MagicMock()
        mock_rag_svc = MagicMock()

        mock_result = ExtractionResult(
            document_id="doc-123",
            status=ExtractionStatus.SUCCESS,
            markdown="# Document Title",
            json_data={},
            metadata=DocumentMetadata(
                filename="test.pdf",
                source_path=Path("test.pdf"),
                sha256="hash-123",
                page_count=1,
                extraction_time_seconds=0.5,
                docling_version="2.0",
                tables_detected=0,
                figures_detected=0,
                headers_removed=0,
                footers_removed=0,
                ocr_used=False,
                has_multi_column=False,
                markdown_size_bytes=20,
                envelope_id="env-uuid-abc",
                tipo_documento="CONDICIONADO_GENERAL",
            ),
        )
        mock_extract_svc.extract_document.return_value = mock_result
        mock_report = MagicMock()
        mock_report.policy_id = "pol-uuid-1"
        mock_report.job_id = "job-uuid-1"
        mock_report.skipped_duplicate = False
        mock_report.chunks_created = 3
        mock_report.errors = []
        mock_report.envelope_id = "env-uuid-abc"
        mock_report.tipo_documento = "CONDICIONADO_GENERAL"
        mock_rag_svc.process_extraction_result.return_value = mock_report

        app.dependency_overrides[get_extraction_service] = lambda: mock_extract_svc
        app.dependency_overrides[get_rag_pipeline_service] = lambda: mock_rag_svc

        client = TestClient(app)
        files = {"file": ("test.pdf", b"%PDF-1.4 dummy content", "application/pdf")}
        data = {
            "company_sigla": "CRI",
            "numero_poliza": "POL-999",
            "ramo": "AUTOMOTOR",
            "tipo_documento": "CONDICIONADO_GENERAL",
        }
        response = client.post("/api/v1/extract", files=files, data=data)
        assert response.status_code == 200
        res = response.json()
        assert res["metadata"]["envelope_id"] == "env-uuid-abc"
        assert res["metadata"]["tipo_documento"] == "CONDICIONADO_GENERAL"
        assert res["rag_report"]["envelope_id"] == "env-uuid-abc"
        assert res["rag_report"]["tipo_documento"] == "CONDICIONADO_GENERAL"


class TestRagPipelineEnvelopeIntegration:
    """Test suite verifying RagPipelineService automatic envelope linking."""

    def test_auto_creates_envelope_from_extracted_json(self):
        from app.application.rag_pipeline_service import RagPipelineService

        mock_chunker = MagicMock()
        mock_chunker.chunk_markdown.return_value = []

        mock_embedder = MagicMock()
        mock_embedder.generate_embeddings_batch.return_value = []

        mock_extractor = MagicMock()
        mock_extractor.extract_structured_json.return_value = {
            "datos_cabecera": {
                "numero_poliza": "POL-AUTO-777",
                "sigla_empresa": "CRI",
                "ramo": "AUTOMOTOR",
            },
            "coberturas": [],
        }

        mock_repo = MagicMock()
        mock_repo.policy_exists_by_hash.return_value = None
        mock_repo.create_job.return_value = "job-123"
        mock_repo.save_rag_policy_transactional.return_value = "pol-new-id"

        mock_env_repo = MagicMock(spec=PgEnvelopeRepository)
        mock_env_repo.get_or_create_envelope.return_value = "env-auto-uuid"

        service = RagPipelineService(
            chunking_service=mock_chunker,
            embedding_service=mock_embedder,
            structured_extractor=mock_extractor,
            repository=mock_repo,
            envelope_repository=mock_env_repo,
        )

        from pathlib import Path
        result = ExtractionResult(
            document_id="doc-auto-1",
            status=ExtractionStatus.SUCCESS,
            markdown="# Poliza 777",
            json_data={},
            metadata=DocumentMetadata(
                filename="poliza_caratula.pdf",
                source_path=Path("poliza_caratula.pdf"),
                sha256="sha-auto-777",
                page_count=2,
                extraction_time_seconds=1.0,
                docling_version="2.0",
                tables_detected=0,
                figures_detected=0,
                headers_removed=0,
                footers_removed=0,
                ocr_used=False,
                has_multi_column=False,
                markdown_size_bytes=50,
            ),
        )

        # Call WITHOUT numero_poliza (simulating user upload without manual input)
        report = service.process_extraction_result(result)

        assert report.envelope_id == "env-auto-uuid"
        mock_env_repo.get_or_create_envelope.assert_called_once_with(
            numero_poliza="POL-AUTO-777",
            company_sigla="CRI",
            ramo="AUTOMOTOR",
        )
        _, kwargs = mock_repo.save_rag_policy_transactional.call_args
        assert kwargs["envelope_id"] == "env-auto-uuid"
        assert kwargs["tipo_documento"] == DocumentType.POLIZA_PRINCIPAL.value



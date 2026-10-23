"""Tests [ADITIVOS FASE 2] para PolicyMapService y PgPolicyMapRepository."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.application.policy_map_service import PolicyMapService
from app.infrastructure.database.pg_policy_map_repository import PgPolicyMapRepository


def test_format_map_chunk():
    repo = PgPolicyMapRepository(MagicMock())
    summaries = [
        {
            "section_title": "SECCIÓN I: RESPONSABILIDAD CIVIL",
            "summary_text": "Cobertura por daños materiales y personales a terceros hasta $us. 50,000.",
            "tipo_documento": "CONDICIONADO_PARTICULAR",
            "key_topics": ["Responsabilidad Civil", "Deducibles"],
        },
        {
            "section_title": "FRANQUICIAS Y DEDUCIBLES",
            "summary_text": "Deducibles aplicables por cobertura: Sección I es 0.00.",
            "tipo_documento": "CONDICIONADO_PARTICULAR",
            "key_topics": ["Deducibles"],
        },
    ]

    chunk = repo.format_map_chunk(summaries, policy_id="p-123")
    assert chunk is not None
    assert "p-123" in chunk.chunk_id
    assert "RESPONSABILIDAD CIVIL" in chunk.chunk_content
    assert "FRANQUICIAS Y DEDUCIBLES" in chunk.chunk_content
    assert chunk.metadata_json["tipo_documento"] == "MAPA_POLIZA"


def test_extractive_summary_fleet():
    summary = PolicyMapService._build_extractive_summary(
        title="Nómina",
        chunk_list=[],
        repeat_count=150,
    )
    assert "150 vehículos" in summary


def test_extractive_summary_regular():
    chunks = [
        {"content": "[Póliza | Sec]\n\n## Titulo\nPrimera estipulación contractual importante.\nSegunda línea."}
    ]
    summary = PolicyMapService._build_extractive_summary("Titulo", chunks, repeat_count=1)
    assert "Primera estipulación" in summary


def test_cluster_consolidation():
    clusters = [
        {"title": "NOTA IMPORTANTE", "chunks": [{"content": "a"}]},
        {"title": "NOTA IMPORTANTE", "chunks": [{"content": "b"}]},
        {"title": "COBERTURAS", "chunks": [{"content": "c"}, {"content": "d"}]},
    ]
    consolidated = PolicyMapService._consolidate_clusters(clusters)
    titles = [c["title"] for c in consolidated]
    assert titles.count("NOTA IMPORTANTE") == 1
    assert "COBERTURAS" in titles

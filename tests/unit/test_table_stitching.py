"""Unit tests for Table Stitching, Table-Aware Chunking metadata, and Flexible TSQuery."""

from unittest.mock import MagicMock
from app.application.chunking_service import ChunkingService
from app.config.settings import EmbeddingConfig
from app.domain.models.query_models import RetrievedChunk
from app.infrastructure.database.pg_hybrid_search import (
    PgHybridSearchRepository,
    _build_flexible_tsquery,
    _is_table_content,
    _extract_table_signature,
)


def test_table_chunking_assigns_group_metadata() -> None:
    """Verifies that split tables receive table_group_id, table_part, and table_total_parts."""
    config = EmbeddingConfig(chunk_size_chars=350, table_chunk_size_chars=350)
    service = ChunkingService(config)

    header = "| Nº | Nombre Completo | CI | Monto |"
    delim = "| --- | --- | --- | --- |"
    rows = [
        f"| {i} | Asegurado de Prueba Numero {i} | {1000000 + i} | 50,000 |"
        for i in range(1, 20)
    ]
    markdown = f"# Nómina de Asegurados\n\nPóliza CAC-SCE0651635\n\n" + "\n".join([header, delim] + rows)

    chunks = service.chunk_markdown(markdown, file_name="poliza.pdf")
    table_chunks = [c for c in chunks if c.metadata_json.get("is_table") is True]

    assert len(table_chunks) >= 2
    first_group_id = table_chunks[0].metadata_json.get("table_group_id")
    assert first_group_id is not None
    assert table_chunks[0].metadata_json.get("table_part") == 1
    assert table_chunks[0].metadata_json.get("table_total_parts") == len(table_chunks)
    assert table_chunks[0].metadata_json.get("is_nomina") is True

    # All sub-chunks of the same table must share table_group_id
    for part_idx, tc in enumerate(table_chunks, start=1):
        assert tc.metadata_json.get("table_group_id") == first_group_id
        assert tc.metadata_json.get("table_part") == part_idx
        assert tc.metadata_json.get("table_total_parts") == len(table_chunks)


def test_build_flexible_tsquery_filters_stopwords() -> None:
    """Verifies conversational words and policy codes are cleaned into a targeted tsquery."""
    q = "Dame la nómina de asegurados de la póliza número SCE0651635"
    flex = _build_flexible_tsquery(q)
    # Must prioritize conjunction without conversational noise
    assert "dame" not in flex.lower()
    assert "número" not in flex.lower()
    assert "sce0651635" not in flex.lower()
    assert "nómina" in flex.lower()
    assert "asegurados" in flex.lower()


def test_is_table_content_and_signature() -> None:
    """Verifies table detection and header extraction."""
    table_text = (
        "| NOMINA | DOC | MONTO |\n"
        "|---|---|---|\n"
        "| JUAN | 123 | 500 |\n"
        "| PEDRO | 456 | 600 |"
    )
    assert _is_table_content(table_text) is True
    assert _extract_table_signature(table_text) == "| NOMINA | DOC | MONTO |"

    plain_text = "Esta es una cláusula común y corriente sin tablas."
    assert _is_table_content(plain_text) is False
    assert _extract_table_signature(plain_text) is None


def test_expand_table_chunks_with_table_group_id() -> None:
    """Verifies that expand_table_chunks retrieves all sibling parts using table_group_id."""
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_cur = MagicMock()

    mock_db.get_connection.return_value.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    # Simulate DB returning part 1 and part 2
    mock_cur.fetchall.return_value = [
        (1, "uuid-1", "| TABLA | ... Parte 1", "pol-1", 10, {"table_group_id": "grp-1", "table_part": 1, "is_table": True}, "parent"),
        (2, "uuid-2", "| TABLA | ... Parte 2", "pol-1", 11, {"table_group_id": "grp-1", "table_part": 2, "is_table": True}, "parent"),
    ]

    repo = PgHybridSearchRepository(mock_db)

    # User only retrieved part 2
    input_chunk = RetrievedChunk(
        chunk_id="uuid-2",
        policy_id="pol-1",
        chunk_index=11,
        chunk_content="| TABLA | ... Parte 2",
        metadata_json={"table_group_id": "grp-1", "table_part": 2, "is_table": True},
        similarity_score=0.9,
    )

    expanded = repo.expand_table_chunks([input_chunk])
    assert len(expanded) == 2
    assert expanded[0].chunk_id == "uuid-1"
    assert expanded[0].chunk_index == 10
    assert expanded[1].chunk_id == "uuid-2"
    assert expanded[1].chunk_index == 11

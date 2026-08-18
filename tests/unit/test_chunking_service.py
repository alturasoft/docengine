"""Unit tests for ChunkingService."""

from app.application.chunking_service import ChunkingService
from app.config.settings import EmbeddingConfig


def test_chunk_markdown_headers() -> None:
    config = EmbeddingConfig(chunk_size_chars=500, chunk_overlap_chars=50)
    service = ChunkingService(config)

    markdown = """# Póliza de Seguro de Salud
Este es el inicio de la póliza.

## Cobertura Principal
Cubre gastos médicos mayores y hospitalización hasta 100,000 USD.

### Exclusiones
No cubre enfermedades preexistentes no declaradas.
"""

    chunks = service.chunk_markdown(markdown, file_name="salud.pdf")

    assert len(chunks) >= 2
    assert chunks[0].chunk_index == 0
    assert "source_file" in chunks[0].metadata_json
    assert chunks[0].metadata_json["source_file"] == "salud.pdf"
    assert "salud" in chunks[0].chunk_content


def test_chunk_markdown_empty() -> None:
    config = EmbeddingConfig()
    service = ChunkingService(config)

    chunks = service.chunk_markdown("", file_name="empty.pdf")
    assert chunks == []


def test_table_isolation_from_text() -> None:
    """Verifies that plain text before and after a table is isolated from table chunks."""
    config = EmbeddingConfig(chunk_size_chars=1800, chunk_overlap_chars=200)
    service = ChunkingService(config)

    markdown = """# Sección 1
Texto introductorio de la cláusula.

| Cobertura | Límite | Deducible |
| --- | --- | --- |
| Hospitalización | 50,000 USD | 10% |
| Ambulatorio | 10,000 USD | 20% |

Texto posterior que no debe mezclarse con la tabla.
"""

    chunks = service.chunk_markdown(markdown, file_name="poliza.pdf")

    # We expect 3 distinct chunks:
    # 1. Heading + Text before table
    # 2. Table alone
    # 3. Text after table
    assert len(chunks) == 3

    # Check indices are consecutive
    assert [c.chunk_index for c in chunks] == [0, 1, 2]

    # Chunk 0: Pre-text
    assert "Texto introductorio" in chunks[0].chunk_content

    # Chunk 1: Table with contextual prefix
    assert "| Cobertura | Límite | Deducible |" in chunks[1].chunk_content
    assert "Texto introductorio" not in chunks[1].chunk_content
    assert "Texto posterior" not in chunks[1].chunk_content
    assert "| Hospitalización | 50,000 USD | 10% |" in chunks[1].chunk_content

    # Chunk 2: Post-text with contextual prefix
    assert "Texto posterior" in chunks[2].chunk_content
    assert "| Cobertura |" not in chunks[2].chunk_content

    # Check metadata propagation
    for c in chunks:
        assert c.metadata_json.get("Header 1") == "Sección 1"
        assert c.metadata_json.get("source_file") == "poliza.pdf"


def test_long_table_splitting_preserves_headers() -> None:
    """Verifies that when a table exceeds chunk_size_chars, every sub-chunk repeats the headers and prefix."""
    config = EmbeddingConfig(chunk_size_chars=350, chunk_overlap_chars=20)
    service = ChunkingService(config)

    header = "| ID | Nombre Asegurado | Parentesco | Plan Contratado |"
    delim = "| --- | --- | --- | --- |"
    rows = [
        f"| {i:03d} | Asegurado Numero {i:03d} | Titular | Plan Oro Full Cobertura |"
        for i in range(1, 15)
    ]
    table_content = "\n".join([header, delim] + rows)
    markdown = f"## Nómina de Asegurados\n\nPóliza Nro. CAC-SCE0651635\n\n{table_content}"

    chunks = service.chunk_markdown(markdown, file_name="Condicionados_Particular.pdf")

    assert len(chunks) > 1

    # Policy number detected in chunks
    assert "CAC-SCE0651635" in chunks[0].chunk_content

    # All subsequent chunks are table sub-chunks
    table_chunks = chunks[1:]
    assert len(table_chunks) >= 2

    for c in table_chunks:
        assert "CAC-SCE0651635" in c.chunk_content
        assert header in c.chunk_content
        assert delim in c.chunk_content
        assert c.metadata_json.get("Header 2") == "Nómina de Asegurados"

    # Verify no row was lost
    all_content = "\n".join(c.chunk_content for c in table_chunks)
    for i in range(1, 15):
        assert f"Asegurado Numero {i:03d}" in all_content


def test_multiple_consecutive_tables() -> None:
    """Verifies that multiple tables in sequence are cleanly separated."""
    config = EmbeddingConfig(chunk_size_chars=1800, chunk_overlap_chars=200)
    service = ChunkingService(config)

    markdown = """# Tablas Consecutivas

| Tabla1 Col1 | Tabla1 Col2 |
| --- | --- |
| Dato 1 | Dato 2 |

| Tabla2 ColA | Tabla2 ColB |
| :--- | :--- |
| Val A | Val B |
"""

    chunks = service.chunk_markdown(markdown)
    # chunk 0: '# Tablas Consecutivas'
    # chunk 1: Table 1
    # chunk 2: Table 2
    assert len(chunks) == 3
    assert "# Tablas Consecutivas" in chunks[0].chunk_content
    assert "Tabla1 Col1" in chunks[1].chunk_content
    assert "Tabla2 ColA" not in chunks[1].chunk_content
    assert "Tabla2 ColA" in chunks[2].chunk_content
    assert "Tabla1 Col1" not in chunks[2].chunk_content


def test_table_with_no_data_rows() -> None:
    """Verifies edge case where table has only header and delimiter."""
    config = EmbeddingConfig(chunk_size_chars=1800, chunk_overlap_chars=200)
    service = ChunkingService(config)

    markdown = """# Tabla Vacía
| Col1 | Col2 |
| --- | --- |
"""
    chunks = service.chunk_markdown(markdown)
    assert len(chunks) == 2
    assert "# Tabla Vacía" in chunks[0].chunk_content
    assert "| Col1 | Col2 |\n| --- | --- |" in chunks[1].chunk_content

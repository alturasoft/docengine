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


def test_chunk_markdown_empty() -> None:
    config = EmbeddingConfig()
    service = ChunkingService(config)

    chunks = service.chunk_markdown("", file_name="empty.pdf")
    assert chunks == []

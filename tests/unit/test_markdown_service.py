"""Unit tests for MarkdownService."""

from __future__ import annotations

import pytest

from app.application.markdown_service import MarkdownService
from app.config.settings import AppSettings


@pytest.fixture
def service(app_settings: AppSettings) -> MarkdownService:
    """Return a MarkdownService configured for testing."""
    return MarkdownService(config=app_settings)


class TestPostProcess:
    """Tests for MarkdownService.post_process()."""

    def test_empty_markdown_returns_empty(self, service: MarkdownService) -> None:
        result = service.post_process("")
        assert result.markdown == ""
        assert result.headers_removed == 0
        assert result.footers_removed == 0

    def test_preserves_headings(self, service: MarkdownService) -> None:
        md = "# Título Principal\n\n## Sección 1\n\nTexto.\n"
        result = service.post_process(md)
        assert "# Título Principal" in result.markdown
        assert "## Sección 1" in result.markdown

    def test_preserves_table_structure(self, service: MarkdownService) -> None:
        md = "| Col1 | Col2 |\n|------|------|\n| A    | B    |\n"
        result = service.post_process(md)
        assert "| Col1 | Col2 |" in result.markdown
        assert "| --- | --- |" in result.markdown

    def test_normalises_excessive_blank_lines(self, service: MarkdownService) -> None:
        """Four consecutive blank lines should be collapsed."""
        md = "# Título\n\n\n\n\n\nContenido."
        result = service.post_process(md)
        assert "\n\n\n\n" not in result.markdown

    def test_result_ends_with_newline(self, service: MarkdownService) -> None:
        md = "# Título\n\nContenido."
        result = service.post_process(md)
        assert result.markdown.endswith("\n")

    def test_normalises_crlf_line_endings(self, service: MarkdownService) -> None:
        """CRLF line endings should be normalised to LF."""
        md = "# Título\r\n\r\nContenido en Windows.\r\n"
        result = service.post_process(md)
        assert "\r" not in result.markdown
        assert "# Título\n\nContenido en Windows.\n" in result.markdown


class TestDetectRepeatedElements:
    """Tests for MarkdownService._detect_repeated_elements()."""

    def test_detects_page_number_repeated_in_many_pages(
        self, service: MarkdownService
    ) -> None:
        """A page number appearing in 8/10 pages (80%) should be detected."""
        page_texts = [f"Página {i} de 10\n# Sección {i}\n\nContenido." for i in range(1, 11)]
        # Replace pages 1-8 with same header
        page_texts = ["Grupo Seguros SA\n# Condiciones\n\nTexto."] * 8 + [
            "# Anexo\nTexto único 1.",
            "# Certificado\nTexto único 2.",
        ]
        repeated = service._detect_repeated_elements(page_texts)
        assert "Grupo Seguros SA" in repeated

    def test_no_false_positives_with_few_pages(
        self, service: MarkdownService
    ) -> None:
        """With only 2 pages, no elements should be flagged as repeated."""
        page_texts = ["# Página 1\nContenido.", "# Página 2\nMás contenido."]
        repeated = service._detect_repeated_elements(page_texts)
        assert repeated == []

    def test_unique_content_not_flagged(self, service: MarkdownService) -> None:
        """Unique content on each page should not be flagged."""
        page_texts = [f"# Capítulo {i}\n\nContenido único {i}." for i in range(10)]
        repeated = service._detect_repeated_elements(page_texts)
        # No single line should appear in 7+ pages since each is unique
        assert not any("Capítulo 1" in r for r in repeated)


class TestRemovePageNumbers:
    """Tests for MarkdownService._remove_page_numbers()."""

    def test_removes_page_number_spanish(self, service: MarkdownService) -> None:
        md = "# Título\n\nPágina 1 de 10\n\nContenido."
        result = service._remove_page_numbers(md)
        assert "Página 1 de 10" not in result
        assert "# Título" in result
        assert "Contenido." in result

    def test_removes_page_english(self, service: MarkdownService) -> None:
        md = "# Title\n\nPage 5 of 20\n\nContent."
        result = service._remove_page_numbers(md)
        assert "Page 5 of 20" not in result

    def test_preserves_content_with_numbers(self, service: MarkdownService) -> None:
        """Content containing numbers should not be removed."""
        md = "La suma es 1000 de los 5000 asegurados en la póliza."
        result = service._remove_page_numbers(md)
        assert "La suma es 1000 de los 5000 asegurados" in result

"""DocEngine — Post-Processor: Repeated Elements & Page Numbers.

Detects and removes repeated page headers, footers, and standalone page number markers.
"""

from __future__ import annotations

import re
from collections import Counter

from app.application.post_processing.base import (
    BasePostProcessor,
    PostProcessingContext,
)

_PAGE_PATTERN = re.compile(
    r"^(página|page|pág\.?|p\.?)\s*\d+\s*(de|of|\/)\s*\d+$",
    re.IGNORECASE | re.MULTILINE,
)


class RepeatedElementsProcessor(BasePostProcessor):
    """Removes repetitive headers, footers, and page number markers across pages."""

    def __init__(self, repetition_threshold: float = 0.7) -> None:
        self._threshold = repetition_threshold

    @property
    def name(self) -> str:
        return "repeated_elements"

    def process(self, markdown: str, context: PostProcessingContext) -> str:
        """Remove page headers/footers and page number markers."""
        if not markdown.strip():
            return markdown

        processed = markdown

        # Remove repeated header/footer lines if page_texts is provided or detectable
        page_texts = context.page_texts or self._split_by_pages(markdown)
        if len(page_texts) >= 3:
            repeated = self._detect_repeated_elements(page_texts)
            if repeated:
                processed, removed_count = self._remove_repeated_elements(
                    processed, repeated
                )
                context.metadata["repeated_headers_removed"] = removed_count

        # Remove standalone page number lines
        processed = self._remove_page_numbers(processed)
        return processed

    def _detect_repeated_elements(self, page_texts: list[str]) -> list[str]:
        """Detect text lines that appear in most pages."""
        total_pages = len(page_texts)
        min_occurrences = max(2, int(total_pages * self._threshold))
        candidate_counter: Counter[str] = Counter()

        for page_text in page_texts:
            lines = page_text.strip().splitlines()
            if not lines:
                continue
            candidates = set(lines[:3] + lines[-3:])
            for line in candidates:
                stripped = line.strip()
                if stripped and len(stripped) > 3:
                    candidate_counter[stripped] += 1

        return [
            text
            for text, count in candidate_counter.items()
            if count >= min_occurrences
        ]

    def _remove_repeated_elements(
        self, markdown: str, repeated_elements: list[str]
    ) -> tuple[str, int]:
        """Remove lines in repeated_elements from Markdown."""
        total_removed = 0
        lines = markdown.splitlines(keepends=True)
        result_lines = []

        for line in lines:
            if line.strip() in repeated_elements:
                total_removed += 1
                continue
            result_lines.append(line)

        return "".join(result_lines), total_removed

    def _remove_page_numbers(self, markdown: str) -> str:
        """Remove standalone page number lines."""
        lines = markdown.splitlines(keepends=True)
        return "".join(
            line
            for line in lines
            if not _PAGE_PATTERN.match(line.strip())
        )

    def _split_by_pages(self, markdown: str) -> list[str]:
        """Split Markdown into per-page chunks."""
        pages = re.split(r"\n---\n|\n\*\*\*\n|<!-- page break -->", markdown)
        if len(pages) > 1:
            return pages
        chunk_size = 3000
        return [
            markdown[i : i + chunk_size]
            for i in range(0, len(markdown), chunk_size)
        ] or [markdown]

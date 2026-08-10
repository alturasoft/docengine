"""DocEngine — Application Service: MarkdownService.

Responsible for post-processing the raw Markdown produced by Docling
to improve quality, remove repetitive elements, and normalise structure.

This service operates purely on text — it has no knowledge of Docling
or any other infrastructure component.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.application.post_processing import (
    PostProcessingContext,
    PostProcessingPipeline,
    create_default_pipeline,
)
from app.config.settings import AppSettings, MarkdownConfig
from app.infrastructure.logging.logger import get_logger

if TYPE_CHECKING:
    from app.application.company_skill_loader import CompanySkill

logger = get_logger(__name__)



@dataclass
class MarkdownPostProcessResult:
    """Result of Markdown post-processing.

    Attributes:
        markdown: The post-processed Markdown text.
        headers_removed: Count of repeated headers removed.
        footers_removed: Count of repeated footers removed.
        repeated_elements: List of detected repeated text patterns.
    """

    markdown: str
    headers_removed: int
    footers_removed: int
    repeated_elements: list[str]


class MarkdownService:
    """Post-processes Docling-generated Markdown for maximum RAG quality.

    Responsibilities:
    - Detect and remove repetitive headers/footers (page numbers, etc.)
    - Normalise whitespace and blank lines
    - Validate heading hierarchy
    - Ensure table Markdown formatting is correct

    Args:
        config: Application settings with MarkdownConfig section.
    """

    # Pattern matching common insurance document page markers
    _PAGE_PATTERN = re.compile(
        r"^(página|page|pág\.?|p\.?)\s*\d+\s*(de|of|\/)\s*\d+$",
        re.IGNORECASE | re.MULTILINE,
    )
    # Heading pattern for hierarchy validation
    _HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
    # Table row pattern
    _TABLE_ROW_PATTERN = re.compile(r"^\|.+\|$", re.MULTILINE)
    # Excessive blank lines
    _EXCESS_BLANK_LINES = re.compile(r"\n{4,}")

    def __init__(
        self,
        config: AppSettings,
        pipeline: PostProcessingPipeline | None = None,
    ) -> None:
        self._config: MarkdownConfig = config.markdown
        self._threshold = config.markdown.repetition_threshold
        self._pipeline = pipeline or create_default_pipeline(
            repetition_threshold=self._threshold
        )

    @property
    def pipeline(self) -> PostProcessingPipeline:
        """Return the post-processing pipeline for adding custom rules."""
        return self._pipeline

    def post_process(
        self,
        raw_markdown: str,
        page_texts: list[str] | None = None,
        company_skill: "CompanySkill | None" = None,
    ) -> MarkdownPostProcessResult:
        """Apply all post-processing rules to raw Markdown via the pipeline.

        When a ``company_skill`` is provided, a ``CompanyKVRulesProcessor``
        is appended to a *copy* of the pipeline so the shared default pipeline
        is never mutated.

        Args:
            raw_markdown: Markdown as produced directly by Docling.
            page_texts: Optional list of per-page text content.
            company_skill: Optional company-specific rule set.
                If provided, company KV and header rules are applied after
                the generic pipeline processors.

        Returns:
            MarkdownPostProcessResult with processed text and statistics.
        """
        if not raw_markdown:
            return MarkdownPostProcessResult(
                markdown="",
                headers_removed=0,
                footers_removed=0,
                repeated_elements=[],
            )

        context = PostProcessingContext(page_texts=page_texts or [])

        # Build effective pipeline: generic + optional company rules
        pipeline = self._pipeline
        if company_skill is not None and not company_skill.is_empty:
            from app.application.post_processing.processors.company_kv_rules import (  # noqa: PLC0415
                CompanyKVRulesProcessor,
            )
            company_processor = CompanyKVRulesProcessor(company_skill)
            # Clone pipeline and append company processor without mutating the shared one
            pipeline = PostProcessingPipeline(
                processors=list(self._pipeline._processors) + [company_processor]
            )
            logger.debug(
                "Company skill injected into pipeline",
                sigla=company_skill.sigla,
                processor=company_processor.name,
            )

        processed, context = pipeline.run(raw_markdown, context)

        # Normalise whitespace
        if self._config.normalize_whitespace:
            processed = self._normalize_whitespace(processed)

        # Ensure document ends with single newline
        processed = processed.rstrip() + "\n"

        headers_removed = context.metadata.get("repeated_headers_removed", 0) // 2
        footers_removed = context.metadata.get("repeated_headers_removed", 0) - headers_removed

        logger.debug(
            "Markdown post-processing complete",
            original_size=len(raw_markdown),
            processed_size=len(processed),
            transformations_applied=context.transformations_applied,
            errors=len(context.errors),
        )

        return MarkdownPostProcessResult(
            markdown=processed,
            headers_removed=headers_removed,
            footers_removed=footers_removed,
            repeated_elements=context.metadata.get("repeated_elements", []),
        )

    def _detect_repeated_elements(self, page_texts: list[str]) -> list[str]:
        """Detect text lines that appear in most pages (likely headers/footers).

        A line is considered repetitive if it appears in at least
        `repetition_threshold` fraction of pages.

        Args:
            page_texts: List of text content per page.

        Returns:
            List of text strings identified as repetitive.

        Example:
            If threshold=0.7 and a document has 10 pages,
            any line appearing in 7+ pages is considered repetitive.
        """
        if len(page_texts) < 3:
            # Not enough pages for reliable repetition detection
            return []

        total_pages = len(page_texts)
        min_occurrences = max(2, int(total_pages * self._threshold))

        # Extract candidate lines from first and last portion of each page
        candidate_counter: Counter[str] = Counter()

        for page_text in page_texts:
            lines = page_text.strip().splitlines()
            if not lines:
                continue

            # Check first 3 and last 3 lines of each page (header/footer zones)
            candidates = set(lines[:3] + lines[-3:])
            for line in candidates:
                stripped = line.strip()
                if stripped and len(stripped) > 3:  # Ignore very short lines
                    candidate_counter[stripped] += 1

        repeated = [
            text
            for text, count in candidate_counter.items()
            if count >= min_occurrences
        ]

        if repeated:
            logger.debug(
                "Detected repeated elements",
                count=len(repeated),
                threshold=self._threshold,
                min_occurrences=min_occurrences,
                total_pages=total_pages,
            )

        return repeated

    def _remove_repeated_elements(
        self, markdown: str, repeated_elements: list[str]
    ) -> tuple[str, int]:
        """Remove detected repeated elements from Markdown text.

        Only removes elements that appear as standalone lines to avoid
        accidentally removing text embedded within content paragraphs.

        Args:
            markdown: Full Markdown text.
            repeated_elements: List of text strings to remove.

        Returns:
            Tuple of (processed_markdown, total_lines_removed).
        """
        total_removed = 0
        lines = markdown.splitlines(keepends=True)
        result_lines = []

        for line in lines:
            stripped = line.strip()
            if stripped in repeated_elements:
                total_removed += 1
                continue  # Drop this line
            result_lines.append(line)

        return "".join(result_lines), total_removed

    def _remove_page_numbers(self, markdown: str) -> str:
        """Remove standalone page number lines using regex pattern.

        Matches patterns like: 'Página 1 de 10', 'Page 2 of 15', 'Pág. 3'

        Args:
            markdown: Markdown text to process.

        Returns:
            Markdown with page number lines removed.
        """
        lines = markdown.splitlines(keepends=True)
        return "".join(
            line
            for line in lines
            if not self._PAGE_PATTERN.match(line.strip())
        )

    def _normalize_whitespace(self, markdown: str) -> str:
        """Collapse excessive blank lines to at most max_consecutive_blank_lines.

        Args:
            markdown: Markdown text to normalise.

        Returns:
            Markdown with normalised whitespace.
        """
        max_blank = self._config.max_consecutive_blank_lines
        replacement = "\n" * (max_blank + 1)
        return self._EXCESS_BLANK_LINES.sub(replacement, markdown)

    def _split_by_pages(self, markdown: str) -> list[str]:
        """Attempt to split Markdown into per-page sections.

        Splits on common page break markers. Falls back to splitting
        by large text chunks if no explicit markers are found.

        Args:
            markdown: Full Markdown text.

        Returns:
            List of per-page text strings (at least one element).
        """
        # Docling may include page break markers
        pages = re.split(r"\n---\n|\n\*\*\*\n|<!-- page break -->", markdown)
        if len(pages) > 1:
            return pages

        # No explicit markers — split by approximately 3000 chars
        chunk_size = 3000
        return [
            markdown[i: i + chunk_size]
            for i in range(0, len(markdown), chunk_size)
        ] or [markdown]

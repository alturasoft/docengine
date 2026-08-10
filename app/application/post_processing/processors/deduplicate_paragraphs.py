"""DocEngine — Post-Processor: Deduplicate Overlapping Paragraphs.

Detects and removes duplicated or overlapping ghost paragraphs produced
by multi-stream insurance PDF renders.
"""

from __future__ import annotations

import re

from app.application.post_processing.base import (
    BasePostProcessor,
    PostProcessingContext,
)


def _normalize_text(text: str) -> str:
    """Strip whitespace and non-alphanumeric chars to compare text content."""
    return re.sub(r"[^\w]", "", text).lower()


class DeduplicateOverlappingParagraphsProcessor(BasePostProcessor):
    """Detects and removes duplicated or overlapping ghost text streams.

    Insurance PDF generators often embed multiple overlapping font/stream layers.
    This rule identifies lines whose canonical text content is a substring of or
    subsumed by a longer, clean surrounding paragraph, preserving only the
    complete clean version.
    """

    @property
    def name(self) -> str:
        return "deduplicate_overlapping_paragraphs"

    def process(self, markdown: str, context: PostProcessingContext) -> str:
        """Filter out subsumed/overlapping ghost lines from the Markdown."""
        if not markdown.strip():
            return markdown

        lines = markdown.splitlines(keepends=True)
        if len(lines) < 2:
            return markdown

        norm_lines = [_normalize_text(l) for l in lines]
        result_lines: list[str] = []
        dropped_count = 0

        for i, line in enumerate(lines):
            norm_i = norm_lines[i]

            # Ignore structural elements (headers, tables, lists, code) or short lines
            if (
                not norm_i
                or len(norm_i) < 15
                or line.strip().startswith(("#", "|", "```", "<!--", "*", "-", ">"))
            ):
                result_lines.append(line)
                continue

            # Check multi-line paragraph block subsumption in window around i
            is_subsumed = False
            window_start = max(0, i - 10)
            window_end = min(len(lines), i + 12)

            # Single line comparison
            for j in range(window_start, window_end):
                if j == i:
                    continue
                norm_j = norm_lines[j]
                if not norm_j or len(norm_j) <= len(norm_i):
                    continue

                if norm_i in norm_j and len(norm_j) >= len(norm_i) * 1.15:
                    is_subsumed = True
                    break

            if not is_subsumed:
                # Multi-line block comparison
                context_block_norm = "".join(
                    norm_lines[j] for j in range(window_start, window_end) if j != i
                )
                if norm_i in context_block_norm and len(context_block_norm) >= len(norm_i) * 1.15:
                    is_subsumed = True
                else:
                    # Detect unspaced/garbled character run (e.g. "EnVirtuddelasolicitud...")
                    words = line.strip().split()
                    has_long_unspaced_run = any(len(w) > 22 for w in words)
                    if has_long_unspaced_run and norm_i in context_block_norm:
                        is_subsumed = True

            if not is_subsumed:
                result_lines.append(line)
            else:
                dropped_count += 1

        if dropped_count > 0:
            context.metadata["deduplicated_paragraphs_count"] = (
                context.metadata.get("deduplicated_paragraphs_count", 0)
                + dropped_count
            )

        return "".join(result_lines)

"""DocEngine — Post-Processor: Spaced Text Fixer.

Detects and collapses letter-spaced text produced by non-standard PDF font maps.
"""

from __future__ import annotations

import re

from app.application.post_processing.base import (
    BasePostProcessor,
    PostProcessingContext,
)


def _collapse_spaced_line(line: str, threshold: float = 0.4) -> str:
    """Collapse letter-spaced line into natural words while preserving leading whitespace."""
    leading = line[: len(line) - len(line.lstrip())]
    stripped = line.strip()
    if not stripped:
        return line

    _SPACED_RUN = re.compile(r"(?:\S ){3,}")
    if not _SPACED_RUN.search(stripped):
        return line

    tokens = stripped.split(" ")
    if not tokens:
        return line

    single_char_ratio = sum(1 for t in tokens if len(t) == 1) / len(tokens)
    if single_char_ratio < threshold:
        return line

    # If double spaces exist between words (PDF letter spacing standard)
    if "  " in stripped:
        word_chunks = stripped.split("  ")
        fixed_words: list[str] = []
        for chunk in word_chunks:
            chunk_tokens = chunk.strip().split(" ")
            if chunk_tokens and (
                sum(1 for t in chunk_tokens if len(t) == 1) / len(chunk_tokens)
                >= 0.5
            ):
                fixed_words.append("".join(chunk_tokens))
            else:
                fixed_words.append(chunk.strip())
        return leading + " ".join(w for w in fixed_words if w)

    # Fallback: join single alpha characters
    result: list[str] = []
    char_buffer: list[str] = []

    def _flush() -> None:
        if char_buffer:
            result.append("".join(char_buffer))
            char_buffer.clear()

    for token in tokens:
        if len(token) == 1 and token.isalpha():
            char_buffer.append(token)
        else:
            _flush()
            result.append(token)

    _flush()
    return leading + " ".join(result)


class SpacedTextFixerProcessor(BasePostProcessor):
    """Collapses letter-spaced text produced by non-standard font maps.

    PDF font glyph maps in Latin-American insurance documents often render
    characters with spaces between them (e.g. "E n  V i r t u d").
    This rule detects such lines and rejoins letters into natural words.
    """

    @property
    def name(self) -> str:
        return "spaced_text_fixer"

    def process(self, markdown: str, context: PostProcessingContext) -> str:
        """Collapse letter-spaced lines in Markdown."""
        if not markdown.strip():
            return markdown

        lines = markdown.splitlines()
        fixed_lines: list[str] = []
        collapsed_count = 0

        for line in lines:
            fixed = _collapse_spaced_line(line)
            if fixed != line:
                collapsed_count += 1
            fixed_lines.append(fixed)

        if collapsed_count > 0:
            context.metadata["spaced_lines_collapsed_count"] = (
                context.metadata.get("spaced_lines_collapsed_count", 0)
                + collapsed_count
            )

        return "\n".join(fixed_lines)

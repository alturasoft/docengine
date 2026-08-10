"""DocEngine — Domain Models: Extraction.

Defines request/response value objects and status enumerations
for the extraction pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ExtractionStatus(str, Enum):
    """Final status of a document extraction operation.

    Values:
        SUCCESS: Document extracted completely without errors.
        PARTIAL: Document extracted with recoverable warnings.
            Content may be incomplete but is usable.
        FAILED: Extraction failed. No usable content was produced.
    """

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class OutputFormat(str, Enum):
    """Supported output formats for extraction results.

    Values:
        MARKDOWN: Markdown text representation (.md).
        JSON: Full structured JSON from Docling (.json).
        ALL: Generate all available formats.
    """

    MARKDOWN = "md"
    JSON = "json"
    ALL = "all"


@dataclass
class ExtractionRequest:
    """Encapsulates the input for a single document extraction operation.

    Attributes:
        source: Source document. Can be a local Path or a URL string.
        output_formats: List of output formats to generate.
            Defaults to all formats.
        config_override: Optional per-request configuration overrides.
            Keys must match AppSettings field names.
        request_id: Optional correlation ID for tracing (e.g., from API).
    """

    source: Path | str
    output_formats: list[str] = field(
        default_factory=lambda: [OutputFormat.ALL.value]
    )
    config_override: dict | None = None
    request_id: str | None = None
    company_sigla: str | None = None

    @property
    def is_url(self) -> bool:
        """Return True if the source is a URL."""
        source_str = str(self.source)
        return source_str.startswith(("http://", "https://"))

    @property
    def is_folder(self) -> bool:
        """Return True if the source is a directory."""
        if self.is_url:
            return False
        return Path(self.source).is_dir()

    @property
    def is_file(self) -> bool:
        """Return True if the source is a regular file."""
        if self.is_url:
            return False
        return Path(self.source).is_file()

    def resolve_source_path(self) -> Path:
        """Return source as an absolute resolved Path.

        Returns:
            Resolved absolute path.

        Raises:
            ValueError: If source is a URL, not a path.
        """
        if self.is_url:
            raise ValueError(f"Source is a URL, not a file path: {self.source}")
        return Path(self.source).resolve()

    def effective_formats(self) -> list[str]:
        """Return the list of concrete formats to generate.

        Expands 'all' into individual format names.

        Returns:
            List of format strings without 'all'.
        """
        formats = set(self.output_formats)
        if OutputFormat.ALL.value in formats:
            formats.discard(OutputFormat.ALL.value)
            formats.update([OutputFormat.MARKDOWN.value, OutputFormat.JSON.value])
        return sorted(formats)


@dataclass
class BatchExtractionRequest:
    """Encapsulates a batch extraction operation over multiple sources.

    Attributes:
        requests: List of individual extraction requests.
        continue_on_error: If True, failures do not abort remaining items.
        max_concurrent: Maximum number of documents to process in parallel.
    """

    requests: list[ExtractionRequest]
    continue_on_error: bool = True
    max_concurrent: int = 4

    def __len__(self) -> int:
        return len(self.requests)

    def __iter__(self):  # type: ignore[override]
        return iter(self.requests)

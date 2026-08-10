"""DocEngine — Domain Interface: IDocumentExtractor.

Defines the contract that every document extractor must fulfil.
Only this interface is visible to the Application layer.
Docling (and any future extractor) lives behind this abstraction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models.document import ExtractionResult
from app.domain.models.extraction import ExtractionRequest


class IDocumentExtractor(ABC):
    """Abstract base class for all document extraction adapters.

    The Application layer only interacts with this interface.
    The Infrastructure layer provides the concrete implementation
    (DoclingAdapter). Any future extractor (e.g. LlamaParse, Azure DI)
    must implement this interface to be pluggable.
    """

    @abstractmethod
    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        """Extract content from a single document.

        Args:
            request: Extraction request containing source path/URL and options.

        Returns:
            ExtractionResult with Markdown, JSON, and metadata.

        Raises:
            ExtractionError: If extraction fails unrecoverably.
        """
        ...

    @abstractmethod
    def extract_batch(
        self, requests: list[ExtractionRequest]
    ) -> list[ExtractionResult]:
        """Extract content from multiple documents.

        Implementations should use the extractor's native batch API
        when available (e.g. DocumentConverter.convert_all()) for efficiency.

        Args:
            requests: List of extraction requests.

        Returns:
            List of ExtractionResult objects, one per request.
            Results may include FAILED status entries rather than raising.
        """
        ...

    @property
    @abstractmethod
    def extractor_name(self) -> str:
        """Human-readable name of the extractor implementation.

        Returns:
            Name string, e.g. 'DoclingAdapter v2.x'.
        """
        ...

    @property
    @abstractmethod
    def supports_ocr(self) -> bool:
        """Whether this extractor supports OCR processing.

        Returns:
            True if OCR can be activated via configuration.
        """
        ...

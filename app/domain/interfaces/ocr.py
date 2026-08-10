"""DocEngine — Domain Interface: IOcrEngine.

Phase 2 stub — fully defined so activation requires only configuration changes,
not architectural changes. The Application layer will never import OCR engines
directly; all OCR configuration flows through this interface into the adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class IOcrEngine(ABC):
    """Abstract base class for OCR engine adapters.

    In Phase 1, only the NullOcrAdapter (no-op) is implemented.
    In Phase 2, implement this interface for:
    - TesseractOcrEngine
    - EasyOcrEngine
    - RapidOcrEngine

    The implementing class must return a Docling-compatible OcrOptions
    object from get_ocr_options(). This object is then passed directly
    to PdfPipelineOptions.ocr_options in the DoclingAdapter.
    """

    @abstractmethod
    def get_ocr_options(self) -> Any:
        """Return a Docling-compatible OcrOptions object.

        Returns:
            An OcrOptions instance (e.g. EasyOcrOptions, TesseractOcrOptions)
            or None if OCR is disabled.
        """
        ...

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """Human-readable OCR engine name.

        Returns:
            Name string, e.g. 'EasyOCR', 'Tesseract', 'RapidOCR', 'None'.
        """
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether the OCR engine runtime is available on the current system.

        Returns:
            True if the engine can be used, False if dependencies are missing.
        """
        ...

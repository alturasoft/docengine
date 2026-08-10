"""DocEngine — Infrastructure Adapter: OCR (Phase 2 Stub).

Phase 1: NullOcrAdapter is the only implementation. It is injected
wherever an IOcrEngine is required and does nothing.

Phase 2: Implement TesseractOcrAdapter, EasyOcrAdapter, or RapidOcrAdapter
by subclassing IOcrEngine. The DoclingAdapter will automatically pick up
the engine via dependency injection — no core code changes needed.
"""

from __future__ import annotations

from typing import Any

from app.domain.interfaces.ocr import IOcrEngine


class NullOcrAdapter(IOcrEngine):
    """No-operation OCR adapter for Phase 1.

    Returns None from get_ocr_options(), which means DoclingAdapter
    will not set ocr_options on PdfPipelineOptions (Docling default).
    Since do_ocr=False in Phase 1 config, this has no effect.
    """

    def get_ocr_options(self) -> Any:
        """Return None — no OCR options for Phase 1.

        Returns:
            None, indicating no OCR engine is configured.
        """
        return None

    @property
    def engine_name(self) -> str:
        """Return the engine name."""
        return "none"

    @property
    def is_available(self) -> bool:
        """NullOcrAdapter is always available."""
        return True


# ---------------------------------------------------------------------------
# Phase 2 stubs (not functional — shown for architecture illustration)
# ---------------------------------------------------------------------------


class EasyOcrAdapter(IOcrEngine):
    """EasyOCR engine adapter — Phase 2.

    Requires: pip install "docling[easyocr]"
    """

    def __init__(self, languages: list[str] | None = None) -> None:
        self._languages = languages or ["es", "en"]

    def get_ocr_options(self) -> Any:
        """Return EasyOcrOptions configured for the selected languages.

        Returns:
            EasyOcrOptions instance for Docling pipeline configuration.
        """
        from docling.datamodel.pipeline_options import EasyOcrOptions  # noqa: PLC0415

        return EasyOcrOptions(
            force_full_page_ocr=False,
            lang=self._languages,
        )

    @property
    def engine_name(self) -> str:
        """Return the engine name."""
        return "EasyOCR"

    @property
    def is_available(self) -> bool:
        """Check if EasyOCR is installed."""
        try:
            import easyocr  # noqa: F401

            return True
        except ImportError:
            return False


class TesseractOcrAdapter(IOcrEngine):
    """Tesseract OCR engine adapter — Phase 2.

    Requires: Tesseract system binary + pip install "docling[tesseract]"
    """

    def __init__(self, languages: list[str] | None = None) -> None:
        self._languages = languages or ["spa", "eng"]

    def get_ocr_options(self) -> Any:
        """Return TesseractOcrOptions configured for the selected languages.

        Returns:
            TesseractOcrOptions instance for Docling pipeline configuration.
        """
        from docling.datamodel.pipeline_options import TesseractOcrOptions  # noqa: PLC0415

        return TesseractOcrOptions(lang=self._languages)

    @property
    def engine_name(self) -> str:
        """Return the engine name."""
        return "Tesseract"

    @property
    def is_available(self) -> bool:
        """Check if Tesseract binary is accessible."""
        import shutil

        return shutil.which("tesseract") is not None


class RapidOcrAdapter(IOcrEngine):
    """RapidOCR engine adapter — Phase 2.

    Requires: pip install "docling[rapidocr]"
    """

    def get_ocr_options(self) -> Any:
        """Return RapidOcrOptions.

        Returns:
            RapidOcrOptions instance for Docling pipeline configuration.
        """
        from docling.datamodel.pipeline_options import RapidOcrOptions  # noqa: PLC0415

        return RapidOcrOptions()

    @property
    def engine_name(self) -> str:
        """Return the engine name."""
        return "RapidOCR"

    @property
    def is_available(self) -> bool:
        """Check if RapidOCR is installed."""
        try:
            import rapidocr_onnxruntime  # noqa: F401

            return True
        except ImportError:
            return False

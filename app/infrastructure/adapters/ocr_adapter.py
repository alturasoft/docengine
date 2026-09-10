"""DocEngine — Infrastructure Adapter: OCR.

Provides OCR engine adapters that wrap Docling’s OCR options into the
IOcrEngine interface.  The DoclingAdapter uses these adapters to configure
OCR on the PDF pipeline.

Gold Standard configuration: All adapters support OcrMode.FULL_PAGE for
maximum extraction fidelity.  When force_full_page_ocr=True, the adapter
sets mode=OcrMode.FULL_PAGE on the returned options, which tells Docling
to OCR the entire page image regardless of detected text regions.
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

    def __init__(
        self,
        languages: list[str] | None = None,
        force_full_page_ocr: bool = False,
    ) -> None:
        self._languages = languages or ["es", "en"]
        self._force_full_page_ocr = force_full_page_ocr

    def get_ocr_options(self) -> Any:
        """Return EasyOcrOptions configured for the selected languages.

        When force_full_page_ocr=True, sets mode=OcrMode.FULL_PAGE
        (the modern Docling 2.x equivalent of the deprecated flag).

        Returns:
            EasyOcrOptions instance for Docling pipeline configuration.
        """
        from docling.datamodel.pipeline_options import EasyOcrOptions, OcrMode  # noqa: PLC0415

        opts = EasyOcrOptions(
            force_full_page_ocr=self._force_full_page_ocr,
            lang=self._languages,
        )
        # Explicitly set mode for Docling 2.119+ (force_full_page_ocr is deprecated)
        if self._force_full_page_ocr:
            opts.mode = OcrMode.FULL_PAGE
        return opts

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

    def __init__(
        self,
        languages: list[str] | None = None,
        force_full_page_ocr: bool = False,
    ) -> None:
        self._languages = languages or ["spa", "eng"]
        self._force_full_page_ocr = force_full_page_ocr

    def get_ocr_options(self) -> Any:
        """Return TesseractOcrOptions configured for the selected languages.

        When force_full_page_ocr=True, sets mode=OcrMode.FULL_PAGE
        (the modern Docling 2.x equivalent of the deprecated flag).

        Returns:
            TesseractOcrOptions instance for Docling pipeline configuration.
        """
        from docling.datamodel.pipeline_options import TesseractOcrOptions, OcrMode  # noqa: PLC0415

        opts = TesseractOcrOptions(
            force_full_page_ocr=self._force_full_page_ocr,
            lang=self._languages,
        )
        # Explicitly set mode for Docling 2.119+ (force_full_page_ocr is deprecated)
        if self._force_full_page_ocr:
            opts.mode = OcrMode.FULL_PAGE
        return opts

    @property
    def engine_name(self) -> str:
        """Return the engine name."""
        return "Tesseract"

    @property
    def is_available(self) -> bool:
        """Check if Tesseract binary is accessible and tesserocr Python library is installed."""
        import shutil

        if shutil.which("tesseract") is None:
            return False
        try:
            import tesserocr  # noqa: F401

            return True
        except (ImportError, Exception):
            return False


class RapidOcrAdapter(IOcrEngine):
    """RapidOCR engine adapter.

    Requires: pip install "docling[rapidocr]"
    """

    def __init__(
        self,
        languages: list[str] | None = None,
        force_full_page_ocr: bool = False,
    ) -> None:
        self._languages = languages or ["latin"]
        self._force_full_page_ocr = force_full_page_ocr

    def get_ocr_options(self) -> Any:
        """Return RapidOcrOptions.

        When force_full_page_ocr=True, sets mode=OcrMode.FULL_PAGE
        (the modern Docling 2.x equivalent of the deprecated flag).

        Returns:
            RapidOcrOptions instance for Docling pipeline configuration.
        """
        from docling.datamodel.pipeline_options import RapidOcrOptions, OcrMode  # noqa: PLC0415

        opts = RapidOcrOptions(
            force_full_page_ocr=self._force_full_page_ocr,
            lang=self._languages,
        )
        # Explicitly set mode for Docling 2.119+ (force_full_page_ocr is deprecated)
        if self._force_full_page_ocr:
            opts.mode = OcrMode.FULL_PAGE
        return opts

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


# ---------------------------------------------------------------------------
# Factory Helper
# ---------------------------------------------------------------------------


def _instantiate_ocr_adapter(
    adapter_cls: type[IOcrEngine],
    languages: list[str],
    force_full_page_ocr: bool,
) -> IOcrEngine:
    """Instantiate a concrete IOcrEngine implementation safely."""
    if adapter_cls is RapidOcrAdapter:
        return RapidOcrAdapter(languages=languages, force_full_page_ocr=force_full_page_ocr)
    if adapter_cls is TesseractOcrAdapter:
        return TesseractOcrAdapter(languages=languages, force_full_page_ocr=force_full_page_ocr)
    if adapter_cls is EasyOcrAdapter:
        return EasyOcrAdapter(languages=languages, force_full_page_ocr=force_full_page_ocr)
    return NullOcrAdapter()


def get_ocr_adapter(
    config: Any,
    force_full_page_ocr: bool = False,
) -> IOcrEngine:
    """Instantiate and return the configured OCR adapter.

    Tries the configured OCR engine (from config.ocr.engine). If that engine is
    not available on the system, falls back to available engines or NullOcrAdapter.

    Args:
        config: Application settings instance (AppSettings).
        force_full_page_ocr: Whether to force full-page OCR.

    Returns:
        An instance of IOcrEngine (RapidOcrAdapter, EasyOcrAdapter,
        TesseractOcrAdapter, or NullOcrAdapter).
    """
    ocr_cfg = getattr(config, "ocr", None)
    engine_type = getattr(ocr_cfg, "engine", "rapidocr").lower() if ocr_cfg else "rapidocr"
    languages = getattr(ocr_cfg, "languages", ["es", "en"]) if ocr_cfg else ["es", "en"]

    adapters: dict[str, type[IOcrEngine]] = {
        "rapidocr": RapidOcrAdapter,
        "easyocr": EasyOcrAdapter,
        "tesseract": TesseractOcrAdapter,
    }

    # Attempt primary configured engine
    adapter_cls = adapters.get(engine_type, RapidOcrAdapter)
    instance = _instantiate_ocr_adapter(adapter_cls, languages, force_full_page_ocr)

    if instance.is_available:
        return instance

    # Fallback search if requested engine is unavailable (prioritizes RapidOCR)
    for candidate_cls in [RapidOcrAdapter, EasyOcrAdapter, TesseractOcrAdapter]:
        if candidate_cls is adapter_cls:
            continue
        cand = _instantiate_ocr_adapter(candidate_cls, languages, force_full_page_ocr)
        if cand.is_available:
            return cand

    return NullOcrAdapter()


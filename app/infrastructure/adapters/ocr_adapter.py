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

    def __init__(
        self,
        languages: list[str] | None = None,
        force_full_page_ocr: bool = False,
    ) -> None:
        self._languages = languages or ["es", "en"]
        self._force_full_page_ocr = force_full_page_ocr

    def get_ocr_options(self) -> Any:
        """Return EasyOcrOptions configured for the selected languages.

        Returns:
            EasyOcrOptions instance for Docling pipeline configuration.
        """
        from docling.datamodel.pipeline_options import EasyOcrOptions  # noqa: PLC0415

        return EasyOcrOptions(
            force_full_page_ocr=self._force_full_page_ocr,
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

    def __init__(
        self,
        languages: list[str] | None = None,
        force_full_page_ocr: bool = False,
    ) -> None:
        self._languages = languages or ["spa", "eng"]
        self._force_full_page_ocr = force_full_page_ocr

    def get_ocr_options(self) -> Any:
        """Return TesseractOcrOptions configured for the selected languages.

        Returns:
            TesseractOcrOptions instance for Docling pipeline configuration.
        """
        from docling.datamodel.pipeline_options import TesseractOcrOptions  # noqa: PLC0415

        return TesseractOcrOptions(
            force_full_page_ocr=self._force_full_page_ocr,
            lang=self._languages,
        )

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

    def __init__(self, force_full_page_ocr: bool = False) -> None:
        self._force_full_page_ocr = force_full_page_ocr

    def get_ocr_options(self) -> Any:
        """Return RapidOcrOptions.

        Returns:
            RapidOcrOptions instance for Docling pipeline configuration.
        """
        from docling.datamodel.pipeline_options import RapidOcrOptions  # noqa: PLC0415

        return RapidOcrOptions(force_full_page_ocr=self._force_full_page_ocr)

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
        return RapidOcrAdapter(force_full_page_ocr=force_full_page_ocr)
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
        An instance of IOcrEngine (EasyOcrAdapter, TesseractOcrAdapter,
        RapidOcrAdapter, or NullOcrAdapter).
    """
    ocr_cfg = getattr(config, "ocr", None)
    engine_type = getattr(ocr_cfg, "engine", "easyocr").lower() if ocr_cfg else "easyocr"
    languages = getattr(ocr_cfg, "languages", ["es", "en"]) if ocr_cfg else ["es", "en"]

    adapters: dict[str, type[IOcrEngine]] = {
        "easyocr": EasyOcrAdapter,
        "tesseract": TesseractOcrAdapter,
        "rapidocr": RapidOcrAdapter,
    }

    # Attempt primary configured engine
    adapter_cls = adapters.get(engine_type, EasyOcrAdapter)
    instance = _instantiate_ocr_adapter(adapter_cls, languages, force_full_page_ocr)

    if instance.is_available:
        return instance

    # Fallback search if requested engine is unavailable
    for candidate_cls in [EasyOcrAdapter, TesseractOcrAdapter, RapidOcrAdapter]:
        if candidate_cls is adapter_cls:
            continue
        cand = _instantiate_ocr_adapter(candidate_cls, languages, force_full_page_ocr)
        if cand.is_available:
            return cand

    return NullOcrAdapter()


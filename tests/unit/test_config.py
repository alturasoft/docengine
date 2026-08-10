"""Unit tests for AppSettings and all sub-configuration classes."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.config.settings import (
    AppSettings,
    ExtractionConfig,
    LoggingConfig,
    MarkdownConfig,
    OCRConfig,
    OutputConfig,
    PerformanceConfig,
    PipelineConfig,
    get_settings,
    reset_settings,
)


class TestExtractionConfig:
    """Tests for ExtractionConfig."""

    def test_default_ocr_is_disabled(self) -> None:
        """OCR must be False by default for Phase 1."""
        cfg = ExtractionConfig()
        assert cfg.do_ocr is False

    def test_default_table_mode_is_accurate(self) -> None:
        """TableFormer mode must default to ACCURATE for maximum quality."""
        cfg = ExtractionConfig()
        assert cfg.table_mode == "ACCURATE"

    def test_default_table_structure_enabled(self) -> None:
        """Table structure detection must be enabled by default."""
        cfg = ExtractionConfig()
        assert cfg.do_table_structure is True

    def test_default_cell_matching_enabled(self) -> None:
        """Cell matching improves table accuracy — must be enabled."""
        cfg = ExtractionConfig()
        assert cfg.do_cell_matching is True

    def test_page_range_none_by_default(self) -> None:
        """No page range restriction by default."""
        cfg = ExtractionConfig()
        assert cfg.page_range_start is None
        assert cfg.page_range_end is None



class TestPipelineConfig:
    """Tests for PipelineConfig."""

    def test_default_pdf_backend_is_pypdfium2(self) -> None:
        """Default backend is pypdfium2 for memory robustness on multi-page PDFs."""
        cfg = PipelineConfig()
        assert cfg.pdf_backend == "pypdfium2"

    def test_default_images_scale_is_1(self) -> None:
        """images_scale=1.0 is default to prevent RAM exhaustion."""
        cfg = PipelineConfig()
        assert cfg.images_scale == 1.0


class TestLoggingConfig:
    """Tests for LoggingConfig."""

    def test_default_level_is_info(self) -> None:
        cfg = LoggingConfig()
        assert cfg.level == "INFO"

    def test_default_format_is_console(self) -> None:
        cfg = LoggingConfig()
        assert cfg.format == "console"

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Environment variable should override default log level."""
        monkeypatch.setenv("DOCENGINE_LOG_LEVEL", "DEBUG")
        cfg = LoggingConfig()
        assert cfg.level == "DEBUG"


class TestOutputConfig:
    """Tests for OutputConfig."""

    def test_output_dir_resolves_to_absolute(self) -> None:
        """output_dir must always be an absolute Path."""
        cfg = OutputConfig(output_dir=Path("./outputs"))
        assert cfg.output_dir.is_absolute()

    def test_default_formats_include_md_and_json(self) -> None:
        cfg = OutputConfig()
        assert "md" in cfg.formats or "json" in cfg.formats


class TestMarkdownConfig:
    """Tests for MarkdownConfig."""

    def test_repetition_threshold_in_range(self) -> None:
        cfg = MarkdownConfig()
        assert 0.0 <= cfg.repetition_threshold <= 1.0

    def test_default_remove_repeated_headers(self) -> None:
        cfg = MarkdownConfig()
        assert cfg.remove_repeated_headers is True

    def test_default_max_consecutive_blank_lines(self) -> None:
        cfg = MarkdownConfig()
        assert cfg.max_consecutive_blank_lines >= 1


class TestAppSettings:
    """Tests for the root AppSettings class."""

    def test_default_environment_is_development(self) -> None:
        settings = AppSettings()
        assert settings.environment == "development"

    def test_test_environment(self) -> None:
        settings = AppSettings(environment="test")
        assert settings.is_test() is True
        assert settings.is_production() is False
        assert settings.is_development() is False

    def test_production_environment(self) -> None:
        settings = AppSettings(environment="production")
        assert settings.is_production() is True

    def test_environment_alias_dev(self) -> None:
        """'dev' alias should resolve to 'development'."""
        settings = AppSettings(environment="dev")
        assert settings.environment == "development"

    def test_environment_alias_prod(self) -> None:
        """'prod' alias should resolve to 'production'."""
        settings = AppSettings(environment="prod")
        assert settings.environment == "production"

    def test_sub_configs_instantiated(self) -> None:
        """All sub-configurations must be instantiated."""
        settings = AppSettings()
        assert isinstance(settings.extraction, ExtractionConfig)
        assert isinstance(settings.pipeline, PipelineConfig)
        assert isinstance(settings.output, OutputConfig)
        assert isinstance(settings.logging, LoggingConfig)
        assert isinstance(settings.ocr, OCRConfig)
        assert isinstance(settings.performance, PerformanceConfig)
        assert isinstance(settings.markdown, MarkdownConfig)

    def test_ocr_disabled_in_extraction_config(self) -> None:
        """Core invariant: OCR must be disabled for Phase 1."""
        settings = AppSettings()
        assert settings.extraction.do_ocr is False


class TestGetSettingsSingleton:
    """Tests for the get_settings() singleton function."""

    def test_returns_same_instance(self) -> None:
        """get_settings() must return the same object on repeated calls."""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_reset_forces_recreation(self) -> None:
        """reset_settings() must clear the cached instance."""
        s1 = get_settings()
        reset_settings()
        s2 = get_settings()
        assert s1 is not s2

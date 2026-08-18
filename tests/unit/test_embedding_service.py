"""Unit tests for EmbeddingService and cache resolution behavior."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from app.application.embedding_service import EmbeddingService
from app.config.settings import EmbeddingConfig


class TestEmbeddingServiceCacheResolution:
    """Tests for EmbeddingService cache folder fallback and custom settings."""

    def test_custom_cache_folder_used_when_configured(self) -> None:
        """Explicitly configured cache_folder in EmbeddingConfig must take precedence."""
        custom_path = Path("/custom/cache/dir")
        cfg = EmbeddingConfig(cache_folder=custom_path)
        service = EmbeddingService(cfg)
        assert service._resolve_cache_folder() == str(custom_path)

    def test_nonexistent_home_triggers_temp_fallback(self) -> None:
        """When home directory is /nonexistent, cache must resolve to a safe temp dir."""
        cfg = EmbeddingConfig()
        service = EmbeddingService(cfg)

        with patch("pathlib.Path.home", return_value=Path("/nonexistent")):
            with patch.dict("os.environ", {}, clear=True):
                resolved = service._resolve_cache_folder()
                assert resolved is not None
                assert "/nonexistent" not in resolved
                assert "huggingface" in resolved

    def test_hf_home_env_var_takes_priority(self) -> None:
        """When HF_HOME is set in environment, service leaves cache resolution to HuggingFace."""
        cfg = EmbeddingConfig()
        service = EmbeddingService(cfg)

        with patch.dict("os.environ", {"HF_HOME": "/tmp/custom_hf"}):
            assert service._resolve_cache_folder() is None

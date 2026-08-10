"""DocEngine — Infrastructure: Local Storage Service.

Persists extraction results to the local filesystem.
Each document gets its own sub-directory under the configured output_dir.

When a company sigla is available in the result metadata, documents are
organised by insurer for easier auditing::

    outputs/
    ├── CRI/                         ← company folder
    │   └── {filename_stem}/
    │       ├── {filename}.md
    │       ├── {filename}.json
    │       ├── metadata.json
    │       └── extraction_report.json
    └── {filename_stem}/             ← generic (no company)
        ├── {filename}.md
        └── ...

This layout keeps outputs organised and makes it easy to locate,
archive, or delete results per company or per document.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import AppSettings
from app.domain.interfaces.storage import IStorageService
from app.domain.models.document import ExtractionResult
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class LocalStorageService(IStorageService):
    """Filesystem-based implementation of IStorageService.

    Creates organised output directories under config.output.output_dir.
    All writes are atomic (write to temp file, then rename) to avoid
    partial output files if the process is interrupted.

    Args:
        config: Application settings with output configuration.
    """

    def __init__(self, config: AppSettings) -> None:
        self._config = config
        self._base_dir = config.output.output_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(
            "LocalStorageService initialized", output_dir=str(self._base_dir)
        )

    # ------------------------------------------------------------------
    # IStorageService implementation
    # ------------------------------------------------------------------

    def save_result(self, result: ExtractionResult) -> dict[str, Path]:
        """Save extraction result to disk in all requested formats.

        When ``result.metadata.company_sigla`` is set, the output directory
        is organised as ``outputs/<SIGLA>/<filename_stem>/``.

        Args:
            result: The completed extraction result to persist.

        Returns:
            Mapping of format names to absolute file paths.

        Raises:
            OSError: If a file cannot be written.
        """
        output_dir = self.get_output_dir(
            result.document_id,
            company_sigla=result.metadata.company_sigla,
            filename=result.metadata.filename,
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        saved_paths: dict[str, Path] = {}
        stem = Path(result.metadata.filename).stem

        formats = result.metadata.filename and self._config.output.formats

        # --- Markdown ---
        if "md" in self._config.output.formats or "all" in self._config.output.formats:
            md_path = output_dir / f"{stem}.md"
            self._write_text(md_path, result.markdown)
            saved_paths["md"] = md_path

        # --- JSON (full Docling document) ---
        if "json" in self._config.output.formats or "all" in self._config.output.formats:
            json_path = output_dir / f"{stem}.json"
            self._write_json(json_path, result.json_data)
            saved_paths["json"] = json_path

        # --- Metadata ---
        if self._config.output.include_metadata:
            meta_path = output_dir / "metadata.json"
            self._write_json(meta_path, result.metadata.to_dict())
            saved_paths["metadata"] = meta_path

        # --- Extraction Report ---
        if self._config.output.include_report:
            report = self._build_extraction_report(result)
            report_path = output_dir / "extraction_report.json"
            self._write_json(report_path, report)
            saved_paths["report"] = report_path

        logger.info(
            "Result saved to disk",
            document_id=result.document_id,
            output_dir=str(output_dir),
            files_saved=list(saved_paths.keys()),
        )

        return saved_paths

    def result_exists(
        self,
        document_id: str,
        company_sigla: str | None = None,
        filename: str | None = None,
    ) -> bool:
        """Check whether outputs already exist for this document.

        Args:
            document_id: The unique extraction identifier.
            company_sigla: Optional company code to locate the correct folder.
            filename: Optional original filename to locate the correct folder.

        Returns:
            True if the output directory exists and contains at least one file.
        """
        output_dir = self.get_output_dir(
            document_id,
            company_sigla=company_sigla,
            filename=filename,
        )
        if not output_dir.exists():
            return False
        return any(output_dir.iterdir())

    def get_output_dir(
        self,
        document_id: str,
        company_sigla: str | None = None,
        filename: str | None = None,
    ) -> Path:
        """Return the output directory for a given document_id or filename.

        When ``filename`` is provided, uses the file stem (name without extension)
        as the folder name. Otherwise falls back to ``document_id``.

        When ``company_sigla`` is provided, returns a path under the
        company subdirectory: ``<base_dir>/<SIGLA>/<folder_name>/``.
        Otherwise returns ``<base_dir>/<folder_name>/``.

        Args:
            document_id: The unique extraction identifier.
            company_sigla: Optional 3-letter company code.
            filename: Optional original filename to use as folder name.

        Returns:
            Path to the document-specific subdirectory.
        """
        folder_name = Path(filename).stem if filename else document_id
        if company_sigla:
            return self._base_dir / company_sigla.upper() / folder_name
        return self._base_dir / folder_name

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_text(self, path: Path, content: str) -> None:
        """Write text content to a file atomically.

        Args:
            path: Target file path.
            content: Text content to write.
        """
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)

    def _write_json(self, path: Path, data: dict) -> None:
        """Write a dictionary as pretty-printed JSON atomically.

        Args:
            path: Target file path.
            data: Dictionary to serialize as JSON.
        """
        tmp_path = path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, default=str)
        tmp_path.replace(path)

    def _build_extraction_report(self, result: ExtractionResult) -> dict:
        """Build a human-readable extraction report dictionary.

        Args:
            result: The extraction result to summarise.

        Returns:
            Dictionary suitable for JSON serialization.
        """
        meta = result.metadata
        return {
            "report_id": str(uuid.uuid4()),
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "document": {
                "filename": meta.filename,
                "sha256": meta.sha256,
                "page_count": meta.page_count,
            },
            "extraction": {
                "document_id": result.document_id,
                "status": result.status.value,
                "duration_seconds": round(meta.extraction_time_seconds, 3),
                "docling_version": meta.docling_version,
                "ocr_used": meta.ocr_used,
            },
            "quality": {
                "tables_detected": meta.tables_detected,
                "figures_detected": meta.figures_detected,
                "headers_removed": meta.headers_removed,
                "footers_removed": meta.footers_removed,
                "has_multi_column": meta.has_multi_column,
                "markdown_size_bytes": meta.markdown_size_bytes,
                "warnings_count": len(meta.warnings),
                "errors_count": len(meta.errors),
            },
            "warnings": meta.warnings,
            "errors": meta.errors,
            "output_files": {
                k: str(v) for k, v in result.output_paths.items()
            },
        }

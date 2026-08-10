"""DocEngine — Domain Interface: IStorageService.

Defines the contract for all storage backends.
The Application layer writes results through this interface.
Local filesystem, S3, Azure Blob, or any other backend must implement it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from app.domain.models.document import ExtractionResult


class IStorageService(ABC):
    """Abstract base class for extraction result storage.

    All storage operations are synchronous to keep the pipeline simple.
    For async backends, wrap the implementation in a thread-pool executor.
    """

    @abstractmethod
    def save_result(self, result: ExtractionResult) -> dict[str, Path]:
        """Persist an extraction result in all requested formats.

        Creates a sub-directory named after the document_id under the
        configured output directory, then writes each format file.

        Args:
            result: The completed extraction result to persist.

        Returns:
            Mapping of format name ('md', 'json', 'metadata', 'report')
            to the absolute path of the saved file.

        Raises:
            StorageError: If any file cannot be written.
        """
        ...

    @abstractmethod
    def result_exists(
        self,
        document_id: str,
        company_sigla: str | None = None,
        filename: str | None = None,
    ) -> bool:
        """Check whether a result for the given document_id or filename already exists.

        Args:
            document_id: The unique extraction identifier.
            company_sigla: Optional company code for organized directory lookup.
            filename: Optional original filename to locate the output folder.

        Returns:
            True if at least the output directory exists and contains files.
        """
        ...

    @abstractmethod
    def get_output_dir(
        self,
        document_id: str,
        company_sigla: str | None = None,
        filename: str | None = None,
    ) -> Path:
        """Return the output directory path for a given document_id or filename.

        The directory may or may not exist yet.

        Args:
            document_id: The unique extraction identifier.
            company_sigla: Optional company code for organized directory layout.
            filename: Optional original filename to use as folder name.

        Returns:
            Path to the document-specific output directory.
        """
        ...

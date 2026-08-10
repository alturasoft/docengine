"""DocEngine — Application: Base Post-Processor Interface.

Defines the abstract interface and execution context for all Markdown
post-processing rules ("skills").
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PostProcessingContext:
    """Execution context passed through the post-processing pipeline.

    Attributes:
        page_texts: Optional per-page text content.
        metadata: Execution metadata dictionary.
        errors: List of non-fatal errors recorded during processing.
        transformations_applied: List of names of processors that made changes.
    """

    page_texts: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    transformations_applied: list[str] = field(default_factory=list)


class BasePostProcessor(ABC):
    """Abstract base class for all Markdown post-processing rules.

    To add a new extraction correction rule, subclass this class and
    implement the `name` property and `process()` method.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name identifier for this post-processor."""
        ...

    @property
    def description(self) -> str:
        """Human-readable summary of what this rule corrects."""
        return (self.__doc__ or self.name).strip().split("\n")[0]

    @property
    def enabled_by_default(self) -> bool:
        """Whether this rule is active by default in the pipeline."""
        return True

    @abstractmethod
    def process(self, markdown: str, context: PostProcessingContext) -> str:
        """Apply post-processing transformation to the Markdown content.

        Args:
            markdown: Current Markdown text.
            context: Shared processing context.

        Returns:
            Transformed Markdown text.
        """
        ...

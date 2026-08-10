"""DocEngine — Application: Post-Processing Pipeline.

Orchestrates sequential execution of Markdown post-processing rules.
"""

from __future__ import annotations

from app.application.post_processing.base import (
    BasePostProcessor,
    PostProcessingContext,
)
from app.infrastructure.logging.logger import get_logger

logger = get_logger(__name__)


class PostProcessingPipeline:
    """Sequential pipeline manager for Markdown post-processing rules.

    Allows registering custom rules dynamically and executing them in order
    with error isolation.
    """

    def __init__(self, processors: list[BasePostProcessor] | None = None) -> None:
        self._processors: list[BasePostProcessor] = []
        if processors:
            for proc in processors:
                self.register(proc)

    def register(self, processor: BasePostProcessor) -> PostProcessingPipeline:
        """Register a new post-processor rule in the pipeline.

        Args:
            processor: Instance of BasePostProcessor.

        Returns:
            self for chaining calls.
        """
        self._processors.append(processor)
        logger.debug(
            "Registered post-processor rule",
            rule_name=processor.name,
            description=processor.description,
        )
        return self

    @property
    def registered_rules(self) -> list[str]:
        """Return names of all registered post-processor rules."""
        return [p.name for p in self._processors]

    def run(
        self,
        markdown: str,
        context: PostProcessingContext | None = None,
    ) -> tuple[str, PostProcessingContext]:
        """Run all registered post-processors sequentially on the Markdown text.

        Each processor operates on the output of the previous processor.
        If a processor raises an exception, the error is logged and recorded in
        context.errors, and the pipeline continues with the next processor.

        Args:
            markdown: Raw or partially processed Markdown text.
            context: Shared PostProcessingContext or None to create new.

        Returns:
            Tuple of (transformed_markdown, final_context).
        """
        if context is None:
            context = PostProcessingContext()

        if not markdown or not self._processors:
            return markdown, context

        current_md = markdown

        for processor in self._processors:
            if not processor.enabled_by_default:
                continue

            try:
                before_len = len(current_md)
                result_md = processor.process(current_md, context)

                if result_md != current_md:
                    context.transformations_applied.append(processor.name)
                    logger.debug(
                        "Post-processor rule applied changes",
                        rule_name=processor.name,
                        before_length=before_len,
                        after_length=len(result_md),
                    )
                current_md = result_md

            except Exception as exc:
                error_msg = f"Post-processor '{processor.name}' failed: {exc}"
                logger.error(
                    "Error executing post-processor rule",
                    rule_name=processor.name,
                    error=str(exc),
                )
                context.errors.append(error_msg)

        return current_md, context

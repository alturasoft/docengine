"""DocEngine — Application Post-Processing Module.

Exports the pipeline orchestrator, base interfaces, and default pipeline factory.
"""

from __future__ import annotations

from app.application.post_processing.base import (
    BasePostProcessor,
    PostProcessingContext,
)
from app.application.post_processing.pipeline import PostProcessingPipeline
from app.application.post_processing.processors import (
    DeduplicateOverlappingParagraphsProcessor,
    InsuranceTableSplitterProcessor,
    PolicyKeyValueFormatterProcessor,
    RepeatedElementsProcessor,
    SpacedTextFixerProcessor,
)


def create_default_pipeline(
    repetition_threshold: float = 0.7,
) -> PostProcessingPipeline:
    """Construct the default post-processing pipeline with all rules active.

    Order of execution:
    1. SpacedTextFixerProcessor (collapses letter spacing first)
    2. DeduplicateOverlappingParagraphsProcessor (removes ghost streams)
    3. PolicyKeyValueFormatterProcessor (structures policy metadata form blocks)
    4. InsuranceTableSplitterProcessor (splits merged tables & cleans footer noise)
    5. RepeatedElementsProcessor (removes repetitive headers/footers)

    Args:
        repetition_threshold: Threshold for header/footer repetition detection.

    Returns:
        Configured PostProcessingPipeline instance.
    """
    pipeline = PostProcessingPipeline()
    pipeline.register(SpacedTextFixerProcessor())
    pipeline.register(DeduplicateOverlappingParagraphsProcessor())
    pipeline.register(PolicyKeyValueFormatterProcessor())
    pipeline.register(InsuranceTableSplitterProcessor())
    pipeline.register(RepeatedElementsProcessor(repetition_threshold))
    return pipeline


__all__ = [
    "BasePostProcessor",
    "PostProcessingContext",
    "PostProcessingPipeline",
    "create_default_pipeline",
]

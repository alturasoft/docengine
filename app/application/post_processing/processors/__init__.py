"""DocEngine — Post-Processor Rules Package.

Exports all concrete post-processor rules ("skills") available in DocEngine.
"""

from app.application.post_processing.processors.deduplicate_paragraphs import (
    DeduplicateOverlappingParagraphsProcessor,
)
from app.application.post_processing.processors.policy_kv_formatter import (
    PolicyKeyValueFormatterProcessor,
)
from app.application.post_processing.processors.repeated_elements import (
    RepeatedElementsProcessor,
)
from app.application.post_processing.processors.spaced_text_fixer import (
    SpacedTextFixerProcessor,
)
from app.application.post_processing.processors.table_splitter import (
    InsuranceTableSplitterProcessor,
)

__all__ = [
    "DeduplicateOverlappingParagraphsProcessor",
    "PolicyKeyValueFormatterProcessor",
    "InsuranceTableSplitterProcessor",
    "SpacedTextFixerProcessor",
    "RepeatedElementsProcessor",
]

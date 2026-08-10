"""DocEngine — Infrastructure: Structured Logging.

Configures structlog for:
- JSON output in production (machine-parseable for log aggregation).
- Human-readable coloured output in development.
- Consistent fields: timestamp, level, event, logger, plus any extras.
- Optional memory and timing enrichment.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor

_logging_configured = False


def configure_logging(
    level: str = "INFO",
    format_: str = "console",
    log_file: str | None = None,
) -> None:
    """Configure structlog and stdlib logging.

    Call this once at application startup (in create_app() or main.py).
    Subsequent calls are no-ops to prevent duplicate handler registration.

    Args:
        level: Log level string. One of DEBUG/INFO/WARNING/ERROR/CRITICAL.
        format_: Output format. 'json' for production, 'console' for dev.
        log_file: Optional path to write logs to. None = stdout only.
    """
    global _logging_configured
    if _logging_configured:
        return

    log_level = getattr(logging, level.upper(), logging.INFO)

    # Force UTF-8 encoding on Windows console streams to prevent charmap UnicodeEncodeErrors
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    # --- Handlers ---
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    # --- stdlib root logger ---
    logging.basicConfig(
        level=log_level,
        handlers=handlers,
        format="%(message)s",
    )
    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # --- Shared processors ---
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
    ]

    if format_ == "json":
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _logging_configured = True


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a named structlog logger.

    Usage::

        logger = get_logger(__name__)
        logger.info("Extraction started", document_id="abc", pages=10)

    Args:
        name: Module or component name, typically ``__name__``.

    Returns:
        Bound structlog logger with name attached.
    """
    return structlog.get_logger(name)


def add_memory_info(
    logger: Any, method: str, event_dict: EventDict
) -> EventDict:
    """Structlog processor that appends current process memory usage.

    Add to the processor chain when PerformanceConfig.include_memory is True.

    Args:
        logger: Structlog logger instance (unused).
        method: Log method name (unused).
        event_dict: Current event dictionary to enrich.

    Returns:
        Enriched event dictionary with 'memory_mb' field.
    """
    try:
        import psutil  # noqa: PLC0415

        process = psutil.Process()
        mem_mb = process.memory_info().rss / 1_048_576
        event_dict["memory_mb"] = round(mem_mb, 1)
    except Exception:
        pass
    return event_dict

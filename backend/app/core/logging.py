import logging
from typing import TextIO

import structlog


def configure_logging(level: int = logging.INFO, stream: TextIO | None = None) -> None:
    """JSON logs. `stream` sends every log line there (the MCP stdio server needs stderr,
    because stdout carries the protocol); by default structlog prints to stdout."""
    logging.basicConfig(level=level, format="%(message)s", stream=stream)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=stream),
    )

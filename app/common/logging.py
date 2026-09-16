"""Structured logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import structlog


def configure_logging(level: str = "INFO", log_dir: Path | str = "logs") -> None:
    """Configure console and UTF-8 file logging."""
    target_dir = Path(log_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(target_dir / "app.log", encoding="utf-8"),
        ],
        force=True,
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    """Return a configured-compatible structured logger."""
    return structlog.get_logger(name)


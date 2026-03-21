"""
Structured logging configuration for FlowBrain.

Sets up:
  - Console handler with human-readable format for development
  - Optional file handler (FLOWBRAIN_LOG_FILE) for production
  - Configurable log level (FLOWBRAIN_LOG_LEVEL, default: INFO)
  - Quiets noisy third-party loggers (chromadb, httpx, uvicorn.access)

Call configure_logging() once at startup, before any other imports log.
"""

import os
import logging
import sys
from pathlib import Path


def configure_logging():
    """Configure logging for the entire FlowBrain process."""
    level_name = os.getenv("FLOWBRAIN_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # Root format
    fmt = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = []

    # Console handler
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    handlers.append(console)

    # Optional file handler
    log_file = os.getenv("FLOWBRAIN_LOG_FILE", "")
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        handlers.append(file_handler)

    # Configure root logger
    logging.basicConfig(level=level, handlers=handlers, force=True)

    # Quiet noisy third-party loggers
    for noisy in ("chromadb", "httpx", "httpcore", "uvicorn.access",
                   "sentence_transformers", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # FlowBrain request logger at configured level
    logging.getLogger("flowbrain.requests").setLevel(level)

    logging.getLogger("flowbrain").info(
        "Logging configured: level=%s file=%s",
        level_name,
        log_file or "(console only)",
    )

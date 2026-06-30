"""Structured logging setup for a2d."""

from __future__ import annotations

import logging
import sys


def setup_logging(*, quiet: bool = False, debug: bool = False) -> logging.Logger:
    """Configure logging for the application.

    Three levels:
    - Default (no flags): INFO — shows progress messages
    - ``--quiet``: WARNING — only warnings and errors
    - ``--debug``: DEBUG — full trace output
    """
    if debug:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.INFO

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(formatter)

    logger = logging.getLogger("a2d")
    logger.handlers.clear()
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger

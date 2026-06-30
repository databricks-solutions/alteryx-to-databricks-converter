"""Custom exception hierarchy for the a2d pipeline.

Only these exceptions (and their subclasses) should be caught by pipeline
orchestration code.  Programming errors (TypeError, AttributeError, KeyError,
etc.) must propagate so they surface during development and in logs.
"""

from __future__ import annotations


class A2dError(Exception):
    """Base for all expected a2d errors."""


class ConverterError(A2dError):
    """Raised when a converter fails to transform a ParsedNode into an IRNode."""


class GenerationError(A2dError):
    """Raised when a generator fails to produce code for an IRNode."""


class ParseError(A2dError):
    """Raised when workflow XML parsing fails."""

"""Expression engine error hierarchy.

All expression-related errors (parsing, translation) inherit from
``BaseTranslationError`` so generators can use a single ``except`` block.
"""

from __future__ import annotations


class BaseTranslationError(Exception):
    """Raised when the expression engine cannot process an expression.

    Concrete subclasses:
    - ``TokenizerError`` — tokenisation failures
    - ``ParserError`` — parsing failures
    - ``TranslationError`` — PySpark translation failures
    - ``SQLTranslationError`` — SQL translation failures
    """

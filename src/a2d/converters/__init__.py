"""Converter subsystem for Alteryx-to-Databricks migration.

Importing this package auto-registers all converters via their sub-packages.
Use :class:`ConverterRegistry` to look up and invoke converters.
"""

# Import sub-packages to trigger auto-registration of all converters
from a2d.converters import developer, io, join, parse, predictive, preparation, spatial, transform
from a2d.converters.registry import ConverterRegistry, ToolConverter

__all__ = [
    "ConverterRegistry",
    "ToolConverter",
    "developer",
    "io",
    "join",
    "parse",
    "predictive",
    "preparation",
    "spatial",
    "transform",
]

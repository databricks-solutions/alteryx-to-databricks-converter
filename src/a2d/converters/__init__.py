"""Converter subsystem for Alteryx-to-Databricks migration.

Importing this package auto-registers all converters via their sub-packages.
Use :class:`ConverterRegistry` to look up and invoke converters.
"""

# Import sub-packages to trigger auto-registration of all converters
from a2d.converters import developer, io, join, parse, predictive, preparation, spatial, transform
from a2d.converters.registry import ConverterRegistry, ToolConverter

# Discover and load third-party converter plugins (a2d.converters entry points).
# Done after the built-ins so a plugin can intentionally override one; failures
# are logged and skipped inside load_plugins.
from a2d.sdk.discovery import load_plugins as _load_plugins

_load_plugins()

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

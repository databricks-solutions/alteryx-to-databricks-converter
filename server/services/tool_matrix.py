"""Tool matrix service — wraps PLUGIN_NAME_MAP + TOOL_METADATA + ConverterRegistry."""

from __future__ import annotations

import logging
from functools import lru_cache

# Ensure all converters are loaded by importing the package
import a2d.converters  # noqa: F401
from a2d.converters.registry import ConverterRegistry
from a2d.expressions.functions import FUNCTION_REGISTRY
from a2d.parser.schema import PLUGIN_NAME_MAP, TOOL_METADATA, ToolMetadata
from server.constants import FORMAT_MAP

logger = logging.getLogger("a2d.server.services.tool_matrix")


@lru_cache(maxsize=1)
def get_tool_matrix() -> dict[str, tuple[dict, ...]]:
    """Return tool info grouped by category (cached, returns immutable tuples)."""
    supported = ConverterRegistry.supported_tools()
    categories: dict[str, list[dict]] = {}

    seen_tool_types: set[str] = set()
    for _plugin, (tool_type, category) in PLUGIN_NAME_MAP.items():
        if tool_type in seen_tool_types:
            continue
        seen_tool_types.add(tool_type)

        meta: ToolMetadata | None = TOOL_METADATA.get(tool_type)
        entry = {
            "tool_type": tool_type,
            "category": category,
            "supported": tool_type in supported,
            "conversion_method": meta.conversion_method if meta else None,
            "description": meta.short_description if meta else None,
            "databricks_equivalent": meta.databricks_equivalent if meta else None,
        }
        categories.setdefault(category, []).append(entry)

    # Convert to tuples for hashable cache
    return {k: tuple(v) for k, v in categories.items()}


@lru_cache(maxsize=1)
def get_stats() -> dict:
    """Return summary statistics computed dynamically."""
    supported = ConverterRegistry.supported_tools()
    seen: set[str] = set()
    for _plugin, (tool_type, _cat) in PLUGIN_NAME_MAP.items():
        seen.add(tool_type)

    return {
        "supported_tools": len(supported),
        "total_tools": len(seen),
        "expression_functions": len(FUNCTION_REGISTRY),
        "output_formats": len(FORMAT_MAP),
    }

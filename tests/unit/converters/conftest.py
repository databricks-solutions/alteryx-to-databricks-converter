"""Shared fixtures and helpers for converter tests."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.parser.schema import ParsedNode

DEFAULT_CONFIG = ConversionConfig()


def make_node(
    tool_id: int = 1,
    plugin_name: str = "",
    tool_type: str = "",
    category: str = "test",
    configuration: dict | None = None,
    annotation: str | None = None,
) -> ParsedNode:
    """Create a ParsedNode for testing."""
    return ParsedNode(
        tool_id=tool_id,
        plugin_name=plugin_name,
        tool_type=tool_type,
        category=category,
        configuration=configuration or {},
        annotation=annotation,
    )

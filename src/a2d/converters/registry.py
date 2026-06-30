"""Converter registry with decorator-based auto-registration.

Each :class:`ToolConverter` subclass declares the Alteryx tool types it handles.
Applying ``@ConverterRegistry.register`` on the class automatically instantiates
it and maps every supported tool type to that instance.

At conversion time, :meth:`ConverterRegistry.convert_node` looks up the right
converter for a :class:`ParsedNode` and returns the corresponding :class:`IRNode`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import ClassVar

from a2d.config import ConversionConfig
from a2d.exceptions import ConverterError
from a2d.ir.nodes import IRNode, UnsupportedNode
from a2d.parser.schema import ParsedNode

logger = logging.getLogger("a2d.converters")


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class ToolConverter(ABC):
    """Base class for tool converters.  Transforms ParsedNode -> IRNode."""

    @abstractmethod
    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        """Convert a parsed Alteryx node into an IR node."""
        ...

    @property
    @abstractmethod
    def supported_tool_types(self) -> list[str]:
        """Return the list of Alteryx tool-type strings this converter handles."""
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ConverterRegistry:
    """Central registry mapping Alteryx tool types to converter instances."""

    _converters: ClassVar[dict[str, ToolConverter]] = {}

    @classmethod
    def register(cls, converter_class: type[ToolConverter]) -> type[ToolConverter]:
        """Class decorator that instantiates *converter_class* and registers
        it for every tool type it declares support for.
        """
        instance = converter_class()
        for tool_type in instance.supported_tool_types:
            if tool_type in cls._converters:
                logger.warning(
                    "Overwriting converter for tool type %r (%s -> %s)",
                    tool_type,
                    type(cls._converters[tool_type]).__name__,
                    converter_class.__name__,
                )
            cls._converters[tool_type] = instance
            logger.debug("Registered converter %s for %r", converter_class.__name__, tool_type)
        return converter_class

    @classmethod
    def get_converter(cls, tool_type: str) -> ToolConverter | None:
        """Return the converter for *tool_type*, or ``None``."""
        return cls._converters.get(tool_type)

    @classmethod
    def supported_tools(cls) -> set[str]:
        """Return the set of all tool types with a registered converter."""
        return set(cls._converters.keys())

    @classmethod
    def convert_node(cls, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        """Convert a *parsed_node* to an IR node, falling back to
        :class:`UnsupportedNode` when no converter is available.
        """
        converter = cls.get_converter(parsed_node.tool_type)
        if converter:
            try:
                return converter.convert(parsed_node, config)
            except (ConverterError, KeyError, TypeError, ValueError):
                logger.exception(
                    "Converter %s failed for tool %s (id=%d)",
                    type(converter).__name__,
                    parsed_node.tool_type,
                    parsed_node.tool_id,
                )
                return UnsupportedNode(
                    node_id=parsed_node.tool_id,
                    original_tool_type=parsed_node.tool_type,
                    original_plugin_name=parsed_node.plugin_name,
                    annotation=parsed_node.annotation,
                    position=parsed_node.position,
                    unsupported_reason=f"Converter error for tool type: {parsed_node.tool_type}",
                )

        return UnsupportedNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            unsupported_reason=f"No converter for tool type: {parsed_node.tool_type}",
        )

    @classmethod
    def coverage_for(cls, tool_types: set[str]) -> float:
        """Return the fraction of *tool_types* that have a registered converter."""
        if not tool_types:
            return 1.0
        return len(tool_types & cls.supported_tools()) / len(tool_types)

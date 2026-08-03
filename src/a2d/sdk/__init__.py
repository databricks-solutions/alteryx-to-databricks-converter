"""Public SDK for third-party converter and frontend authors.

This is the **stable contract** a plugin builds against. Import everything you
need from :mod:`a2d.sdk` rather than reaching into internal modules — the SDK
surface is what we keep backwards-compatible; internal layout may change.

Write a converter
-----------------

.. code-block:: python

    from a2d.sdk import ConverterRegistry, ToolConverter, ParsedNode, ConversionConfig
    from a2d.sdk import FilterNode, IRNode

    @ConverterRegistry.register
    class MyToolConverter(ToolConverter):
        @property
        def supported_tool_types(self) -> list[str]:
            return ["MyTool"]

        def convert(self, node: ParsedNode, config: ConversionConfig) -> IRNode:
            return FilterNode(node_id=node.tool_id, expression=node.configuration["expr"])

Ship it as a package that declares the entry point:

.. code-block:: toml

    [project.entry-points."a2d.converters"]
    my_tool = "my_pkg.converters"   # module is imported → decorators run

a2d discovers and loads it automatically (see :func:`a2d.sdk.discovery.load_plugins`).

Write a frontend
----------------

Subclass :class:`SourceFrontend`, return a ``ParsedWorkflow`` from ``parse``,
and declare an ``a2d.frontends`` entry point.

The SDK version tracks the contract, not the app: check :data:`SDK_VERSION`.
"""

from __future__ import annotations

# -- Version of the plugin contract (bump on breaking SDK changes) --
SDK_VERSION = "1.0"

# -- Converter contract --
from a2d.config import CatalogMode, ConversionConfig, OutputFormat
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.exceptions import ConverterError, ParseError
from a2d.frontends.base import SourceFrontend

# -- IR: base + the node types plugin authors most commonly produce --
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    FilterNode,
    FormulaField,
    FormulaNode,
    IRNode,
    JoinNode,
    ReadNode,
    SelectNode,
    SortNode,
    SummarizeNode,
    UnionNode,
    UnsupportedNode,
    WriteNode,
)

# -- Parsed source model (frontend authors + converter authors read this) --
from a2d.parser.schema import (
    ConnectionAnchor,
    ParsedConnection,
    ParsedNode,
    ParsedWorkflow,
)
from a2d.sdk.discovery import PluginInfo, list_plugins, load_plugins

__all__ = [
    "SDK_VERSION",
    "CatalogMode",
    "ConnectionAnchor",
    "ConversionConfig",
    "ConverterError",
    "ConverterRegistry",
    "FilterNode",
    "FormulaField",
    "FormulaNode",
    "IRNode",
    "JoinNode",
    "OutputFormat",
    "ParseError",
    "ParsedConnection",
    "ParsedNode",
    "ParsedWorkflow",
    "PluginInfo",
    "ReadNode",
    "SelectNode",
    "SortNode",
    "SourceFrontend",
    "SummarizeNode",
    "ToolConverter",
    "UnionNode",
    "UnsupportedNode",
    "WorkflowDAG",
    "WriteNode",
    "list_plugins",
    "load_plugins",
]

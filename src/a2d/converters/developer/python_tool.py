"""Converter for Alteryx PythonTool tool -> PythonToolNode."""

from __future__ import annotations

import html

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, PythonToolNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class PythonToolConverter(ToolConverter):
    """Converts Alteryx PythonTool to :class:`PythonToolNode`.

    The embedded Python code is extracted verbatim but flagged for manual
    review, since Alteryx Python uses a different runtime (AlteryxPythonSDK).
    """

    @property
    def supported_tool_types(self) -> list[str]:
        return ["PythonTool"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        code = safe_get(cfg, "Code") or safe_get(cfg, "PythonScript") or safe_get(cfg, "#text")
        if code:
            code = html.unescape(code)

        mode = safe_get(cfg, "Mode", default="script").lower()
        if mode not in ("script", "jupyter"):
            mode = "script"

        return PythonToolNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            code=code,
            mode=mode,
            conversion_confidence=0.3,
            conversion_notes=[
                "Embedded Python code requires manual review and rewrite.",
                "Alteryx Python SDK APIs (Alteryx.read, Alteryx.write) must be replaced with Spark equivalents.",
            ],
        )

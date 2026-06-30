"""Converter for Alteryx XMLParse tool -> XMLParseNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import IRNode, XMLParseNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class XMLParseConverter(ToolConverter):
    """Converts Alteryx XMLParse tool to :class:`XMLParseNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["XMLParse"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        input_field = safe_get(cfg, "XMLField", safe_get(cfg, "Field", ""))
        root_element = safe_get(cfg, "RootElement", "")
        output_field = safe_get(cfg, "OutputField", "xml_parsed")

        xpath_expressions: list[tuple[str, str]] = []
        xpath_list = cfg.get("XPathExpressions", cfg.get("Children", []))
        if isinstance(xpath_list, list):
            for item in xpath_list:
                if isinstance(item, dict):
                    xpath = item.get("@xpath", item.get("XPath", ""))
                    name = item.get("@name", item.get("Name", xpath))
                    xpath_expressions.append((xpath, name))

        return XMLParseNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            input_field=input_field,
            xpath_expressions=xpath_expressions,
            root_element=root_element,
            output_field=output_field,
        )

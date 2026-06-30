"""Converter for Alteryx Geocoder tool -> GeocoderNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import safe_get
from a2d.ir.nodes import GeocoderNode, IRNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class GeocoderConverter(ToolConverter):
    """Converts Alteryx Geocoder tool to :class:`GeocoderNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Geocoder"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        return GeocoderNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            address_field=safe_get(cfg, "AddressField"),
            city_field=safe_get(cfg, "CityField"),
            state_field=safe_get(cfg, "StateField"),
            zip_field=safe_get(cfg, "ZipField"),
            country_field=safe_get(cfg, "CountryField"),
            conversion_confidence=0.3,
            conversion_method="mapping",
            conversion_notes=[
                "Alteryx uses built-in Experian/TomTom geocoding; Databricks requires external API.",
                "Generated code provides UDF scaffolding for a geocoding API call.",
            ],
        )

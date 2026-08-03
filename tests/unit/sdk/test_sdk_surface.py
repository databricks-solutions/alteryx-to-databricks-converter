"""Tests for the public SDK surface (the plugin contract)."""

from __future__ import annotations

import a2d.sdk as sdk


class TestSdkSurface:
    def test_version_present(self):
        assert isinstance(sdk.SDK_VERSION, str)
        assert sdk.SDK_VERSION

    def test_contract_symbols_exported(self):
        # The core contract a plugin author builds against.
        for name in [
            "ConverterRegistry",
            "ToolConverter",
            "ParsedNode",
            "ParsedWorkflow",
            "ConversionConfig",
            "IRNode",
            "FilterNode",
            "SourceFrontend",
            "WorkflowDAG",
            "load_plugins",
            "list_plugins",
        ]:
            assert hasattr(sdk, name), f"SDK missing {name}"
            assert name in sdk.__all__, f"{name} not in __all__"

    def test_can_build_a_converter_against_sdk(self):
        # A plugin-style converter defined purely against a2d.sdk works and
        # registers into the shared registry.
        @sdk.ConverterRegistry.register
        class _SdkExampleConverter(sdk.ToolConverter):
            @property
            def supported_tool_types(self) -> list[str]:
                return ["_SdkExampleTool"]

            def convert(self, node: sdk.ParsedNode, config: sdk.ConversionConfig) -> sdk.IRNode:
                return sdk.FilterNode(node_id=node.tool_id, expression="[x] > 0")

        try:
            node = sdk.ParsedNode(tool_id=1, plugin_name="p", tool_type="_SdkExampleTool", category="test")
            result = sdk.ConverterRegistry.convert_node(node, sdk.ConversionConfig())
            assert isinstance(result, sdk.FilterNode)
            assert result.expression == "[x] > 0"
        finally:
            sdk.ConverterRegistry._converters.pop("_SdkExampleTool", None)

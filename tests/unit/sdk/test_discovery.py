"""Tests for converter-plugin discovery via entry points."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from a2d.converters.registry import ConverterRegistry
from a2d.sdk import discovery


@dataclass
class _FakeEP:
    """Stand-in for an importlib.metadata EntryPoint."""

    name: str
    value: str
    _target: object

    def load(self):
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


@pytest.fixture(autouse=True)
def _reset_discovery():
    """Reset discovery state so each test loads fresh."""
    discovery._loaded = False
    discovery._plugin_infos.clear()
    yield
    discovery._loaded = False
    discovery._plugin_infos.clear()


def _make_converter_class(tool_type: str):
    from a2d.sdk import ConversionConfig, FilterNode, ParsedNode, ToolConverter

    class _Conv(ToolConverter):
        @property
        def supported_tool_types(self):
            return [tool_type]

        def convert(self, node: ParsedNode, config: ConversionConfig) -> FilterNode:
            return FilterNode(node_id=node.tool_id, expression="1=1")

    return _Conv


class TestLoadPlugins:
    def test_loads_converter_class_entry_point(self, monkeypatch):
        conv_cls = _make_converter_class("_PluginToolA")
        ep = _FakeEP(name="plugin_a", value="pkg:Conv", _target=conv_cls)
        monkeypatch.setattr(discovery, "_iter_entry_points", lambda group: [ep])

        try:
            infos = discovery.load_plugins(force=True)
            assert len(infos) == 1
            assert infos[0].loaded is True
            assert "_PluginToolA" in infos[0].tool_types
            assert "_PluginToolA" in ConverterRegistry.supported_tools()
        finally:
            ConverterRegistry._converters.pop("_PluginToolA", None)

    def test_failing_plugin_is_recorded_not_raised(self, monkeypatch):
        ep = _FakeEP(name="bad", value="pkg:boom", _target=ImportError("no module"))
        monkeypatch.setattr(discovery, "_iter_entry_points", lambda group: [ep])

        infos = discovery.load_plugins(force=True)
        assert len(infos) == 1
        assert infos[0].loaded is False
        assert "no module" in infos[0].error

    def test_no_plugins(self, monkeypatch):
        monkeypatch.setattr(discovery, "_iter_entry_points", lambda group: [])
        assert discovery.load_plugins(force=True) == []

    def test_idempotent_without_force(self, monkeypatch):
        calls = []
        monkeypatch.setattr(discovery, "_iter_entry_points", lambda group: calls.append(1) or [])
        discovery.load_plugins(force=True)
        discovery.load_plugins()  # should not re-scan
        assert len(calls) == 1

"""Plugin discovery for third-party converters (and reporting of loaded plugins).

Community converter packages declare an ``a2d.converters`` entry point whose
value is an import target (a module or a ToolConverter subclass). Loading it
runs the module — and thus any ``@ConverterRegistry.register`` decorators — so
the converters register themselves exactly like the built-ins.

``load_plugins`` is idempotent and defensive: a plugin that fails to import is
recorded with its error and skipped, never crashing the host.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from importlib.metadata import entry_points

from a2d.converters.registry import ConverterRegistry, ToolConverter

logger = logging.getLogger("a2d.sdk.discovery")

_CONVERTER_GROUP = "a2d.converters"

_loaded = False


@dataclass
class PluginInfo:
    """Outcome of attempting to load one converter plugin."""

    name: str
    value: str  # entry-point target, e.g. "my_pkg.converters"
    loaded: bool
    tool_types: list[str] = field(default_factory=list)
    error: str = ""


_plugin_infos: list[PluginInfo] = []


def _iter_entry_points(group: str):
    try:
        return list(entry_points(group=group))
    except TypeError:  # pragma: no cover - pre-3.10 importlib API
        return list(entry_points().get(group, []))  # type: ignore[attr-defined]


def load_plugins(*, force: bool = False) -> list[PluginInfo]:
    """Discover and load ``a2d.converters`` entry-point plugins.

    Idempotent: only runs once unless *force* is set. Returns the per-plugin
    load outcomes.
    """
    global _loaded
    if _loaded and not force:
        return list(_plugin_infos)

    _plugin_infos.clear()
    before = ConverterRegistry.supported_tools()

    for ep in _iter_entry_points(_CONVERTER_GROUP):
        info = PluginInfo(name=ep.name, value=getattr(ep, "value", str(ep)), loaded=False)
        try:
            obj = ep.load()
            # If the entry point resolves to a ToolConverter subclass, register it.
            if isinstance(obj, type) and issubclass(obj, ToolConverter):
                ConverterRegistry.register(obj)
            # Otherwise it's a module whose import side effect registered converters.
            info.loaded = True
            info.tool_types = sorted(ConverterRegistry.supported_tools() - before)
            logger.info("Loaded converter plugin %r (%s)", ep.name, info.value)
        except Exception as exc:  # a bad plugin must not break the host
            info.error = str(exc)
            logger.warning("Failed to load converter plugin %r: %s", ep.name, exc)
        _plugin_infos.append(info)
        before = ConverterRegistry.supported_tools()

    _loaded = True
    return list(_plugin_infos)


def list_plugins() -> list[PluginInfo]:
    """Return the load outcomes, loading plugins first if not yet done."""
    return load_plugins()

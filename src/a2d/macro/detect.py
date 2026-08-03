"""Detect macro-call nodes in a parsed workflow and resolve their paths."""

from __future__ import annotations

import re
from dataclasses import dataclass

from a2d.parser.schema import ParsedNode, ParsedWorkflow

# Plugin strings for the macro *boundary* tools (not macro calls) — these live
# INSIDE a .yxmc and must not be mistaken for a macro call.
_BOUNDARY_TOOL_TYPES = frozenset({"MacroInput", "MacroOutput"})


def macro_path_for_node(node: ParsedNode) -> str | None:
    """Return the ``.yxmc`` path a node references, or None if it isn't a call.

    A macro call is recognized by an explicit ``MacroPath`` in configuration, or
    a ``macro:<file>`` plugin name synthesized by the parser from
    ``EngineSettings Macro=``. Boundary tools (MacroInput/MacroOutput) are
    excluded.
    """
    if node.tool_type in _BOUNDARY_TOOL_TYPES:
        return None

    macro_path = node.configuration.get("MacroPath", "")
    if isinstance(macro_path, dict):  # element_to_dict may wrap text values
        macro_path = macro_path.get("#text", "")
    if isinstance(macro_path, str) and macro_path.strip():
        return macro_path.strip()

    # Parser encodes EngineSettings Macro="foo.yxmc" as plugin_name "macro:foo.yxmc".
    if node.plugin_name.startswith("macro:"):
        return node.plugin_name.split(":", 1)[1]

    return None


@dataclass
class MacroCall:
    """A macro-call node in the parent workflow and its referenced path."""

    node_id: int
    macro_path: str
    tool_type: str


def find_macro_calls(workflow: ParsedWorkflow) -> list[MacroCall]:
    """Return every macro-call node in *workflow*, in tool-id order."""
    calls: list[MacroCall] = []
    for node in workflow.nodes:
        if node.disabled:
            continue
        path = macro_path_for_node(node)
        if path:
            calls.append(MacroCall(node_id=node.tool_id, macro_path=path, tool_type=node.tool_type))
    calls.sort(key=lambda c: c.node_id)
    return calls


_IDENT_RE = re.compile(r"[^0-9a-zA-Z]+")


def function_name_for(macro_path: str) -> str:
    """Derive a safe SQL/Python identifier from a macro file path.

    ``macros/Standard Cleanse.yxmc`` -> ``macro_standard_cleanse``.
    """
    stem = macro_path.replace("\\", "/").rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0]  # drop extension
    ident = _IDENT_RE.sub("_", stem).strip("_").lower()
    if not ident:
        ident = "macro"
    if ident[0].isdigit():
        ident = f"m_{ident}"
    return f"macro_{ident}" if not ident.startswith("macro") else ident

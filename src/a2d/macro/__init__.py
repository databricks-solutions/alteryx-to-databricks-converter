"""Macro expansion engine.

Alteryx macros (``.yxmc``) are reusable sub-workflows referenced from a parent
workflow by a *macro-call* node. Left alone, those call nodes convert to an
:class:`~a2d.ir.nodes.UnsupportedNode` — a coverage hole and a manual-migration
burden repeated at every call site.

This package resolves the referenced ``.yxmc``, parses it into its own IR DAG,
and **inlines** that DAG into the parent workflow at the call site: the parent's
upstream feeds the macro's ``MacroInput`` boundary and the macro's
``MacroOutput`` boundary feeds the parent's downstream. The same macro is
captured once as a reusable :class:`MacroDefinition` so a generator can emit it
as a shared Unity Catalog function / Lakeflow Designer UDO instead of copying
it per call.

* :mod:`a2d.macro.detect` — find macro-call nodes and their referenced paths.
* :mod:`a2d.macro.models` — :class:`MacroDefinition` / :class:`ExpansionResult`.
* :mod:`a2d.macro.engine` — resolve, parse, and inline macros into a DAG.
"""

from __future__ import annotations

from a2d.macro.detect import MacroCall, find_macro_calls, macro_path_for_node
from a2d.macro.engine import MacroExpansionEngine
from a2d.macro.models import (
    ExpansionResult,
    MacroBoundary,
    MacroDefinition,
    UnresolvedMacro,
)

__all__ = [
    "ExpansionResult",
    "MacroBoundary",
    "MacroCall",
    "MacroDefinition",
    "MacroExpansionEngine",
    "UnresolvedMacro",
    "find_macro_calls",
    "macro_path_for_node",
]

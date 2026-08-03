"""Pluggable source frontends — one IR, many sources.

a2d's value is its intermediate representation: everything downstream (all five
generators, ``verify``, ``portfolio``, ``assist``, the bridges, the review
workspace) operates on a :class:`~a2d.ir.graph.WorkflowDAG`, not on Alteryx XML.
A *frontend* is the front half of the pipeline — it parses some source format
into a :class:`~a2d.parser.schema.ParsedWorkflow`, which ``_build_dag`` then
turns into IR. Add a frontend and every downstream capability works on the new
source for free.

* :class:`SourceFrontend` — the contract: ``parse(path) -> ParsedWorkflow`` plus
  the file extensions / name it handles.
* :class:`FrontendRegistry` — resolves a frontend by name or by file extension,
  and discovers third-party frontends via the ``a2d.frontends`` entry-point
  group (so a plugin package can add one without touching core).
* Built-ins: :class:`AlteryxFrontend` (the existing ``.yxmd``/``.yxmc`` parser)
  and :class:`DbtFrontend` (dbt ``manifest.json`` → IR).
"""

from __future__ import annotations

from a2d.frontends.alteryx import AlteryxFrontend
from a2d.frontends.base import SourceFrontend
from a2d.frontends.dbt import DbtFrontend
from a2d.frontends.registry import FrontendRegistry

__all__ = [
    "AlteryxFrontend",
    "DbtFrontend",
    "FrontendRegistry",
    "SourceFrontend",
]

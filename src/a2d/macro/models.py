"""Data models for the macro expansion engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from a2d.ir.graph import WorkflowDAG


@dataclass
class MacroBoundary:
    """One input/output boundary of a macro (a MacroInput/MacroOutput tool).

    ``node_id`` is the id of the boundary node *inside the macro's own DAG*.
    ``name`` is the boundary's field/parameter name, used to line up multiple
    inputs/outputs with the parent's connection anchors when a macro has more
    than one of each.
    """

    node_id: int
    name: str
    direction: str  # "input" or "output"


@dataclass
class MacroDefinition:
    """A parsed macro (.yxmc), captured once for reuse across call sites.

    ``function_name`` is a sanitized identifier a generator can use to emit the
    macro as a shared Unity Catalog function / Designer UDO.
    """

    macro_path: str  # normalized path used as the dedupe key
    source_path: str  # the resolved on-disk path actually parsed
    function_name: str
    dag: WorkflowDAG
    inputs: list[MacroBoundary] = field(default_factory=list)
    outputs: list[MacroBoundary] = field(default_factory=list)
    node_count: int = 0

    @property
    def interior_node_count(self) -> int:
        """Nodes excluding the input/output boundary nodes."""
        return self.node_count - len(self.inputs) - len(self.outputs)


@dataclass
class UnresolvedMacro:
    """A macro reference that could not be resolved or parsed."""

    macro_path: str
    call_node_id: int
    reason: str


@dataclass
class ExpansionResult:
    """Outcome of expanding all macro calls in one workflow.

    ``dag`` is the parent DAG with every resolvable macro inlined. ``definitions``
    holds each distinct macro parsed (for reusable-function emission).
    ``expanded_calls`` counts call sites successfully inlined; ``unresolved``
    lists the ones left as-is (still convertible manually).
    """

    dag: WorkflowDAG
    definitions: list[MacroDefinition] = field(default_factory=list)
    expanded_calls: int = 0
    unresolved: list[UnresolvedMacro] = field(default_factory=list)

    @property
    def macro_count(self) -> int:
        return len(self.definitions)

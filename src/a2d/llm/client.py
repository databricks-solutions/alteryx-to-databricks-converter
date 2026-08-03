"""LLM client abstraction and the offline deterministic default.

The :class:`LLMClient` protocol is provider-agnostic: given a
:class:`ConversionRequest` it returns zero or more :class:`ConversionCandidate`
objects. The default :class:`StubLLMClient` is fully offline and deterministic —
it maps a handful of well-understood unsupported tools onto supported IR nodes
via a built-in knowledge base, so the feature is exercisable in CI without any
model access. A real model-serving client can be dropped in behind the same
protocol (see :func:`get_default_client`).
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from a2d.llm.models import ConversionCandidate, ConversionRequest, ProposedNode

logger = logging.getLogger("a2d.llm.client")


@runtime_checkable
class LLMClient(Protocol):
    """Provider-agnostic candidate proposer."""

    def propose(self, request: ConversionRequest, *, max_candidates: int = 3) -> list[ConversionCandidate]:
        """Return candidate conversions for one unsupported node (best first)."""
        ...


# ---------------------------------------------------------------------------
# Offline stub knowledge base
# ---------------------------------------------------------------------------

# Each handler takes a ConversionRequest and returns a ConversionCandidate or
# None. Handlers only ever emit *supported* IR node kinds so the result is
# verifiable and generatable. Keyed by Alteryx tool_type.


def _cfg_str(cfg: dict, *keys: str, default: str = "") -> str:
    """Best-effort nested string lookup tolerant of element_to_dict shapes."""
    cur: object = cfg
    for key in keys:
        if isinstance(cur, dict):
            cur = cur.get(key, {})
        else:
            return default
    if isinstance(cur, dict):
        cur = cur.get("#text", "")
    return str(cur) if cur not in ({}, None) else default


def _propose_message(req: ConversionRequest) -> ConversionCandidate | None:
    """Message tool logs a message and passes data through unchanged.

    Equivalent to a no-op Select that keeps all columns.
    """
    return ConversionCandidate(
        nodes=[ProposedNode(ref="n0", kind="SelectNode", params={"select_all_unknown": True})],
        output_ref="n0",
        rationale="Message is a logging side-effect with no data change; passes rows through unchanged.",
        confidence=0.9,
        source="stub",
    )


def _propose_test(req: ConversionRequest) -> ConversionCandidate | None:
    """Test tool validates rows against expectations but does not modify them."""
    return ConversionCandidate(
        nodes=[ProposedNode(ref="n0", kind="SelectNode", params={"select_all_unknown": True})],
        output_ref="n0",
        rationale="Test asserts expectations without changing the data; models as a pass-through.",
        confidence=0.8,
        source="stub",
    )


def _propose_dynamic_rename(req: ConversionRequest) -> ConversionCandidate | None:
    """DynamicRename in 'Formula'/prefix/suffix modes can map to a Select rename.

    Only handles the simple explicit-rename case where the config carries a
    field->new-name mapping; anything data-dependent is left to the model / a
    human. A rename map is expressed as SelectNode field_operations.
    """
    cfg = req.configuration
    rename_info = cfg.get("Fields") or cfg.get("Rename") or {}
    mapping: dict[str, str] = {}
    if isinstance(rename_info, dict):
        fields = rename_info.get("Field")
        if isinstance(fields, dict):
            fields = [fields]
        if isinstance(fields, list):
            for f in fields:
                if not isinstance(f, dict):
                    continue
                old = f.get("@field") or f.get("field") or f.get("@name") or f.get("name")
                new = f.get("@rename") or f.get("rename") or f.get("@newname")
                if old and new:
                    mapping[str(old)] = str(new)
    if not mapping:
        return None

    field_ops = [
        {"field_name": old, "action": "rename", "rename_to": new, "selected": True} for old, new in mapping.items()
    ]
    return ConversionCandidate(
        nodes=[
            ProposedNode(
                ref="n0",
                kind="SelectNode",
                params={"field_operations": field_ops, "select_all_unknown": True},
            )
        ],
        output_ref="n0",
        rationale=f"Explicit rename map ({len(mapping)} field(s)) modelled as a Select rename.",
        confidence=0.7,
        source="stub",
    )


# tool_type -> handler
_KNOWLEDGE_BASE = {
    "Message": _propose_message,
    "Test": _propose_test,
    "DynamicRename": _propose_dynamic_rename,
}


class StubLLMClient:
    """Deterministic, offline candidate proposer backed by a small KB.

    Returns real, verifiable candidates for the tools it knows and an empty list
    otherwise — so downstream code exercises the full propose→verify→accept /
    reject path without any network dependency.
    """

    def propose(self, request: ConversionRequest, *, max_candidates: int = 3) -> list[ConversionCandidate]:
        handler = _KNOWLEDGE_BASE.get(request.tool_type)
        if handler is None:
            return []
        candidate = handler(request)
        if candidate is None:
            return []
        return [candidate][:max_candidates]

    @property
    def known_tool_types(self) -> set[str]:
        return set(_KNOWLEDGE_BASE)


def get_default_client() -> LLMClient:
    """Return the default proposer.

    Currently the offline :class:`StubLLMClient`. A future model-serving client
    would be selected here based on configuration/environment, keeping call
    sites unaware of the provider.
    """
    return StubLLMClient()

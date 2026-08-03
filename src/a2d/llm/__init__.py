"""LLM-assisted conversion for the unsupported-tool tail.

The deterministic converters cover the common Alteryx tools; a long tail of
rarer tools still falls through to :class:`~a2d.ir.nodes.UnsupportedNode`. This
package proposes conversions for that tail and — critically — **verifies every
proposal against the Q1 equivalence harness before trusting it**.

Design principles:

* **Propose as IR, not free code.** A proposal is a small graph of *already-
  supported* IR nodes (Filter/Formula/Select/…), never arbitrary Python. That
  keeps proposals emittable by all four generators, executable by the pandas
  reference executor, and free of arbitrary-code execution.
* **Gated by verification.** A proposal is only *accepted* (spliced into the
  dataflow) when the reference executor + parity engine confirm it reproduces
  the expected output on sample data. Unverified proposals are surfaced as
  clearly-labelled suggestions — never silently merged.
* **Offline-safe by default.** The default client is a deterministic, network-
  free :class:`StubLLMClient` backed by a small built-in knowledge base, so the
  whole feature (and its tests) run in CI with no model access. A real model-
  serving client is opt-in behind configuration.

Entry points:

* :class:`a2d.llm.client.LLMClient` — provider-agnostic client protocol.
* :class:`a2d.llm.client.StubLLMClient` — offline default.
* :class:`a2d.llm.assist.LLMAssistedConverter` — orchestrates propose→verify.
"""

from __future__ import annotations

from a2d.llm.assist import AssistOutcome, LLMAssistedConverter
from a2d.llm.client import LLMClient, StubLLMClient, get_default_client
from a2d.llm.models import (
    ConversionCandidate,
    ConversionRequest,
    ProposedNode,
    VerificationVerdict,
)
from a2d.llm.workflow import (
    WorkflowAssistReport,
    scan_dag,
    scan_workflow_file,
)

__all__ = [
    "AssistOutcome",
    "ConversionCandidate",
    "ConversionRequest",
    "LLMAssistedConverter",
    "LLMClient",
    "ProposedNode",
    "StubLLMClient",
    "VerificationVerdict",
    "WorkflowAssistReport",
    "get_default_client",
    "scan_dag",
    "scan_workflow_file",
]

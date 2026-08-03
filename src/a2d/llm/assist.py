"""Orchestrate LLM-assisted conversion: propose → build → verify → accept/reject.

This is the gate that makes LLM proposals trustworthy. For an unsupported node
the flow is:

1. Ask the client for candidate sub-graphs of supported IR nodes.
2. Build each candidate into a real IR sub-DAG (through the allow-list).
3. If a golden ``sample_input``/``expected_output`` pair is available, execute
   the candidate with the pandas reference executor and diff the result against
   the expected output with the parity engine. Only an exact-equivalence pass
   marks the candidate ``verified``.
4. Return the best outcome. A ``verified`` candidate is safe to splice into the
   dataflow; an ``unverified`` one is surfaced as a suggestion for human review;
   ``rejected`` ones are discarded.

Without a golden pair the gate cannot confirm equivalence, so candidates are
returned as ``unverified`` — never silently accepted. This preserves the
project's "unsupported ops are never a false pass" invariant.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from a2d.ir.graph import WorkflowDAG
from a2d.llm.builder import CandidateBuildError, build_node
from a2d.llm.client import LLMClient, get_default_client
from a2d.llm.models import ConversionCandidate, ConversionRequest, VerificationVerdict

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger("a2d.llm.assist")

# Node ids inside a candidate sub-DAG live in a private band so they never
# collide with real workflow ids when the candidate is later spliced in.
_CANDIDATE_ID_BASE = 900_000

# Id for the synthetic ReadNode used only during verification to inject the
# sample frame into the candidate's source node.
_SYNTHETIC_READ_ID = 899_999


@dataclass
class AssistOutcome:
    """The result of attempting LLM-assisted conversion for one node."""

    node_id: int
    tool_type: str
    candidate: ConversionCandidate | None = None
    verdict: VerificationVerdict | None = None
    dag: WorkflowDAG | None = None  # built sub-DAG for an accepted/suggested candidate
    output_node_id: int | None = None  # id of the sub-DAG's output node
    considered: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.verdict is not None and self.verdict.accepted


class LLMAssistedConverter:
    """Propose and verify conversions for unsupported nodes."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or get_default_client()

    def assist(
        self,
        request: ConversionRequest,
        *,
        sample_input: pd.DataFrame | None = None,
        expected_output: pd.DataFrame | None = None,
        max_candidates: int = 3,
        abs_tol: float = 1e-9,
        rel_tol: float = 1e-6,
    ) -> AssistOutcome:
        """Return the best verified (or otherwise best-effort) conversion."""
        candidates = self.client.propose(request, max_candidates=max_candidates)
        outcome = AssistOutcome(node_id=request.node_id, tool_type=request.tool_type, considered=len(candidates))
        if not candidates:
            outcome.notes.append("No candidate proposed for this tool type.")
            return outcome

        best_unverified: AssistOutcome | None = None

        for candidate in candidates:
            try:
                dag, output_id = self._build_dag(candidate)
            except CandidateBuildError as exc:
                logger.debug("Discarding candidate for node %d: %s", request.node_id, exc)
                continue

            verdict = self._verify(
                dag,
                output_id,
                sample_input=sample_input,
                expected_output=expected_output,
                abs_tol=abs_tol,
                rel_tol=rel_tol,
            )
            candidate_outcome = AssistOutcome(
                node_id=request.node_id,
                tool_type=request.tool_type,
                candidate=candidate,
                verdict=verdict,
                dag=dag,
                output_node_id=output_id,
                considered=len(candidates),
            )
            if verdict.accepted:
                return candidate_outcome
            if best_unverified is None:
                best_unverified = candidate_outcome

        if best_unverified is not None:
            return best_unverified

        outcome.notes.append("All candidates failed to build into valid IR.")
        return outcome

    # -- Build --

    def _build_dag(self, candidate: ConversionCandidate) -> tuple[WorkflowDAG, int]:
        """Assemble a candidate's ProposedNodes into a WorkflowDAG.

        Returns the DAG and the node_id of the output node. Raises
        :class:`CandidateBuildError` on unknown refs / kinds / cycles.
        """
        if not candidate.nodes:
            raise CandidateBuildError("candidate has no nodes")

        ref_to_id: dict[str, int] = {}
        dag = WorkflowDAG()
        for i, proposed in enumerate(candidate.nodes):
            if proposed.ref in ref_to_id:
                raise CandidateBuildError(f"duplicate node ref {proposed.ref!r}")
            node_id = _CANDIDATE_ID_BASE + i
            ref_to_id[proposed.ref] = node_id
            dag.add_node(build_node(proposed.kind, node_id, proposed.params))

        for proposed in candidate.nodes:
            target = ref_to_id[proposed.ref]
            for upstream_ref in proposed.inputs:
                if upstream_ref not in ref_to_id:
                    raise CandidateBuildError(f"input ref {upstream_ref!r} not defined")
                dag.add_edge(ref_to_id[upstream_ref], target)

        if candidate.output_ref not in ref_to_id:
            raise CandidateBuildError(f"output_ref {candidate.output_ref!r} not defined")
        if dag.has_cycle():
            raise CandidateBuildError("candidate sub-DAG contains a cycle")

        return dag, ref_to_id[candidate.output_ref]

    # -- Verify (the gate) --

    def _verify(
        self,
        dag: WorkflowDAG,
        output_id: int,
        *,
        sample_input: pd.DataFrame | None,
        expected_output: pd.DataFrame | None,
        abs_tol: float,
        rel_tol: float,
    ) -> VerificationVerdict:
        """Run the candidate through the reference executor + parity gate."""
        if sample_input is None or expected_output is None:
            return VerificationVerdict(
                status="unverified",
                detail="No golden sample_input/expected_output pair; candidate not verified.",
            )

        try:
            from a2d.verification.parity import compare_frames
            from a2d.verification.reference import ReferenceExecutor
        except ImportError as exc:  # pandas not installed
            return VerificationVerdict(status="unverified", detail=f"verify extra unavailable: {exc}")

        # The candidate expects exactly one external input.
        source_ids = [n.node_id for n in dag.get_source_nodes()]
        if len(source_ids) != 1:
            return VerificationVerdict(
                status="unverified",
                detail=f"candidate needs exactly one input, found {len(source_ids)}",
            )

        # Prepend a synthetic ReadNode so the reference executor (which only
        # seeds source_data into Read nodes) can inject the sample frame.
        exec_dag = self._with_synthetic_source(dag, source_ids[0])
        executor = ReferenceExecutor(source_data={_SYNTHETIC_READ_ID: sample_input})
        result = executor.execute(exec_dag)
        if result.skipped:
            reasons = "; ".join(r for _, r in result.skipped)
            return VerificationVerdict(status="unverified", detail=f"reference executor skipped nodes: {reasons}")

        actual = result.outputs.get(output_id)
        if actual is None:
            return VerificationVerdict(status="unverified", detail="candidate produced no output frame")

        parity = compare_frames(expected_output, actual, abs_tol=abs_tol, rel_tol=rel_tol)
        if parity.passed:
            return VerificationVerdict(status="verified", parity_score=parity.parity_score, detail=parity.summary())
        return VerificationVerdict(status="rejected", parity_score=parity.parity_score, detail=parity.summary())

    @staticmethod
    def _with_synthetic_source(dag: WorkflowDAG, source_id: int) -> WorkflowDAG:
        """Return a copy of *dag* with a synthetic ReadNode feeding *source_id*."""
        from a2d.ir.nodes import ReadNode

        exec_dag = WorkflowDAG()
        exec_dag.add_node(ReadNode(node_id=_SYNTHETIC_READ_ID, original_tool_type="Input"))
        for node in dag.all_nodes():
            exec_dag.add_node(node)
        for src, dst, info in dag.all_edges():
            exec_dag.add_edge(src, dst, info.origin_anchor, info.destination_anchor, info.is_wireless)
        exec_dag.add_edge(_SYNTHETIC_READ_ID, source_id)
        return exec_dag

"""Orchestrate an equivalence-verification run over a workflow.

Ties the pieces together: parse a ``.yxmd`` into an IR DAG, execute it with the
pandas reference executor (and the Spark backend when a JVM is available), and
compare the sink result against supplied golden output with the parity engine.

Three modes, chosen by what the caller supplies:

* **golden** — an expected-output DataFrame is given (exported from Alteryx).
  The reference result is compared against it. This is true equivalence.
* **cross_check** — no golden output, but Spark is available. The pandas and
  Spark results are compared against each other (agreement of two independent
  implementations).
* **reference_only** — no golden output and no Spark. The reference result is
  produced and reported, but there's nothing to diff against, so the verdict is
  ``inconclusive`` (never a false pass).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from a2d.config import ConversionConfig
from a2d.verification.parity import ParityReport, compare_frames
from a2d.verification.reference import ReferenceExecutor, ReferenceResult
from a2d.verification.spark_backend import SparkBackend, SparkResult, spark_available

if TYPE_CHECKING:
    import pandas as pd

VerifyMode = Literal["golden", "cross_check", "reference_only"]
VerifyStatus = Literal["pass", "fail", "inconclusive", "error"]


@dataclass
class VerificationResult:
    """Full outcome of an ``a2d verify`` run."""

    workflow: str
    status: VerifyStatus
    mode: VerifyMode
    parity: ParityReport | None = None
    reference: ReferenceResult | None = None
    spark: SparkResult | None = None
    sink_node_id: int | None = None
    skipped_nodes: list[tuple[int, str]] = field(default_factory=list)
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "workflow": self.workflow,
            "status": self.status,
            "mode": self.mode,
            "sink_node_id": self.sink_node_id,
            "skipped_nodes": [{"node_id": nid, "reason": r} for nid, r in self.skipped_nodes],
            "parity": self.parity.to_dict() if self.parity else None,
            "spark_available": bool(self.spark and self.spark.available),
            "error": self.error,
            "notes": self.notes,
        }


def _sink_frame(result_outputs: dict[int, pd.DataFrame], sink_ids: list[int]) -> tuple[int | None, pd.DataFrame | None]:
    """Pick the sink node result to compare (single sink, or last available)."""
    for nid in sink_ids:
        if nid in result_outputs:
            return nid, result_outputs[nid]
    if result_outputs:
        nid = max(result_outputs)
        return nid, result_outputs[nid]
    return None, None


def verify_workflow(
    workflow_path: Path,
    *,
    source_data: dict[str | int, pd.DataFrame],
    expected_output: pd.DataFrame | None = None,
    config: ConversionConfig | None = None,
    use_spark: bool = True,
    abs_tol: float = 1e-9,
    rel_tol: float = 1e-6,
) -> VerificationResult:
    """Run equivalence verification for a single workflow.

    ``source_data`` maps each source node (by node_id, table name, or file path)
    to the sample input DataFrame. ``expected_output`` is the golden result
    exported from Alteryx (optional; enables ``golden`` mode).
    """
    from a2d.pipeline import ConversionPipeline

    name = workflow_path.stem
    cfg = config or ConversionConfig(input_path=workflow_path, output_dir=Path("."))

    # Parse + build the IR DAG (reuse the pipeline's parser/builder).
    try:
        pipeline = ConversionPipeline(cfg)
        parsed = pipeline._parser.parse(workflow_path)
        dag = pipeline._build_dag(parsed)
    except Exception as exc:
        return VerificationResult(workflow=name, status="error", mode="reference_only", error=str(exc))

    # Reference execution (always).
    try:
        ref = ReferenceExecutor(source_data).execute(dag)
    except Exception as exc:
        return VerificationResult(workflow=name, status="error", mode="reference_only", error=str(exc))

    ref_sink_id, ref_frame = _sink_frame(ref.outputs, ref.sink_node_ids)

    # Spark execution (optional / when available).
    spark_res: SparkResult | None = None
    if use_spark:
        ok, _reason = spark_available()
        if ok:
            spark_res = SparkBackend(source_data).execute(dag)

    result = VerificationResult(
        workflow=name,
        status="inconclusive",
        mode="reference_only",
        reference=ref,
        spark=spark_res,
        sink_node_id=ref_sink_id,
        skipped_nodes=list(ref.skipped),
    )

    if ref_frame is None:
        result.status = "error"
        result.error = "Reference executor produced no sink output"
        return result

    # -- Mode selection + parity --
    if expected_output is not None:
        result.mode = "golden"
        result.parity = compare_frames(expected_output, ref_frame, abs_tol=abs_tol, rel_tol=rel_tol)
        result.status = "pass" if result.parity.passed else "fail"
    elif spark_res is not None and spark_res.available:
        result.mode = "cross_check"
        _sid, spark_frame = _sink_frame(spark_res.outputs, spark_res.sink_node_ids)
        if spark_frame is not None:
            result.parity = compare_frames(ref_frame, spark_frame, abs_tol=abs_tol, rel_tol=rel_tol)
            result.status = "pass" if result.parity.passed else "fail"
        else:
            result.notes.append("Spark produced no sink output; falling back to reference-only.")
    else:
        result.mode = "reference_only"
        result.notes.append(
            "No golden output supplied and Spark unavailable — reference result "
            "produced but not compared (inconclusive)."
        )

    # A partially-supported workflow can't be a clean pass.
    if ref.skipped and result.status == "pass":
        result.status = "inconclusive"
        result.notes.append(
            f"{len(ref.skipped)} node(s) unsupported by the reference executor — "
            "verified subset only."
        )

    return result


def load_csv_inputs(mapping: dict[str, Path]) -> dict[str | int, pd.DataFrame]:
    """Load a ``{source_key: csv_path}`` mapping into DataFrames.

    Keys that look like integers are coerced to node ids so callers can key by
    either a ReadNode id or a table/file identifier.
    """
    import pandas as pd

    out: dict[str | int, pd.DataFrame] = {}
    for key, path in mapping.items():
        df = pd.read_csv(path)
        # Register under the string key, and also under the int node-id when the
        # key is numeric, so ReferenceExecutor can resolve by either.
        out[key] = df
        if key.lstrip("-").isdigit():
            out[int(key)] = df
    return out

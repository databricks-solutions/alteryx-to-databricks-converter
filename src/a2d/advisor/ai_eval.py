"""AI completion eval: how a model does on a fixed set of real workflows.

Runs the app's own completion engine (same conversion, prompt, wiring and
checks) on each workflow and records, per step: whether the reply passed the
checks, why not, how long the call took and the tokens used. The summary is
what to compare before changing the model or the prompt.

"Completed" means the reply passed the checks (valid Python, assigns what later
steps read, no forbidden calls). It doesn't prove the code is right; read a
sample of the replies too.
"""

from __future__ import annotations

import json
import logging
import statistics
import tempfile
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

from a2d.advisor.completion import complete_notebook
from a2d.advisor.context import build_migration_context
from a2d.advisor.llm_client import AdvisoryClient, ChatMessage
from a2d.config import ConversionConfig, OutputFormat
from a2d.pipeline import ConversionPipeline

logger = logging.getLogger("a2d.advisor.ai_eval")

_PACKT = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "packt"
# Varied real workflows (Packt "Alteryx for Data Engineers"): dynamic tools,
# Make Columns, Mongo input, Download, the ML suite, Calgary Join and more.
DEFAULT_FIXTURES = [
    "Server_Usage_Testing.yxmd",
    "Transforming_and_Profiling_Places.yxmd",
    "Public_Dataset_Download.yxmd",
    "Make_Columns_Fix_for_Excel_data.yxmd",
    "CH09-R03-Dynamically_Replacing_values.yxmd",
    "CH04-R02-Fixing_CrossTabRenames.yxmd",
    "CH06-R03-MakeGroups.yxmd",
    "CH12-R03-_Blob_Input_-_Using_Web_Python.yxmd",
    "Spatial_Analytics.yxmd",
    "CH07-R01_-_Join_vs._FindReplace.yxmd",
    "CH02R03_-_3_-_CalgaryJoin.yxmd",
    "GenerateFlat.yxmd",
    "Machine_Learning_-_Intelligence_Suite.yxmd",
]


def default_paths() -> list[Path]:
    return [_PACKT / name for name in DEFAULT_FIXTURES]


@dataclass
class StepResult:
    workflow: str
    node_id: int | None
    tool_type: str | None
    status: str
    reason: str
    seconds: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass
class EvalReport:
    model: str
    steps: list[StepResult] = field(default_factory=list)
    seconds: float = 0.0

    def summary(self) -> dict:
        status = Counter(s.status for s in self.steps)
        total = len(self.steps)
        times = sorted(s.seconds for s in self.steps if s.seconds is not None)
        reasons = Counter(s.reason for s in self.steps if s.status != "completed")
        per_tool: dict[str, Counter] = {}
        for s in self.steps:
            per_tool.setdefault(s.tool_type or "?", Counter())[s.status] += 1
        return {
            "model": self.model,
            "workflows": len({s.workflow for s in self.steps}),
            "steps": total,
            "completed": status["completed"],
            "failed": status["failed"],
            "skipped": status["skipped"],
            "completed_rate": round(status["completed"] / total, 3) if total else 0.0,
            "median_seconds": round(statistics.median(times), 2) if times else None,
            "p90_seconds": round(times[int(len(times) * 0.9)], 2) if times else None,
            "prompt_tokens": sum(s.prompt_tokens or 0 for s in self.steps),
            "completion_tokens": sum(s.completion_tokens or 0 for s in self.steps),
            "wall_seconds": round(self.seconds, 1),
            "reasons": dict(reasons.most_common()),
            "per_tool": {t: dict(c) for t, c in sorted(per_tool.items())},
        }

    def to_dict(self) -> dict:
        return {"summary": self.summary(), "steps": [asdict(s) for s in self.steps]}


class _Recorder:
    """Wraps a client and keeps each call's time and tokens by the step it was for."""

    def __init__(self, inner: AdvisoryClient) -> None:
        self.inner = inner
        self.calls: dict[int, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    @property
    def model_name(self) -> str:
        return getattr(self.inner, "model_name", "") or type(self.inner).__name__

    def chat_with_usage(self, messages: list[ChatMessage], *, max_tokens: int = 4000) -> tuple[str, dict]:
        started = time.monotonic()
        with_usage = getattr(self.inner, "chat_with_usage", None)
        if callable(with_usage):
            text, usage = with_usage(messages, max_tokens=max_tokens)
        else:
            text, usage = self.inner.chat(messages, max_tokens=max_tokens), {}
        node_id = _node_id(messages[-1].content)
        if node_id is not None:
            with self._lock:
                self.calls[node_id] = (time.monotonic() - started, usage)
        return text, usage

    def chat(self, messages: list[ChatMessage], *, max_tokens: int = 4000) -> str:
        return self.chat_with_usage(messages, max_tokens=max_tokens)[0]


def _node_id(prompt: str) -> int | None:
    for line in prompt.splitlines():
        if line.startswith("Alteryx node id: "):
            try:
                return int(line.split(": ", 1)[1])
            except ValueError:
                return None
    return None


def run_eval(paths: list[Path], client: AdvisoryClient) -> EvalReport:
    """Complete every workflow in ``paths`` with ``client`` and report per step."""
    started = time.monotonic()
    report = EvalReport(model=getattr(client, "model_name", "") or type(client).__name__)
    for path in paths:
        recorder = _Recorder(client)
        with tempfile.TemporaryDirectory() as tmp:
            config = ConversionConfig(input_path=path, output_dir=Path(tmp), output_format=OutputFormat.PYSPARK)
            result = ConversionPipeline(config).convert(path)
        notebook = next(f for f in result.output.files if f.filename.endswith(".py"))
        ctx = build_migration_context(
            result.dag,
            workflow_name=path.stem,
            output_format="pyspark",
            format_warnings=list(result.output.warnings),
            generated_code=notebook.content,
        )
        completion = complete_notebook(
            notebook.content,
            ctx,
            recorder,
            result.dag,
            result.output.cell_nodes.get(notebook.filename),
            node_io=result.output.node_io.get(notebook.filename),
        )
        for cell in completion.cells:
            seconds, usage = recorder.calls.get(cell.node_id, (None, {})) if cell.node_id is not None else (None, {})
            report.steps.append(
                StepResult(
                    workflow=path.name,
                    node_id=cell.node_id,
                    tool_type=cell.tool_type,
                    status=cell.status,
                    reason=cell.reason,
                    seconds=round(seconds, 2) if seconds is not None else None,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                )
            )
        logger.info("%s: %s", path.name, completion.to_dict()["summary"])
    report.seconds = time.monotonic() - started
    return report


def compare(summary: dict, baseline: dict) -> list[str]:
    """Plain lines on how ``summary`` differs from ``baseline`` (both from ``EvalReport.summary``)."""
    lines = []
    for key in ("steps", "completed", "failed", "skipped", "completed_rate", "median_seconds", "p90_seconds"):
        new, old = summary.get(key), baseline.get(key)
        if new != old:
            lines.append(f"{key}: {old} -> {new}")
    return lines


def load_summary(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("summary", data)

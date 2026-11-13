"""AI tracing: one trace per completion or suggestion, a span per model call,
and nothing at all when it isn't configured."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from a2d.advisor import tracing
from a2d.advisor.completion import complete_notebook
from a2d.advisor.context import build_migration_context
from a2d.advisor.llm_client import ChatMessage
from a2d.config import ConversionConfig, OutputFormat
from a2d.pipeline import ConversionPipeline

WF = Path(__file__).parent.parent.parent / "fixtures" / "workflows" / "message_passthrough.yxmd"


class FakeSpan:
    def __init__(self, store, name, span_type, parent, inputs, attributes):
        self.name, self.span_type, self.parent, self.inputs = name, span_type, parent, inputs
        self.attributes = dict(attributes or {})
        self.outputs, self.status, self.ended = None, None, False
        self.trace_id = parent.trace_id if parent else f"tr-{len(store):032x}"
        store.append(self)

    def end(self, outputs=None, attributes=None, status="OK"):
        self.outputs, self.status, self.ended = outputs, status, True
        self.attributes.update(attributes or {})


@pytest.fixture()
def fake_mlflow(monkeypatch):
    spans: list[FakeSpan] = []
    mod = types.ModuleType("mlflow")

    def start_span_no_context(name, span_type="UNKNOWN", parent_span=None, inputs=None, attributes=None, **kw):
        # Only a root names the experiment (MLflow rejects it on a child).
        assert (kw.get("experiment_id") == "123") == (parent_span is None)
        return FakeSpan(spans, name, span_type, parent_span, inputs, attributes)

    mod.start_span_no_context = start_span_no_context
    mod.set_experiment = lambda experiment_id=None, **kw: None
    mod.feedback = []

    def log_feedback(trace_id, name, value, source=None, rationale=None):
        mod.feedback.append((trace_id, name, value, source.source_type if source else None))

    mod.log_feedback = log_feedback
    entities = types.ModuleType("mlflow.entities")

    class AssessmentSource:
        def __init__(self, source_type, source_id):
            self.source_type, self.source_id = source_type, source_id

    entities.AssessmentSource = AssessmentSource
    mod.entities = entities
    monkeypatch.setitem(sys.modules, "mlflow", mod)
    monkeypatch.setitem(sys.modules, "mlflow.entities", entities)
    monkeypatch.setenv(tracing.ENV_EXPERIMENT, "123")
    tracing.reset()
    yield spans
    tracing.reset()


class UsageClient:
    endpoint = "https://h/serving-endpoints/databricks-claude-opus-5-5/invocations"
    model_name = "databricks-claude-opus-5-5"

    def chat_with_usage(self, messages: list[ChatMessage], *, max_tokens: int = 4000):
        return "df_2 = df_1.limit(5)", {"prompt_tokens": 900, "completion_tokens": 12}

    def chat(self, messages, *, max_tokens=4000):
        return self.chat_with_usage(messages)[0]


def _convert():
    result = ConversionPipeline(ConversionConfig(input_path=WF, output_format=OutputFormat.PYSPARK)).convert(WF)
    nb = result.output.files[0]
    ctx = build_migration_context(result.dag, workflow_name=WF.stem, output_format="pyspark", generated_code=nb.content)
    return result, nb, ctx


def test_a_completion_is_one_trace_with_a_span_per_model_call(fake_mlflow):
    result, nb, ctx = _convert()
    out = complete_notebook(
        nb.content,
        ctx,
        UsageClient(),
        result.dag,
        result.output.cell_nodes[nb.filename],
        node_io=result.output.node_io[nb.filename],
    )
    root, *steps = fake_mlflow
    assert root.name == "ai_completion" and root.parent is None and root.ended
    assert root.attributes["model"] == "databricks-claude-opus-5-5"
    assert root.attributes["completed"] == 1
    assert out.trace_id == root.trace_id and out.to_dict()["trace_id"] == root.trace_id
    (step,) = steps
    assert step.parent is root and step.span_type == "LLM" and step.ended
    assert step.inputs["messages"][0]["role"] == "system"
    assert step.outputs == {"reply": "df_2 = df_1.limit(5)"}
    assert step.attributes["status"] == "completed" and step.attributes["check"] == "passed"
    assert step.attributes["prompt_tokens"] == 900 and step.attributes["completion_tokens"] == 12


def test_a_failed_check_is_on_the_span(fake_mlflow):
    class Bad(UsageClient):
        def chat_with_usage(self, messages, *, max_tokens=4000):
            return "import os\nos.remove('x')", {}

    result, nb, ctx = _convert()
    complete_notebook(
        nb.content,
        ctx,
        Bad(),
        result.dag,
        result.output.cell_nodes[nb.filename],
        node_io=result.output.node_io[nb.filename],
    )
    step = fake_mlflow[1]
    assert step.attributes["status"] == "failed"
    assert "imports os" in step.attributes["check"]


def test_a_suggestion_is_its_own_trace(fake_mlflow):
    result, nb, ctx = _convert()
    complete_notebook(
        nb.content,
        ctx,
        UsageClient(),
        result.dag,
        result.output.cell_nodes[nb.filename],
        node_io=result.output.node_io[nb.filename],
        only={2},
        hint="keep 5 rows",
    )
    assert fake_mlflow[0].name == "ai_suggestion"
    assert fake_mlflow[0].inputs["hint"] == "keep 5 rows"


def test_nothing_happens_without_the_setting(monkeypatch):
    monkeypatch.delenv(tracing.ENV_EXPERIMENT, raising=False)
    tracing.reset()
    result, nb, ctx = _convert()
    out = complete_notebook(nb.content, ctx, UsageClient(), result.dag, result.output.cell_nodes[nb.filename])
    assert out.trace_id is None
    assert tracing.enabled() is False
    assert tracing.log_outcome("tr-0123456789abcdef", "used") is False


def test_a_missing_package_turns_tracing_off(monkeypatch):
    monkeypatch.setenv(tracing.ENV_EXPERIMENT, "123")
    monkeypatch.setitem(sys.modules, "mlflow", None)  # import fails
    tracing.reset()
    assert tracing.enabled() is False
    tracing.reset()


def test_a_tracing_error_never_fails_the_request(monkeypatch, fake_mlflow):
    import mlflow

    def boom(*a, **k):
        raise RuntimeError("tracking server down")

    monkeypatch.setattr(mlflow, "start_span_no_context", boom)
    result, nb, ctx = _convert()
    out = complete_notebook(nb.content, ctx, UsageClient(), result.dag, result.output.cell_nodes[nb.filename])
    assert out.completed == 1 and out.trace_id is None


def test_outcome_is_logged_as_human_feedback(fake_mlflow):
    import mlflow

    assert tracing.log_outcome("trace:/cat.sch.a2d/0123456789abcdef", "edited") is True
    assert mlflow.feedback == [("trace:/cat.sch.a2d/0123456789abcdef", "reviewer_outcome", "edited", "HUMAN")]
    with pytest.raises(ValueError):
        tracing.log_outcome("tr-0123456789abcdef", "liked")


def test_outcome_waits_for_a_trace_that_is_still_exporting(monkeypatch, fake_mlflow):
    import mlflow

    attempts = []

    def flaky(trace_id, name, value, source=None, rationale=None):
        attempts.append(trace_id)
        if len(attempts) < 3:
            raise RuntimeError("NOT_FOUND: Trace with ID tr-x not found.")

    monkeypatch.setattr(mlflow, "log_feedback", flaky)
    monkeypatch.setattr(tracing, "_FEEDBACK_WAIT_SECONDS", 0)
    assert tracing.log_outcome("tr-0123456789abcdef", "used") is True
    assert len(attempts) == 3


def test_tracing_makes_the_experiment_active(fake_mlflow, monkeypatch):
    """So MLflow finds the experiment's Unity Catalog link and exports there."""
    import os

    result, nb, ctx = _convert()
    complete_notebook(nb.content, ctx, UsageClient(), result.dag, result.output.cell_nodes[nb.filename])
    assert os.environ["MLFLOW_EXPERIMENT_ID"] == "123"

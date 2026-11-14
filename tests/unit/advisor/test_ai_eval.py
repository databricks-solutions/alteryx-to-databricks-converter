"""The AI eval's report, comparison and CLI."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from a2d.advisor import ai_eval
from a2d.advisor.ai_eval import EvalReport, StepResult, compare, run_eval

WF = Path(__file__).parent.parent.parent / "fixtures" / "workflows" / "message_passthrough.yxmd"


class UsageClient:
    model_name = "fake-model"

    def chat_with_usage(self, messages, *, max_tokens: int = 4000):
        return "df_2 = df_1", {"prompt_tokens": 100, "completion_tokens": 7}

    def chat(self, messages, *, max_tokens: int = 4000):
        return self.chat_with_usage(messages)[0]


def test_records_status_time_and_tokens_per_step():
    report = run_eval([WF], UsageClient())
    (step,) = report.steps
    assert (step.workflow, step.node_id, step.status) == ("message_passthrough.yxmd", 2, "completed")
    assert step.prompt_tokens == 100 and step.completion_tokens == 7 and step.seconds is not None
    s = report.summary()
    assert s["model"] == "fake-model" and s["completed_rate"] == 1.0 and s["prompt_tokens"] == 100


class RetryClient(UsageClient):
    """First reply fails the checks (reads a DataFrame that doesn't exist), the retry passes."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_with_usage(self, messages, *, max_tokens: int = 4000):
        self.calls += 1
        reply = "df_2 = df_99" if self.calls == 1 else "df_2 = df_1"
        return reply, {"prompt_tokens": 100, "completion_tokens": 7}


def test_a_retried_step_adds_up_both_calls():
    report = run_eval([WF], RetryClient())
    (step,) = report.steps
    assert (step.status, step.attempts) == ("completed", 2)
    assert step.prompt_tokens == 200 and step.completion_tokens == 14
    s = report.summary()
    assert (s["retried"], s["completed_on_retry"]) == (1, 1)


def test_summary_counts_reasons_and_tools():
    r = EvalReport(model="m")
    r.steps = [
        StepResult("a", 1, "Join", "completed", ""),
        StepResult("a", 2, "Join", "failed", "not valid Python"),
        StepResult("b", 3, "Message", "skipped", "ran out of time"),
    ]
    s = r.summary()
    assert (s["completed"], s["failed"], s["skipped"], s["completed_rate"]) == (1, 1, 1, 0.333)
    assert s["reasons"] == {"not valid Python": 1, "ran out of time": 1}
    assert s["per_tool"]["Join"] == {"completed": 1, "failed": 1}


def test_compare_lists_what_changed():
    assert compare({"steps": 70, "completed": 70}, {"steps": 70, "completed": 70}) == []
    assert compare({"steps": 70, "completed": 65}, {"steps": 70, "completed": 70}) == ["completed: 70 -> 65"]


def test_cli_writes_the_report_compares_and_gates(tmp_path, monkeypatch):
    from a2d import cli

    monkeypatch.setattr("a2d.advisor.resolve_client", lambda *a, **k: UsageClient())
    out = tmp_path / "report.json"
    baseline = tmp_path / "base.json"
    baseline.write_text(json.dumps({"summary": {"steps": 1, "completed": 0}}))
    runner = CliRunner()
    res = runner.invoke(
        cli.app,
        ["eval-ai", str(WF), "--endpoint", "https://h/x/invocations", "-o", str(out), "--baseline", str(baseline)],
    )
    assert res.exit_code == 0, res.output
    assert json.loads(out.read_text())["summary"]["completed"] == 1
    assert "completed: 0 -> 1" in res.output
    gate = runner.invoke(
        cli.app, ["eval-ai", str(WF), "--endpoint", "https://h/x/invocations", "--min-completed-rate", "1.01"]
    )
    assert gate.exit_code == 1


def test_baseline_in_the_repo_is_a_report():
    summary = ai_eval.load_summary(Path(__file__).parent.parent.parent / "fixtures" / "ai_eval" / "baseline.json")
    assert summary["steps"] > 0 and summary["model"]

"""AI completion wiring on every real workflow, without a model.

A stub replies with the step's own generated code, which already has the right
shape. So every step the AI works on must reach the model (nothing skipped for
wiring) and a well-formed reply must pass the checks (nothing failed). This
guards the inputs/outputs the generator records and the step's own variable.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from a2d.advisor.ai_eval import run_eval

PACKT = sorted((Path(__file__).parent.parent / "fixtures" / "packt").glob("*.yxmd"))


class EchoClient:
    model_name = "echo"

    def chat(self, messages, *, max_tokens: int = 4000) -> str:
        prompt = messages[-1].content
        body = prompt.split("The step's code as generated:\n", 1)[1]
        return body.split("\n\nThe reviewer's note", 1)[0].split("\n\nReply with the code", 1)[0]


@pytest.fixture(autouse=True)
def _quiet():
    logging.disable(logging.WARNING)
    yield
    logging.disable(logging.NOTSET)


def test_every_step_reaches_the_model_and_a_well_formed_reply_passes():
    report = run_eval(PACKT, EchoClient())
    summary = report.summary()
    bad = [(s.workflow, s.node_id, s.tool_type, s.status, s.reason) for s in report.steps if s.status != "completed"]
    assert bad == []
    assert summary["steps"] >= 150 and summary["workflows"] >= 35, summary

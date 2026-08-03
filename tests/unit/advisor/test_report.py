"""Tests for the Markdown suggestions report and the grounded chat.

The load-bearing test here is
:meth:`TestNeverModifiesGeneratedCode.test_generated_files_are_byte_identical` —
the product rule is that an advisory model never changes converted output.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from a2d.advisor.chat import MigrationChat
from a2d.advisor.context import build_migration_context
from a2d.advisor.llm_client import ENV_ENDPOINT, ChatMessage, LLMRequestError
from a2d.advisor.report import CLARIFYING_QUESTIONS, render_report
from a2d.config import ConversionConfig, OutputFormat
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import ReadNode, UnsupportedNode, WriteNode
from a2d.pipeline import ConversionPipeline

WORKFLOWS = Path(__file__).parent.parent.parent / "fixtures" / "workflows"


class FakeClient:
    """Deterministic stand-in for a configured FMAPI endpoint."""

    def __init__(self, reply: str = "Use a built-in function instead.") -> None:
        self.reply = reply
        self.calls: list[list[ChatMessage]] = []

    def chat(self, messages: list[ChatMessage], *, max_tokens: int = 1500) -> str:
        self.calls.append(messages)
        return self.reply


class FailingClient:
    def chat(self, messages, *, max_tokens: int = 1500) -> str:
        raise LLMRequestError("endpoint exploded")


def _gap_dag() -> WorkflowDAG:
    dag = WorkflowDAG()
    dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
    dag.add_node(
        UnsupportedNode(
            node_id=2,
            original_tool_type="Message",
            original_configuration={"MessageText": "hi"},
            unsupported_reason="No converter for tool type: Message",
        )
    )
    dag.add_node(WriteNode(node_id=3, original_tool_type="Output"))
    dag.add_edge(1, 2)
    dag.add_edge(2, 3)
    return dag


def _ctx(**kwargs):
    return build_migration_context(_gap_dag(), workflow_name="wf", output_format="pyspark", **kwargs)


class TestReportHeader:
    def test_marks_itself_as_ai_generated_and_unverified(self):
        md = render_report(_ctx(), FakeClient())
        assert "AI-generated advisory notes" in md
        assert "not** part of the generated code" in md
        assert "no generated file was modified" in md

    def test_reports_deterministic_facts(self):
        md = render_report(_ctx(coverage=66.6), FakeClient())
        assert "66.6%" in md
        assert "3 nodes, 2 edges" in md
        assert "Gaps found: 1" in md


class TestOptInDegradation:
    def test_without_client_report_still_lists_gaps(self):
        md = render_report(_ctx(), None)
        assert "Suggestions unavailable (AI is opt-in)" in md
        assert ENV_ENDPOINT in md
        # The deterministic gap is still reported.
        assert "Message has no deterministic converter" in md
        assert "**Suggested approach**" not in md

    def test_with_client_includes_suggestions(self):
        md = render_report(_ctx(), FakeClient("Do X instead."))
        assert "**Suggested approach**" in md
        assert "Do X instead." in md

    def test_no_gaps_short_circuits(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
        ctx = build_migration_context(dag, workflow_name="clean", output_format="pyspark")
        md = render_report(ctx, FakeClient())
        assert "No gaps found" in md
        assert "**Suggested approach**" not in md

    def test_failing_endpoint_degrades_per_gap(self):
        md = render_report(_ctx(), FailingClient())
        assert "Suggestion unavailable" in md
        # The document is still produced with its facts intact.
        assert "Message has no deterministic converter" in md


class TestPromptGrounding:
    def test_original_configuration_reaches_the_model(self):
        client = FakeClient()
        render_report(_ctx(), client)
        user_turn = client.calls[0][1].content
        assert "MessageText" in user_turn
        assert "Message" in user_turn

    def test_system_prompt_forbids_editing_code(self):
        client = FakeClient()
        render_report(_ctx(), client)
        system_turn = client.calls[0][0].content
        assert "never into the generated code" in system_turn

    def test_answers_are_recorded_in_the_document(self):
        md = render_report(_ctx(), FakeClient(), answers={"Which catalog?": "main.sales"})
        assert "Context you provided" in md
        assert "main.sales" in md


class TestChat:
    def test_opening_summary_needs_no_model_call(self):
        client = FakeClient()
        chat = MigrationChat(context=_ctx(), client=client)
        summary = chat.opening_summary()
        assert "wf" in summary
        assert "never modif" in summary
        assert client.calls == []  # deterministic

    def test_ask_records_history(self):
        chat = MigrationChat(context=_ctx(), client=FakeClient("because X"))
        assert chat.ask("why?") == "because X"
        assert [m.role for m in chat.history] == ["user", "assistant"]

    def test_facts_are_sent_as_system_grounding(self):
        client = FakeClient()
        chat = MigrationChat(context=_ctx(), client=client)
        chat.ask("what failed?")
        system_turn = client.calls[0][0].content
        assert "Migration facts (authoritative)" in system_turn
        assert "Message" in system_turn

    def test_failed_turn_does_not_poison_history(self):
        chat = MigrationChat(context=_ctx(), client=FailingClient())
        with pytest.raises(LLMRequestError):
            chat.ask("hello")
        assert chat.history == []

    def test_clarifying_questions_offered(self):
        chat = MigrationChat(context=_ctx(), client=FakeClient())
        assert chat.clarifying_questions() == CLARIFYING_QUESTIONS
        assert len(CLARIFYING_QUESTIONS) >= 2

    def test_generate_report_returns_markdown(self):
        chat = MigrationChat(context=_ctx(), client=FakeClient())
        md = chat.generate_report({"Which catalog?": "main"})
        assert md.startswith("# Migration suggestions")
        assert "main" in md


class TestNeverModifiesGeneratedCode:
    def test_generated_files_are_byte_identical(self, tmp_path):
        """The product invariant: advisory output cannot change converted code."""
        wf = WORKFLOWS / "message_passthrough.yxmd"
        cfg = ConversionConfig(input_path=wf, output_dir=tmp_path, output_format=OutputFormat.PYSPARK)
        result = ConversionPipeline(cfg).convert(wf)
        before = {f.filename: f.content for f in result.output.files}

        code = "\n".join(f.content for f in result.output.files)
        ctx = build_migration_context(
            result.dag,
            workflow_name=wf.stem,
            output_format="pyspark",
            format_warnings=list(result.output.warnings),
            generated_code=code,
        )
        chat = MigrationChat(context=ctx, client=FakeClient())
        chat.ask("please rewrite the code")
        chat.generate_report()
        render_report(ctx, FakeClient())

        after = {f.filename: f.content for f in result.output.files}
        assert after == before

    def test_report_is_a_separate_document_not_a_generated_file(self):
        """The report is returned as text; it is never added to output.files."""
        wf = WORKFLOWS / "message_passthrough.yxmd"
        cfg = ConversionConfig(input_path=wf, output_dir=Path("/tmp/unused"), output_format=OutputFormat.PYSPARK)
        result = ConversionPipeline(cfg).convert(wf)
        filenames_before = [f.filename for f in result.output.files]

        ctx = build_migration_context(result.dag, workflow_name=wf.stem, output_format="pyspark")
        md = render_report(ctx, FakeClient())

        assert isinstance(md, str)
        assert [f.filename for f in result.output.files] == filenames_before
        assert all(md not in f.content for f in result.output.files)

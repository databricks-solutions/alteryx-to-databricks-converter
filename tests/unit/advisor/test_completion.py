"""Tests for AI completion — the optional, marked copy of a converted notebook.

The load-bearing rules: only cells the converter couldn't finish are touched,
everything else is byte-identical, every AI-written cell is marked, and a reply
that doesn't parse (or breaks the variable wiring) is rejected rather than
spliced in.
"""

from __future__ import annotations

from pathlib import Path

from a2d.advisor.completion import (
    AI_BEGIN,
    AI_END,
    CELL_SEPARATOR,
    complete_notebook,
    completed_filename,
    split_cells,
)
from a2d.advisor.context import build_migration_context
from a2d.advisor.llm_client import ChatMessage, LLMRequestError
from a2d.config import ConversionConfig, OutputFormat
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import ReadNode, UnsupportedNode, WriteNode
from a2d.pipeline import ConversionPipeline

WORKFLOWS = Path(__file__).parent.parent.parent / "fixtures" / "workflows"

GOOD_REPLY = '# Step 2: Message\nprint("orders loaded")\ndf_1 = df_1.filter(F.col("id").isNotNull())'


class FakeClient:
    def __init__(self, reply: str = GOOD_REPLY) -> None:
        self.reply = reply
        self.calls: list[list[ChatMessage]] = []

    def chat(self, messages: list[ChatMessage], *, max_tokens: int = 4000) -> str:
        self.calls.append(messages)
        return self.reply


class FailingClient:
    def chat(self, messages, *, max_tokens: int = 4000) -> str:
        raise LLMRequestError("endpoint down")


def _convert(name: str):
    path = WORKFLOWS / name
    result = ConversionPipeline(ConversionConfig(input_path=path, output_format=OutputFormat.PYSPARK)).convert(path)
    notebook = result.output.files[0].content
    ctx = build_migration_context(
        result.dag,
        workflow_name=path.stem,
        output_format="pyspark",
        format_warnings=list(result.output.warnings),
        generated_code=notebook,
    )
    return result, notebook, ctx


class TestOnlyGapCellsChange:
    def test_untouched_cells_are_byte_identical(self):
        result, notebook, ctx = _convert("message_passthrough.yxmd")
        out = complete_notebook(notebook, ctx, FakeClient(), result.dag)

        original = split_cells(notebook)
        completed = split_cells(out.content)
        # One banner cell was inserted after the "notebook source" line.
        assert completed[0] == original[0]
        assert len(completed) == len(original) + 1
        rest = completed[2:]
        changed = [i for i, (a, b) in enumerate(zip(original[1:], rest, strict=True)) if a != b]
        assert len(changed) == 1  # only the Message cell
        assert out.completed == 1

    def test_ai_cells_are_marked_and_file_has_banner(self):
        result, notebook, ctx = _convert("message_passthrough.yxmd")
        out = complete_notebook(notebook, ctx, FakeClient(), result.dag)
        assert out.content.startswith("# Databricks notebook source")
        assert "AI-COMPLETED COPY - NOT DETERMINISTIC" in out.content
        assert out.content.count(AI_BEGIN) == 1
        assert out.content.count(AI_END) == 1
        assert out.filename == "message_passthrough.ai-completed.py"
        assert out.filename != result.output.files[0].filename

    def test_deterministic_output_is_unchanged(self):
        result, notebook, ctx = _convert("message_passthrough.yxmd")
        before = result.output.files[0].content
        complete_notebook(notebook, ctx, FakeClient(), result.dag)
        assert result.output.files[0].content == before

    def test_pass_through_is_told_to_rebind_its_input(self):
        result, notebook, ctx = _convert("message_passthrough.yxmd")
        client = FakeClient()
        complete_notebook(notebook, ctx, client, result.dag)
        prompt = client.calls[0][1].content
        assert "assign your result back to df_1" in prompt

    def test_no_gaps_means_no_model_calls(self):
        result, notebook, ctx = _convert("simple_filter.yxmd")
        client = FakeClient()
        out = complete_notebook(notebook, ctx, client, result.dag)
        if not out.cells:
            assert client.calls == []
            assert AI_BEGIN not in out.content


class TestRejectsBadReplies:
    def test_reply_that_does_not_parse_keeps_deterministic_cell(self):
        result, notebook, ctx = _convert("message_passthrough.yxmd")
        out = complete_notebook(notebook, ctx, FakeClient("df_1 = = broken("), result.dag)
        assert out.completed == 0
        assert out.cells[0].status == "failed"
        assert "not valid Python" in out.cells[0].reason
        assert AI_BEGIN not in out.content
        assert out.cells[0].after == out.cells[0].before

    def test_reply_that_drops_the_wired_variable_is_rejected(self):
        result, notebook, ctx = _convert("message_passthrough.yxmd")
        out = complete_notebook(notebook, ctx, FakeClient("df_other = spark.range(1)"), result.dag)
        assert out.cells[0].status == "failed"
        assert "df_1" in out.cells[0].reason

    def test_markdown_fences_are_stripped(self):
        result, notebook, ctx = _convert("message_passthrough.yxmd")
        out = complete_notebook(notebook, ctx, FakeClient(f"```python\n{GOOD_REPLY}\n```"), result.dag)
        assert out.completed == 1
        assert "```" not in out.content

    def test_endpoint_error_is_reported_not_raised(self):
        result, notebook, ctx = _convert("message_passthrough.yxmd")
        out = complete_notebook(notebook, ctx, FailingClient(), result.dag)
        assert out.cells[0].status == "failed"
        assert "endpoint" in out.cells[0].reason
        assert AI_BEGIN not in out.content


class TestFanOutIsSkipped:
    def test_input_shared_with_another_step_is_not_rebound(self):
        # 1 -> 2 (unsupported) -> 3, and 1 -> 4: rebinding df_1 inside step 2
        # would silently change what step 4 reads.
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
        dag.add_node(UnsupportedNode(node_id=2, original_tool_type="Message", unsupported_reason="no converter"))
        dag.add_node(WriteNode(node_id=3, original_tool_type="Output"))
        dag.add_node(WriteNode(node_id=4, original_tool_type="Output"))
        dag.add_edge(1, 2)
        dag.add_edge(2, 3)
        dag.add_edge(1, 4)
        notebook = CELL_SEPARATOR.join(
            [
                "# Databricks notebook source\n",
                "# Step 1: Input\ndf_1 = spark.table('a')",
                "# Step 2: Message\n# Message: manual conversion required",
                "# Step 3: Output\ndf_1.write.saveAsTable('b')",
                "# Step 4: Output\ndf_1.write.saveAsTable('c')",
            ]
        )
        ctx = build_migration_context(dag, workflow_name="wf", output_format="pyspark", generated_code=notebook)
        client = FakeClient()
        out = complete_notebook(notebook, ctx, client, dag)
        step2 = next(c for c in out.cells if c.node_id == 2)
        assert step2.status == "skipped"
        assert "feeds other steps" in step2.reason
        assert client.calls == []


def test_completed_filename_never_collides_with_the_notebook():
    assert completed_filename("sales") == "sales.ai-completed.py"

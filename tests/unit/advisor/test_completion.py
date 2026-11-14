"""Tests for AI completion: the optional, marked copy of a converted notebook.

The rules these pin down:
- only steps the converter couldn't finish are sent to the model, and which cell
  is which step comes from the generator's map, never from comment text;
- every other cell is byte-identical, and every AI-written line sits between the
  markers, under the step's own (unchanged) header;
- a reply is rejected (the step keeps its deterministic code) when it doesn't
  parse, doesn't wire the right variable, reassigns another step's DataFrame,
  reads one that isn't defined yet, drops a write, forges markers, or does
  something a completed step isn't allowed to (shell out, delete, destructive SQL);
- endpoint failures, time limits and the per-run cap are reported per step, not raised.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from a2d.advisor.completion import (
    AI_BEGIN,
    AI_END,
    CELL_SEPARATOR,
    MAX_CELLS,
    CompletionUnavailableError,
    completable_steps,
    complete_notebook,
    completed_filename,
    redact_secrets,
    split_cells,
)
from a2d.advisor.context import build_migration_context
from a2d.advisor.llm_client import ChatMessage
from a2d.config import ConversionConfig, OutputFormat
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import ReadNode, SortNode, UnsupportedNode, WriteNode
from a2d.pipeline import ConversionPipeline

WORKFLOWS = Path(__file__).parent.parent.parent / "fixtures" / "workflows"


class FakeClient:
    """Replies with ``reply`` (or ``reply(prompt)``) and records every prompt."""

    def __init__(self, reply="df_1 = df_1.dropDuplicates()") -> None:
        self.reply = reply
        self.prompts: list[str] = []

    def chat(self, messages: list[ChatMessage], *, max_tokens: int = 4000) -> str:
        prompt = messages[-1].content
        self.prompts.append(prompt)
        return self.reply(prompt) if callable(self.reply) else self.reply


class BrokenClient:
    def chat(self, messages, *, max_tokens: int = 4000) -> str:
        raise ConnectionResetError("connection reset by peer")


def _convert(name: str):
    path = WORKFLOWS / name
    result = ConversionPipeline(ConversionConfig(input_path=path, output_format=OutputFormat.PYSPARK)).convert(path)
    nb = result.output.files[0]
    ctx = build_migration_context(
        result.dag,
        workflow_name=path.stem,
        output_format="pyspark",
        format_warnings=list(result.output.warnings),
        generated_code=nb.content,
    )
    return result, nb.content, ctx, result.output.cell_nodes[nb.filename]


def _notebook(*node_cells: tuple[int, str]) -> tuple[str, list[int | None]]:
    """A synthetic notebook in the generator's layout, with its cell map."""
    cells = ["# Databricks notebook source\n", "# header", "from pyspark.sql import functions as F"]
    cells += [text for _, text in node_cells] + ["# footer\n"]
    return CELL_SEPARATOR.join(cells), [None, None, None, *(nid for nid, _ in node_cells), None]


def _complete(dag, cells, reply, **kw):
    notebook, cell_nodes = _notebook(*cells)
    ctx = build_migration_context(dag, workflow_name="wf", output_format="pyspark", generated_code=notebook)
    client = FakeClient(reply)
    return complete_notebook(notebook, ctx, client, dag, cell_nodes, **kw), client, notebook


def _chain_with_message() -> WorkflowDAG:
    """1 read -> 2 Message (unsupported) -> 3 write."""
    dag = WorkflowDAG()
    dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
    dag.add_node(UnsupportedNode(node_id=2, original_tool_type="Message", unsupported_reason="no converter"))
    dag.add_node(WriteNode(node_id=3, original_tool_type="Output"))
    dag.add_edge(1, 2)
    dag.add_edge(2, 3)
    return dag


CHAIN = [
    (1, "# Step 1: Input\ndf_1 = spark.table('main.default.orders')"),
    (2, "# Step 2: Message\n# Message: manual conversion required"),
    (3, "# Step 3: Output\ndf_1.write.mode('overwrite').saveAsTable('main.default.orders_out')"),
]


class TestOnlyStepsNeedingWorkChange:
    def test_untouched_cells_are_byte_identical(self):
        result, notebook, ctx, cell_nodes = _convert("message_passthrough.yxmd")
        out = complete_notebook(notebook, ctx, FakeClient("df_2 = df_1.dropDuplicates()"), result.dag, cell_nodes)
        original, completed = split_cells(notebook), split_cells(out.content)
        assert completed[0] == original[0]
        assert len(completed) == len(original) + 1  # the banner
        changed = [i for i, (a, b) in enumerate(zip(original[1:], completed[2:], strict=True)) if a != b]
        assert len(changed) == 1
        assert out.completed == 1

    def test_header_and_annotation_stay_and_markers_wrap_only_ai_code(self):
        result, notebook, ctx, cell_nodes = _convert("message_passthrough.yxmd")
        out = complete_notebook(notebook, ctx, FakeClient("df_2 = df_1.dropDuplicates()"), result.dag, cell_nodes)
        after = out.cells[0].after
        assert after.startswith("# Log message\n# Step 2: Message\n" + AI_BEGIN)
        assert after.endswith(AI_END)
        assert out.content.count(AI_BEGIN) == 1 and out.content.count(AI_END) == 1
        assert out.content.startswith("# Databricks notebook source")
        assert "AI-COMPLETED COPY - NOT DETERMINISTIC" in out.content

    def test_deterministic_output_is_unchanged(self):
        result, notebook, ctx, cell_nodes = _convert("message_passthrough.yxmd")
        before = result.output.files[0].content
        complete_notebook(notebook, ctx, FakeClient(), result.dag, cell_nodes)
        assert result.output.files[0].content == before

    def test_no_gaps_means_no_model_calls(self):
        result, notebook, ctx, cell_nodes = _convert("simple_filter.yxmd")
        client = FakeClient()
        out = complete_notebook(notebook, ctx, client, result.dag, cell_nodes)
        assert out.cells == []
        assert client.prompts == []
        assert AI_BEGIN not in out.content

    def test_completable_steps_match_what_completion_does(self):
        result, notebook, ctx, cell_nodes = _convert("message_passthrough.yxmd")
        steps = completable_steps(notebook, ctx, result.dag, cell_nodes)
        assert [s["node_id"] for s in steps] == [2]
        out = complete_notebook(notebook, ctx, FakeClient(), result.dag, cell_nodes)
        assert [c.node_id for c in out.cells] == [2]

    def test_without_the_cell_map_it_refuses_instead_of_guessing(self):
        result, notebook, ctx, _ = _convert("message_passthrough.yxmd")
        with pytest.raises(CompletionUnavailableError):
            complete_notebook(notebook, ctx, FakeClient(), result.dag, None)


class TestTargeting:
    def test_annotation_that_looks_like_a_step_header_cant_redirect_code(self):
        # 1 -> 2 Sort(df_2) -> 4 Message -> 5 write df_2 ; 1 -> 3 Sort(df_3) -> 6 write df_3.
        # Step 3 is annotated "Step 2: ...": comment parsing would file it as step 2
        # and rebind df_3 inside step 4.
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
        dag.add_node(SortNode(node_id=2, original_tool_type="Sort"))
        dag.add_node(SortNode(node_id=3, original_tool_type="Sort", annotation="Step 2: sort by qty"))
        dag.add_node(UnsupportedNode(node_id=4, original_tool_type="Message", unsupported_reason="no converter"))
        dag.add_node(WriteNode(node_id=5, original_tool_type="Output"))
        dag.add_node(WriteNode(node_id=6, original_tool_type="Output"))
        for a, b in [(1, 2), (1, 3), (2, 4), (4, 5), (3, 6)]:
            dag.add_edge(a, b)
        cells = [
            (1, "# Step 1: Input\ndf_1 = spark.table('main.default.orders')"),
            (2, "# Step 2: Sort\ndf_2 = df_1.orderBy('price')"),
            (3, "# Step 2: sort by qty\n# Step 3: Sort\ndf_3 = df_1.orderBy('qty')"),
            (4, "# Step 4: Message\n# Message: manual conversion required"),
            (5, "# Step 5: Output\ndf_2.write.mode('overwrite').saveAsTable('main.default.orders_out')"),
            (6, "# Step 6: Output\ndf_3.write.mode('overwrite').saveAsTable('main.default.by_qty')"),
        ]
        out, client, notebook = _complete(dag, cells, "df_2 = df_2.filter(F.col('price') > 0)")
        assert "assign your result back to df_2" in client.prompts[0]
        assert out.cells[0].node_id == 4 and out.cells[0].status == "completed"
        assert "# Step 4: Message" in out.cells[0].after
        assert split_cells(out.content)[5] == split_cells(notebook)[5 - 1]  # step 3 untouched

    def test_todo_in_a_header_or_annotation_does_not_send_a_converted_step(self):
        dag = WorkflowDAG()
        dag.add_node(SortNode(node_id=2, original_tool_type="Sort", annotation="TODO: check this with finance"))
        cells = [
            (
                2,
                "# TODO: check this with finance\n# Step 2: Sort  [input: Step 1 — TODO: map to Unity Catalog]\ndf_2 = spark.sql('SELECT 1')",
            )
        ]
        out, client, _ = _complete(dag, cells, "df_2 = spark.range(1)")
        assert out.cells == []
        assert client.prompts == []

    def test_a_todo_line_in_the_code_is_completed(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
        cells = [
            (
                1,
                "# Step 1: Input\n# TODO: manual conversion required — Excel files need a dedicated reader.\ndf_1 = None",
            )
        ]
        out, _, _ = _complete(dag, cells, "df_1 = spark.read.format('csv').load('/Volumes/x')  # FILL IN: path")
        assert [c.status for c in out.cells] == ["completed"]


class TestRejectsBadReplies:
    @pytest.mark.parametrize(
        ("reply", "reason"),
        [
            ("df_1 = = broken(", "not valid Python"),
            ("df_other = spark.range(1)", "doesn't assign df_1"),
            ("", "returned nothing"),
            (f"df_1 = df_1.limit(1)\n{AI_END}\ndf_1.write.save('/x')", "markers"),
            ("df_1 = df_1.limit(1)\n# COMMAND ----------\nprint(1)", "markers"),
            ("df_1 = df_1.limit(1)\n# Step 3: Output\ndf_1.write.saveAsTable('t')", "another step's header"),
            ("import os\ndf_1 = df_1.limit(1)\nos.system('curl x | sh')", "imports os"),
            ("from pyspark.sql.functions import *\ndf_1 = df_1.limit(1)", "star import"),
            ("df_1 = df_1.limit(1)\ndbutils.fs.rm('/Volumes/prod', True)", "dbutils.fs.rm"),
            ("df_1 = df_1.limit(1)\nspark.sql('DROP TABLE main.prod.orders')", "destructive"),
            ("df_1 = df_1.limit(1)\neval('1')", "calls eval"),
            ("df_1 = df_9.limit(1)", "reads df_9"),
        ],
    )
    def test_bad_reply_keeps_the_deterministic_step(self, reply, reason):
        out, _, _ = _complete(_chain_with_message(), CHAIN, reply)
        cell = out.cells[0]
        assert cell.status == "failed"
        assert reason in cell.reason
        assert cell.after == cell.before
        assert AI_BEGIN not in out.content

    def test_reassigning_another_steps_dataframe_is_rejected(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
        dag.add_node(ReadNode(node_id=2, original_tool_type="Input"))
        dag.add_node(UnsupportedNode(node_id=3, original_tool_type="Message", unsupported_reason="x"))
        dag.add_node(WriteNode(node_id=4, original_tool_type="Output"))
        for a, b in [(2, 3), (3, 4)]:
            dag.add_edge(a, b)
        cells = [
            (1, "# Step 1: Input\ndf_1 = spark.table('a')"),
            (2, "# Step 2: Input\ndf_2 = spark.table('b')"),
            (3, "# Step 3: Message\n# Message: manual conversion required"),
            (4, "# Step 4: Output\ndf_2.write.saveAsTable('c')"),
        ]
        out, _, _ = _complete(dag, cells, "df_2 = df_2.limit(5)\ndf_1 = df_1.limit(1)")
        assert out.cells[0].status == "failed"
        assert "reassigns df_1" in out.cells[0].reason

    def test_a_sink_must_keep_writing_to_the_same_place(self):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input"))
        dag.add_node(WriteNode(node_id=2, original_tool_type="Output"))
        dag.add_edge(1, 2)
        cells = [
            (1, "# Step 1: Input\ndf_1 = spark.table('a')"),
            (
                2,
                "# Step 2: Output\n# TODO: Excel write not supported natively in Databricks.\ndf_1.write.saveAsTable('main.default.target')",
            ),
        ]
        dropped, _, _ = _complete(dag, cells, "print('done')")
        assert dropped.cells[0].status == "failed" and "doesn't" in dropped.cells[0].reason
        moved, _, _ = _complete(dag, cells, "df_1.write.saveAsTable('main.prod.other')")
        assert moved.cells[0].status == "failed" and "main.default.target" in moved.cells[0].reason
        kept, _, _ = _complete(dag, cells, "df_1.write.format('delta').saveAsTable('main.default.target')")
        assert kept.cells[0].status == "completed"

    def test_markdown_fences_and_a_repeated_header_are_stripped(self):
        out, _, _ = _complete(_chain_with_message(), CHAIN, "```python\n# Step 2: Message\ndf_1 = df_1.limit(1)\n```")
        assert out.completed == 1
        assert "```" not in out.content
        assert out.cells[0].after.count("# Step 2:") == 1


class ScriptedClient:
    """Replies in turn from ``replies`` and keeps every conversation it was sent."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.conversations: list[list[ChatMessage]] = []

    def chat(self, messages: list[ChatMessage], *, max_tokens: int = 4000) -> str:
        self.conversations.append(list(messages))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _run_scripted(client, **kw):
    notebook, cell_nodes = _notebook(*CHAIN)
    dag = _chain_with_message()
    ctx = build_migration_context(dag, workflow_name="wf", output_format="pyspark", generated_code=notebook)
    return complete_notebook(notebook, ctx, client, dag, cell_nodes, **kw)


class TestRetryOnAFailedCheck:
    def test_a_good_first_reply_is_one_call(self):
        client = ScriptedClient("df_1 = df_1.limit(1)")
        out = _run_scripted(client)
        assert out.cells[0].status == "completed" and out.cells[0].attempts == 1
        assert len(client.conversations) == 1

    def test_a_failed_check_is_sent_back_once_with_the_reason(self):
        client = ScriptedClient("df_1 = df_9.limit(1)", "df_1 = df_1.limit(1)")
        out = _run_scripted(client)
        cell = out.cells[0]
        assert (cell.status, cell.attempts, cell.reason) == ("completed", 2, "")
        assert "df_1 = df_1.limit(1)" in cell.after and "df_9" not in cell.after
        retry = client.conversations[1]
        assert [m.role for m in retry] == ["system", "user", "assistant", "user"]
        assert retry[1].content == client.conversations[0][1].content  # same step prompt
        assert retry[2].content == "df_1 = df_9.limit(1)"
        assert "your code reads df_9, which isn't defined at this point" in retry[3].content

    def test_two_failed_replies_keep_the_converted_step(self):
        client = ScriptedClient("df_1 = = broken(", "import os\ndf_1 = df_1")
        out = _run_scripted(client)
        cell = out.cells[0]
        assert (cell.status, cell.attempts) == ("failed", 2)
        assert "imports os" in cell.reason and "also on the second try" in cell.reason
        assert cell.after == cell.before and AI_BEGIN not in out.content
        assert len(client.conversations) == 2  # never a third call

    def test_an_endpoint_error_is_not_retried(self):
        client = ScriptedClient(ConnectionResetError("connection reset by peer"))
        out = _run_scripted(client)
        assert out.cells[0].status == "failed" and "connection reset" in out.cells[0].reason
        assert len(client.conversations) == 1

    def test_an_endpoint_error_on_the_retry_keeps_the_first_reason(self):
        client = ScriptedClient("df_other = spark.range(1)", TimeoutError("read timed out"))
        out = _run_scripted(client)
        cell = out.cells[0]
        assert cell.status == "failed" and cell.attempts == 2
        assert "doesn't assign df_1" in cell.reason and "read timed out" in cell.reason

    def test_no_retry_past_the_deadline(self, monkeypatch):
        from a2d.advisor import completion

        clock = iter([0.0, 0.0, 0.0, 100.0, 100.0, 100.0])
        monkeypatch.setattr(completion.time, "monotonic", lambda: next(clock, 100.0))
        client = ScriptedClient("df_1 = df_9.limit(1)", "df_1 = df_1.limit(1)")
        out = _run_scripted(client, deadline=50.0)
        cell = out.cells[0]
        assert cell.status == "failed" and cell.attempts == 1
        assert "reads df_9" in cell.reason and "ran out of time before a second try" in cell.reason
        assert len(client.conversations) == 1

    def test_attempts_are_in_the_report(self):
        out = _run_scripted(ScriptedClient("df_1 = df_9", "df_1 = df_1"))
        assert out.to_dict()["cells"][0]["attempts"] == 2


class TestFailuresAreReportedNotRaised:
    def test_transport_error_marks_the_step_failed(self):
        notebook, cell_nodes = _notebook(*CHAIN)
        dag = _chain_with_message()
        ctx = build_migration_context(dag, workflow_name="wf", output_format="pyspark", generated_code=notebook)
        out = complete_notebook(notebook, ctx, BrokenClient(), dag, cell_nodes)
        assert out.cells[0].status == "failed"
        assert "connection reset" in out.cells[0].reason

    def test_past_the_deadline_steps_are_skipped(self):
        out, client, _ = _complete(_chain_with_message(), CHAIN, "df_1 = df_1.limit(1)", deadline=time.monotonic() - 1)
        assert out.cells[0].status == "skipped"
        assert client.prompts == []

    def test_steps_over_the_per_run_cap_are_skipped(self):
        dag = WorkflowDAG()
        cells = []
        for i in range(1, MAX_CELLS + 2):
            dag.add_node(UnsupportedNode(node_id=i, original_tool_type="Message", unsupported_reason="x"))
            cells.append((i, f"# Step {i}: Message\n# Message: manual conversion required"))
        out, client, _ = _complete(dag, cells, "print('n/a')")
        sent = {p for p in client.prompts if p.startswith("Workflow:")}  # first prompts, not retries
        assert len(sent) == MAX_CELLS
        assert [c.status for c in out.cells].count("skipped") == 1
        assert "limit" in out.cells[-1].reason


class TestPassThroughWiring:
    def test_pass_through_is_told_to_rebind_its_input(self):
        out, client, _ = _complete(_chain_with_message(), CHAIN, "df_1 = df_1.limit(1)")
        assert "assign your result back to df_1" in client.prompts[0]
        assert out.completed == 1

    def test_input_shared_with_another_step_is_not_rebound(self):
        dag = _chain_with_message()
        dag.add_node(WriteNode(node_id=4, original_tool_type="Output"))
        dag.add_edge(1, 4)
        cells = [*CHAIN, (4, "# Step 4: Output\ndf_1.write.saveAsTable('main.default.copy')")]
        out, client, _ = _complete(dag, cells, "df_1 = df_1.limit(1)")
        step2 = next(c for c in out.cells if c.node_id == 2)
        assert step2.status == "skipped"
        assert "feeds other steps" in step2.reason
        assert client.prompts == []


class TestWhatLeavesForTheModel:
    def test_credentials_are_masked_in_prompts(self):
        dag = _chain_with_message()
        dag.get_node(2).original_configuration = {"Connection": "DSN=x;UID=me;PWD=hunter2", "password": "s3cret"}
        _, client, _ = _complete(dag, CHAIN, "df_1 = df_1.limit(1)")
        assert "hunter2" not in client.prompts[0]
        assert "s3cret" not in client.prompts[0]

    def test_redact_secrets(self):
        assert redact_secrets("DSN=a;PWD=hunter2;UID=me") == "DSN=a;PWD=***;UID=me"
        assert "abc123" not in redact_secrets('token: "abc123"')


def test_completed_filename_never_collides_with_the_notebook():
    assert completed_filename("sales") == "sales.ai-completed.py"
    assert "\n" not in completed_filename("evil\nname")


class TestRealInputsAndColumns:
    """Steps get their own output variable, and the model is told every input by
    its Alteryx anchor, with columns when the workflow saved them."""

    @staticmethod
    def _generate(dag: WorkflowDAG):
        from a2d.generators.pyspark import PySparkGenerator

        out = PySparkGenerator(ConversionConfig(output_format=OutputFormat.PYSPARK)).generate(dag, "wf")
        nb = out.files[0]
        ctx = build_migration_context(dag, workflow_name="wf", output_format="pyspark", generated_code=nb.content)
        return nb.content, ctx, out.cell_nodes[nb.filename], out.node_io[nb.filename]

    def test_unsupported_step_assigns_its_own_variable(self):
        dag = _chain_with_message()
        notebook, _ctx, _cells, io = self._generate(dag)
        assert "df_2 = df_1  # passes its input through" in notebook
        assert io[2] == {"inputs": {"Input": "df_1"}, "outputs": {"Output": "df_2"}}
        assert io[3]["inputs"] == {"Input": "df_2"}

    def test_source_step_without_converter_is_a_placeholder(self):
        dag = WorkflowDAG()
        dag.add_node(UnsupportedNode(node_id=5, original_tool_type="MongoInput", unsupported_reason="no converter"))
        notebook, *_ = self._generate(dag)
        assert "df_5 = None  # PLACEHOLDER" in notebook

    def test_step_whose_input_feeds_others_is_now_sent(self):
        """Before, a pass-through couldn't be completed when its input fed another
        step too (its result would have overwritten that step's input)."""
        dag = _chain_with_message()
        dag.add_node(WriteNode(node_id=4, original_tool_type="Output"))
        dag.add_edge(1, 4)
        notebook, ctx, cells, io = self._generate(dag)
        client = FakeClient("df_2 = df_1.dropDuplicates()")
        out = complete_notebook(notebook, ctx, client, dag, cells, node_io=io)
        assert [(c.node_id, c.status) for c in out.cells] == [(2, "completed")]
        assert "df_1.write" in out.content or "saveAsTable" in out.content  # step 4 untouched

    def test_prompt_lists_inputs_by_anchor_with_columns(self):
        path = WORKFLOWS.parent / "packt" / "CH04-R02-Fixing_CrossTabRenames.yxmd"
        result = ConversionPipeline(ConversionConfig(input_path=path, output_format=OutputFormat.PYSPARK)).convert(path)
        nb = result.output.files[0]
        ctx = build_migration_context(
            result.dag, workflow_name=path.stem, output_format="pyspark", generated_code=nb.content
        )
        client = FakeClient("df_14 = df_2")
        complete_notebook(
            nb.content,
            ctx,
            client,
            result.dag,
            result.output.cell_nodes[nb.filename],
            node_io=result.output.node_io[nb.filename],
        )
        prompt = next(p for p in client.prompts if "Alteryx node id: 14" in p)
        assert "- df_2 (Alteryx input Targets); columns: Year (Double), Month (Double)" in prompt
        assert "(Alteryx input Source)" in prompt  # the rename mapping input is named, not hidden
        assert (
            "columns it should have (from the workflow's saved metadata): Year (Double), Month (Double), 7.50" in prompt
        )

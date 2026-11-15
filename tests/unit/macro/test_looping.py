"""Batch and iterative macros: converted to a function and a loop.

Real Packt workflows (tests/fixtures/looping_macros) pin what the converter
produces for each kind of setting a macro takes; small synthetic macros pin the
cases that must stay a TODO instead of guessing.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

from a2d.advisor.completion import _df_assigned, completable_steps
from a2d.advisor.context import build_migration_context
from a2d.analyzer.coverage import CoverageAnalyzer
from a2d.config import ConversionConfig, OutputFormat
from a2d.generators.looping_macro_code import substitute
from a2d.ir.nodes import LoopingMacroNode, UnsupportedNode
from a2d.macro.looping import ITERATION_SENTINEL
from a2d.pipeline import ConversionPipeline

FIXTURES = Path(__file__).parents[2] / "fixtures" / "looping_macros"
GROUP_BY = FIXTURES / "advanced_ch1" / "Batch Macros (Group By).yxmd"
ITERATIVE = FIXTURES / "advanced_ch1" / "Iterative Macros.yxmd"
READ_EACH_FILE = FIXTURES / "cookbook_ch1_r3" / "CH01-R03-DifferentSchema.yxmd"
PAGED_API = FIXTURES / "cookbook_ch11_r3" / "CH11R03-Paged Results +Iterative Macro.yxmd"
FILTER_BY_DATE = FIXTURES / "engineering_ch10" / "User Gallery Modification.yxmd"
ALL = [GROUP_BY, ITERATIVE, READ_EACH_FILE, PAGED_API, FILTER_BY_DATE]


def _convert(path: Path, fmt: OutputFormat = OutputFormat.PYSPARK):
    return ConversionPipeline(ConversionConfig(input_path=path, output_format=fmt, expand_macros=True)).convert(path)


def _loop(result, node_id: int) -> LoopingMacroNode:
    node = result.dag.get_node(node_id)
    assert isinstance(node, LoopingMacroNode)
    return node


def _cell(result, node_id: int) -> str:
    nb = result.output.files[0]
    cells = nb.content.split("\n\n# COMMAND ----------\n\n")
    return next(c for c, nid in zip(cells, result.output.cell_nodes[nb.filename], strict=True) if nid == node_id)


class TestRealWorkflows:
    def test_batch_group_by_runs_per_control_value_on_matching_rows(self):
        result = _convert(GROUP_BY)
        node = _loop(result, 9)
        assert node.kind == "batch" and node.group_by == [("field1", "Input8", "field1")]
        cell = _cell(result, 9)
        assert "def macro_batch_groupby_macro_9(df_1000008):" in cell
        assert "df_1.filter(F.col('field1').eqNullSafe(F.lit(_row['field1'])))" in cell
        assert "for _i, _row in enumerate(df_2.collect())" in cell
        assert "unionByName(b, allowMissingColumns=True)" in cell

    def test_iterative_feeds_its_iteration_output_back(self):
        result = _convert(ITERATIVE)
        node = _loop(result, 27)
        assert (node.iteration_input, node.iteration_output, node.limit_behavior) == ("Input", "iterate", "Error")
        assert node.uses_iteration_number
        cell = _cell(result, 27)
        assert '"iteration": (F.lit(iteration) + 1)' in cell  # [Engine.IterationNumber]+1
        assert '(F.col("iteration") >= 10)' in cell  # the call's "Numeric Up Down (11)" = 10
        assert "for iteration in range(100):" in cell and "raise RuntimeError" in cell
        assert "_df_27_iter = _out['iterate'].localCheckpoint()" in cell
        # Both outputs are wired: the parent reads final and iterate.
        assert {"df_27_final", "df_27_iterate"} <= _df_assigned(cell)

    def test_a_control_value_in_a_filter_expression_becomes_a_parameter(self):
        result = _convert(FILTER_BY_DATE)
        node = _loop(result, 18)
        (param,) = node.params
        assert (param.question, param.control_field) == ("Control Parameter (5)", "Max_DateUpdated")
        cell = _cell(result, 18)
        assert 'F.col("DateUpdated") >= F.lit(p_control_parameter_5)' in cell
        assert "p_control_parameter_5=_text(_row['Max_DateUpdated'])" in cell

    def test_a_control_value_as_the_file_to_read(self):
        cell = _cell(_convert(READ_EACH_FILE), 6)
        assert "def macro_batchreadworksheets_6(p_control_parameter_2):" in cell
        assert "p_control_parameter_2=_text(_row['FullPath'])" in cell
        # The saved file's extension still picks the reader (Excel here, which needs work).
        assert "Excel files need a dedicated reader" in cell

    def test_a_question_referenced_as_hash_1(self):
        cell = _cell(_convert(PAGED_API), 36)
        assert 'F.replace(F.col("Endpoint"), F.lit("xxxx"), F.lit("1536"))' in cell  # Text Box (22) = 1536
        assert "#1" not in cell

    @pytest.mark.parametrize("path", ALL, ids=lambda p: p.stem)
    def test_no_placeholder_is_left_and_the_notebook_is_python(self, path):
        content = _convert(path).output.files[0].content
        ast.parse(content)
        assert "zza2dparam" not in content.lower() and ITERATION_SENTINEL not in content

    @pytest.mark.parametrize("path", ALL, ids=lambda p: p.stem)
    def test_coverage_counts_the_tools_inside_the_macro(self, path):
        result = _convert(path)
        report = CoverageAnalyzer().analyze_dag(result.dag)
        stats = result.output.stats
        assert (report.total_nodes, report.supported_nodes) == (stats["total_nodes"], stats["supported_nodes"])

    def test_an_unconverted_tool_inside_the_macro_counts_as_unconverted(self):
        report = CoverageAnalyzer().analyze_dag(_convert(FILTER_BY_DATE).dag)
        assert "MongoInput" in report.unsupported_types

    @pytest.mark.parametrize("fmt", [f for f in OutputFormat if f != OutputFormat.PYSPARK], ids=lambda f: f.value)
    def test_other_formats_point_to_the_pyspark_output(self, fmt):
        result = _convert(GROUP_BY, fmt)
        text = "\n".join(f.content for f in result.output.files)
        assert "batch macro batch_groupby_macro.yxmc" in text.lower()


class TestAiCompletion:
    def test_only_top_level_outputs_count_as_the_steps_variables(self):
        cell = _cell(_convert(GROUP_BY), 9)
        assert _df_assigned(cell) == {"df_9"}

    def test_a_macro_with_an_unconverted_tool_goes_to_the_model_with_its_config(self):
        result = _convert(FILTER_BY_DATE)
        nb = result.output.files[0]
        ctx = build_migration_context(
            result.dag, workflow_name="wf", output_format="pyspark", generated_code=nb.content
        )
        (gap,) = [g for g in ctx.gaps if g.node_id == 18]
        assert gap.tool_type == "Batch macro" and "MongoInput" in gap.detail
        assert any("MongoInput" in key for key in gap.original_configuration)
        steps = completable_steps(nb.content, ctx, result.dag, result.output.cell_nodes[nb.filename])
        assert 18 in [s["node_id"] for s in steps]


# ── settings that must stay a TODO ─────────────────────────────────────────


def _macro(action: str, expression: str = '[d] >= "2022-01-01"', question: str = "ControlParam") -> str:
    """MacroInput(1) -> Filter(2) -> MacroOutput(3); question 5 -> Action 6 -> Filter 2."""
    plugin = {
        "ControlParam": "AlteryxGuiToolkit.Questions.ControlParam.ControlParam",
        "TextBox": "AlteryxGuiToolkit.Questions.TextBox.QuestionTextBox",
    }[question]
    expression = expression.replace('"', "&quot;")
    nodes = [
        (1, "AlteryxBasePluginsGui.MacroInput.MacroInput", "<Name>In</Name>"),
        (2, "AlteryxBasePluginsGui.Filter.Filter", f"<Mode>Custom</Mode><Expression>{expression}</Expression>"),
        (3, "AlteryxBasePluginsGui.MacroOutput.MacroOutput", "<Name>Out</Name>"),
        (5, plugin, ""),
        (6, "AlteryxGuiToolkit.Action.Action", ""),
    ]
    xml_nodes = "".join(
        f'<Node ToolID="{i}"><GuiSettings Plugin="{p}"><Position x="0" y="0"/></GuiSettings>'
        f"<Properties><Configuration>{c}</Configuration></Properties></Node>"
        for i, p, c in nodes
    )
    conns = [
        (1, "Output", 2, "Input"),
        (2, "True", 3, "Input"),
        (5, "Question", 6, "Question"),
        (6, "Action", 2, "Action"),
    ]
    xml_conns = "".join(
        f'<Connection><Origin ToolID="{a}" Connection="{x}"/><Destination ToolID="{b}" Connection="{y}"/></Connection>'
        for a, x, b, y in conns
    )
    runtime = (
        f"<Actions>{action}</Actions>"
        f'<Questions><Question><Type>{question}</Type><Name>CP</Name><ToolId value="5"/></Question></Questions>'
        "<BatchMacro><OutputMode>AllSame</OutputMode></BatchMacro>"
    )
    return (
        '<?xml version="1.0"?><AlteryxDocument yxmdVer="2023.1">'
        f"<Nodes>{xml_nodes}</Nodes><Connections>{xml_conns}</Connections>"
        f"<Properties><RuntimeProperties>{runtime}</RuntimeProperties></Properties></AlteryxDocument>"
    )


def _update(replace: bool = True, text: str = "2022-01-01", mode: str = "Simple", kind: str = "UpdateValue") -> str:
    replace_xml = (
        f'<Replace value="{replace}"/><ReplaceText>{text}</ReplaceText>' if replace else '<Replace value="False"/>'
    )
    return (
        f'<NoCondition><Type>NoCondition</Type><True><Action><Type>{kind}</Type><ToolId value="6"/>'
        f"<Mode>{mode}</Mode>{replace_xml}<Destination>2/Expression</Destination></Action></True></NoCondition>"
    )


def _caller(values: str = '<Value name="ControlParams">CP=When</Value>') -> str:
    nodes = [
        (1, "AlteryxBasePluginsGui.TextInput.TextInput", ""),
        (4, "AlteryxBasePluginsGui.TextInput.TextInput", ""),
        (2, "AlteryxBasePluginsGui.BrowseV2.BrowseV2", ""),
    ]
    xml_nodes = "".join(
        f'<Node ToolID="{i}"><GuiSettings Plugin="{p}"><Position x="0" y="0"/></GuiSettings>'
        f"<Properties><Configuration>{c}</Configuration></Properties></Node>"
        for i, p, c in nodes
    )
    xml_nodes += (
        '<Node ToolID="10"><GuiSettings><Position x="0" y="0"/></GuiSettings>'
        f'<Properties><Configuration>{values}</Configuration></Properties><EngineSettings Macro="M.yxmc"/></Node>'
    )
    conns = [(1, "Output", 10, "In"), (4, "Output", 10, "Control"), (10, "Out", 2, "Input")]
    xml_conns = "".join(
        f'<Connection><Origin ToolID="{a}" Connection="{x}"/><Destination ToolID="{b}" Connection="{y}"/></Connection>'
        for a, x, b, y in conns
    )
    return (
        '<?xml version="1.0"?><AlteryxDocument yxmdVer="2023.1">'
        f"<Nodes>{xml_nodes}</Nodes><Connections>{xml_conns}</Connections></AlteryxDocument>"
    )


def _run(tmp_path, macro: str, caller: str | None = None):
    (tmp_path / "M.yxmc").write_text(macro)
    wf = tmp_path / "main.yxmd"
    wf.write_text(caller or _caller())
    result = _convert(wf)
    return _loop(result, 10), _cell(result, 10)


class TestSettingsThatStayATodo:
    def test_text_in_a_string_is_replaced(self, tmp_path):
        node, cell = _run(tmp_path, _macro(_update()))
        assert node.issues == [] and [p.var for p in node.params] == ["p_cp"]
        assert "F.lit(p_cp)" in cell and "def macro_m_10(df_1000001, p_cp):" in cell

    def test_text_outside_a_string_isnt_replaced(self, tmp_path):
        node, cell = _run(tmp_path, _macro(_update(text="100"), expression="[n] > 100"))
        assert node.params == []  # no parameter for a value that wasn't wired in
        assert "outside a string" in node.issues[0]
        assert "# TODO: CP writes the control value into the expression of tool 2 outside a string" in cell

    def test_a_whole_expression_from_the_control_isnt_replaced(self, tmp_path):
        node, _ = _run(tmp_path, _macro(_update(replace=False)))
        assert "outside a string" in node.issues[0]

    def test_a_formula_action_isnt_converted(self, tmp_path):
        node, _ = _run(tmp_path, _macro(_update(kind="UpdateValueFormula")))
        assert "an Action of type UpdateValueFormula" in node.issues[0]

    def test_a_conditional_action_isnt_converted(self, tmp_path):
        conditional = _update().replace("NoCondition", "Condition")
        node, _ = _run(tmp_path, _macro(conditional))
        assert "conditional Action" in node.issues[0]

    def test_a_credential_from_the_call_isnt_copied(self, tmp_path):
        macro = _macro(_update(replace=False), question="TextBox").replace("<Name>CP</Name>", "<Name>Password</Name>")
        node, cell = _run(tmp_path, macro, _caller('<Value name="Password">hunter2</Value>'))
        assert "hunter2" not in cell
        assert "looks like a credential" in node.issues[0]

    def test_a_value_from_the_call_is_written_in(self, tmp_path):
        macro = _macro(_update(), question="TextBox")
        node, cell = _run(tmp_path, macro, _caller('<Value name="CP">2023-06-30</Value>'))
        assert node.params == [] and "2023-06-30" in cell

    def test_no_control_input_is_a_todo(self, tmp_path):
        caller = _caller().replace(
            '<Connection><Origin ToolID="4" Connection="Output"/><Destination ToolID="10" Connection="Control"/></Connection>',
            "",
        )
        node, cell = _run(tmp_path, _macro(_update()), caller)
        assert "the call has no Control input" in node.issues
        assert "# TODO: the call has no Control input" in cell


_P = {0: "p_x"}


class TestSubstitute:
    def test_inside_a_string(self):
        out, left = substitute("F.lit('a zza2dparam0zz b')", _P, None)
        assert (out, left) == ("F.lit(('a ' + p_x + ' b'))", [])

    def test_the_whole_string(self):
        assert substitute('load("zza2dparam0zz")', _P, None) == ("load(p_x)", [])

    def test_a_file_suffix_goes_with_the_value(self):
        assert substitute('load("zza2dparam0zz.csv")', _P, None, {0: ".csv"}) == ("load(p_x)", [])

    def test_the_iteration_number(self):
        out, _ = substitute(f"x = {ITERATION_SENTINEL} + 1\ny = '{ITERATION_SENTINEL}'", {}, "iteration")
        assert out == "x = F.lit(iteration) + 1\ny = str(iteration)"

    def test_comments_read_as_the_parameter(self):
        assert substitute("# path: zza2dparam0zz", _P, None)[0] == "# path: p_x"

    def test_implicit_concatenation_is_left(self):
        out, left = substitute("x = 'a' 'zza2dparam0zz'", _P, None)
        assert out == "x = 'a' 'zza2dparam0zz'" and left

    @pytest.mark.skipif(sys.version_info < (3, 12), reason="f-strings tokenize as one STRING before 3.12")
    def test_an_f_string_is_left(self):
        _, left = substitute("x = f'{a}zza2dparam0zz'", _P, None)
        assert left

    def test_an_unknown_placeholder_is_left(self):
        _, left = substitute("x = 'zza2dparam7zz'", _P, None)
        assert left


def test_the_body_has_no_interface_tools():
    node = _loop(_convert(READ_EACH_FILE), 6)
    assert not [n for n in node.body.all_nodes() if isinstance(n, UnsupportedNode)]
    assert {type(n).__name__ for n in node.body.all_nodes()} == {"ReadNode", "MacroIONode"}

"""Generated code must stay valid when IR values contain hostile characters.

Real Alteryx workflows carry Windows paths, regex patterns and quoted field names.
Interpolating those into hand-written quotes produced genuinely broken output: the
Packt fixtures emitted ``dbutils.fs.ls('..\\DATA')``, where ``\\D`` is an invalid
escape — Python warned and the path silently meant something else.

The contract: every externally-sourced string goes through the generator's literal
renderer, and generated Python always compiles with no escape warnings.
"""

from __future__ import annotations

import warnings

import pytest

from a2d.config import ConversionConfig
from a2d.generators.dlt import DLTGenerator
from a2d.generators.pyspark import PySparkGenerator
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import DirectoryNode, ReadNode, RegExNode, TextToColumnsNode

# Values that break naive f-string interpolation. Each has bitten a real tool.
HOSTILE_VALUES = [
    pytest.param(r"..\DATA", id="windows-relative-path"),
    pytest.param(r"C:\Users\new\table", id="windows-path-with-n-and-t"),
    pytest.param(r"\\server\share\file.csv", id="unc-path"),
    pytest.param('has "double" quotes', id="double-quotes"),
    pytest.param("has 'single' quotes", id="single-quotes"),
    pytest.param("mixed \"and' quotes", id="mixed-quotes"),
    pytest.param("line\nbreak", id="newline"),
    pytest.param("tab\there", id="tab"),
    pytest.param(r"regex \d+\s*\w", id="regex-escapes"),
    pytest.param('triple"""quote', id="triple-quote"),
    pytest.param("unicode-café-日本", id="unicode"),
    pytest.param("trailing-backslash\\", id="trailing-backslash"),
]


def _compile_clean(code: str, name: str) -> list[str]:
    """Compile *code*, returning any escape/syntax warning messages raised."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        compile(code, name, "exec")
        return [str(w.message) for w in caught if "escape" in str(w.message).lower()]


def _all_python(output) -> str:
    return "\n".join(f.content for f in output.files if f.filename.endswith(".py"))


@pytest.fixture
def config() -> ConversionConfig:
    return ConversionConfig()


class TestLiteralRenderer:
    @pytest.mark.parametrize("value", HOSTILE_VALUES)
    def test_pyspark_literal_round_trips(self, value):
        """The rendered literal must evaluate back to the original string."""
        rendered = PySparkGenerator._lit(value)
        assert eval(rendered) == value  # evaluating our own generated literal

    @pytest.mark.parametrize("value", HOSTILE_VALUES)
    def test_dlt_literal_round_trips(self, value):
        rendered = DLTGenerator._lit(value)
        assert eval(rendered) == value  # evaluating our own generated literal

    @pytest.mark.parametrize("value", HOSTILE_VALUES)
    def test_rendered_literal_is_self_contained(self, value):
        """A value must never be able to escape its own literal."""
        rendered = PySparkGenerator._lit(value)
        # Valid on its own, as a complete expression.
        assert _compile_clean(f"x = {rendered}", "<lit>") == []


class TestDirectoryPathsSurviveGeneration:
    """The concrete Packt failure: a Windows path in a directory listing."""

    @pytest.mark.parametrize("path", [r"..\DATA", r"C:\new\temp", r"\\srv\share"])
    def test_windows_directory_path_compiles_cleanly(self, config, path):
        dag = WorkflowDAG()
        dag.add_node(DirectoryNode(node_id=1, original_tool_type="Directory", directory_path=path))

        output = PySparkGenerator(config).generate(dag)
        code = _all_python(output)

        assert _compile_clean(code, "gen.py") == [], f"invalid escape for path {path!r}"
        # The path is still present and correct after escaping.
        assert path in code or repr(path)[1:-1] in code

    def test_file_pattern_is_escaped(self, config):
        dag = WorkflowDAG()
        dag.add_node(
            DirectoryNode(
                node_id=1,
                original_tool_type="Directory",
                directory_path="/mnt/data",
                file_pattern=r"*\d.csv",
            )
        )
        output = PySparkGenerator(config).generate(dag)
        assert _compile_clean(_all_python(output), "gen.py") == []


class TestRegexPatternsSurviveGeneration:
    """Regex patterns are backslash-dense by definition."""

    @pytest.mark.parametrize("pattern", [r"\d+", r"\s*\w+", r"^\D{2,}$", r"a\\b"])
    def test_pyspark_regex_compiles_cleanly(self, config, pattern):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input", file_path="/d.csv", file_format="csv"))
        dag.add_node(
            RegExNode(
                node_id=2,
                original_tool_type="RegEx",
                field_name="col",
                expression=pattern,
                replacement="x",
            )
        )
        dag.add_edge(1, 2)

        output = PySparkGenerator(config).generate(dag)
        assert _compile_clean(_all_python(output), "gen.py") == []

    @pytest.mark.parametrize("pattern", [r"\d+", r"^\D{2,}$"])
    def test_dlt_regex_compiles_cleanly(self, config, pattern):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input", file_path="/d.csv", file_format="csv"))
        dag.add_node(
            RegExNode(
                node_id=2,
                original_tool_type="RegEx",
                field_name="col",
                expression=pattern,
                replacement="x",
            )
        )
        dag.add_edge(1, 2)

        output = DLTGenerator(config).generate(dag)
        assert _compile_clean(_all_python(output), "gen_dlt.py") == []

    def test_backslash_delimiter_compiles_cleanly(self, config):
        """A backslash delimiter in TextToColumns previously broke the split call."""
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input", file_path="/d.csv", file_format="csv"))
        dag.add_node(
            TextToColumnsNode(node_id=2, original_tool_type="TextToColumns", field_name="path", delimiter="\\")
        )
        dag.add_edge(1, 2)

        for gen in (PySparkGenerator(config), DLTGenerator(config)):
            output = gen.generate(dag)
            assert _compile_clean(_all_python(output), "gen.py") == []


class TestPacktFixturesCompileWithoutWarnings:
    """Regression guard for the fixtures that actually surfaced this."""

    @pytest.mark.parametrize(
        "fixture_name",
        [
            "CH12-R03-_Blob_Input_-_Using_Web_Python.yxmd",
            "CH1-R05-Determine_which_file_to_process_-_Plus_CUSTOM_LOG.yxmd",
        ],
    )
    def test_no_invalid_escape_in_generated_python(self, config, fixture_name):
        from pathlib import Path

        from a2d.pipeline import ConversionPipeline

        fixture = Path(__file__).parent.parent.parent / "fixtures" / "packt" / fixture_name
        if not fixture.exists():
            pytest.skip(f"fixture {fixture_name} not present")

        result = ConversionPipeline(ConversionConfig(input_path=fixture)).convert(fixture)
        for generated in result.output.files:
            if generated.filename.endswith(".py"):
                assert _compile_clean(generated.content, generated.filename) == [], (
                    f"{generated.filename} still emits an invalid escape sequence"
                )

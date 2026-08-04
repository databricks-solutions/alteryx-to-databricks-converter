"""Generators must refuse to emit code for multi-input nodes missing an input.

Previously each generator substituted a placeholder identifier (``MISSING_RIGHT``,
``dlt.read("MISSING")``) for an unconnected join side. The conversion reported
success and the defect only surfaced much later at runtime as a confusing
"table not found" / ``NameError``, far from its cause.

Silent wrong output is the worst failure mode for this tool, so the contract is:
no placeholder identifiers, an explicit warning naming the missing side, and
generated code that cannot be mistaken for working code.
"""

from __future__ import annotations

import pytest

from a2d.config import ConversionConfig
from a2d.generators.dlt import DLTGenerator
from a2d.generators.pyspark import PySparkGenerator
from a2d.generators.sql import SQLGenerator
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import AppendFieldsNode, JoinKey, JoinNode, ReadNode

# Placeholder identifiers that must never reach generated code.
FORBIDDEN_SENTINELS = ("MISSING_LEFT", "MISSING_RIGHT", '"MISSING"', 'dlt.read("MISSING")')


@pytest.fixture
def config() -> ConversionConfig:
    return ConversionConfig()


def _join_dag(*, connect_left: bool = True, connect_right: bool = True) -> WorkflowDAG:
    """A Join whose Left/Right anchors can each be left unconnected."""
    dag = WorkflowDAG()
    dag.add_node(ReadNode(node_id=1, original_tool_type="Input Data", file_path="/l.csv", file_format="csv"))
    dag.add_node(ReadNode(node_id=2, original_tool_type="Input Data", file_path="/r.csv", file_format="csv"))
    dag.add_node(
        JoinNode(
            node_id=3,
            original_tool_type="Join",
            join_keys=[JoinKey(left_field="id", right_field="id")],
            join_type="inner",
        )
    )
    if connect_left:
        dag.add_edge(1, 3, destination_anchor="Left")
    if connect_right:
        dag.add_edge(2, 3, destination_anchor="Right")
    return dag


def _all_content(output) -> str:
    return "\n".join(f.content for f in output.files)


class TestSQLGenerator:
    def test_missing_right_input_emits_warning_not_sentinel(self, config):
        output = SQLGenerator(config).generate(_join_dag(connect_right=False))
        content = _all_content(output)

        assert "MISSING_RIGHT" not in content
        assert "right input is not connected" in " ".join(output.warnings)
        # The statement must be inert rather than a plausible-looking join.
        assert "SELECT 1 WHERE FALSE" in content
        assert "INNER JOIN" not in content

    def test_missing_left_input_names_the_left_side(self, config):
        output = SQLGenerator(config).generate(_join_dag(connect_left=False))

        assert "left input is not connected" in " ".join(output.warnings)
        assert "MISSING_LEFT" not in _all_content(output)

    def test_connected_join_still_generates_normally(self, config):
        """The guard must not disturb the happy path."""
        output = SQLGenerator(config).generate(_join_dag())
        content = _all_content(output)

        assert "INNER JOIN" in content
        assert "SELECT 1 WHERE FALSE" not in content
        assert not any("not connected" in w for w in output.warnings)

    def test_append_fields_missing_source(self, config):
        dag = WorkflowDAG()
        dag.add_node(ReadNode(node_id=1, original_tool_type="Input Data", file_path="/t.csv", file_format="csv"))
        dag.add_node(AppendFieldsNode(node_id=2, original_tool_type="Append Fields"))
        dag.add_edge(1, 2, destination_anchor="Target")

        output = SQLGenerator(config).generate(dag)

        assert "source input is not connected" in " ".join(output.warnings)
        assert "MISSING" not in _all_content(output)


class TestPySparkGenerator:
    def test_missing_right_input_emits_warning_not_sentinel(self, config):
        output = PySparkGenerator(config).generate(_join_dag(connect_right=False))
        content = _all_content(output)

        assert "MISSING_RIGHT" not in content
        assert "right input is not connected" in " ".join(output.warnings)
        assert "CANNOT CONVERT" in content

    def test_missing_left_input_names_the_left_side(self, config):
        output = PySparkGenerator(config).generate(_join_dag(connect_left=False))

        assert "left input is not connected" in " ".join(output.warnings)
        assert "MISSING_LEFT" not in _all_content(output)

    def test_connected_join_still_generates_normally(self, config):
        output = PySparkGenerator(config).generate(_join_dag())
        content = _all_content(output)

        assert ".join(" in content
        assert "CANNOT CONVERT" not in content


class TestDLTGenerator:
    def test_missing_right_input_emits_warning_not_sentinel(self, config):
        output = DLTGenerator(config).generate(_join_dag(connect_right=False))
        content = _all_content(output)

        assert 'dlt.read("MISSING")' not in content
        assert "right input is not connected" in " ".join(output.warnings)
        assert "CANNOT CONVERT" in content

    def test_connected_join_still_generates_normally(self, config):
        output = DLTGenerator(config).generate(_join_dag())

        assert "CANNOT CONVERT" not in _all_content(output)


class TestNoSentinelsAcrossGenerators:
    """Whole-output sweep: no generator may leak a placeholder identifier."""

    @pytest.mark.parametrize("generator_cls", [SQLGenerator, PySparkGenerator, DLTGenerator])
    @pytest.mark.parametrize(
        ("connect_left", "connect_right"),
        [(True, False), (False, True), (False, False)],
    )
    def test_no_placeholder_identifier_reaches_output(self, config, generator_cls, connect_left, connect_right):
        dag = _join_dag(connect_left=connect_left, connect_right=connect_right)
        output = generator_cls(config).generate(dag)
        content = _all_content(output)

        for sentinel in FORBIDDEN_SENTINELS:
            assert sentinel not in content, f"{generator_cls.__name__} leaked {sentinel!r}"
        # And the user is always told something is wrong.
        assert any("not connected" in w for w in output.warnings)

"""How a macro call in a real Alteryx file is parsed.

Alteryx saves a tool that runs a macro with no GuiSettings plugin and an
``<EngineSettings Macro="...">`` element. Those calls used to parse as an
"Unknown" tool with no macro path, so nothing downstream (expansion, the
complexity score's macro factor, the portfolio's shared macros) ever saw them.
"""

from __future__ import annotations

from pathlib import Path

from a2d.macro.detect import find_macro_calls
from a2d.parser.workflow_parser import WorkflowParser

PACKT = Path(__file__).parent.parent.parent / "fixtures" / "packt"


def _workflow(tmp_path: Path, engine_macro: str) -> Path:
    path = tmp_path / "wf.yxmd"
    path.write_text(
        '<?xml version="1.0"?><AlteryxDocument yxmdVer="2023.1"><Nodes>'
        '<Node ToolID="7"><GuiSettings><Position x="0" y="0"/></GuiSettings>'
        "<Properties><Configuration/></Properties>"
        f'<EngineSettings Macro="{engine_macro}"/></Node>'
        "</Nodes><Connections/></AlteryxDocument>",
        encoding="utf-8",
    )
    return path


def test_custom_macro_call_keeps_its_path(tmp_path):
    parsed = WorkflowParser().parse(_workflow(tmp_path, r".\Supporting_Macros\Connector.yxmc"))
    (node,) = parsed.nodes
    assert node.tool_type == "Macro"
    assert node.plugin_name == r"macro:.\Supporting_Macros\Connector.yxmc"
    assert [c.macro_path for c in find_macro_calls(parsed)] == [r".\Supporting_Macros\Connector.yxmc"]
    assert parsed.macro_references == [r".\Supporting_Macros\Connector.yxmc"]


def test_builtin_count_records_maps_to_its_converter(tmp_path):
    parsed = WorkflowParser().parse(_workflow(tmp_path, "CountRecords.yxmc"))
    (node,) = parsed.nodes
    assert node.tool_type == "CountRecords"
    assert find_macro_calls(parsed) == []


def test_builtin_random_records_maps_to_sample(tmp_path):
    parsed = WorkflowParser().parse(_workflow(tmp_path, "RandomRecords.yxmc"))
    assert parsed.nodes[0].tool_type == "Sample"
    assert find_macro_calls(parsed) == []


def test_real_packt_workflow_calls_are_found():
    parsed = WorkflowParser().parse(PACKT / "Cleansing_Data_Files.yxmd")
    calls = find_macro_calls(parsed)
    assert len(calls) == 3
    assert {c.macro_path for c in calls} == {r".\supporting_macros\Parse Column SQL records.yxmc"}

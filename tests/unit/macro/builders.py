"""Small Alteryx documents for macro tests: a workflow that calls macros, and
macros that do some work or call further macros."""

from __future__ import annotations

from itertools import pairwise


def _node(tool_id: int, plugin: str, config: str = "") -> str:
    return (
        f'<Node ToolID="{tool_id}"><GuiSettings Plugin="{plugin}"><Position x="0" y="0"/></GuiSettings>'
        f"<Properties><Configuration>{config}</Configuration></Properties></Node>"
    )


def _call(tool_id: int, macro_path: str) -> str:
    """A macro call the way Alteryx saves one: no plugin, an EngineSettings Macro."""
    return (
        f'<Node ToolID="{tool_id}"><GuiSettings><Position x="0" y="0"/></GuiSettings>'
        f'<Properties><Configuration/></Properties><EngineSettings Macro="{macro_path}"/></Node>'
    )


def _chain(ids: list[int]) -> str:
    return "".join(
        f'<Connection><Origin ToolID="{a}" Connection="Output"/><Destination ToolID="{b}" Connection="Input"/></Connection>'
        for a, b in pairwise(ids)
    )


def _doc(nodes: list[str], ids: list[int], runtime: str = "") -> str:
    properties = f"<Properties><RuntimeProperties>{runtime}</RuntimeProperties></Properties>" if runtime else ""
    return (
        '<?xml version="1.0"?><AlteryxDocument yxmdVer="2023.1">'
        f"<Nodes>{''.join(nodes)}</Nodes><Connections>{_chain(ids)}</Connections>{properties}</AlteryxDocument>"
    )


# How a .yxmc marks its type (in its document-level RuntimeProperties).
BATCH = (
    "<BatchMacro><OutputMode>AllSame</OutputMode><ControlParams><ControlParam><Name>CP</Name>"
    "</ControlParam></ControlParams></BatchMacro>"
)
ITERATIVE = (
    '<IterativeMacro><Input>In</Input><Output>Out</Output><IterationLimit value="100" />'
    "<LimitBehavior>Error</LimitBehavior></IterativeMacro>"
)
# A standard macro whose interface rewrites one of its tools from the caller's settings.
TAKES_SETTINGS = (
    "<Actions><NoCondition><Type>NoCondition</Type><True><Action><Type>UpdateRawXml</Type>"
    '<ToolId value="2" /><Expression>[#1]</Expression></Action></True></NoCondition></Actions>'
)


def workflow_calling(*macro_paths: str) -> str:
    """Input -> one call per macro, in sequence -> Output."""
    calls = [_call(10 + i, path) for i, path in enumerate(macro_paths)]
    ids = [1, *[10 + i for i in range(len(macro_paths))], 2]
    nodes = [
        _node(1, "AlteryxBasePluginsGui.DbFileInput.DbFileInput", '<File FileFormat="19" FilePath="in.csv"/>'),
        *calls,
        _node(
            2,
            "AlteryxBasePluginsGui.DbFileOutput.DbFileOutput",
            '<File FileFormat="19" FilePath="out.csv"/><WriteMode>Overwrite</WriteMode>',
        ),
    ]
    return _doc(nodes, ids)


def formula_macro(field: str = "Name", runtime: str = "") -> str:
    """MacroInput -> Formula -> MacroOutput (``runtime``: e.g. BATCH, ITERATIVE)."""
    nodes = [
        _node(1, "AlteryxBasePluginsGui.MacroInput.MacroInput", "<Name>In</Name>"),
        _node(
            2,
            "AlteryxBasePluginsGui.Formula.Formula",
            f'<FormulaFields><FormulaField expression="Uppercase([{field}])" field="{field}" '
            'type="V_WString" size="255"/></FormulaFields>',
        ),
        _node(3, "AlteryxBasePluginsGui.MacroOutput.MacroOutput", "<Name>Out</Name>"),
    ]
    return _doc(nodes, [1, 2, 3], runtime)


def macro_calling(macro_path: str) -> str:
    """MacroInput -> a call to another macro -> MacroOutput."""
    nodes = [
        _node(1, "AlteryxBasePluginsGui.MacroInput.MacroInput", "<Name>In</Name>"),
        _call(2, macro_path),
        _node(3, "AlteryxBasePluginsGui.MacroOutput.MacroOutput", "<Name>Out</Name>"),
    ]
    return _doc(nodes, [1, 2, 3])

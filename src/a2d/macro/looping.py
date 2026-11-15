"""Batch and iterative macro calls, as a function and a loop.

Alteryx runs a batch macro once per record of its Control input: before each
run, the macro's interface Actions write that record's values into the macro's
tools, and the runs' outputs are unioned. An iterative macro runs on its input,
feeds whatever reaches its iteration output back in, and stops when nothing is
left or at its iteration limit.

:func:`build_looping_node` turns such a call into a :class:`LoopingMacroNode`:

* The macro's tools are parsed again for each call and the Actions are applied
  to their settings: a value from the calling tool (a question answered on the
  call) is written in as is, and a value from the control record is written in
  as a placeholder (``MacroParam.sentinel``) that the generator turns into a
  function parameter. ``[Engine.IterationNumber]`` gets a numeric placeholder.
* Interface tools (questions, Actions, Control Parameters) are dropped from the
  body; the MacroInput/MacroOutput boundaries stay, as the function's inputs
  and outputs.
* What can't be wired in safely (a conditional Action, a raw-XML update, a
  control value that would land in an expression outside a string) is kept as
  the macro's saved value and listed in ``issues``; the generated code carries
  a TODO for each, so AI completion and the reviewer see it.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import (
    IRNode,
    LoopingMacroNode,
    MacroIONode,
    MacroParam,
    UnsupportedNode,
    WidgetNode,
    WorkflowControlNode,
)
from a2d.parser.schema import ParsedWorkflow

# Placeholders written into the macro's settings. Lower-case letters and digits
# only, so they survive any quoting the converters apply; matched case-insensitively.
_SENTINEL = "zza2dparam{n}zz"
SENTINEL_RE = re.compile(r"zza2dparam(\d+)zz", re.IGNORECASE)
# [Engine.IterationNumber] is a number, so it gets a number nobody writes by hand.
ITERATION_SENTINEL = "918273645"
_ITERATION_RE = re.compile(r"\[Engine\.IterationNumber\]", re.IGNORECASE)

# A question whose value looks like a credential is never copied into code.
_SECRET_NAME_RE = re.compile(r"(?i)pass|pwd|secret|token|api.?key|credential")

# Interface tools: they set values before a run, they don't touch data.
_INTERFACE_PREFIX = "AlteryxGuiToolkit."


@dataclass
class _Action:
    tool_id: int  # the Action tool
    spec: dict
    conditional: bool


def _text(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("#text", value.get("@value", ""))
    return value if isinstance(value, str) else ""


def _as_list(value: object) -> list:
    if value is None or value == {}:
        return []
    return value if isinstance(value, list) else [value]


def _int(value: object, default: int) -> int:
    try:
        return int(_text(value).strip())
    except ValueError:
        return default


def _questions(block: object, out: dict[int, tuple[str, str]]) -> dict[int, tuple[str, str]]:
    """tool id -> (question type, question name), through nested Tabs."""
    for q in _as_list(block.get("Question") if isinstance(block, dict) else None):
        if not isinstance(q, dict):
            continue
        tool_id = _int(q.get("ToolId"), -1)
        if tool_id >= 0:
            out[tool_id] = (_text(q.get("Type")), _text(q.get("Name")))
        if isinstance(q.get("Questions"), dict):
            _questions(q["Questions"], out)
    return out


def _actions(runtime: dict) -> list[_Action]:
    found: list[_Action] = []
    blocks = runtime.get("Actions")
    if not isinstance(blocks, dict):
        return found
    for key, entries in blocks.items():
        for entry in _as_list(entries):
            if not isinstance(entry, dict):
                continue
            conditional = key != "NoCondition"
            for branch in ("True", "False"):
                block = entry.get(branch)
                for spec in _as_list(block.get("Action") if isinstance(block, dict) else None):
                    if isinstance(spec, dict):
                        found.append(_Action(_int(spec.get("ToolId"), -1), spec, conditional))
    return found


def _caller_values(config: dict) -> dict[str, str]:
    """The calling tool's ``<Value name="...">`` settings."""
    values: dict[str, str] = {}
    for item in _as_list(config.get("Value") if isinstance(config, dict) else None):
        if isinstance(item, dict) and item.get("@name"):
            values[str(item["@name"])] = _text(item)
    return values


def _pairs(text: str) -> list[tuple[str, str]]:
    out = []
    for line in (text or "").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip():
            out.append((name.strip(), value.strip()))
    return out


def _group_by(text: str) -> list[tuple[str, str, str]]:
    """``Control=f1\\nInput8=f1`` -> [("f1", "Input8", "f1")]."""
    groups: list[tuple[str, str, str]] = []
    control: str | None = None
    for name, value in _pairs(text):
        if name == "Control":
            control = value
        elif control is not None:
            groups.append((control, name, value))
    return groups


# ── settings paths ─────────────────────────────────────────────────────────

_STEP_RE = re.compile(r"^(?P<name>[^\[]+)(\[@(?P<attr>[\w:]+)='(?P<val>[^']*)'\])?$")


def _locate(config: dict, path: list[str]) -> tuple[dict | list, str | int] | None:
    """The container and key holding the value at an Action's destination path
    (``Simple/Operands/Operand``), or None when the path isn't there."""
    node: object = config
    for i, step in enumerate(path):
        m = _STEP_RE.match(step)
        if not m or not isinstance(node, dict):
            return None
        name = m.group("name")
        child = node.get(name)
        if m.group("attr"):
            matches = [
                c for c in _as_list(child) if isinstance(c, dict) and c.get(f"@{m.group('attr')}") == m.group("val")
            ]
            if len(matches) != 1:
                return None
            child = matches[0]
            if i == len(path) - 1:
                return None  # a whole element, not a value
            node = child
            continue
        if i == len(path) - 1:
            return (node, name) if name in node else None
        node = child
    return None


def _get(holder: dict | list, key: str | int) -> str | None:
    value = holder[key]  # type: ignore[index]
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("#text", ""), str):
        return value.get("#text", "")
    return None


def _set(holder: dict | list, key: str | int, text: str) -> None:
    value = holder[key]  # type: ignore[index]
    if isinstance(value, dict):
        value["#text"] = text
    else:
        holder[key] = text  # type: ignore[index]


def _inside_quotes(expression: str, needle: str) -> bool:
    """True when every occurrence of ``needle`` in an Alteryx expression sits
    inside a string literal, so swapping it for text keeps the expression valid."""
    if not needle or needle not in expression:
        return False
    inside: list[tuple[int, int]] = []
    quote: str | None = None
    start = 0
    for i, ch in enumerate(expression):
        if quote is None and ch in "\"'":
            quote, start = ch, i
        elif quote is not None and ch == quote:
            inside.append((start, i))
            quote = None
    pos = expression.find(needle)
    while pos != -1:
        if not any(a < pos and pos + len(needle) <= b for a, b in inside):
            return False
        pos = expression.find(needle, pos + 1)
    return True


def _is_expression(path: list[str]) -> bool:
    last = path[-1].lower() if path else ""
    return "expression" in last


def _replace_iteration_number(value: object) -> bool:
    """Swap ``[Engine.IterationNumber]`` for its placeholder in every setting."""
    found = False
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, str) and _ITERATION_RE.search(v):
                value[k] = _ITERATION_RE.sub(ITERATION_SENTINEL, v)
                found = True
            elif _replace_iteration_number(v):
                found = True
    elif isinstance(value, list):
        for i, v in enumerate(value):
            if isinstance(v, str) and _ITERATION_RE.search(v):
                value[i] = _ITERATION_RE.sub(ITERATION_SENTINEL, v)
                found = True
            elif _replace_iteration_number(v):
                found = True
    return found


def _identifier(text: str, used: set[str]) -> str:
    base = "p_" + (re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower() or "value")
    name, n = base, 2
    while name in used:
        name, n = f"{base}_{n}", n + 1
    used.add(name)
    return name


# ── building the node ──────────────────────────────────────────────────────


def apply_actions(
    parsed: ParsedWorkflow,
    kind: str,
    caller_config: dict,
) -> tuple[list[MacroParam], list[str], bool]:
    """Apply the macro's Actions and question references to ``parsed`` (a copy)
    in place.

    Returns the control-record parameters, the issues, and whether the steps
    use ``[Engine.IterationNumber]``.
    """
    runtime = parsed.properties.get("RuntimeProperties") if isinstance(parsed.properties, dict) else None
    runtime = runtime if isinstance(runtime, dict) else {}
    questions = _questions(runtime.get("Questions") or {}, {})
    nodes = {n.tool_id: n for n in parsed.nodes}
    # Questions wired into a tool, in connection order: an Action reads its one
    # question; any other tool refers to them as [#1], [#2], ...
    asked: dict[int, list[int]] = {}
    for c in parsed.connections:
        if c.origin.anchor_name == "Question":
            asked.setdefault(c.destination.tool_id, []).append(c.origin.tool_id)
    targets = {c.origin.tool_id: c.destination.tool_id for c in parsed.connections if c.origin.anchor_name == "Action"}
    values = _caller_values(caller_config)
    control_fields = dict(_pairs(values.get("ControlParams", "")))

    params: dict[str, MacroParam] = {}
    used: set[str] = set()
    issues: list[str] = []

    def resolve(question_id: int | None) -> tuple[str, MacroParam | None, str | None] | None:
        """(question name, control parameter or None, value from the call or None);
        None when the call leaves the macro's saved value (an issue is noted if
        that's because it can't be wired in)."""
        q_type, q_name = questions.get(question_id if question_id is not None else -1, ("", ""))
        if q_type == "ControlParam":
            if kind != "batch":
                issues.append(f"{q_name} is a control parameter, which only a batch macro has")
                return None
            control_field = control_fields.get(q_name)
            if not control_field:
                issues.append(f"the call doesn't say which control field feeds {q_name}")
                return None
            param = params.get(q_name) or MacroParam(q_name, control_field, "", _SENTINEL.format(n=len(params)))
            return q_name, param, None
        if q_name in values:
            if _SECRET_NAME_RE.search(q_name):
                issues.append(f"{q_name} looks like a credential, so it isn't copied into the code; use a secret scope")
                return None
            return q_name, None, values[q_name]
        return None  # the call doesn't set it: the macro's saved value stands

    def claim(param: MacroParam | None) -> None:
        """Keep a control parameter once its value has been written in somewhere."""
        if param is not None and param.question not in params:
            param.var = _identifier(param.question, used)
            params[param.question] = param

    for action in _actions(runtime):
        spec = action.spec
        action_type = _text(spec.get("Type"))
        target_id = targets.get(action.tool_id)
        wired_in = asked.get(action.tool_id)
        question = wired_in[0] if wired_in else None
        if action.conditional:
            name = questions.get(question if question is not None else -1, ("", "a setting"))[1]
            issues.append(f"{name} is applied by a conditional Action, which isn't converted; check tool {target_id}")
            continue
        resolved = resolve(question)
        if resolved is None:
            continue
        what, param, literal = resolved
        value = param.sentinel if param else (literal or "")

        if action_type == "UpdateInput":
            node = nodes.get(target_id) if target_id is not None else None
            holder = (node.configuration, "File") if node is not None and "File" in node.configuration else None
            saved = _get(*holder) if holder is not None else None
            if holder is None or saved is None:
                issues.append(f"{what} sets the file of tool {target_id}, which couldn't be found")
                continue
            if param:
                # Keep the saved file's extension after the placeholder, so the
                # reader is picked from it; the control value replaces both.
                base = saved.replace("\\", "/").rsplit("/", 1)[-1]
                param.suffix = base[base.find(".") :] if "." in base else ""
                value = param.sentinel + param.suffix
            _set(*holder, value)
            claim(param)
            continue
        if action_type != "UpdateValue" or _text(spec.get("Mode")) not in ("", "Simple"):
            kind_of = f"an Action of type {action_type}" if action_type else "a custom Action"
            issues.append(f"{what} is applied by {kind_of} on tool {target_id}, which isn't converted")
            continue

        destination = _text(spec.get("Destination"))
        tool_part, _, rest = destination.partition("/")
        node = nodes.get(_int(tool_part, -1))
        path = [p for p in rest.split("/") if p]
        located = _locate(node.configuration, path) if node is not None and path else None
        current = _get(*located) if located else None
        if located is None or current is None:
            issues.append(f"{what} updates {destination!r}, which isn't a setting the converter can find")
            continue
        replace_part = _text(spec.get("Replace")) == "True"
        find = _text(spec.get("ReplaceText"))
        if param and _is_expression(path) and not (replace_part and _inside_quotes(current, find)):
            issues.append(
                f"{what} writes the control value into the expression of tool {tool_part} outside a string, "
                "which isn't converted; check that step"
            )
            continue
        if replace_part:
            if not (find and find in current):
                issues.append(f"{what} replaces {find!r} in tool {tool_part}, which isn't in its saved setting")
                continue
            _set(*located, current.replace(find, value))
        else:
            _set(*located, value)
        claim(param)

    # [#1], [#2]... in a tool's settings: the questions wired into that tool.
    for tool_id, question_ids in asked.items():
        node = nodes.get(tool_id)
        if node is None or node.tool_type == "Action":
            continue
        for k, question_id in enumerate(question_ids, start=1):
            if not _mentions(node.configuration, f"[#{k}]"):
                continue
            resolved = resolve(question_id)
            if resolved is None:
                continue
            what, param, literal = resolved
            text = param.sentinel if param else (literal or "")
            if '"' in text and "'" in text:
                issues.append(f"{what} has both kinds of quote, so it isn't written into tool {tool_id}; check it")
                continue
            quote = "'" if '"' in text else '"'
            _replace_text(node.configuration, f"[#{k}]", f"{quote}{text}{quote}")
            claim(param)

    uses_iteration = any(_replace_iteration_number(n.configuration) for n in parsed.nodes)
    return list(params.values()), issues, uses_iteration


def _mentions(value: object, needle: str) -> bool:
    if isinstance(value, str):
        return needle in value
    if isinstance(value, dict):
        return any(_mentions(v, needle) for v in value.values())
    if isinstance(value, list):
        return any(_mentions(v, needle) for v in value)
    return False


def _replace_text(value: object, needle: str, text: str) -> None:
    """Replace ``needle`` with ``text`` in every string setting, in place."""
    items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for key, v in list(items):
        if isinstance(v, str):
            if needle in v:
                value[key] = v.replace(needle, text)  # type: ignore[index]
        else:
            _replace_text(v, needle, text)


def is_interface(node: IRNode) -> bool:
    """Questions, Actions and Control Parameters: they set values, they don't touch data."""
    if isinstance(node, WidgetNode):
        return True
    if isinstance(node, WorkflowControlNode):
        return node.control_type in ("control_param", "action", "condition")
    return isinstance(node, UnsupportedNode) and node.original_plugin_name.startswith(_INTERFACE_PREFIX)


def build_looping_node(
    call: IRNode,
    *,
    kind: str,
    macro_name: str,
    function_name: str,
    parsed: ParsedWorkflow,
    build_dag,
) -> LoopingMacroNode:
    """The :class:`LoopingMacroNode` for one call. ``parsed`` is the macro (it is
    copied, not changed); ``build_dag`` builds an IR DAG from a parsed macro."""
    parsed = copy.deepcopy(parsed)
    caller_config = getattr(call, "original_configuration", None) or {}
    params, issues, uses_iteration = apply_actions(parsed, kind, caller_config)
    body: WorkflowDAG = build_dag(parsed)
    for node in list(body.all_nodes()):
        if is_interface(node):
            body.remove_node(node.node_id)

    inputs = sorted(
        ((n.field_name, n.node_id) for n in body.all_nodes() if isinstance(n, MacroIONode) and n.direction == "input"),
        key=lambda b: b[1],
    )
    outputs = sorted(
        ((n.field_name, n.node_id) for n in body.all_nodes() if isinstance(n, MacroIONode) and n.direction == "output"),
        key=lambda b: b[1],
    )
    runtime = parsed.properties.get("RuntimeProperties") if isinstance(parsed.properties, dict) else {}
    runtime = runtime if isinstance(runtime, dict) else {}
    node = LoopingMacroNode(
        node_id=call.node_id,
        original_tool_type=call.original_tool_type,
        original_plugin_name=call.original_plugin_name,
        annotation=call.annotation,
        position=call.position,
        conversion_confidence=0.7,
        conversion_method="template",
        output_fields=dict(call.output_fields),
        kind=kind,
        macro_name=macro_name,
        function_name=function_name,
        body=body,
        inputs=inputs,
        outputs=outputs,
        params=params,
        uses_iteration_number=uses_iteration,
        issues=issues,
    )
    if kind == "batch":
        found = runtime.get("BatchMacro")
        settings: dict = found if isinstance(found, dict) else {}
        node.output_mode = _text(settings.get("OutputMode"))
        node.group_by = _group_by(_caller_values(caller_config).get("BatchMacroGroupBy", ""))
        known = {name for name, _ in inputs}
        for _, anchor, _ in node.group_by:
            if anchor not in known:
                issues.append(f"the call groups input {anchor}, which the macro doesn't have")
    else:
        found = runtime.get("IterativeMacro")
        settings = found if isinstance(found, dict) else {}
        node.output_mode = _text(settings.get("OutputMode"))
        node.iteration_input = _text(settings.get("Input"))
        node.iteration_output = _text(settings.get("Output"))
        node.iteration_limit = _int(settings.get("IterationLimit"), 100)
        node.limit_behavior = _text(settings.get("LimitBehavior")) or "Error"
        if node.iteration_input not in {name for name, _ in inputs}:
            issues.append(f"the iteration input {node.iteration_input!r} isn't one of the macro's inputs")
        if node.iteration_output not in {name for name, _ in outputs}:
            issues.append(f"the iteration output {node.iteration_output!r} isn't one of the macro's outputs")
    node.conversion_notes = list(issues)
    return node

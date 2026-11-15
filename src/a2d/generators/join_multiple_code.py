"""Code for Alteryx's Join Multiple tool, shared by the generators.

What Alteryx does (help: Join Multiple tool):

* Inputs are numbered #1, #2, ... (the connection's ``name``), and the order
  decides the output's column order and names.
* They join on each input's key fields, matched by position (key 1 of every
  input, key 2 of every input, ...), or with "Join by Record Position", record
  1 of every input together, then record 2, and so on.
* "Only output records that join from all inputs" is an inner join; without
  it, all records are kept, with nulls where an input has no match (a full
  outer join, so with 3, 5 and 7 records by position you get 7 rows).
* Every field of every input is kept. A name an earlier input already used
  comes out as ``Input_#k_<name>``. The tool's select list names fields as
  ``Input_#k_<name>`` too, and can rename or drop them; ``*Unknown`` decides
  what happens to fields it doesn't list.

The joins go through hidden ``_a2d_key<i>`` columns, joined by name, so in a
full outer join a record from input #3 still meets the key of a record that
only came from #2.
"""

from __future__ import annotations

from collections.abc import Callable

from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import JoinMultipleNode
from a2d.ir.schema import input_columns


def _number(name: str) -> int:
    text = (name or "").lstrip("#")
    return int(text) if text.isdigit() else 10**6


def ordered(dag: WorkflowDAG | None, node_id: int, inputs: dict[str, str]) -> list[str]:
    """``inputs`` (as a generator resolved them, in predecessor order) sorted by
    input number (#1, #2, ...), for any tool whose inputs are ordered (Join
    Multiple, Union). Without numbers the order is kept."""
    values = list(inputs.values())
    if dag is None:
        return values
    preds = dag.get_predecessors(node_id)
    if len(preds) != len(values):
        return values
    numbered = [
        (_number(dag.get_edge_info(p.node_id, node_id).input_name), i, v)
        for i, (p, v) in enumerate(zip(preds, values, strict=True))
    ]
    return [v for _, _, v in sorted(numbered)]


def keys(node: JoinMultipleNode, count: int) -> list[list[str]] | None:
    """Each input's key fields, in input order; None to join by record position."""
    if node.by_position:
        return None
    if node.keys_by_input:
        return [list(node.keys_by_input.get(k, [])) for k in range(1, count + 1)]
    if node.join_keys:  # the older two-sided form: #1 on the left fields, the rest on the right
        return [[k.left_field for k in node.join_keys]] + [[k.right_field for k in node.join_keys]] * (count - 1)
    return [[] for _ in range(count)]


def problem(node: JoinMultipleNode, count: int) -> str | None:
    """Why the inputs can't be joined as configured, or None."""
    if count < 2:
        return None
    per_input = keys(node, count)
    if per_input is None:
        return None
    if not any(per_input):
        return "it has no key fields and doesn't join by record position"
    if any(not k for k in per_input):
        missing = [str(i) for i, k in enumerate(per_input, start=1) if not k]
        return f"input #{', #'.join(missing)} has no key fields"
    if len({len(k) for k in per_input}) > 1:
        return "the inputs don't all have the same number of key fields"
    return None


def _how(node: JoinMultipleNode) -> str:
    return node.join_type if node.join_type in ("inner", "left", "right", "full") else "inner"


def describe(node: JoinMultipleNode) -> str:
    on = "by record position" if node.by_position else "on their key fields"
    keep = "only records that join from all inputs" if _how(node) == "inner" else "all records"
    return f"Join Multiple: inputs joined {on}, keeping {keep}, like Alteryx"


def python_lines(node: JoinMultipleNode, inputs: list[str], out: str, lit: Callable[[str], str]) -> list[str]:
    """PySpark lines that assign ``out``. ``inputs`` are DataFrame expressions in
    input order (#1 first)."""
    n = node.node_id
    count = len(inputs)
    if count < 2:
        return [f"{out} = {inputs[0] if inputs else 'MISSING_INPUT'}"]
    why = problem(node, count)
    if why:
        return [
            f"# TODO: Join Multiple can't be converted as configured: {why}.",
            f"{out} = {inputs[0]}  # PLACEHOLDER: input #1 only",
        ]
    per_input = keys(node, count)
    key_list = (
        "None"
        if per_input is None
        else "[" + ", ".join("[" + ", ".join(lit(k) for k in ks) + "]" for ks in per_input) + "]"
    )
    acc, names = f"_jm_{n}", f"_jm_names_{n}"
    lines = [
        f"# {describe(node)}",
        '_q = lambda c: F.col("`" + c.replace("`", "``") + "`")  # a column by its exact name',
        f"{acc}, {names} = None, {{}}  # names: Input_#k_<field> -> output column",
        f"for _k, (_df, _keys) in enumerate(zip([{', '.join(inputs)}], {key_list} or [None] * {count}), start=1):",
        "    if _keys is None:  # join by record position",
        '        _df = _df.withColumn("_a2d_key0", F.row_number().over(Window.orderBy(F.monotonically_increasing_id())))',
        "    else:",
        '        _df = _df.withColumns({f"_a2d_key{_i}": _q(_c) for _i, _c in enumerate(_keys)})',
        "    _rename = {}",
        "    for _c in _df.columns:",
        '        if _c.startswith("_a2d_key"):',
        "            continue",
        f'        _new = f"Input_#{{_k}}_{{_c}}" if _c in {names}.values() else _c  # a name an earlier input took',
        f'        {names}[f"Input_#{{_k}}_{{_c}}"] = _new',
        "        if _new != _c:",
        "            _rename[_c] = _new",
        "    _df = _df.withColumnsRenamed(_rename)",
        '    _on = [_c for _c in _df.columns if _c.startswith("_a2d_key")]',
        f"    {acc} = _df if {acc} is None else {acc}.join(_df, on=_on, how={lit(_how(node))})",
    ]
    if node.select_fields or not node.keep_unlisted:
        listed = ", ".join(f"{lit(f)}: ({sel}, {lit(ren) if ren else 'None'})" for f, sel, ren in node.select_fields)
        lines += [
            "# The tool's select list (fields named Input_#k_<field>); fields it doesn't list are "
            + ("kept." if node.keep_unlisted else "dropped."),
            f"_select_{n} = {{{listed}}}",
            f"{out} = {acc}.select(*[",
            "    _q(_new).alias(_ren or _new)",
            f"    for _field, _new in {names}.items()",
            f"    for _sel, _ren in [_select_{n}.get(_field, ({node.keep_unlisted}, None))]",
            "    if _sel",
            "])",
        ]
    else:
        lines.append(f'{out} = {acc}.drop(*[_c for _c in {acc}.columns if _c.startswith("_a2d_key")])')
    return lines


def _ident(name: str) -> str:
    return "`" + name.replace("`", "``") + "`"


def sql_body(node: JoinMultipleNode, tables: list[str], dag: WorkflowDAG | None) -> tuple[str, list[str]]:
    """The SELECT for a Join Multiple CTE, and warnings. ``tables`` are CTE
    names in input order (#1 first)."""
    warnings: list[str] = []
    count = len(tables)
    if count < 2:
        return f"SELECT * FROM {tables[0] if tables else 'MISSING'}", warnings
    why = problem(node, count)
    if why:
        warnings.append(f"JoinMultiple node {node.node_id}: {why}; it isn't converted")
        return f"SELECT * FROM {tables[0]} /* TODO: Join Multiple can't be converted as configured: {why} */", warnings
    per_input = keys(node, count)
    width = 1 if per_input is None else len(per_input[0])

    def keyed(i: int, table: str) -> str:
        if per_input is None:
            exprs = "ROW_NUMBER() OVER (ORDER BY monotonically_increasing_id()) AS _a2d_key0"
        else:
            exprs = ", ".join(f"{_ident(k)} AS _a2d_key{j}" for j, k in enumerate(per_input[i]))
        return f"(SELECT *, {exprs} FROM {table}) AS j{i + 1}"

    how = {"inner": "INNER", "left": "LEFT OUTER", "right": "RIGHT OUTER", "full": "FULL OUTER"}[_how(node)]
    sql = f"FROM {keyed(0, tables[0])}"
    for i, table in enumerate(tables[1:], start=1):
        conds = []
        for j in range(width):
            earlier = [f"j{m + 1}._a2d_key{j}" for m in range(i)]
            left = earlier[0] if len(earlier) == 1 or how == "INNER" else f"COALESCE({', '.join(earlier)})"
            conds.append(f"{left} = j{i + 1}._a2d_key{j}")
        sql += f"\n{how} JOIN {keyed(i, table)} ON {' AND '.join(conds)}"

    # Column names, the Alteryx way, when every input's columns are known.
    columns = None
    if dag is not None:
        known = input_columns(dag, node.node_id)
        if len(known) == count and all(known.values()):  # an empty list isn't a known schema
            ordered_cols = ordered(dag, node.node_id, {a: a for a in known})
            columns = [[c for c, _ in known[a]] for a in ordered_cols]  # type: ignore[union-attr]
    if columns is None:
        warnings.append(
            f"JoinMultiple node {node.node_id}: the inputs' columns aren't known, so a name two inputs share "
            "isn't renamed Input_#k_<name>; use the PySpark output, or list the columns, if that matters"
        )
        return "SELECT " + ", ".join(f"j{i + 1}.*" for i in range(count)) + " " + sql, warnings
    select = {f: (sel, ren) for f, sel, ren in node.select_fields}
    taken: set[str] = set()
    items = []
    for k, cols in enumerate(columns, start=1):
        for c in cols:
            new = f"Input_#{k}_{c}" if c in taken else c
            taken.add(new)
            sel, ren = select.get(f"Input_#{k}_{c}", (node.keep_unlisted, None))
            if sel:
                items.append(f"j{k}.{_ident(c)} AS {_ident(ren or new)}")
    if not items:
        warnings.append(f"JoinMultiple node {node.node_id}: its select list keeps no columns")
        return "SELECT NULL AS _no_columns " + sql, warnings
    return "SELECT " + ", ".join(items) + "\n" + sql, warnings

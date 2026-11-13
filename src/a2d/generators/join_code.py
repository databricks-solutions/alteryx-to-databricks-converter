"""PySpark code for an Alteryx Join's J output, shared by the PySpark and DLT generators.

Alteryx names every right-side field that is also on the left ``Right_<name>``,
and the Join's Select settings refer to fields by those output names (for
example ``Right_COMPANY_ID``). Spark would keep both copies under the same name,
so later steps fail on an ambiguous column and the Select settings miss. The
generated code renames the right side the way Alteryx does, at run time because
the input schemas aren't known when converting, then joins on unique names.
"""

from __future__ import annotations

import json

from a2d.ir.nodes import JoinNode


def lit(text: str) -> str:
    """A Python string literal for ``text``."""
    return json.dumps(text)


def col(name: str) -> str:
    """``F.col`` for a column name, quoted so dots and spaces stay part of the name."""
    return f"F.col({lit('`' + name.replace('`', '``') + '`')})"


def _plain(name: str) -> bool:
    return not any(ch in name for ch in ".` ")


def col_ref(name: str) -> str:
    """``F.col`` for a name known now; backticks only when the name needs them."""
    return f"F.col({lit(name)})" if _plain(name) else col(name)


def renamed_ref(names_var: str, right_field: str) -> str:
    """``F.col`` for a right-side field under its run-time (maybe Right_-prefixed) name."""
    looked_up = f"{names_var}[{lit(right_field)}]"
    if _plain(right_field):
        return f"F.col({looked_up})"
    return f'F.col("`" + {looked_up}.replace("`", "``") + "`")'


def join_output_lines(
    node: JoinNode,
    left: str,
    right: str,
    out: str,
    *,
    broadcast: str | None = None,
) -> list[str]:
    """Lines that assign the Join's J output to ``out``.

    ``left`` and ``right`` are DataFrame variables already in scope.
    ``broadcast`` is ``"left"`` or ``"right"`` to add a broadcast hint to that side.
    """
    nid = node.node_id
    names = f"_rn_{nid}"
    renamed = f"_r_{nid}"
    lines = [
        "# Right-side fields also on the left get Alteryx's Right_ prefix, so every name is unique.",
        f'{names} = {{c: (f"Right_{{c}}" if c in {left}.columns else c) for c in {right}.columns}}',
        f"{renamed} = {right}.toDF(*{names}.values())",
    ]

    if node.join_keys:
        parts = [f"({col_ref(jk.left_field)} == {renamed_ref(names, jk.right_field)})" for jk in node.join_keys]
        condition = parts[0][1:-1] if len(parts) == 1 else " & ".join(parts)
    else:
        condition = "F.lit(True)"

    join_left = f"F.broadcast({left})" if broadcast == "left" else left
    join_right = f"F.broadcast({renamed})" if broadcast == "right" else renamed

    ops = node.select_left + node.select_right
    chain: list[str] = []
    renames = [
        (op.field_name, op.rename_to) for op in ops if op.selected and op.rename_to and op.rename_to != op.field_name
    ]
    if renames:
        chain.append(".withColumnsRenamed({" + ", ".join(f"{lit(a)}: {lit(b)}" for a, b in renames) + "})")
    if node.keep_unlisted:
        drops = [op.field_name for op in ops if not op.selected]
        if drops:
            chain.append(".drop(" + ", ".join(lit(d) for d in drops) + ")")
    else:
        # *Unknown is deselected: only the fields the Join lists as selected come out.
        kept = [op.rename_to or op.field_name for op in ops if op.selected]
        chain.append(".select(" + ", ".join(col_ref(k) for k in kept) + ")" if kept else ".select()")

    join_expr = f'{join_left}.join({join_right}, {condition}, "{node.join_type or "inner"}")'
    if chain:
        body = "\n".join(f"    {c}" for c in chain)
        lines.append(f"{out} = (\n    {join_expr}\n{body}\n)")
    else:
        lines.append(f"{out} = {join_expr}")
    return lines

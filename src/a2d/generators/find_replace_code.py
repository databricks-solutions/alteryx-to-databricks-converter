"""PySpark code for an Alteryx Find Replace tool, shared by the PySpark and DLT generators.

Find Replace looks up each value of the R input's Find Value field in the F
input's Find Within field, then either replaces the found text with the R
input's replacement field or appends R fields to the row. Output has one row
per F row, like a lookup:

* Entire field: a left join on the value (lower-cased for a case-insensitive find).
* Any part of the field: Spark can't join on "this value appears in that text",
  so the lookup is read to the driver and turned into a match expression. That
  suits the lookup-sized R inputs this tool is used with.
"""

from __future__ import annotations

from a2d.generators.join_code import col_ref, lit
from a2d.ir.nodes import FindReplaceNode


def problem(node: FindReplaceNode) -> str | None:
    """Why this Find Replace can't be generated, or None."""
    if node.find_mode not in ("exact", "contains"):
        return f"find mode {node.raw_find_mode or node.find_mode!r} isn't supported yet"
    if not node.find_field or not node.search_field:
        return "the find fields aren't set"
    if node.replace_mode == "replace" and not node.replace_field:
        return "no replacement field is set"
    if node.replace_mode == "append" and not node.append_fields:
        return "no fields to append are set"
    return None


def describe(node: FindReplaceNode) -> str:
    where = "the whole of" if node.find_mode == "exact" else "any part of"
    options = ["case-insensitive" if not node.case_sensitive else "case-sensitive"]
    if node.whole_word and node.find_mode == "contains":
        options.append("whole words only")
    action = (
        f"replace with {node.replace_field}"
        + (" (every found item)" if node.replace_multiple and node.find_mode == "contains" else "")
        if node.replace_mode == "replace"
        else f"append {', '.join(node.append_fields)}"
    )
    return (
        f"# Find Replace: find the lookup's {node.search_field} in {where} {node.find_field} "
        f"({', '.join(options)}), then {action}."
    )


def find_replace_lines(node: FindReplaceNode, target: str, lookup: str, out: str) -> list[str]:
    """Lines that assign the Find Replace output to ``out``. Call :func:`problem` first."""
    lines = [describe(node)]
    lines += _exact(node, target, lookup, out) if node.find_mode == "exact" else _contains(node, target, lookup, out)
    return lines


def _exact(node: FindReplaceNode, target: str, lookup: str, out: str) -> list[str]:
    nid = node.node_id
    table = f"_fr_{nid}"
    search, find = col_ref(node.search_field), col_ref(node.find_field)
    key = search if node.case_sensitive else f"F.lower({search})"
    target_key = find if node.case_sensitive else f"F.lower({find})"
    if node.replace_mode == "replace":
        picked = f'{col_ref(node.replace_field)}.alias("_fr_value")'
        after = [
            f'.withColumn({lit(node.find_field)}, F.when(F.col("_fr_key").isNotNull(), F.col("_fr_value")).otherwise({find}))',
            '.drop("_fr_key", "_fr_value")',
        ]
    else:
        picked = ", ".join(col_ref(a) for a in node.append_fields)
        after = ['.drop("_fr_key")']
    return [
        "# Alteryx uses the first lookup row for a value found more than once; dropDuplicates keeps one of them.",
        f'{table} = {lookup}.select({key}.alias("_fr_key"), {picked}).dropDuplicates(["_fr_key"])',
        f"{out} = (\n"
        f'    {target}.join({table}, {target_key} == F.col("_fr_key"), "left")\n'
        + "\n".join(f"    {a}" for a in after)
        + "\n)",
    ]


def _contains(node: FindReplaceNode, target: str, lookup: str, out: str) -> list[str]:
    nid = node.node_id
    rows, pattern, field = f"_fr_{nid}_rows", f"_fr_{nid}_pattern", col_ref(node.find_field)
    searched = f'{field}.cast("string")'
    flags = "" if node.case_sensitive else "(?i)"
    # \Q...\E matches the value literally; (?<!\S)...(?!\S) is Alteryx's whole word
    # (spaces around it, or the start or end of the field).
    body = '"\\\\Q" + str(value).replace("\\\\E", "\\\\E\\\\\\\\E\\\\Q") + "\\\\E"'
    if node.whole_word:
        body = f'"(?<!\\\\S)" + {body} + "(?!\\\\S)"'
    lines = [
        f"def {pattern}(value):",
        f"    return {lit(flags) + ' + ' if flags else ''}{body}",
        "",
    ]
    first_wins = "# Lookup rows are tried in the order Spark returns them; the first match wins."
    if node.replace_mode == "replace":
        lines += [
            f"{rows} = {lookup}.select({col_ref(node.search_field)}, {col_ref(node.replace_field)}).collect()",
            f"_fr_{nid}_col = {field}",
        ]
        text = '(replacement or "").replace("\\\\", "\\\\\\\\").replace("$", "\\\\$")'
        if node.replace_multiple:
            lines += [
                f"for value, replacement in {rows}:",
                '    if value is not None and str(value) != "":',
                f"        _fr_{nid}_col = F.regexp_replace(_fr_{nid}_col, {pattern}(value), {text})",
            ]
        else:
            lines += [
                first_wins,
                f"for value, replacement in reversed({rows}):",
                '    if value is not None and str(value) != "":',
                f"        _fr_{nid}_col = F.when({searched}.rlike({pattern}(value)), "
                f"F.regexp_replace({field}, {pattern}(value), {text})).otherwise(_fr_{nid}_col)",
            ]
        lines.append(f"{out} = {target}.withColumn({lit(node.find_field)}, _fr_{nid}_col)")
        return lines
    appended = ", ".join(col_ref(a) for a in node.append_fields)
    lines += [
        first_wins,
        f"{rows} = {lookup}.select({col_ref(node.search_field)}, {appended}).collect()",
        f"{out} = {target}",
        f"for i, name in enumerate({[*node.append_fields]!r}, start=1):",
        "    value_col = F.lit(None)",
        f"    for row in reversed({rows}):",
        '        if row[0] is not None and str(row[0]) != "":',
        f"            value_col = F.when({searched}.rlike({pattern}(row[0])), F.lit(row[i])).otherwise(value_col)",
        f"    {out} = {out}.withColumn(name, value_col)",
    ]
    return lines

"""Pre-answer the estate questions from an analyzed workflow set.

This is the "smart / tailored" hook: when a user uploads their actual `.yxmd`
estate, the *Estate & workflow profile* questions can be answered mechanically from
the converter's own analysis (workflow count, macro usage, presence of
spatial/predictive/custom tools) so the survey starts grounded in reality. Purely
deterministic — a mapping of derived facts to the closest option value.

Only the estate dimension is prefilled; people/platform/governance are human
judgment and left blank.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2d.analyzer.profiler import TOOL_CATEGORY

if TYPE_CHECKING:
    from a2d.analyzer.readiness import WorkflowAnalysis

# Categories (from the profiler's PLUGIN_NAME_MAP-derived mapping) that make an
# estate "heavy" vs merely "some" for the advanced-tools question.
_HEAVY_CATEGORIES = {"predictive", "developer"}
_SOME_CATEGORIES = {"spatial", "reporting"}
# Fallback names in case a tool isn't in TOOL_CATEGORY.
_HEAVY_NAMES = {"PythonTool", "JupyterCode", "RunCommand", "RTool", "R"}


def prefill_from_estate(analyses: list[WorkflowAnalysis]) -> dict[str, str]:
    """Return suggested answers for the estate questions from analysis results.

    Returns an empty dict for an empty estate. Keys are question ids from
    :mod:`a2d.questionnaire.bank`; values are option values.
    """
    if not analyses:
        return {}

    answers: dict[str, str] = {}
    total = len(analyses)

    # estate_size — bucket the workflow count.
    if total <= 10:
        answers["estate_size"] = "small"
    elif total <= 50:
        answers["estate_size"] = "medium"
    elif total <= 200:
        answers["estate_size"] = "large"
    else:
        answers["estate_size"] = "xlarge"

    # macros — how many workflows reference macros.
    macro_wf = sum(1 for wf in analyses if wf.complexity.has_macro_refs)
    if macro_wf == 0:
        answers["macros"] = "none"
    elif macro_wf / total < 0.3:
        answers["macros"] = "few"
    else:
        answers["macros"] = "many"

    # advanced_tools — scan the estate's tool types for heavy vs some.
    has_heavy = False
    has_some = False
    for wf in analyses:
        if wf.complexity.spatial_tool_count > 0:
            has_some = True
        for tool in wf.tool_types_used:
            category = TOOL_CATEGORY.get(tool)
            if tool in _HEAVY_NAMES or (category in _HEAVY_CATEGORIES):
                has_heavy = True
            elif category in _SOME_CATEGORIES:
                has_some = True
    if has_heavy:
        answers["advanced_tools"] = "heavy"
    elif has_some:
        answers["advanced_tools"] = "some"
    else:
        answers["advanced_tools"] = "none"

    return answers

"""Migration-profiler service — estate footprint, complexity, tool-difficulty tiers.

Wraps :func:`a2d.analyzer.profiler.build_estate_profile` over the same
``BatchAnalyzer`` output the ``analyze``/``portfolio`` surfaces use, so the web
"Profiler" page and the ``a2d assess`` CLI report identical numbers.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from a2d.analyzer.batch import BatchAnalyzer
from a2d.analyzer.profiler import ProfilerConfig, build_estate_profile
from server.utils.package import materialize_uploads

logger = logging.getLogger("a2d.server.services.assess")


def profile_estate(
    files: list[tuple[str, bytes]],
    *,
    show_hours: bool = False,
    overrides: dict | None = None,
) -> dict:
    """Profile uploaded workflows and return the estate-profile dict.

    ``overrides`` is an optional mapping of profiler-config overrides (same shape
    as the CLI ``--config`` file: ``category_tiers``, ``tool_overrides``, etc.),
    merged over the defaults. Raises :class:`ValueError` when nothing usable was
    supplied, or when an override is invalid, so the router can answer 4xx rather
    than returning an empty profile. ``.yxzp`` packages are unzipped first.
    """
    if not files:
        raise ValueError("at least one workflow file is required")

    cfg = ProfilerConfig.from_mapping(overrides) if overrides else ProfilerConfig.default()
    cfg.show_hours = show_hours or cfg.show_hours

    skipped: list[str] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        paths = materialize_uploads(files, Path(tmpdir), skipped=skipped)
        # Expand macros so a .yxzp's co-located .yxmc is inlined rather than
        # classified as an unsupported Unknown tier; no-op when no macro is present.
        analyses = BatchAnalyzer(expand_macros=True).analyze_files(paths)

    if not analyses:
        raise ValueError("no workflows could be analyzed")

    profile = build_estate_profile(analyses, cfg)

    logger.info(
        "Profiled estate: %d workflow(s), %d tools, hours=%s, skipped=%d",
        profile.total_workflows,
        profile.total_tools,
        show_hours,
        len(skipped),
    )
    result = profile.to_dict()
    # Surface any files that could not be read so the totals aren't mistaken for
    # a complete estate.
    result["skipped_files"] = skipped
    return result

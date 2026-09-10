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


def profile_estate(files: list[tuple[str, bytes]], *, show_hours: bool = False) -> dict:
    """Profile uploaded workflows and return the estate-profile dict.

    Raises :class:`ValueError` when nothing usable was supplied so the router can
    answer 422 rather than returning an empty profile that looks like a result.
    ``.yxzp`` packages are unzipped to their primary workflow first.
    """
    if not files:
        raise ValueError("at least one workflow file is required")

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = materialize_uploads(files, Path(tmpdir))
        analyses = BatchAnalyzer().analyze_files(paths)

    if not analyses:
        raise ValueError("no workflows could be analyzed")

    cfg = ProfilerConfig.default()
    cfg.show_hours = show_hours
    profile = build_estate_profile(analyses, cfg)

    logger.info(
        "Profiled estate: %d workflow(s), %d tools, hours=%s",
        profile.total_workflows,
        profile.total_tools,
        show_hours,
    )
    return profile.to_dict()

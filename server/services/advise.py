"""Advisor service — cluster sizing and Spark optimization hints for one workflow.

Deterministic and offline: this is a planning aid derived from the IR shape, not a
benchmark and not a quote. Mirrors the ``a2d advise`` CLI command and reuses
``AdvisorReport.to_dict()`` so both surfaces report the same numbers.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from a2d.advisor import CostPerformanceAdvisor
from a2d.config import ConversionConfig
from a2d.pipeline import ConversionPipeline
from server.utils.validation import sanitize_filename

logger = logging.getLogger("a2d.server.services.advise")

VALID_CLOUDS = ("aws", "azure", "gcp")


def advise_workflow(filename: str, content: bytes, cloud: str = "aws") -> dict:
    """Return a cluster recommendation plus performance hints for one workflow.

    Raises :class:`ValueError` for an unknown cloud or an unparseable workflow, so
    the router can map those to 422.
    """
    normalized = (cloud or "").strip().lower()
    if normalized not in VALID_CLOUDS:
        raise ValueError(f"unknown cloud {cloud!r}; valid: {', '.join(VALID_CLOUDS)}")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / sanitize_filename(filename)
        path.write_bytes(content)

        config = ConversionConfig(cloud=normalized)  # type: ignore[arg-type]
        pipeline = ConversionPipeline(config)
        parsed = pipeline._frontend.parse(path)
        dag = pipeline._build_dag(parsed)

        report = CostPerformanceAdvisor().analyze(dag, config, workflow_name=path.stem)

    logger.info(
        "Advisory for %s [%s]: tier=%s, %d hint(s)",
        filename,
        normalized,
        report.cluster.tier,
        len(report.hints),
    )
    return report.to_dict()

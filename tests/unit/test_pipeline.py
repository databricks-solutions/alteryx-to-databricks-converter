"""Smoke-level tests for ``a2d.pipeline.ConversionPipeline``.

The smoke + integration tests cover the full conversion flow; this module
focuses on shape-of-result invariants that the CLI/server depend on (e.g.
per-format ``duration_ms`` being non-negative).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from a2d.config import ConversionConfig, OutputFormat
from a2d.pipeline import (
    ConversionPipeline,
    FormatConversionResult,
    MultiFormatConversionResult,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "workflows"
SIMPLE_FIXTURE = FIXTURES_DIR / "simple_filter.yxmd"


@pytest.fixture
def pipeline(tmp_path: Path) -> ConversionPipeline:
    cfg = ConversionConfig(
        input_path=SIMPLE_FIXTURE,
        output_dir=tmp_path,
        output_format=OutputFormat.PYSPARK,
    )
    return ConversionPipeline(cfg)


class TestConvertAllFormats:
    def test_returns_all_four_formats(self, pipeline: ConversionPipeline) -> None:
        result = pipeline.convert_all_formats(SIMPLE_FIXTURE)
        assert isinstance(result, MultiFormatConversionResult)
        assert set(result.formats.keys()) == {"pyspark", "dlt", "sql", "lakeflow"}

    def test_per_format_duration_ms_recorded(self, pipeline: ConversionPipeline) -> None:
        result = pipeline.convert_all_formats(SIMPLE_FIXTURE)
        for fmt_key, fr in result.formats.items():
            assert isinstance(fr, FormatConversionResult), fmt_key
            # Generators take real time on a non-trivial fixture, so this
            # should always be > 0. Even if a generator failed, the timer
            # captures the time spent before the exception propagated.
            assert fr.duration_ms >= 0.0, fmt_key
        # At least one successful generator should have non-trivial duration —
        # otherwise we're not actually measuring anything.
        nonzero = [fr.duration_ms for fr in result.formats.values() if fr.duration_ms > 0]
        assert nonzero, "no format reported a positive duration_ms"

    def test_duration_ms_default_for_bare_dataclass(self) -> None:
        # Default-constructed FormatConversionResult should leave duration_ms
        # at 0.0 — used as a back-compat fallback by the CLI.
        fr = FormatConversionResult(format="pyspark", status="success", output=None)
        assert fr.duration_ms == 0.0

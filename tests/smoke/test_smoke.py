"""YAML-driven smoke tests for common conversion patterns.

Each YAML config file defines:
  - name: human-readable test name
  - input: path to .yxmd fixture (relative to repo root)
  - format: output format (pyspark, dlt, sql, lakeflow)
  - expect: assertions about the conversion output
    - min_confidence: minimum overall confidence score (0-100)
    - max_warnings: maximum number of warnings allowed
    - must_contain: strings that must appear in generated code
    - must_not_contain: strings that must NOT appear in generated code
    - min_nodes: minimum number of nodes in the DAG
    - success: whether conversion should succeed (default True)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from a2d.config import ConversionConfig, OutputFormat
from a2d.pipeline import ConversionPipeline

REPO_ROOT = Path(__file__).parent.parent.parent


def test_smoke_conversion(smoke_config: dict) -> None:
    """Run a single smoke test defined by a YAML config."""
    input_path = REPO_ROOT / smoke_config["input"]
    assert input_path.exists(), f"Fixture not found: {input_path}"

    fmt = smoke_config.get("format", "pyspark")
    output_format = OutputFormat(fmt)

    config = ConversionConfig(
        input_path=input_path,
        output_format=output_format,
        generate_orchestration=False,
    )

    pipeline = ConversionPipeline(config)
    expect = smoke_config.get("expect", {})

    if expect.get("success", True):
        result = pipeline.convert(input_path)

        # Get generated code content
        code_content = "\n".join(f.content for f in result.output.files)

        # Check minimum confidence score
        if "min_confidence" in expect:
            assert result.confidence is not None, "Confidence scoring returned None"
            assert result.confidence.overall >= expect["min_confidence"], (
                f"Confidence {result.confidence.overall:.1f} < min {expect['min_confidence']}"
            )

        # Check maximum warnings
        if "max_warnings" in expect:
            assert len(result.warnings) <= expect["max_warnings"], (
                f"Got {len(result.warnings)} warnings (max {expect['max_warnings']}): " + "; ".join(result.warnings[:5])
            )

        # Check must_contain
        for pattern in expect.get("must_contain", []):
            assert pattern in code_content, f"Expected '{pattern}' in generated code but not found"

        # Check must_not_contain
        for pattern in expect.get("must_not_contain", []):
            assert pattern not in code_content, f"Unexpected '{pattern}' found in generated code"

        # Check minimum node count
        if "min_nodes" in expect:
            assert result.dag.node_count >= expect["min_nodes"], (
                f"DAG has {result.dag.node_count} nodes (min {expect['min_nodes']})"
            )

    else:
        # Expect failure
        with pytest.raises(Exception):
            pipeline.convert(input_path)

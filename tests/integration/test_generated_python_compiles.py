"""Every Python file generated from the real workflows compiles, with no escape warnings.

The Packt corpus has caught real breakage: a multi-line Alteryx expression quoted
in a one-line comment, a placeholder comment that swallowed the next formula's
comma, a regex pattern with quotes in it.
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import pytest

from a2d.config import ConversionConfig
from a2d.pipeline import ConversionPipeline

FIXTURES = Path(__file__).parent.parent / "fixtures"
WORKFLOWS = sorted((FIXTURES / "packt").glob("*.yxmd")) + sorted((FIXTURES / "looping_macros").glob("*/*.yxmd"))


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.stem)
def test_generated_python_compiles(path: Path) -> None:
    logging.disable(logging.WARNING)
    try:
        result = ConversionPipeline(ConversionConfig(input_path=path, expand_macros=True)).convert_all_formats(path)
    finally:
        logging.disable(logging.NOTSET)
    files = [f for r in result.formats.values() if r.output for f in r.output.files if f.filename.endswith(".py")]
    assert files
    for f in files:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            compile(f.content, f.filename, "exec")

"""Test the `a2d sync` command."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from a2d.cli import app

runner = CliRunner()

WORKFLOWS = Path(__file__).parent.parent.parent / "fixtures" / "workflows"


def _seed(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy(WORKFLOWS / "simple_filter.yxmd", src / "simple_filter.yxmd")
    shutil.copy(WORKFLOWS / "join_and_summarize.yxmd", src / "join_and_summarize.yxmd")
    return src


class TestSyncCommand:
    def test_first_run_converts_all(self, tmp_path):
        src = _seed(tmp_path)
        out = tmp_path / "out"
        manifest = tmp_path / "m.json"
        rjson = tmp_path / "r.json"
        result = runner.invoke(
            app,
            [
                "sync",
                str(src),
                "-o",
                str(out),
                "--manifest",
                str(manifest),
                "-f",
                "pyspark",
                "--json",
                str(rjson),
                "-q",
            ],
        )
        assert result.exit_code == 0, result.output
        summary = json.loads(rjson.read_text())["summary"]
        assert summary["converted"] == 2
        assert manifest.exists()

    def test_second_run_skips(self, tmp_path):
        src = _seed(tmp_path)
        out = tmp_path / "out"
        manifest = tmp_path / "m.json"
        args = ["sync", str(src), "-o", str(out), "--manifest", str(manifest), "-f", "pyspark", "-q"]
        runner.invoke(app, args)
        rjson = tmp_path / "r2.json"
        runner.invoke(app, [*args, "--json", str(rjson)])
        summary = json.loads(rjson.read_text())["summary"]
        assert summary["converted"] == 0
        assert summary["skipped"] == 2

    def test_not_a_directory_errors(self, tmp_path):
        f = tmp_path / "x.yxmd"
        f.write_text("<x/>")
        result = runner.invoke(app, ["sync", str(f), "-q"])
        assert result.exit_code == 1
        assert "not a directory" in result.output

"""Test the `a2d plugins` command."""

from __future__ import annotations

from typer.testing import CliRunner

from a2d.cli import app

runner = CliRunner()


def test_plugins_lists_frontends_and_contract_version():
    result = runner.invoke(app, ["plugins"])
    assert result.exit_code == 0, result.output
    assert "SDK contract" in result.output
    # Built-in frontends are always listed.
    assert "alteryx" in result.output
    assert "dbt" in result.output


def test_plugins_reports_no_converter_plugins_by_default():
    result = runner.invoke(app, ["plugins"])
    assert result.exit_code == 0
    assert "No third-party converter plugins installed" in result.output

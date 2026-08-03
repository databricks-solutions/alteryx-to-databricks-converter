"""Tests for the dbt frontend."""

from __future__ import annotations

from pathlib import Path

import pytest

from a2d.exceptions import ParseError
from a2d.frontends.dbt import DbtFrontend

DBT_DIR = Path(__file__).parent.parent.parent / "fixtures" / "dbt"
MANIFEST = DBT_DIR / "manifest.json"


class TestCanParse:
    def test_recognizes_manifest_file(self):
        assert DbtFrontend().can_parse(MANIFEST)

    def test_recognizes_dir_with_manifest(self):
        assert DbtFrontend().can_parse(DBT_DIR)

    def test_rejects_yxmd(self, tmp_path):
        p = tmp_path / "x.yxmd"
        p.write_text("<x/>")
        assert not DbtFrontend().can_parse(p)


class TestParse:
    def _parse(self):
        return DbtFrontend().parse(MANIFEST)

    def test_source_and_seed_become_inputs(self):
        wf = self._parse()
        inputs = [n for n in wf.nodes if n.tool_type == "Input"]
        names = {n.configuration["TableName"] for n in inputs}
        assert "raw.public.orders" in names  # source
        assert "analytics.seeds.country_codes" in names  # seed

    def test_models_become_outputs(self):
        wf = self._parse()
        outputs = {n.configuration["TableName"] for n in wf.nodes if n.tool_type == "Output"}
        assert "analytics.staging.stg_orders" in outputs
        assert "analytics.marts.fct_orders" in outputs

    def test_tests_are_excluded(self):
        wf = self._parse()
        assert all("not_null" not in (n.annotation or "") for n in wf.nodes)

    def test_dependency_edges(self):
        wf = self._parse()
        # fct_orders depends on stg_orders AND the seed → 2 incoming edges to it.
        by_name = {n.tool_id: n for n in wf.nodes}
        fct_id = next(n.tool_id for n in wf.nodes if n.annotation == "fct_orders")
        incoming = [c for c in wf.connections if c.destination.tool_id == fct_id]
        assert len(incoming) == 2
        upstream_tables = {by_name[c.origin.tool_id].configuration["TableName"] for c in incoming}
        assert "analytics.staging.stg_orders" in upstream_tables

    def test_incremental_materialization_is_append(self):
        wf = self._parse()
        fct = next(n for n in wf.nodes if n.annotation == "fct_orders")
        assert fct.configuration["WriteMode"] == "append"

    def test_view_materialization_is_overwrite(self):
        wf = self._parse()
        stg = next(n for n in wf.nodes if n.annotation == "stg_orders")
        assert stg.configuration["WriteMode"] == "overwrite"

    def test_metadata_captured(self):
        wf = self._parse()
        assert wf.properties["project_name"] == "demo_shop"
        assert wf.alteryx_version.startswith("dbt:")

    def test_missing_manifest_raises(self, tmp_path):
        with pytest.raises(ParseError, match="no dbt manifest"):
            DbtFrontend().parse(tmp_path)

    def test_corrupt_manifest_raises(self, tmp_path):
        bad = tmp_path / "manifest.json"
        bad.write_text("{ not json")
        with pytest.raises(ParseError, match="could not read"):
            DbtFrontend().parse(bad)

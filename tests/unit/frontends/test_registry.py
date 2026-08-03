"""Tests for the frontend registry (resolution + plugin discovery)."""

from __future__ import annotations

from pathlib import Path

import pytest

from a2d.frontends.alteryx import AlteryxFrontend
from a2d.frontends.base import SourceFrontend
from a2d.frontends.dbt import DbtFrontend
from a2d.frontends.registry import FrontendRegistry
from a2d.parser.schema import ParsedWorkflow

DBT_DIR = Path(__file__).parent.parent.parent / "fixtures" / "dbt"


class TestBuiltins:
    def test_builtin_names(self):
        names = FrontendRegistry.names()
        assert "alteryx" in names
        assert "dbt" in names

    def test_get_by_name(self):
        assert isinstance(FrontendRegistry.get("alteryx"), AlteryxFrontend)
        assert isinstance(FrontendRegistry.get("dbt"), DbtFrontend)

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError, match="unknown frontend"):
            FrontendRegistry.get("informatica")


class TestResolution:
    def test_yxmd_autodetects_alteryx(self):
        assert FrontendRegistry.for_path(Path("wf.yxmd")).name == "alteryx"

    def test_dbt_dir_autodetects_dbt(self):
        assert FrontendRegistry.for_path(DBT_DIR).name == "dbt"

    def test_unknown_extension_falls_back_to_alteryx(self):
        assert FrontendRegistry.for_path(Path("mystery.foo")).name == "alteryx"

    def test_explicit_name_overrides_detection(self):
        assert FrontendRegistry.resolve(Path("wf.yxmd"), "dbt").name == "dbt"

    def test_resolve_without_name_autodetects(self):
        assert FrontendRegistry.resolve(DBT_DIR).name == "dbt"


class TestRegisterCustom:
    def test_register_and_retrieve(self):
        class _Custom(SourceFrontend):
            name = "custom_test_fe"

            @property
            def supported_extensions(self):
                return [".custom"]

            def parse(self, path):
                return ParsedWorkflow(file_path=str(path), alteryx_version="custom")

        FrontendRegistry.register(_Custom())
        try:
            assert FrontendRegistry.for_path(Path("x.custom")).name == "custom_test_fe"
        finally:
            FrontendRegistry._frontends.pop("custom_test_fe", None)

    def test_register_without_name_raises(self):
        class _NoName(SourceFrontend):
            @property
            def supported_extensions(self):
                return []

            def parse(self, path):
                return ParsedWorkflow(file_path=str(path), alteryx_version="x")

        with pytest.raises(ValueError, match="no name"):
            FrontendRegistry.register(_NoName())

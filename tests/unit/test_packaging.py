"""Tests for a2d.packaging — safe .yxzp extraction and primary-workflow selection."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from a2d.packaging import (
    PackageError,
    extract_package,
    extract_primary_workflow,
    find_primary_workflow,
    is_package,
)

_WF_XML = '<AlteryxDocument yxmdVer="1"><Nodes/><Connections/></AlteryxDocument>'


def _zip_bytes(members: dict[str, str], *, compress: bool = False) -> bytes:
    buf = io.BytesIO()
    mode = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buf, "w", mode) as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return buf.getvalue()


class TestIsPackage:
    def test_yxzp_is_package(self):
        assert is_package("MyApp.yxzp")
        assert is_package(Path("nested/MyApp.YXZP"))  # case-insensitive

    def test_others_are_not(self):
        assert not is_package("a.yxmd")
        assert not is_package("a.yxwz")
        assert not is_package("a.yxmc")


class TestExtractPackage:
    def test_happy_path_extracts_all_and_colocates_macros(self, tmp_path):
        data = _zip_bytes(
            {
                "MyApp.yxwz": _WF_XML,
                "macros/Clean.yxmc": _WF_XML,
                "data/sample.csv": "a,b\n1,2\n",
            }
        )
        extracted = extract_package(data, tmp_path)
        names = {p.name for p in extracted}
        assert names == {"MyApp.yxwz", "Clean.yxmc", "sample.csv"}
        assert (tmp_path / "macros" / "Clean.yxmc").exists()

    def test_accepts_path_source(self, tmp_path):
        pkg = tmp_path / "pkg.yxzp"
        pkg.write_bytes(_zip_bytes({"W.yxmd": _WF_XML}))
        out = tmp_path / "out"
        extracted = extract_package(pkg, out)
        assert [p.name for p in extracted] == ["W.yxmd"]

    def test_zip_slip_rejected(self, tmp_path):
        data = _zip_bytes({"../evil.yxmd": "x"})
        with pytest.raises(PackageError, match="unsafe path"):
            extract_package(data, tmp_path)

    def test_absolute_path_rejected(self, tmp_path):
        # Build an entry with a leading-slash name.
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("/etc/evil.yxmd", "x")
        with pytest.raises(PackageError, match="unsafe path"):
            extract_package(buf.getvalue(), tmp_path)

    def test_member_count_cap(self, tmp_path):
        data = _zip_bytes({f"f{i}.txt": "x" for i in range(5)})
        with pytest.raises(PackageError, match="too many entries"):
            extract_package(data, tmp_path, max_members=4)

    def test_zip_bomb_cap_on_written_bytes(self, tmp_path):
        data = _zip_bytes({"MyApp.yxmd": "A" * 1_000_000}, compress=True)
        with pytest.raises(PackageError, match="expands beyond"):
            extract_package(data, tmp_path, max_total_bytes=1000)

    def test_bad_zip_bytes(self, tmp_path):
        with pytest.raises(PackageError, match="bad ZIP archive"):
            extract_package(b"not a zip at all", tmp_path)


class TestFindPrimaryWorkflow:
    def test_single_workflow(self, tmp_path):
        p = tmp_path / "a.yxwz"
        assert find_primary_workflow([p, tmp_path / "m.yxmc"], tmp_path) == p

    def test_no_workflow(self, tmp_path):
        with pytest.raises(PackageError, match="no .yxmd or .yxwz"):
            find_primary_workflow([tmp_path / "only.yxmc"], tmp_path)

    def test_prefers_root_level_when_multiple(self, tmp_path):
        root = tmp_path / "top.yxmd"
        nested = tmp_path / "sub" / "inner.yxwz"
        assert find_primary_workflow([nested, root], tmp_path) == root

    def test_ambiguous_same_depth_raises(self, tmp_path):
        a = tmp_path / "a.yxmd"
        b = tmp_path / "b.yxwz"
        with pytest.raises(PackageError, match="multiple candidate workflows"):
            find_primary_workflow([a, b], tmp_path)


class TestExtractPrimaryWorkflow:
    def test_end_to_end(self, tmp_path):
        data = _zip_bytes({"MyApp.yxwz": _WF_XML, "macros/Clean.yxmc": _WF_XML})
        primary = extract_primary_workflow(data, tmp_path)
        assert primary.name == "MyApp.yxwz"
        assert primary.exists()
        assert (tmp_path / "macros" / "Clean.yxmc").exists()

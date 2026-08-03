"""Tests for the incremental manifest tracker and sync."""

from __future__ import annotations

from pathlib import Path

from a2d.incremental import ManifestTracker, sync_directory


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


class TestManifestTracker:
    def test_new_file_needs_conversion(self, tmp_path):
        f = _write(tmp_path / "a.yxmd", "<x/>")
        tracker = ManifestTracker(tmp_path / "m.json")
        assert tracker.needs_conversion(f) is True

    def test_recorded_file_is_skipped(self, tmp_path):
        f = _write(tmp_path / "a.yxmd", "<x/>")
        tracker = ManifestTracker(tmp_path / "m.json")
        tracker.record(f)
        assert tracker.needs_conversion(f) is False

    def test_modified_file_needs_reconversion(self, tmp_path):
        f = _write(tmp_path / "a.yxmd", "<x/>")
        tracker = ManifestTracker(tmp_path / "m.json")
        tracker.record(f)
        _write(f, "<x/><!-- changed -->")
        assert tracker.needs_conversion(f) is True

    def test_persistence_roundtrip(self, tmp_path):
        f = _write(tmp_path / "a.yxmd", "<x/>")
        m = tmp_path / "m.json"
        t1 = ManifestTracker(m)
        t1.record(f)
        t1.save()
        # Fresh tracker reads the manifest and skips the unchanged file.
        t2 = ManifestTracker(m)
        assert t2.needs_conversion(f) is False

    def test_prune_removes_deleted(self, tmp_path):
        f = _write(tmp_path / "a.yxmd", "<x/>")
        tracker = ManifestTracker(tmp_path / "m.json")
        tracker.record(f)
        removed = tracker.prune(existing=set())  # nothing exists anymore
        assert removed == [str(f)]
        assert tracker.tracked_paths() == []

    def test_corrupt_manifest_is_ignored(self, tmp_path):
        m = tmp_path / "m.json"
        m.write_text("{ not json")
        tracker = ManifestTracker(m)
        # Degrades to empty (full reconversion), never raises.
        assert tracker.tracked_paths() == []

    def test_output_hash_recorded(self, tmp_path):
        f = _write(tmp_path / "a.yxmd", "<x/>")
        tracker = ManifestTracker(tmp_path / "m.json")
        state = tracker.record(f, output_contents=["generated code"])
        assert state.output_hash


class TestSyncDirectory:
    def _mk_dir(self, tmp_path):
        d = tmp_path / "src"
        d.mkdir()
        _write(d / "a.yxmd", "<a/>")
        _write(d / "b.yxmd", "<b/>")
        return d

    def test_first_pass_converts_all(self, tmp_path):
        d = self._mk_dir(tmp_path)
        converted = []
        tracker = ManifestTracker(tmp_path / "m.json")
        result = sync_directory(d, lambda p: converted.append(p) or ["code"], tracker)
        assert len(result.converted) == 2
        assert len(result.skipped) == 0

    def test_second_pass_skips_unchanged(self, tmp_path):
        d = self._mk_dir(tmp_path)
        tracker = ManifestTracker(tmp_path / "m.json")
        sync_directory(d, lambda p: ["code"], tracker)
        result2 = sync_directory(d, lambda p: ["code"], tracker)
        assert len(result2.converted) == 0
        assert len(result2.skipped) == 2

    def test_modified_file_reconverted(self, tmp_path):
        d = self._mk_dir(tmp_path)
        tracker = ManifestTracker(tmp_path / "m.json")
        sync_directory(d, lambda p: ["code"], tracker)
        _write(d / "a.yxmd", "<a/><!-- changed -->")
        result = sync_directory(d, lambda p: ["code"], tracker)
        assert len(result.converted) == 1
        assert len(result.skipped) == 1

    def test_deleted_file_pruned(self, tmp_path):
        d = self._mk_dir(tmp_path)
        tracker = ManifestTracker(tmp_path / "m.json")
        sync_directory(d, lambda p: ["code"], tracker)
        (d / "b.yxmd").unlink()
        result = sync_directory(d, lambda p: ["code"], tracker)
        assert result.removed == [str(d / "b.yxmd")]

    def test_conversion_failure_is_isolated(self, tmp_path):
        d = self._mk_dir(tmp_path)
        tracker = ManifestTracker(tmp_path / "m.json")

        def _convert(path):
            if path.name == "a.yxmd":
                raise ValueError("boom")
            return ["code"]

        result = sync_directory(d, _convert, tracker)
        assert len(result.failed) == 1
        assert len(result.converted) == 1
        # The failed file is not recorded, so it retries next pass.
        assert tracker.needs_conversion(d / "a.yxmd") is True

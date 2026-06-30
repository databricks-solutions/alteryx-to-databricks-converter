"""Tests for a2d.observability.metrics module."""

from __future__ import annotations

from datetime import datetime, timezone

from a2d.observability.metrics import BatchMetrics, FileMetrics


class TestFileMetrics:
    def test_defaults(self):
        m = FileMetrics()
        assert m.file_path == ""
        assert m.workflow_name == ""
        assert m.started_at is None
        assert m.completed_at is None
        assert m.duration_seconds == 0.0
        assert m.node_count == 0
        assert m.edge_count == 0
        assert m.supported_node_count == 0
        assert m.unsupported_node_count == 0
        assert m.coverage_percentage == 0.0
        assert m.files_generated == 0
        assert m.success is False

    def test_creation_with_values(self):
        now = datetime.now(timezone.utc)
        m = FileMetrics(
            file_path="/test.yxmd",
            workflow_name="test",
            started_at=now,
            completed_at=now,
            duration_seconds=1.5,
            node_count=10,
            edge_count=9,
            supported_node_count=8,
            unsupported_node_count=2,
            coverage_percentage=80.0,
            files_generated=3,
            success=True,
        )
        assert m.file_path == "/test.yxmd"
        assert m.node_count == 10
        assert m.success is True

    def test_to_dict(self):
        now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        m = FileMetrics(
            file_path="/test.yxmd",
            workflow_name="test",
            started_at=now,
            completed_at=now,
            duration_seconds=2.0,
            node_count=5,
            edge_count=4,
            supported_node_count=5,
            unsupported_node_count=0,
            coverage_percentage=100.0,
            files_generated=2,
            success=True,
        )
        d = m.to_dict()
        assert d["file_path"] == "/test.yxmd"
        assert d["started_at"] == "2025-01-15T12:00:00+00:00"
        assert d["completed_at"] == "2025-01-15T12:00:00+00:00"
        assert d["duration_seconds"] == 2.0
        assert d["success"] is True

    def test_to_dict_none_timestamps(self):
        m = FileMetrics()
        d = m.to_dict()
        assert d["started_at"] is None
        assert d["completed_at"] is None


class TestBatchMetrics:
    def test_defaults(self):
        m = BatchMetrics()
        assert m.total_files == 0
        assert m.successful_files == 0
        assert m.failed_files == 0
        assert m.partial_files == 0
        assert m.total_nodes == 0
        assert m.total_errors == 0
        assert m.total_warnings == 0
        assert m.avg_coverage_percentage == 0.0

    def test_creation_with_values(self):
        now = datetime.now(timezone.utc)
        m = BatchMetrics(
            started_at=now,
            completed_at=now,
            duration_seconds=5.0,
            total_files=10,
            successful_files=8,
            failed_files=1,
            partial_files=1,
            total_nodes=100,
            total_errors=2,
            total_warnings=5,
            avg_coverage_percentage=85.0,
        )
        assert m.total_files == 10
        assert m.successful_files == 8

    def test_to_dict(self):
        m = BatchMetrics(
            total_files=3,
            successful_files=2,
            failed_files=1,
            total_errors=1,
        )
        d = m.to_dict()
        assert d["total_files"] == 3
        assert d["successful_files"] == 2
        assert d["failed_files"] == 1
        assert d["total_errors"] == 1
        assert d["started_at"] is None

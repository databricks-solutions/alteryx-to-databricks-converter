"""Per-file and aggregate metrics for batch conversions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class FileMetrics:
    """Metrics for a single file conversion."""

    file_path: str = ""
    workflow_name: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float = 0.0
    node_count: int = 0
    edge_count: int = 0
    supported_node_count: int = 0
    unsupported_node_count: int = 0
    coverage_percentage: float = 0.0
    files_generated: int = 0
    success: bool = False

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON output."""
        return {
            "file_path": self.file_path,
            "workflow_name": self.workflow_name,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "supported_node_count": self.supported_node_count,
            "unsupported_node_count": self.unsupported_node_count,
            "coverage_percentage": self.coverage_percentage,
            "files_generated": self.files_generated,
            "success": self.success,
        }


@dataclass
class BatchMetrics:
    """Aggregate metrics for a batch conversion run."""

    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float = 0.0
    total_files: int = 0
    successful_files: int = 0
    failed_files: int = 0
    partial_files: int = 0
    total_nodes: int = 0
    total_errors: int = 0
    total_warnings: int = 0
    avg_coverage_percentage: float = 0.0

    def to_dict(self) -> dict:
        """Serialize to a plain dict for JSON output."""
        return {
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds,
            "total_files": self.total_files,
            "successful_files": self.successful_files,
            "failed_files": self.failed_files,
            "partial_files": self.partial_files,
            "total_nodes": self.total_nodes,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "avg_coverage_percentage": self.avg_coverage_percentage,
        }

"""Continuous / incremental migration.

Re-converting an entire gallery on every run is wasteful when only a few
workflows changed. This package tracks each source file's content hash in a
JSON manifest and re-converts only what's new or modified.

* :class:`ManifestTracker` — persistent per-file state (content hash + output
  fingerprint + timestamp), with change detection.
* :func:`sync_directory` — scan a directory, convert only changed/new files,
  record results, and report what was skipped / converted / removed.

Exposed as the ``a2d sync`` CLI command (a single incremental pass; run it on a
schedule or in a loop to approximate "watch").
"""

from __future__ import annotations

from a2d.incremental.tracker import (
    FileState,
    ManifestTracker,
    SyncResult,
    sync_directory,
)

__all__ = [
    "FileState",
    "ManifestTracker",
    "SyncResult",
    "sync_directory",
]

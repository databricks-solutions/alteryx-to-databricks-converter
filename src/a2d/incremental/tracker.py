"""Manifest-based change tracking for incremental re-conversion."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("a2d.incremental.tracker")

_MANIFEST_VERSION = 1


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class FileState:
    """Recorded state for one converted source file."""

    path: str
    source_hash: str
    converted_at: str  # ISO-8601 UTC
    output_hash: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "source_hash": self.source_hash,
            "converted_at": self.converted_at,
            "output_hash": self.output_hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FileState:
        return cls(
            path=data["path"],
            source_hash=data["source_hash"],
            converted_at=data.get("converted_at", ""),
            output_hash=data.get("output_hash", ""),
        )


class ManifestTracker:
    """Load/save per-file conversion state and detect changes.

    The manifest is a JSON document keyed by (string) file path. It never raises
    on a missing/corrupt manifest — it starts empty and logs a warning — so a
    bad manifest degrades to a full re-conversion rather than an error.
    """

    def __init__(self, manifest_path: Path) -> None:
        self.manifest_path = manifest_path
        self._states: dict[str, FileState] = {}
        self._loaded = False

    def load(self) -> ManifestTracker:
        if self._loaded:
            return self
        self._loaded = True
        if not self.manifest_path.exists():
            return self
        try:
            doc = json.loads(self.manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable manifest %s: %s", self.manifest_path, exc)
            return self
        for entry in doc.get("files", []):
            try:
                state = FileState.from_dict(entry)
            except (KeyError, TypeError) as exc:
                logger.warning("Skipping malformed manifest entry: %s", exc)
                continue
            self._states[state.path] = state
        return self

    def save(self) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "version": _MANIFEST_VERSION,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "files": [s.to_dict() for s in self._states.values()],
        }
        tmp = self.manifest_path.with_suffix(self.manifest_path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, indent=2) + "\n")
        tmp.replace(self.manifest_path)

    # -- Change detection --

    def source_hash(self, path: Path) -> str:
        return _hash_bytes(path.read_bytes())

    def needs_conversion(self, path: Path) -> bool:
        """True if *path* is new or its contents changed since last conversion."""
        self.load()
        prev = self._states.get(str(path))
        if prev is None:
            return True
        return prev.source_hash != self.source_hash(path)

    def record(self, path: Path, output_contents: list[str] | None = None) -> FileState:
        """Record a successful conversion of *path*."""
        self.load()
        output_hash = ""
        if output_contents:
            output_hash = _hash_bytes(" ".join(output_contents).encode("utf-8"))
        state = FileState(
            path=str(path),
            source_hash=self.source_hash(path),
            converted_at=datetime.now(timezone.utc).isoformat(),
            output_hash=output_hash,
        )
        self._states[str(path)] = state
        return state

    def prune(self, existing: set[str]) -> list[str]:
        """Drop manifest entries whose source file no longer exists.

        Returns the list of removed paths.
        """
        self.load()
        removed = [p for p in self._states if p not in existing]
        for p in removed:
            del self._states[p]
        return removed

    def tracked_paths(self) -> list[str]:
        self.load()
        return sorted(self._states)


@dataclass
class SyncResult:
    """Outcome of one incremental sync pass over a directory."""

    converted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (path, error)
    removed: list[str] = field(default_factory=list)

    @property
    def total_seen(self) -> int:
        return len(self.converted) + len(self.skipped) + len(self.failed)

    def to_dict(self) -> dict:
        return {
            "converted": self.converted,
            "skipped": self.skipped,
            "failed": [{"path": p, "error": e} for p, e in self.failed],
            "removed": self.removed,
            "summary": {
                "seen": self.total_seen,
                "converted": len(self.converted),
                "skipped": len(self.skipped),
                "failed": len(self.failed),
                "removed": len(self.removed),
            },
        }


def sync_directory(
    directory: Path,
    convert_fn: Callable[[Path], list[str]],
    tracker: ManifestTracker,
    *,
    pattern: str = "**/*.yxmd",
    prune: bool = True,
) -> SyncResult:
    """Convert only changed/new files under *directory*, updating *tracker*.

    ``convert_fn(path)`` performs the conversion and returns the generated file
    contents (used for the output fingerprint); it may raise to signal failure.
    The manifest is saved once at the end.
    """
    tracker.load()
    result = SyncResult()

    files = sorted(directory.glob(pattern))
    seen: set[str] = set()

    for path in files:
        seen.add(str(path))
        if not tracker.needs_conversion(path):
            result.skipped.append(str(path))
            continue
        try:
            contents = convert_fn(path)
        except Exception as exc:  # a bad file must not abort the whole sweep
            logger.warning("Failed to convert %s: %s", path, exc)
            result.failed.append((str(path), str(exc)))
            continue
        tracker.record(path, contents)
        result.converted.append(str(path))

    if prune:
        result.removed = tracker.prune(seen)

    tracker.save()
    return result

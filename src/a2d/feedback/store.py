"""Persistent store for learned conversion mappings (JSON-backed)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from a2d.feedback.models import FeedbackStats, LearnedMapping, config_signature
from a2d.llm.models import ConversionCandidate

logger = logging.getLogger("a2d.feedback.store")


def default_store_path() -> Path:
    """Return the default feedback-store location.

    Honours ``A2D_FEEDBACK_STORE`` if set, else ``~/.a2d/feedback.json``.
    """
    override = os.environ.get("A2D_FEEDBACK_STORE")
    if override:
        return Path(override)
    return Path.home() / ".a2d" / "feedback.json"


class FeedbackStore:
    """Load/save learned mappings, keyed by tool+config signature.

    The store is a flat JSON document; it is loaded lazily and written
    atomically. It never raises on a missing/corrupt file — it starts empty and
    logs a warning — so a bad store can never break a conversion run.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_store_path()
        self._mappings: dict[str, LearnedMapping] = {}
        self._loaded = False

    # -- Persistence --

    def load(self) -> FeedbackStore:
        """Load mappings from disk (idempotent)."""
        if self._loaded:
            return self
        self._loaded = True
        if not self.path.exists():
            return self
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Ignoring unreadable feedback store %s: %s", self.path, exc)
            return self
        for entry in data.get("mappings", []):
            try:
                mapping = LearnedMapping.from_dict(entry)
            except (KeyError, TypeError) as exc:
                logger.warning("Skipping malformed feedback entry: %s", exc)
                continue
            self._mappings[mapping.signature] = mapping
        return self

    def save(self) -> None:
        """Write mappings to disk atomically."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"mappings": [m.to_dict() for m in self._mappings.values()]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, indent=2) + "\n")
        tmp.replace(self.path)

    # -- Access --

    def get(self, tool_type: str, configuration: dict) -> LearnedMapping | None:
        """Return the learned mapping for a tool+config shape, if any."""
        self.load()
        return self._mappings.get(config_signature(tool_type, configuration))

    def all_mappings(self) -> list[LearnedMapping]:
        self.load()
        return list(self._mappings.values())

    def record(
        self,
        tool_type: str,
        configuration: dict,
        candidate: ConversionCandidate,
        *,
        source: str = "verified",
        save: bool = True,
    ) -> LearnedMapping:
        """Capture an accepted conversion as a learned mapping.

        If a mapping already exists for this signature it is updated (its use
        count carried forward and incremented); otherwise a new one is created.
        """
        self.load()
        signature = config_signature(tool_type, configuration)
        existing = self._mappings.get(signature)
        uses = (existing.uses if existing else 0) + 1
        mapping = LearnedMapping(
            signature=signature,
            tool_type=tool_type,
            candidate_nodes=list(candidate.nodes),
            output_ref=candidate.output_ref,
            rationale=candidate.rationale,
            uses=uses,
            source=source,
        )
        self._mappings[signature] = mapping
        if save:
            self.save()
        return mapping

    def stats(self) -> FeedbackStats:
        self.load()
        by_tool: dict[str, int] = {}
        total_uses = 0
        for m in self._mappings.values():
            by_tool[m.tool_type] = by_tool.get(m.tool_type, 0) + 1
            total_uses += m.uses
        return FeedbackStats(total_mappings=len(self._mappings), total_uses=total_uses, by_tool=by_tool)

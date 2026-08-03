"""Interactive review workspace — per-node canvas ↔ generated-code model.

The web UI's review workspace shows the Alteryx canvas beside the generated
code and lets a reviewer accept or edit each node's conversion. This package
builds the backend model that powers it: a :class:`ReviewSession` pairing every
IR node with its generated code cell, confidence, warnings, and a review
*status* (auto-accepted / needs-review / cannot-convert), plus mutable per-node
review state (accepted / edited / rejected) with an edit override.

The assembler reuses each generator's existing per-node ``# Step <id>:`` cell
boundary, so the code shown per node is exactly what the generator emits — no
second code path to drift.

* :mod:`a2d.review.models` — :class:`ReviewNode` / :class:`ReviewSession`.
* :mod:`a2d.review.builder` — build a session from an IR DAG.
"""

from __future__ import annotations

from a2d.review.builder import build_review_session
from a2d.review.models import (
    ReviewNode,
    ReviewSession,
    ReviewStatus,
    node_review_status,
)

__all__ = [
    "ReviewNode",
    "ReviewSession",
    "ReviewStatus",
    "build_review_session",
    "node_review_status",
]

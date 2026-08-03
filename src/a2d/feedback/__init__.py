"""Feedback / correction capture — learn conversion mappings from user edits.

When a human accepts or corrects a conversion for an otherwise-unsupported tool,
that decision is worth remembering: the next time the same tool shows up with a
similar configuration, a2d should propose the learned conversion instead of
falling back to a TODO stub.

This package persists accepted conversions as :class:`LearnedMapping` records
(keyed by tool type + a configuration signature) and exposes them as an
:class:`LearnedClient` proposer. Crucially, a learned mapping is *still* a
proposal — it re-enters the same equivalence gate as any LLM candidate, so a
mapping that stops being correct (e.g. a schema changed) is caught rather than
trusted blindly.

* :mod:`a2d.feedback.models` — :class:`LearnedMapping` and signatures.
* :mod:`a2d.feedback.store` — :class:`FeedbackStore` (JSON-backed persistence).
* :mod:`a2d.feedback.client` — :class:`LearnedClient` (a store-backed proposer).
"""

from __future__ import annotations

from a2d.feedback.client import LearnedClient
from a2d.feedback.models import LearnedMapping, config_signature
from a2d.feedback.store import FeedbackStore, default_store_path

__all__ = [
    "FeedbackStore",
    "LearnedClient",
    "LearnedMapping",
    "config_signature",
    "default_store_path",
]

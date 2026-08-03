"""A store-backed proposer that replays learned mappings, then falls back.

:class:`LearnedClient` implements the :class:`~a2d.llm.client.LLMClient`
protocol. It first offers any learned mapping matching the node's tool+config
signature (so previously-accepted conversions are proposed first), then defers
to a wrapped fallback client (the offline stub or a real model client) for
tools it hasn't seen. Because it emits ordinary ``ConversionCandidate`` objects,
learned mappings pass through exactly the same verification gate as any other
proposal — a mapping that has silently gone stale is caught, not trusted.
"""

from __future__ import annotations

from a2d.feedback.store import FeedbackStore
from a2d.llm.client import LLMClient, get_default_client
from a2d.llm.models import ConversionCandidate, ConversionRequest


class LearnedClient:
    """Propose learned mappings first, then defer to a fallback client."""

    def __init__(self, store: FeedbackStore | None = None, fallback: LLMClient | None = None) -> None:
        self.store = (store or FeedbackStore()).load()
        self.fallback = fallback if fallback is not None else get_default_client()

    def propose(self, request: ConversionRequest, *, max_candidates: int = 3) -> list[ConversionCandidate]:
        candidates: list[ConversionCandidate] = []

        mapping = self.store.get(request.tool_type, request.configuration)
        if mapping is not None:
            candidates.append(mapping.to_candidate())

        if len(candidates) < max_candidates:
            for cand in self.fallback.propose(request, max_candidates=max_candidates):
                candidates.append(cand)
                if len(candidates) >= max_candidates:
                    break

        return candidates[:max_candidates]

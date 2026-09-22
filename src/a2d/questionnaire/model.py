"""Config and result models for the readiness questionnaire.

``QuestionnaireConfig`` follows the same ``default`` / ``from_mapping`` /
``from_file`` contract as :class:`~a2d.analyzer.profiler.ProfilerConfig`, so the
CLI ``--config`` file and the ``/api/readiness`` endpoint share one merge path.
Only the *weights* and *thresholds* are configurable — the question bank itself is
fixed content (see :mod:`a2d.questionnaire.bank`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from a2d.questionnaire.bank import DIMENSIONS

# Tiers from highest bar down. A score lands in the first tier whose ``min_score``
# it meets. Names/labels chosen to read as a maturity ramp.
DEFAULT_TIERS: list[dict] = [
    {"name": "Advanced", "min_score": 80.0},
    {"name": "Ready", "min_score": 60.0},
    {"name": "Developing", "min_score": 40.0},
    {"name": "Not Ready", "min_score": 0.0},
]

# Selected options scoring below this surface their tip in the result.
DEFAULT_TIP_THRESHOLD = 70.0


def _finite_float(value: object, name: str) -> float:
    """Coerce to a finite float or raise ValueError (mapped to 4xx, never 500).

    A bare ``float(...)`` raises TypeError on ``None``/lists — which the router
    would surface as a 500 — and silently accepts NaN/Infinity, which then break
    JSON serialization downstream. Funnel every numeric config value through here.
    """
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None
    if not math.isfinite(out):
        raise ValueError(f"{name} must be a finite number, got {out}")
    return out


@dataclass
class QuestionnaireConfig:
    """Tunable weights + thresholds. Defaults are sensible out of the box."""

    dimension_weights: dict[str, float] = field(default_factory=lambda: {dim: 1.0 for dim in DIMENSIONS})
    tiers: list[dict] = field(default_factory=lambda: [dict(t) for t in DEFAULT_TIERS])
    tip_score_threshold: float = DEFAULT_TIP_THRESHOLD

    @classmethod
    def default(cls) -> QuestionnaireConfig:
        return cls()

    @classmethod
    def from_mapping(cls, data: dict) -> QuestionnaireConfig:
        """Merge a mapping of overrides over the defaults, validating shapes."""
        if not isinstance(data, dict):
            raise ValueError("questionnaire config must be a mapping")

        cfg = cls.default()

        weights = data.get("dimension_weights")
        if weights:
            if not isinstance(weights, dict):
                raise ValueError("dimension_weights must be a mapping")
            unknown = set(weights) - set(DIMENSIONS)
            if unknown:
                raise ValueError(f"unknown dimension(s) in dimension_weights: {sorted(unknown)}")
            for dim, w in weights.items():
                fw = _finite_float(w, f"dimension_weights[{dim}]")
                if fw < 0:
                    raise ValueError(f"dimension_weights[{dim}] must be non-negative")
                cfg.dimension_weights[dim] = fw

        tiers = data.get("tiers")
        if tiers:
            if not isinstance(tiers, list) or not all(isinstance(t, dict) for t in tiers):
                raise ValueError("tiers must be a list of {name, min_score} objects")
            parsed: list[dict] = []
            for t in tiers:
                if "name" not in t or "min_score" not in t:
                    raise ValueError("each tier needs a name and a min_score")
                parsed.append({"name": str(t["name"]), "min_score": _finite_float(t["min_score"], "tier min_score")})
            # Require a floor tier so a score below every configured bar still
            # classifies correctly. Without this, a custom list like [{Ready, 60}]
            # would (via the tier_for fallback) label a score of 25 "Ready".
            if min(t["min_score"] for t in parsed) > 0:
                raise ValueError("tiers must include a floor tier with min_score <= 0")
            cfg.tiers = sorted(parsed, key=lambda t: t["min_score"], reverse=True)

        if "tip_score_threshold" in data and data["tip_score_threshold"] is not None:
            cfg.tip_score_threshold = _finite_float(data["tip_score_threshold"], "tip_score_threshold")

        return cfg

    @classmethod
    def from_file(cls, path: Path) -> QuestionnaireConfig:
        """Load overrides from a YAML or JSON file, merged over the defaults."""
        text = Path(path).read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise ImportError("PyYAML is required to read a YAML questionnaire config") from exc
            data = yaml.safe_load(text) or {}
        else:
            import json

            data = json.loads(text) or {}
        return cls.from_mapping(data)

    def tier_for(self, score: float) -> str:
        """Resolve a 0-100 score to a tier name (first bar it meets)."""
        for tier in self.tiers:
            if score >= tier["min_score"]:
                return tier["name"]
        # Defensive: if no tier has min_score 0, fall back to the lowest.
        return self.tiers[-1]["name"] if self.tiers else "Unknown"

    def to_dict(self) -> dict:
        return {
            "dimension_weights": dict(self.dimension_weights),
            "tiers": [dict(t) for t in self.tiers],
            "tip_score_threshold": self.tip_score_threshold,
        }


@dataclass
class ReadinessResult:
    """The scored outcome of a completed (or partial) questionnaire."""

    overall_score: float  # 0-100, weighted across scored dimensions
    tier: str
    dimension_scores: dict[str, float]  # dimension id -> 0-100 (only scored ones)
    dimension_labels: dict[str, str]  # dimension id -> human label
    tips: list[dict]  # [{question_id, dimension, tip, score}], weakest first
    answered: int
    total_questions: int
    unanswered: list[str]  # question ids not answered

    def to_dict(self) -> dict:
        return {
            "overall_score": round(self.overall_score, 1),
            "tier": self.tier,
            "dimension_scores": {k: round(v, 1) for k, v in self.dimension_scores.items()},
            "dimension_labels": dict(self.dimension_labels),
            "tips": list(self.tips),
            "answered": self.answered,
            "total_questions": self.total_questions,
            "unanswered": list(self.unanswered),
            "disclaimer": (
                "Self-assessment aid, not an audit. Scores reflect the answers given "
                "and are meant to prioritize preparation, not to gate a decision."
            ),
        }

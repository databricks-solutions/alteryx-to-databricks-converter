"""MLflow tracing for the AI steps: opt-in, and never in the way of a request.

Set ``A2D_MLFLOW_EXPERIMENT`` to an MLflow experiment path (or id) in the
workspace to log one trace per AI completion or Review suggestion, with a span
per model call: the prompt, the reply, whether it passed the checks and why
not, the time it took and the tokens used. A reviewer's use / edit / discard of
a suggestion is logged on its trace as feedback (``reviewer_outcome``), which is
what tells you how often the AI helps, per tool.

Needs the ``mlflow-tracing`` package. Without it, or without the variable, or
when the experiment can't be found, every call here does nothing. A tracing
error is logged and swallowed; it never fails the AI request.

Prompts carry workflow configuration (credentials masked) and generated code,
so the traces are as sensitive as the workflow: they stay in the workspace's
experiment, readable by whoever can read that experiment.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger("a2d.advisor.tracing")

ENV_EXPERIMENT = "A2D_MLFLOW_EXPERIMENT"
FEEDBACK_NAME = "reviewer_outcome"
OUTCOMES = ("used", "edited", "discarded")
_FEEDBACK_ATTEMPTS = 5
_FEEDBACK_WAIT_SECONDS = 3.0

_lock = threading.Lock()
_state: dict[str, Any] = {"resolved": False, "experiment_id": None, "mlflow": None}


def _resolve() -> tuple[Any, str | None]:
    """(mlflow module, experiment id), or (None, None) when tracing is off."""
    with _lock:
        if _state["resolved"]:
            return _state["mlflow"], _state["experiment_id"]
        _state["resolved"] = True
        target = os.environ.get(ENV_EXPERIMENT, "").strip()
        if not target:
            return None, None
        try:
            import mlflow
        except ImportError as exc:
            # Say what failed: "not installed" and "installed but won't import"
            # (a clash with another mlflow package) need different fixes.
            logger.warning("%s is set but mlflow won't import (%s); AI tracing is off", ENV_EXPERIMENT, exc)
            return None, None
        if not hasattr(mlflow, "start_span_no_context"):
            logger.warning(
                "%s is set but the installed mlflow (%s) has no start_span_no_context; AI tracing is off",
                ENV_EXPERIMENT,
                getattr(mlflow, "__version__", "unknown version"),
            )
            return None, None
        os.environ.setdefault("MLFLOW_TRACKING_URI", "databricks")
        try:
            experiment_id = target if target.isdigit() else _experiment_id_by_name(target)
        except Exception as exc:
            logger.warning("AI tracing is off: experiment %r couldn't be found (%s)", target, exc)
            return None, None
        _state["mlflow"], _state["experiment_id"] = mlflow, experiment_id
        logger.info("AI tracing on: MLflow experiment %s", experiment_id)
        return mlflow, experiment_id


def _experiment_id_by_name(name: str) -> str:
    from databricks.sdk import WorkspaceClient

    exp = WorkspaceClient().experiments.get_by_name(name).experiment
    if exp is None or not exp.experiment_id:
        raise LookupError(f"no experiment named {name}")
    return exp.experiment_id


def enabled() -> bool:
    return _resolve()[0] is not None


def reset() -> None:
    """Forget the resolved configuration (tests, and after the variable changes)."""
    with _lock:
        _state.update(resolved=False, experiment_id=None, mlflow=None)


class Span:
    """A live span, or a stand-in that does nothing when tracing is off."""

    def __init__(self, live: Any = None) -> None:
        self._live = live

    @property
    def trace_id(self) -> str | None:
        return getattr(self._live, "trace_id", None) if self._live is not None else None

    def child(self, name: str, span_type: str = "UNKNOWN", inputs: Any = None, attributes: dict | None = None) -> Span:
        mlflow, _ = _resolve()
        if mlflow is None or self._live is None:
            return Span()
        try:
            return Span(
                # A child goes to its root's experiment; only a root takes experiment_id.
                mlflow.start_span_no_context(
                    name,
                    span_type=span_type,
                    parent_span=self._live,
                    inputs=inputs,
                    attributes=_clean(attributes),
                )
            )
        except Exception as exc:
            logger.debug("Couldn't start span %s: %s", name, exc)
            return Span()

    def end(self, outputs: Any = None, attributes: dict | None = None, error: str | None = None) -> None:
        if self._live is None:
            return
        try:
            self._live.end(outputs=outputs, attributes=_clean(attributes), status="ERROR" if error else "OK")
        except Exception as exc:
            logger.debug("Couldn't end span: %s", exc)


def start_trace(name: str, inputs: Any = None, attributes: dict | None = None) -> Span:
    """Start a trace's root span (a stand-in when tracing is off). End it with ``.end()``."""
    mlflow, experiment_id = _resolve()
    if mlflow is None:
        return Span()
    try:
        return Span(
            mlflow.start_span_no_context(
                name, span_type="CHAIN", inputs=inputs, attributes=_clean(attributes), experiment_id=experiment_id
            )
        )
    except Exception as exc:
        logger.warning("Couldn't start an AI trace: %s", exc)
        return Span()


def log_outcome(trace_id: str, outcome: str, rationale: str | None = None) -> bool:
    """Record a reviewer's use / edit / discard of a suggestion on its trace."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}")
    if not enabled():
        return False
    try:
        from databricks.sdk import WorkspaceClient

        body: dict[str, Any] = {
            "assessment": {
                "trace_id": trace_id,
                "assessment_name": FEEDBACK_NAME,
                "source": {"source_type": "HUMAN", "source_id": "reviewer"},
                "feedback": {"value": outcome},
            }
        }
        if rationale:
            body["assessment"]["rationale"] = rationale[:1000]
        api = WorkspaceClient().api_client
        # A trace is exported in the background a few seconds after its request,
        # so a quick reviewer can be ahead of it: wait a little for it to land.
        for attempt in range(_FEEDBACK_ATTEMPTS):
            try:
                api.do("POST", f"/api/3.0/mlflow/traces/{trace_id}/assessments", body=body)
                return True
            except Exception as exc:
                if "not found" not in str(exc).lower() or attempt == _FEEDBACK_ATTEMPTS - 1:
                    raise
                time.sleep(_FEEDBACK_WAIT_SECONDS)
        return False
    except Exception as exc:
        logger.warning("Couldn't record the reviewer outcome on trace %s: %s", trace_id, exc)
        return False


def _clean(attributes: dict | None) -> dict | None:
    """Span attributes as plain values (MLflow stores them as JSON)."""
    if not attributes:
        return None
    return {k: v for k, v in attributes.items() if v is not None}

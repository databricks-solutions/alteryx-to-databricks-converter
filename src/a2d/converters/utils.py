"""Shared helper functions for converter modules.

Centralizes ``safe_get``, ``safe_get_nested``, ``parse_field_list``,
``ensure_list``, and ``parse_int_list`` so every converter can import them
instead of redefining identical copies.
"""

from __future__ import annotations


def safe_get(cfg: dict, key: str, default: str = "") -> str:
    """Return ``cfg[key]`` as a string, falling back to *default*.

    Handles XML-parsed dicts like ``{'@value': '5000'}`` by extracting the
    ``@value`` (or ``#text``) key before coercing to string.
    """
    val = cfg.get(key, default)
    if isinstance(val, dict):
        val = val.get("@value", val.get("#text", default))
    return val if isinstance(val, str) else str(val) if val is not None else default


def safe_get_nested(d: object, *keys: str, default: str = "") -> str:
    """Traverse nested dicts via *keys* and return a string."""
    current = d
    for k in keys:
        if isinstance(current, dict):
            current = current.get(k, default)
        else:
            return default
    if current is None:
        return default
    return str(current)


def parse_field_list(cfg: dict, key: str) -> list[str]:
    """Parse a comma-separated string or list of field names from *cfg[key]*."""
    raw = cfg.get(key, [])
    if isinstance(raw, str):
        return [f.strip() for f in raw.split(",") if f.strip()]
    if isinstance(raw, list):
        return [str(f) for f in raw]
    return []


def ensure_list(obj: object) -> list:
    """Wrap *obj* in a list if it is not already one (``None`` → ``[]``)."""
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    return [obj]


def parse_int_list(cfg: dict, key: str, default: list[int] | None = None) -> list[int]:
    """Parse a comma-separated string or list of ints from *cfg[key]*."""
    if default is None:
        default = [64, 32]
    raw = cfg.get(key, "")
    if isinstance(raw, str) and raw.strip():
        try:
            return [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            return default
    if isinstance(raw, list):
        try:
            return [int(x) for x in raw]
        except (ValueError, TypeError):
            return default
    return default

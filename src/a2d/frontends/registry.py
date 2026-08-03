"""Frontend registry — resolve a source frontend by name or file, plus plugins.

Built-in frontends are registered eagerly. Third-party frontends are discovered
lazily via the ``a2d.frontends`` entry-point group, so a plugin package can add
a new source (Talend, Informatica, SSIS, …) by declaring an entry point — no
core edit required. A failing plugin is logged and skipped, never fatal.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from pathlib import Path
from typing import ClassVar

from a2d.frontends.alteryx import AlteryxFrontend
from a2d.frontends.base import SourceFrontend
from a2d.frontends.dbt import DbtFrontend

logger = logging.getLogger("a2d.frontends.registry")

_ENTRY_POINT_GROUP = "a2d.frontends"


class FrontendRegistry:
    """Central lookup of source frontends by name and by file recognition."""

    _frontends: ClassVar[dict[str, SourceFrontend]] = {}
    _plugins_loaded: ClassVar[bool] = False

    @classmethod
    def register(cls, frontend: SourceFrontend) -> None:
        """Register (or replace) a frontend instance by its ``name``."""
        if not frontend.name:
            raise ValueError(f"{type(frontend).__name__} has no name")
        if frontend.name in cls._frontends:
            logger.debug("Replacing frontend %r", frontend.name)
        cls._frontends[frontend.name] = frontend

    @classmethod
    def _ensure_loaded(cls) -> None:
        if cls._plugins_loaded:
            return
        cls._plugins_loaded = True
        # Built-ins first.
        cls.register(AlteryxFrontend())
        cls.register(DbtFrontend())
        # Third-party plugins via entry points.
        try:
            eps = entry_points(group=_ENTRY_POINT_GROUP)
        except TypeError:  # pragma: no cover - very old importlib API
            eps = entry_points().get(_ENTRY_POINT_GROUP, [])  # type: ignore[attr-defined]
        for ep in eps:
            try:
                obj = ep.load()
                frontend = obj() if isinstance(obj, type) else obj
                cls.register(frontend)
                logger.info("Loaded frontend plugin %r", ep.name)
            except Exception as exc:  # a bad plugin must not break the app
                logger.warning("Failed to load frontend plugin %r: %s", ep.name, exc)

    @classmethod
    def names(cls) -> list[str]:
        """All registered frontend names, sorted."""
        cls._ensure_loaded()
        return sorted(cls._frontends)

    @classmethod
    def get(cls, name: str) -> SourceFrontend:
        """Return the frontend registered under *name*.

        Raises :class:`KeyError` if unknown.
        """
        cls._ensure_loaded()
        if name not in cls._frontends:
            raise KeyError(f"unknown frontend {name!r}; available: {cls.names()}")
        return cls._frontends[name]

    @classmethod
    def for_path(cls, path: Path) -> SourceFrontend:
        """Pick the frontend that recognises *path* (extension / filename).

        Falls back to the Alteryx frontend when nothing matches, preserving
        prior behaviour for bare ``.yxmd`` inputs.

        Raises :class:`KeyError` only if the fallback itself is missing.
        """
        cls._ensure_loaded()
        for frontend in cls._frontends.values():
            if frontend.can_parse(path):
                return frontend
        return cls.get("alteryx")

    @classmethod
    def resolve(cls, path: Path, name: str | None = None) -> SourceFrontend:
        """Resolve by explicit *name* if given, else auto-detect from *path*."""
        return cls.get(name) if name else cls.for_path(path)

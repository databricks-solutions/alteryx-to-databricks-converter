"""The SourceFrontend contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from a2d.parser.schema import ParsedWorkflow


class SourceFrontend(ABC):
    """Parse a source-pipeline format into a normalized ParsedWorkflow.

    A frontend owns only the *parse* step. Everything after — IR build,
    generation, verification, analysis — is source-agnostic and already exists.
    """

    #: Stable identifier used for ``--frontend <name>`` and registry lookup.
    name: str = ""

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """File extensions this frontend handles, lower-case incl. dot.

        e.g. ``[".yxmd", ".yxmc"]`` for Alteryx. A frontend that consumes a
        directory or a well-known filename (like dbt's ``manifest.json``) may
        return an empty list and rely on :meth:`can_parse`.
        """
        ...

    @abstractmethod
    def parse(self, path: Path) -> ParsedWorkflow:
        """Parse *path* into a ParsedWorkflow.

        Raises :class:`~a2d.exceptions.ParseError` (or a subclass) on malformed
        input, and ``FileNotFoundError`` when *path* does not exist.
        """
        ...

    def can_parse(self, path: Path) -> bool:
        """Whether this frontend recognises *path*.

        Default: match on extension. Frontends keyed on a directory or a
        specific filename override this.
        """
        return path.suffix.lower() in self.supported_extensions

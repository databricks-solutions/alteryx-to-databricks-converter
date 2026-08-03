"""Alteryx frontend — wraps the existing WorkflowParser."""

from __future__ import annotations

from pathlib import Path

from a2d.frontends.base import SourceFrontend
from a2d.parser.schema import ParsedWorkflow
from a2d.parser.workflow_parser import WorkflowParser


class AlteryxFrontend(SourceFrontend):
    """The default frontend: Alteryx ``.yxmd`` / ``.yxmc`` / ``.yxwz`` files."""

    name = "alteryx"

    def __init__(self) -> None:
        self._parser = WorkflowParser()

    @property
    def supported_extensions(self) -> list[str]:
        return [".yxmd", ".yxmc", ".yxwz"]

    def parse(self, path: Path) -> ParsedWorkflow:
        return self._parser.parse(path)

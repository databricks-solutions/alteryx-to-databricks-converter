"""dbt frontend — parse a dbt ``manifest.json`` into a ParsedWorkflow.

dbt already compiles a project into ``target/manifest.json`` (the model DAG with
dependencies, materialization, and compiled SQL). We map that directly onto the
IR:

* each **model** → an ``Output`` node (materialized as a table/view), and
* each **source** or **seed** the models read → an ``Input`` node,
* a model's ``depends_on`` → connections from the upstream model/source's
  output into this model.

The result flows through the ordinary IR build, so all generators / verify /
portfolio / advisor work on a dbt project unchanged. Per-model SQL-level
transforms (SELECT/WHERE/GROUP BY) are left as an Output carrying the compiled
query — a deliberate first-cut scope; deeper SQL→IR lowering is a follow-on.
"""

from __future__ import annotations

import json
from pathlib import Path

from a2d.exceptions import ParseError
from a2d.frontends.base import SourceFrontend
from a2d.parser.schema import (
    ConnectionAnchor,
    ParsedConnection,
    ParsedNode,
    ParsedWorkflow,
)

_MANIFEST_NAME = "manifest.json"


class DbtFrontend(SourceFrontend):
    """Parse a dbt project's compiled ``manifest.json`` into a ParsedWorkflow."""

    name = "dbt"

    @property
    def supported_extensions(self) -> list[str]:
        # dbt is keyed on the manifest filename, not an extension.
        return []

    def can_parse(self, path: Path) -> bool:
        """Recognise a manifest.json file, or a dir/project containing one."""
        return self._locate_manifest(path) is not None

    def parse(self, path: Path) -> ParsedWorkflow:
        manifest_path = self._locate_manifest(path)
        if manifest_path is None:
            raise ParseError(f"no dbt manifest.json found at or under {path}")

        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ParseError(f"could not read dbt manifest {manifest_path}: {exc}") from exc

        nodes_meta: dict = manifest.get("nodes", {})
        sources_meta: dict = manifest.get("sources", {})

        # Assign each dbt unique_id a stable integer tool_id.
        all_ids = sorted(list(nodes_meta) + list(sources_meta))
        id_map = {uid: i + 1 for i, uid in enumerate(all_ids)}

        parsed_nodes: list[ParsedNode] = []
        connections: list[ParsedConnection] = []

        # Sources / seeds → Input nodes.
        for uid, meta in sources_meta.items():
            parsed_nodes.append(
                ParsedNode(
                    tool_id=id_map[uid],
                    plugin_name="dbt.source",
                    tool_type="Input",
                    category="io",
                    configuration={"TableName": self._relation_name(meta)},
                    annotation=meta.get("name"),
                )
            )

        # Models / seeds / snapshots → Output nodes; deps → connections.
        for uid, meta in nodes_meta.items():
            resource_type = meta.get("resource_type", "")
            if resource_type == "seed":
                tool_type, plugin = "Input", "dbt.seed"
                config = {"TableName": self._relation_name(meta)}
            elif resource_type in ("model", "snapshot"):
                tool_type, plugin = "Output", f"dbt.{resource_type}"
                config = {
                    "TableName": self._relation_name(meta),
                    "WriteMode": self._write_mode(meta),
                    "Query": meta.get("compiled_code") or meta.get("raw_code", ""),
                }
            else:
                continue  # tests, analyses, etc. are not part of the data DAG

            parsed_nodes.append(
                ParsedNode(
                    tool_id=id_map[uid],
                    plugin_name=plugin,
                    tool_type=tool_type,
                    category="io",
                    configuration=config,
                    annotation=meta.get("name"),
                )
            )

            for dep_uid in meta.get("depends_on", {}).get("nodes", []):
                if dep_uid in id_map:
                    connections.append(
                        ParsedConnection(
                            origin=ConnectionAnchor(tool_id=id_map[dep_uid], anchor_name="Output"),
                            destination=ConnectionAnchor(tool_id=id_map[uid], anchor_name="Input"),
                        )
                    )

        project = manifest.get("metadata", {}).get("project_name", "dbt_project")
        return ParsedWorkflow(
            file_path=str(manifest_path),
            alteryx_version=f"dbt:{manifest.get('metadata', {}).get('dbt_version', 'unknown')}",
            nodes=parsed_nodes,
            connections=connections,
            properties={"project_name": project, "source": "dbt"},
        )

    # -- helpers --

    @staticmethod
    def _locate_manifest(path: Path) -> Path | None:
        if path.is_file() and path.name == _MANIFEST_NAME:
            return path
        if path.is_dir():
            direct = path / _MANIFEST_NAME
            if direct.is_file():
                return direct
            target = path / "target" / _MANIFEST_NAME
            if target.is_file():
                return target
        return None

    @staticmethod
    def _relation_name(meta: dict) -> str:
        """Fully-qualified relation name (database.schema.table) when available."""
        parts = [meta.get("database"), meta.get("schema"), meta.get("alias") or meta.get("name")]
        return ".".join(p for p in parts if p)

    @staticmethod
    def _write_mode(meta: dict) -> str:
        materialized = meta.get("config", {}).get("materialized", "table")
        # dbt incremental → append; everything else → overwrite (table/view).
        return "append" if materialized == "incremental" else "overwrite"

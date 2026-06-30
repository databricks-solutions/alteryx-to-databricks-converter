"""Main parser for Alteryx .yxmd workflow files."""

from __future__ import annotations

import logging
from pathlib import Path

from lxml import etree

from a2d.parser.connection_parser import ConnectionParser
from a2d.parser.node_parser import NodeParser
from a2d.parser.schema import ParsedNode, ParsedWorkflow
from a2d.utils.xml_helpers import element_to_dict, get_attr

logger = logging.getLogger("a2d.parser.workflow")

# Secure XML parser: disable entity resolution and network access to prevent XXE attacks
_SAFE_PARSER = etree.XMLParser(resolve_entities=False, no_network=True)


class WorkflowParser:
    """Parses Alteryx .yxmd (XML) files into ParsedWorkflow objects.

    The .yxmd format structure::

        <AlteryxDocument yxmdVer="...">
          <Nodes>
            <Node ToolID="1">...</Node>
            ...
          </Nodes>
          <Connections>
            <Connection>...</Connection>
            ...
          </Connections>
          <Properties>...</Properties>
        </AlteryxDocument>
    """

    def __init__(self) -> None:
        self._node_parser = NodeParser()
        self._connection_parser = ConnectionParser()

    def parse(self, path: Path) -> ParsedWorkflow:
        """Parse a .yxmd file from disk."""
        if not path.exists():
            raise FileNotFoundError(f"Workflow file not found: {path}")

        if path.suffix.lower() not in (".yxmd", ".yxmc", ".yxwz"):
            logger.warning("Unexpected file extension: %s", path.suffix)

        tree = etree.parse(str(path), _SAFE_PARSER)
        root = tree.getroot()
        return self._parse_root(root, str(path))

    def parse_string(self, xml_string: str, file_path: str = "<string>") -> ParsedWorkflow:
        """Parse XML string directly (useful for testing)."""
        root = etree.fromstring(xml_string.encode("utf-8"), _SAFE_PARSER)
        return self._parse_root(root, file_path)

    def _parse_root(self, root: etree._Element, file_path: str) -> ParsedWorkflow:
        """Parse from root XML element."""
        version = get_attr(root, "yxmdVer", "unknown")

        # Parse nodes (recursively — ToolContainer nests children in <ChildNodes>)
        nodes: list[ParsedNode] = []
        nodes_elem = root.find("Nodes")
        if nodes_elem is not None:
            self._collect_nodes(nodes_elem, nodes, parent_disabled=False)

        # Parse connections
        connections = []
        conns_elem = root.find("Connections")
        if conns_elem is not None:
            connections = self._connection_parser.parse_all(conns_elem)

        # Parse workflow properties
        properties: dict = {}
        props_elem = root.find("Properties")
        if props_elem is not None:
            properties = element_to_dict(props_elem)

        # Detect macro references
        macro_refs = self._find_macro_references(nodes)

        logger.info("Parsed %s: %d nodes, %d connections, version=%s", file_path, len(nodes), len(connections), version)

        return ParsedWorkflow(
            file_path=file_path,
            alteryx_version=version,
            nodes=nodes,
            connections=connections,
            properties=properties,
            macro_references=macro_refs,
        )

    def _collect_nodes(
        self,
        parent_elem: etree._Element,
        nodes: list[ParsedNode],
        parent_disabled: bool,
    ) -> None:
        """Recursively collect nodes, propagating disabled state from ToolContainers."""
        for node_elem in parent_elem.findall("Node"):
            parsed = self._node_parser.parse(node_elem)

            # Check if this is a disabled ToolContainer
            is_disabled = parent_disabled or self._is_container_disabled(node_elem)
            if is_disabled:
                parsed.disabled = True

            nodes.append(parsed)

            # Recurse into ChildNodes (ToolContainer pattern)
            child_nodes_elem = node_elem.find("ChildNodes")
            if child_nodes_elem is not None:
                self._collect_nodes(child_nodes_elem, nodes, parent_disabled=is_disabled)

    @staticmethod
    def _is_container_disabled(node_elem: etree._Element) -> bool:
        """Check if a ToolContainer node has Disabled=True."""
        config = node_elem.find("Properties/Configuration/Disabled")
        if config is not None:
            return get_attr(config, "value", "False") == "True"
        return False

    def _find_macro_references(self, nodes: list[ParsedNode]) -> list[str]:
        """Find any macro file references in the workflow."""
        refs = []
        for node in nodes:
            if node.plugin_name and "Macro" in node.plugin_name:
                macro_path = node.configuration.get("MacroPath", "")
                if macro_path:
                    refs.append(macro_path)
        return refs

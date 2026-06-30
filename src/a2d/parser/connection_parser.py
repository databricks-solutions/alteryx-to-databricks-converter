"""Parse connections between Alteryx tools."""

from __future__ import annotations

import logging

from lxml import etree

from a2d.parser.schema import ConnectionAnchor, ParsedConnection
from a2d.utils.xml_helpers import get_attr

logger = logging.getLogger("a2d.parser.connection")


class ConnectionParser:
    """Parses <Connection> XML elements."""

    def parse(self, conn_element: etree._Element) -> ParsedConnection:
        """Parse a single <Connection> XML element."""
        origin_elem = conn_element.find("Origin")
        dest_elem = conn_element.find("Destination")

        if origin_elem is None or dest_elem is None:
            raise ValueError("Connection missing Origin or Destination element")

        origin = ConnectionAnchor(
            tool_id=int(get_attr(origin_elem, "ToolID", "0")),
            anchor_name=get_attr(origin_elem, "Connection", "Output"),
        )

        destination = ConnectionAnchor(
            tool_id=int(get_attr(dest_elem, "ToolID", "0")),
            anchor_name=get_attr(dest_elem, "Connection", "Input"),
        )

        is_wireless = conn_element.get("Wireless", "False").lower() == "true"

        return ParsedConnection(
            origin=origin,
            destination=destination,
            is_wireless=is_wireless,
        )

    def parse_all(self, connections_element: etree._Element) -> list[ParsedConnection]:
        """Parse all connections from a <Connections> element."""
        connections = []
        for conn_elem in connections_element.findall("Connection"):
            try:
                connections.append(self.parse(conn_elem))
            except ValueError as e:
                logger.warning(f"Skipping malformed connection: {e}")
        return connections

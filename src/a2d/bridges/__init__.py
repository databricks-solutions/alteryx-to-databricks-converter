"""Spatial and reporting bridges.

Two "last-mile" bridges that turn Alteryx tools with no clean 1:1 Databricks
equivalent into first-class Databricks artifacts:

* :mod:`a2d.bridges.spatial` — a template library that renders each spatial IR
  node into a chosen backend: **Databricks-native ST functions** (default),
  **Apache Sedona**, or **H3**. Handles unit→metre conversion consistently
  (the inline generator code hard-codes Mosaic and skips unit conversion).
* :mod:`a2d.bridges.reporting` — generates a Databricks **AI/BI (Lakeview)
  dashboard** JSON spec from a workflow's Chart / Report / Browse nodes, so a
  reporting workflow becomes an actual dashboard instead of a bare ``display()``.

Both are pure functions of the IR — deterministic and offline.
"""

from __future__ import annotations

from a2d.bridges.reporting import DashboardSpec, build_dashboard_spec
from a2d.bridges.spatial import (
    SPATIAL_BACKENDS,
    SpatialBackend,
    SpatialSnippet,
    render_spatial_node,
)

__all__ = [
    "SPATIAL_BACKENDS",
    "DashboardSpec",
    "SpatialBackend",
    "SpatialSnippet",
    "build_dashboard_spec",
    "render_spatial_node",
]

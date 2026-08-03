"""Spatial template library: render spatial IR nodes to a chosen backend.

Alteryx spatial tools map to several possible Databricks stacks. This module
renders each spatial IR node into a :class:`SpatialSnippet` for a selected
backend:

* ``databricks`` (default) — native ST SQL functions (``st_buffer``,
  ``st_distance``, ``st_point``, ``st_intersects``) available in DBSQL /
  Photon. The modern, dependency-free choice.
* ``sedona`` — Apache Sedona (``ST_*`` via the sedona registrator), for clusters
  running Sedona.
* ``h3`` — Databricks H3 functions (``h3_*``) for grid / k-ring workloads.

Unlike the inline generator code (which hard-codes Mosaic and ignores units),
these templates convert the tool's distance units to the backend's native unit
(metres) up front, so ``buffer_distance`` in miles is rendered correctly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from a2d.ir.nodes import (
    BufferNode,
    CreatePointsNode,
    DistanceNode,
    IRNode,
    MakeGridNode,
    SpatialMatchNode,
    TradeAreaNode,
)

SpatialBackend = Literal["databricks", "sedona", "h3"]
SPATIAL_BACKENDS: tuple[SpatialBackend, ...] = ("databricks", "sedona", "h3")

# Metres per distance unit — used to normalise Alteryx units to the backend's
# native metre-based ST functions.
_METRES_PER_UNIT = {
    "miles": 1609.344,
    "mile": 1609.344,
    "km": 1000.0,
    "kilometers": 1000.0,
    "kilometres": 1000.0,
    "meters": 1.0,
    "metres": 1.0,
    "m": 1.0,
    "feet": 0.3048,
    "ft": 0.3048,
}


def metres_for(distance: float, units: str) -> float:
    """Convert a distance in Alteryx units to metres (default: assume metres)."""
    return distance * _METRES_PER_UNIT.get((units or "").lower(), 1.0)


@dataclass
class SpatialSnippet:
    """Rendered spatial code for one node on one backend."""

    backend: SpatialBackend
    code_lines: list[str]
    imports: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def render_spatial_node(node: IRNode, backend: SpatialBackend = "databricks") -> SpatialSnippet | None:
    """Render a spatial IR node for *backend*, or None if it isn't spatial.

    Raises :class:`ValueError` for an unknown backend.
    """
    if backend not in SPATIAL_BACKENDS:
        raise ValueError(f"unknown spatial backend {backend!r}; choose one of {SPATIAL_BACKENDS}")

    if isinstance(node, BufferNode):
        return _buffer(node, backend)
    if isinstance(node, DistanceNode):
        return _distance(node, backend)
    if isinstance(node, CreatePointsNode):
        return _create_points(node, backend)
    if isinstance(node, SpatialMatchNode):
        return _spatial_match(node, backend)
    if isinstance(node, TradeAreaNode):
        return _trade_area(node, backend)
    if isinstance(node, MakeGridNode):
        return _make_grid(node, backend)
    return None


# ── Buffer ───────────────────────────────────────────────────────────────


def _buffer(node: BufferNode, backend: SpatialBackend) -> SpatialSnippet:
    metres = metres_for(node.buffer_distance, node.buffer_units)
    col = node.input_field
    out = f"{col}_buffer"
    if backend == "databricks":
        return SpatialSnippet(
            backend,
            [
                f"# Buffer {node.buffer_distance} {node.buffer_units} (= {metres:g} m) via native ST",
                f'df = df.withColumn("{out}", F.expr("st_buffer({col}, {metres:g})"))',
            ],
        )
    if backend == "sedona":
        return SpatialSnippet(
            backend,
            [
                f"# Buffer {node.buffer_distance} {node.buffer_units} (= {metres:g} m) via Apache Sedona",
                f'df = df.withColumn("{out}", F.expr("ST_Buffer({col}, {metres:g})"))',
            ],
            imports=["from sedona.spark import SedonaContext"],
            notes=["Sedona must be registered: SedonaContext.create(spark)"],
        )
    # h3
    return SpatialSnippet(
        backend,
        [
            f"# Buffer via H3 k-ring approximation ({node.buffer_distance} {node.buffer_units})",
            f'df = df.withColumn("{out}_cells", F.expr("h3_kring({col}, 1))"))',
        ],
        notes=["H3 buffering is an approximation via k-ring; choose resolution to match the buffer size."],
    )


# ── Distance ─────────────────────────────────────────────────────────────


def _distance(node: DistanceNode, backend: SpatialBackend) -> SpatialSnippet:
    src, tgt, out = node.source_field, node.target_field, node.output_field
    if backend == "databricks":
        return SpatialSnippet(
            backend,
            [
                f"# Distance ({node.distance_units}) via native ST (metres → converted)",
                f'df = df.withColumn("{out}", F.expr("st_distancesphere({src}, {tgt})") '
                f"/ {_METRES_PER_UNIT.get(node.distance_units.lower(), 1.0):g})",
            ],
        )
    if backend == "sedona":
        return SpatialSnippet(
            backend,
            [
                f"# Distance ({node.distance_units}) via Sedona ST_DistanceSphere",
                f'df = df.withColumn("{out}", F.expr("ST_DistanceSphere({src}, {tgt})") '
                f"/ {_METRES_PER_UNIT.get(node.distance_units.lower(), 1.0):g})",
            ],
            imports=["from sedona.spark import SedonaContext"],
        )
    return SpatialSnippet(
        backend,
        [
            f"# Distance via H3 grid distance ({node.distance_units})",
            f'df = df.withColumn("{out}_cells", F.expr("h3_gridpathcells({src}, {tgt})"))',
        ],
        notes=["H3 grid distance is measured in cells, not physical units."],
    )


# ── CreatePoints ───────────────────────────────────────────────────────────


def _create_points(node: CreatePointsNode, backend: SpatialBackend) -> SpatialSnippet:
    lat, lon, out = node.lat_field, node.lon_field, node.output_field
    if backend == "databricks":
        return SpatialSnippet(
            backend,
            [
                "# CreatePoints: build point geometry from lat/lon via native ST",
                f'df = df.withColumn("{out}", F.expr("st_point({lon}, {lat})"))',
            ],
        )
    if backend == "sedona":
        return SpatialSnippet(
            backend,
            [f'df = df.withColumn("{out}", F.expr("ST_Point({lon}, {lat})"))'],
            imports=["from sedona.spark import SedonaContext"],
        )
    return SpatialSnippet(
        backend,
        [
            "# CreatePoints → H3 cell index (resolution 9)",
            f'df = df.withColumn("{out}", F.expr("h3_longlatash3({lon}, {lat}, 9)"))',
        ],
    )


# ── SpatialMatch ───────────────────────────────────────────────────────────


def _spatial_match(node: SpatialMatchNode, backend: SpatialBackend) -> SpatialSnippet:
    a, b = node.spatial_field_target, node.spatial_field_universe
    predicate = {"intersects": "intersects", "contains": "contains", "within": "within"}.get(
        node.match_type, "intersects"
    )
    if backend == "databricks":
        return SpatialSnippet(
            backend,
            [
                f"# Spatial match ({predicate}) via native ST join",
                f'df = left.join(right, F.expr("st_{predicate}(left.{a}, right.{b})"), "inner")',
            ],
        )
    if backend == "sedona":
        return SpatialSnippet(
            backend,
            [f'df = left.join(right, F.expr("ST_{predicate.capitalize()}(left.{a}, right.{b})"), "inner")'],
            imports=["from sedona.spark import SedonaContext"],
        )
    return SpatialSnippet(
        backend,
        [
            "# Spatial match via shared H3 cell (point-in-cell join)",
            f'df = left.join(right, left.{a} == right.{b}, "inner")',
        ],
        notes=["H3 match assumes both sides carry an H3 cell id at the same resolution."],
    )


# ── TradeArea ──────────────────────────────────────────────────────────────


def _trade_area(node: TradeAreaNode, backend: SpatialBackend) -> SpatialSnippet:
    metres = metres_for(node.radius, node.radius_units)
    col, out = node.input_field, node.output_field
    if backend == "h3":
        return SpatialSnippet(
            backend,
            [
                f"# TradeArea via H3 k-ring ({node.ring_count} ring(s))",
                f'df = df.withColumn("{out}", F.expr("h3_kring({col}, {node.ring_count})"))',
            ],
        )
    fn = "st_buffer" if backend == "databricks" else "ST_Buffer"
    return SpatialSnippet(
        backend,
        [
            f"# TradeArea: {node.radius} {node.radius_units} (= {metres:g} m) ring buffer",
            f'df = df.withColumn("{out}", F.expr("{fn}({col}, {metres:g})"))',
        ],
        imports=["from sedona.spark import SedonaContext"] if backend == "sedona" else [],
    )


# ── MakeGrid ─────────────────────────────────────────────────────────────


def _make_grid(node: MakeGridNode, backend: SpatialBackend) -> SpatialSnippet:
    if backend == "h3":
        return SpatialSnippet(
            backend,
            [
                "# MakeGrid → H3 polyfill of the extent (resolution 8)",
                f'df = df.withColumn("{node.output_field}", F.expr("h3_polyfillash3({node.extent_field}, 8)"))',
            ],
        )
    metres = metres_for(node.grid_size, node.grid_units)
    return SpatialSnippet(
        backend,
        [
            f"# MakeGrid: {node.grid_size} {node.grid_units} (= {metres:g} m) cells",
            "# Native/Sedona grid generation typically uses ST_SubDivide or a generated grid;",
            f"# emit the extent + target cell size ({metres:g} m) for manual grid construction.",
        ],
        notes=["Regular-grid generation has no single ST call; H3 backend is recommended for gridding."],
    )

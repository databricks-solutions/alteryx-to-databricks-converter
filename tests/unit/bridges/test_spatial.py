"""Tests for the spatial template library."""

from __future__ import annotations

import pytest

from a2d.bridges.spatial import (
    SPATIAL_BACKENDS,
    metres_for,
    render_spatial_node,
)
from a2d.ir.nodes import (
    BufferNode,
    CreatePointsNode,
    DistanceNode,
    FilterNode,
    MakeGridNode,
    SpatialMatchNode,
    TradeAreaNode,
)


class TestUnitConversion:
    def test_miles_to_metres(self):
        assert metres_for(5, "miles") == pytest.approx(8046.72)

    def test_km_to_metres(self):
        assert metres_for(2, "km") == pytest.approx(2000.0)

    def test_unknown_unit_assumes_metres(self):
        assert metres_for(3, "furlongs") == 3.0


class TestBackendSelection:
    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="unknown spatial backend"):
            render_spatial_node(BufferNode(node_id=1), "postgis")

    def test_non_spatial_node_returns_none(self):
        assert render_spatial_node(FilterNode(node_id=1, expression="[x]>0")) is None

    def test_all_backends_render_buffer(self):
        node = BufferNode(node_id=1, input_field="geom", buffer_distance=1, buffer_units="miles")
        for backend in SPATIAL_BACKENDS:
            snip = render_spatial_node(node, backend)
            assert snip is not None
            assert snip.backend == backend
            assert snip.code_lines


class TestBufferTemplates:
    def test_databricks_uses_native_st_and_converts_units(self):
        node = BufferNode(node_id=1, input_field="geom", buffer_distance=1, buffer_units="miles")
        snip = render_spatial_node(node, "databricks")
        code = "\n".join(snip.code_lines)
        assert "st_buffer(geom, 1609.34" in code

    def test_sedona_imports_context(self):
        node = BufferNode(node_id=1, input_field="geom", buffer_distance=1, buffer_units="km")
        snip = render_spatial_node(node, "sedona")
        assert any("sedona" in imp for imp in snip.imports)
        assert "ST_Buffer" in "\n".join(snip.code_lines)

    def test_h3_notes_approximation(self):
        node = BufferNode(node_id=1, input_field="geom", buffer_distance=1, buffer_units="miles")
        snip = render_spatial_node(node, "h3")
        assert snip.notes


class TestOtherSpatialNodes:
    def test_distance_default(self):
        snip = render_spatial_node(DistanceNode(node_id=1, source_field="a", target_field="b"), "databricks")
        assert "st_distancesphere" in "\n".join(snip.code_lines)

    def test_create_points(self):
        snip = render_spatial_node(CreatePointsNode(node_id=1, lat_field="lat", lon_field="lon"), "databricks")
        assert "st_point(lon, lat)" in "\n".join(snip.code_lines)

    def test_spatial_match_predicate(self):
        node = SpatialMatchNode(node_id=1, match_type="contains")
        snip = render_spatial_node(node, "databricks")
        assert "st_contains" in "\n".join(snip.code_lines)

    def test_trade_area_h3_uses_kring(self):
        node = TradeAreaNode(node_id=1, input_field="geom", radius=2, radius_units="miles", ring_count=2)
        snip = render_spatial_node(node, "h3")
        assert "h3_kring" in "\n".join(snip.code_lines)

    def test_make_grid_h3_polyfill(self):
        snip = render_spatial_node(MakeGridNode(node_id=1, extent_field="geom"), "h3")
        assert "h3_polyfill" in "\n".join(snip.code_lines)

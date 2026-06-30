"""Tests for spatial converters."""

from __future__ import annotations

from a2d.converters import ConverterRegistry
from a2d.ir.nodes import (
    BufferNode,
    CreatePointsNode,
    DistanceNode,
    FindNearestNode,
    GeocoderNode,
    MakeGridNode,
    SpatialMatchNode,
    TradeAreaNode,
)

from .conftest import DEFAULT_CONFIG, make_node


class TestBufferConverter:
    def test_buffer(self):
        node = make_node(
            tool_type="Buffer",
            configuration={"DistanceValue": "5", "DistanceUnits": "Miles", "BufferStyle": "Circle"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, BufferNode)
        assert result.buffer_distance == 5.0
        assert result.buffer_units == "miles"
        assert result.conversion_method == "mapping"
        assert result.conversion_confidence < 1.0


class TestSpatialMatchConverter:
    def test_spatial_match(self):
        node = make_node(
            tool_type="SpatialMatch",
            configuration={"MatchType": "Contains", "TargetSpatialField": "Geo1"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, SpatialMatchNode)
        assert result.match_type == "contains"
        assert result.spatial_field_target == "Geo1"
        assert result.conversion_method == "mapping"


class TestCreatePointsConverter:
    def test_create_points(self):
        node = make_node(
            tool_type="CreatePoints",
            configuration={"LatitudeField": "Lat", "LongitudeField": "Lon"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, CreatePointsNode)
        assert result.lat_field == "Lat"
        assert result.lon_field == "Lon"
        assert result.conversion_confidence == 0.8


class TestDistanceConverter:
    def test_distance(self):
        node = make_node(
            tool_type="Distance",
            configuration={"DistanceUnits": "Kilometers"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, DistanceNode)
        assert result.distance_units == "kilometers"
        assert result.conversion_method == "mapping"


class TestFindNearestConverter:
    def test_find_nearest(self):
        node = make_node(
            tool_type="FindNearest",
            configuration={"MaxMatches": "3", "MaxDistance": "10"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, FindNearestNode)
        assert result.max_matches == 3
        assert result.max_distance == 10.0
        assert result.conversion_method == "mapping"


class TestGeocoderConverter:
    def test_geocoder(self):
        node = make_node(
            tool_type="Geocoder",
            configuration={"AddressField": "Address", "CityField": "City"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, GeocoderNode)
        assert result.address_field == "Address"
        assert result.city_field == "City"
        assert result.conversion_confidence == 0.3


class TestTradeAreaConverter:
    def test_trade_area(self):
        node = make_node(
            tool_type="TradeArea",
            configuration={"Radius": "5", "RadiusUnits": "Kilometers", "NumberOfRings": "3"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, TradeAreaNode)
        assert result.radius == 5.0
        assert result.radius_units == "kilometers"
        assert result.ring_count == 3
        assert result.conversion_method == "mapping"


class TestMakeGridConverter:
    def test_make_grid(self):
        node = make_node(
            tool_type="MakeGrid",
            configuration={"GridSize": "2", "GridUnits": "Miles"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, MakeGridNode)
        assert result.grid_size == 2.0
        assert result.grid_units == "miles"
        assert result.conversion_method == "mapping"

"""Tests for the generic predictive/ML converter."""

from __future__ import annotations

import pytest

from a2d.converters import ConverterRegistry
from a2d.ir.nodes import PredictiveModelNode

from .conftest import DEFAULT_CONFIG, make_node

# All 28 predictive tool types handled by the generic converter.
_ALL_PREDICTIVE_TOOLS = [
    "DecisionTree",
    "ForestModel",
    "LinearRegression",
    "LogisticRegression",
    "ScoreModel",
    "BoostedModel",
    "NaiveBayes",
    "SupportVectorMachine",
    "NeuralNetwork",
    "GammaRegression",
    "CountRegression",
    "SplineModel",
    "Stepwise",
    "KCentroids",
    "PrincipalComponents",
    "CrossValidation",
    "ARIMA",
    "ETS",
    "ABAnalysis",
    "AppendCluster",
    "FindNearestNeighbors",
    "KCentroidsDiagnostics",
    "LiftChart",
    "ModelComparison",
    "ModelCoefficients",
    "TSForecast",
    "TestOfMeans",
    "VarianceInflationFactors",
]


@pytest.mark.parametrize("tool_type", _ALL_PREDICTIVE_TOOLS)
def test_all_predictive_tools_produce_predictive_model_node(tool_type: str) -> None:
    """Every predictive tool type should produce a PredictiveModelNode."""
    node = make_node(tool_type=tool_type, configuration={"TargetField": "label"})
    result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
    assert isinstance(result, PredictiveModelNode)
    assert result.model_type == tool_type
    assert result.conversion_method == "stub"


class TestGenericPredictiveConverter:
    def test_extracts_target_and_features(self) -> None:
        node = make_node(
            tool_type="LinearRegression",
            configuration={"TargetField": "price", "FeatureFields": "sqft,beds,baths"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, PredictiveModelNode)
        assert result.target_field == "price"
        assert result.feature_fields == ["sqft", "beds", "baths"]

    def test_extracts_config_params(self) -> None:
        node = make_node(
            tool_type="DecisionTree",
            configuration={
                "TargetField": "label",
                "FeatureFields": "f1,f2",
                "MaxDepth": "10",
                "ModelType": "classification",
            },
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, PredictiveModelNode)
        assert result.config["MaxDepth"] == "10"
        assert result.config["ModelType"] == "classification"

    def test_arima_extracts_time_series_params(self) -> None:
        node = make_node(
            tool_type="ARIMA",
            configuration={"TimeField": "date", "ValueField": "sales", "P": "2", "D": "1", "Q": "1"},
        )
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, PredictiveModelNode)
        assert result.config["TimeField"] == "date"
        assert result.config["ValueField"] == "sales"
        assert result.config["P"] == "2"

    def test_low_confidence(self) -> None:
        node = make_node(tool_type="NeuralNetwork", configuration={})
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, PredictiveModelNode)
        assert result.conversion_confidence == pytest.approx(0.3)

    def test_empty_config(self) -> None:
        node = make_node(tool_type="KCentroids", configuration={})
        result = ConverterRegistry.convert_node(node, DEFAULT_CONFIG)
        assert isinstance(result, PredictiveModelNode)
        assert result.target_field == ""
        assert result.feature_fields == []
        assert result.config == {}

"""Generic converter for all Alteryx predictive/ML tools -> PredictiveModelNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import parse_field_list, safe_get
from a2d.ir.nodes import IRNode, PredictiveModelNode
from a2d.parser.schema import ParsedNode

# All predictive tool types handled by this single converter.
_PREDICTIVE_TOOL_TYPES = [
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
    # Intelligence Suite / AutoML
    "AutoML",
    "Fit",
    "Insights",
    "Modeling",
    "Predict",
    "Regression",
    "Transformation",
]


@ConverterRegistry.register
class PredictiveModelConverter(ToolConverter):
    """Converts all Alteryx predictive tools to :class:`PredictiveModelNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return _PREDICTIVE_TOOL_TYPES

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        # Extract common fields present in most predictive tools.
        target = safe_get(cfg, "TargetField")
        features = parse_field_list(cfg, "FeatureFields")

        # Collect all remaining config keys into a generic dict.
        extra: dict[str, str] = {}
        for key in (
            "ModelType",
            "MaxDepth",
            "NumTrees",
            "Regularization",
            "MaxIterations",
            "LearningRate",
            "Smoothing",
            "HiddenLayers",
            "LinkFunction",
            "MaxKnots",
            "Direction",
            "K",
            "NumComponents",
            "NumFolds",
            "ModelReference",
            "ModelReferences",
            "TimeField",
            "ValueField",
            "ForecastField",
            "P",
            "D",
            "Q",
            "ErrorType",
            "TrendType",
            "SeasonalType",
            "TreatmentField",
            "ResponseField",
            "PredictionField",
            "ActualField",
            "FieldA",
            "FieldB",
            "TestType",
            "DistanceMetric",
        ):
            val = safe_get(cfg, key)
            if val:
                extra[key] = val

        return PredictiveModelNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            model_type=parsed_node.tool_type,
            target_field=target,
            feature_fields=features,
            config=extra,
            conversion_confidence=0.3,
            conversion_method="stub",
            conversion_notes=[
                f"Predictive tool '{parsed_node.tool_type}' requires manual conversion to Spark MLlib or equivalent.",
            ],
        )

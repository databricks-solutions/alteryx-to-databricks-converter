"""Migration profiler — estate footprint, complexity, and tool-difficulty tiers.

A presentation + classification layer over the metrics :mod:`a2d.analyzer` already
computes (:class:`~a2d.analyzer.readiness.WorkflowAnalysis`). It produces the
"Migration Profiler" view: portfolio totals, workflow-size distribution, migration
difficulty distribution, and a **tool-by-difficulty breakdown** — each tool
classified into Low / Medium / High / Very High, matching the Databricks Lakebridge
Analyzer's complexity vocabulary.

Everything here is deterministic. Effort *hours* are optional and off by default:
per Databricks/field guidance they are model-based estimates, so they only appear
when explicitly enabled, and their anchors — like the tier mapping itself — are
configurable via :class:`ProfilerConfig` (defaults are sensible out of the box).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from a2d.parser.schema import PLUGIN_NAME_MAP

if TYPE_CHECKING:
    from a2d.analyzer.readiness import WorkflowAnalysis

# Difficulty tiers. Same labels as ComplexityScore.level and Lakebridge's
# object-complexity classes, so the two read consistently.
LOW = "Low"
MEDIUM = "Medium"
HIGH = "High"
VERY_HIGH = "Very High"
TIER_ORDER: tuple[str, ...] = (LOW, MEDIUM, HIGH, VERY_HIGH)

# tool_type (friendly name) -> Alteryx tool category, derived from the parser's
# PLUGIN_NAME_MAP so the category-based defaults below cover every mapped tool.
TOOL_CATEGORY: dict[str, str] = {name: category for (name, category) in PLUGIN_NAME_MAP.values()}

# Default difficulty per tool category. The single biggest driver of migration
# effort is whether a construct has a native/1:1 equivalent (Lakebridge weights
# unsupported constructs highest, as does our complexity engine) — so simple
# passthrough/prep tools are Low, transforms/joins/parses Medium, and anything
# needing a special runtime (spatial), model reimplementation (predictive), custom
# code (developer) or manual orchestration (workflow) is High.
DEFAULT_CATEGORY_TIERS: dict[str, str] = {
    "io": LOW,
    "container": LOW,
    "preparation": LOW,
    "parse": MEDIUM,
    "join": MEDIUM,
    "transform": MEDIUM,
    "interface": MEDIUM,
    "reporting": MEDIUM,
    "connectors": MEDIUM,
    "spatial": HIGH,
    "predictive": HIGH,
    "developer": HIGH,
    "workflow": HIGH,
}

# Per-tool exceptions to the category default (both directions).
DEFAULT_TOOL_OVERRIDES: dict[str, str] = {
    # preparation: expression-bearing / dynamic-metadata tools need real work.
    "Formula": MEDIUM,
    "MultiRowFormula": MEDIUM,
    "MultiFieldFormula": MEDIUM,
    "Filter": MEDIUM,
    "GenerateRows": MEDIUM,
    "Imputation": MEDIUM,
    "DynamicRename": MEDIUM,
    "DynamicReplace": MEDIUM,
    "DynamicSelect": MEDIUM,
    # transform: a plain record count is trivial.
    "CountRecords": LOW,
    # join: Calgary is a proprietary indexed dataset join.
    "CalgaryJoin": HIGH,
    # developer: custom code has no deterministic equivalent — reimplementation.
    "PythonTool": VERY_HIGH,
    "JupyterCode": VERY_HIGH,
    "RunCommand": VERY_HIGH,
    "Download": HIGH,
    "DynamicInput": HIGH,
    "DynamicOutput": HIGH,
    "Message": LOW,
    "Test": LOW,
    "BasicDataProfile": LOW,
    # spatial: geocoding needs an external service, not just a spatial runtime.
    "Geocoder": VERY_HIGH,
    # predictive: the heaviest models are effectively a rebuild on Spark ML/MLflow.
    "AutoML": VERY_HIGH,
    "NeuralNetwork": VERY_HIGH,
    "SupportVectorMachine": VERY_HIGH,
    "Optimization": VERY_HIGH,
    "SurvivalAnalysis": VERY_HIGH,
    # connectors: SaaS/system connectors need bespoke reconnection; blob is easy.
    "SharePointInput": HIGH,
    "DataverseInput": HIGH,
    "MongoInput": HIGH,
    "AmazonS3Download": MEDIUM,
    "AmazonS3Upload": MEDIUM,
    "AzureBlobInput": MEDIUM,
    "AzureBlobOutput": MEDIUM,
    # reporting: rendering/email delivery is reimplemented, charts map to AI/BI.
    "Render": HIGH,
    "ComposerRender": HIGH,
    "EmailOutput": HIGH,
    # interface: a Tab is a no-op container; the rest map to notebook widgets.
    "Tab": LOW,
}

# Optional effort model: hours per workflow keyed on its complexity level. Anchors
# match the bands documented for the analyzer (Low ~2h, Medium ~8h, High ~16h,
# Very High ~40h). Only used when hours are explicitly enabled.
DEFAULT_HOUR_ANCHORS: dict[str, float] = {LOW: 2.0, MEDIUM: 8.0, HIGH: 16.0, VERY_HIGH: 40.0}

# Tool types that represent a data source (used for the "data sources" total).
DEFAULT_SOURCE_TOOLS: frozenset[str] = frozenset(
    {
        "Input",
        "TextInput",
        "BlobInput",
        "Directory",
        "DynamicInput",
        "AmazonS3Download",
        "AzureBlobInput",
        "DataverseInput",
        "MongoInput",
        "SharePointInput",
        "CalgaryJoin",
    }
)


@dataclass
class ProfilerConfig:
    """Tunable inputs for the profiler. Defaults are sensible out of the box.

    ``category_tiers`` and ``tool_overrides`` control how tools are classified;
    ``hour_anchors`` and ``show_hours`` control the optional effort estimate.
    Load overrides from a YAML/JSON file with :meth:`from_file` — only the keys
    present in the file are overridden, everything else keeps its default.
    """

    category_tiers: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CATEGORY_TIERS))
    tool_overrides: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_TOOL_OVERRIDES))
    unsupported_tier: str = VERY_HIGH
    unknown_tier: str = MEDIUM
    hour_anchors: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_HOUR_ANCHORS))
    source_tools: frozenset[str] = DEFAULT_SOURCE_TOOLS
    show_hours: bool = False

    @classmethod
    def default(cls) -> ProfilerConfig:
        return cls()

    @classmethod
    def from_mapping(cls, data: dict) -> ProfilerConfig:
        """Build a config by merging a mapping of overrides over the defaults.

        Recognized keys: ``category_tiers`` (map), ``tool_overrides`` (map),
        ``hour_anchors`` (map), ``unsupported_tier``/``unknown_tier`` (str),
        ``show_hours`` (bool). Tier values must be one of Low/Medium/High/Very High.
        Shared by :meth:`from_file` (CLI) and the ``/api/assess`` endpoint (App).
        """
        if not isinstance(data, dict):
            raise ValueError("profiler config must be a mapping")

        cfg = cls.default()
        cfg.category_tiers.update(data.get("category_tiers") or {})
        cfg.tool_overrides.update(data.get("tool_overrides") or {})
        cfg.hour_anchors.update({k: float(v) for k, v in (data.get("hour_anchors") or {}).items()})
        if "unsupported_tier" in data:
            cfg.unsupported_tier = str(data["unsupported_tier"])
        if "unknown_tier" in data:
            cfg.unknown_tier = str(data["unknown_tier"])
        if "show_hours" in data:
            cfg.show_hours = bool(data["show_hours"])

        valid = set(TIER_ORDER)
        for label, mapping in (
            ("category_tiers", cfg.category_tiers),
            ("tool_overrides", cfg.tool_overrides),
            ("unsupported_tier", {"_": cfg.unsupported_tier}),
            ("unknown_tier", {"_": cfg.unknown_tier}),
        ):
            bad = {k: v for k, v in mapping.items() if v not in valid}
            if bad:
                raise ValueError(f"invalid tier(s) in {label}: {sorted(set(bad.values()))}; must be one of {sorted(valid)}")
        return cfg

    @classmethod
    def from_file(cls, path: Path) -> ProfilerConfig:
        """Load overrides from a YAML or JSON file, merged over the defaults."""
        text = Path(path).read_text(encoding="utf-8")
        if path.suffix.lower() in (".yaml", ".yml"):
            try:
                import yaml
            except ImportError as exc:  # pragma: no cover - env-dependent
                raise ImportError("PyYAML is required to read a YAML profiler config") from exc
            data = yaml.safe_load(text) or {}
        else:
            import json

            data = json.loads(text) or {}
        return cls.from_mapping(data)


def classify_tool(tool_type: str, *, is_unsupported: bool, config: ProfilerConfig | None = None) -> str:
    """Return the difficulty tier for a single tool type.

    Precedence: an unsupported tool (no converter) is always the unsupported tier;
    otherwise a per-tool override wins, then the tool's category default, then the
    unknown-tool fallback.
    """
    cfg = config or ProfilerConfig.default()
    if is_unsupported:
        return cfg.unsupported_tier
    if tool_type in cfg.tool_overrides:
        return cfg.tool_overrides[tool_type]
    category = TOOL_CATEGORY.get(tool_type)
    if category and category in cfg.category_tiers:
        return cfg.category_tiers[category]
    return cfg.unknown_tier


def default_tool_tiers() -> list[dict[str, str]]:
    """Every known tool with its category and default (supported) difficulty tier.

    Powers the App's optional per-tool override picker. The default is computed as
    if the tool had a converter; a tool that is actually unsupported in a given
    workflow is still forced to the unsupported tier at profiling time, regardless
    of any per-tool override.
    """
    cfg = ProfilerConfig.default()
    return [
        {"name": name, "category": category, "default": classify_tool(name, is_unsupported=False, config=cfg)}
        for name, category in sorted(TOOL_CATEGORY.items(), key=lambda kv: (kv[1], kv[0]))
    ]


@dataclass
class WorkflowSize:
    """Per-workflow row for the profiler (Lakebridge-like object record)."""

    workflow_name: str
    file_name: str
    node_count: int
    connection_count: int
    unique_tool_types: int
    coverage_percentage: float
    complexity_level: str
    complexity_score: float
    unsupported_count: int
    expression_count: int
    max_dag_depth: int
    has_macros: bool
    migration_priority: str
    estimated_effort: str
    estimated_hours: float | None = None


@dataclass
class EstateProfile:
    """Aggregated migration-profiler view over an estate of workflows."""

    workflows: list[WorkflowSize]
    # Portfolio totals
    total_workflows: int
    total_tools: int
    total_connections: int
    total_expressions: int
    total_data_sources: int
    workflows_with_macros: int
    unique_tool_types: int
    # Size distribution
    avg_tools_per_workflow: float
    max_tools: int
    max_tools_workflow: str
    avg_dag_depth: float
    max_dag_depth: int
    max_dag_depth_workflow: str
    # Distributions
    difficulty_distribution: dict[str, int]  # complexity level -> workflow count
    tool_tier_counts: dict[str, int]  # tier -> tool-instance count
    tool_tier_types: dict[str, list[str]]  # tier -> sorted unique tool types
    # Optional effort (only populated when show_hours)
    total_hours: float | None = None

    def to_dict(self) -> dict:
        return {
            "totals": {
                "workflows": self.total_workflows,
                "tools": self.total_tools,
                "connections": self.total_connections,
                "expressions": self.total_expressions,
                "data_sources": self.total_data_sources,
                "workflows_with_macros": self.workflows_with_macros,
                "unique_tool_types": self.unique_tool_types,
            },
            "size_distribution": {
                "avg_tools_per_workflow": round(self.avg_tools_per_workflow, 1),
                "max_tools": self.max_tools,
                "max_tools_workflow": self.max_tools_workflow,
                "avg_dag_depth": round(self.avg_dag_depth, 1),
                "max_dag_depth": self.max_dag_depth,
                "max_dag_depth_workflow": self.max_dag_depth_workflow,
            },
            "difficulty_distribution": self.difficulty_distribution,
            "tool_difficulty": {
                "counts": self.tool_tier_counts,
                "types": self.tool_tier_types,
            },
            "total_hours": self.total_hours,
            "workflows": [
                {
                    "workflow_name": w.workflow_name,
                    "file_name": w.file_name,
                    "node_count": w.node_count,
                    "connection_count": w.connection_count,
                    "unique_tool_types": w.unique_tool_types,
                    "coverage_percentage": w.coverage_percentage,
                    "complexity_level": w.complexity_level,
                    "complexity_score": round(w.complexity_score, 1),
                    "unsupported_count": w.unsupported_count,
                    "expression_count": w.expression_count,
                    "max_dag_depth": w.max_dag_depth,
                    "has_macros": w.has_macros,
                    "migration_priority": w.migration_priority,
                    "estimated_effort": w.estimated_effort,
                    "estimated_hours": w.estimated_hours,
                }
                for w in self.workflows
            ],
        }


def build_estate_profile(
    analyses: list[WorkflowAnalysis], config: ProfilerConfig | None = None
) -> EstateProfile:
    """Aggregate a list of :class:`WorkflowAnalysis` into an :class:`EstateProfile`."""
    cfg = config or ProfilerConfig.default()

    tier_counts: Counter[str] = Counter({t: 0 for t in TIER_ORDER})
    tier_types: dict[str, set[str]] = {t: set() for t in TIER_ORDER}
    difficulty: Counter[str] = Counter()
    total_data_sources = 0
    unique_types: set[str] = set()

    rows: list[WorkflowSize] = []
    total_hours = 0.0

    for a in analyses:
        cx = a.complexity
        unsupported = a.coverage.unsupported_types
        for tool_type, count in a.coverage.per_tool_counts.items():
            unique_types.add(tool_type)
            tier = classify_tool(tool_type, is_unsupported=tool_type in unsupported, config=cfg)
            tier_counts[tier] += count
            tier_types[tier].add(tool_type)
            if tool_type in cfg.source_tools:
                total_data_sources += count

        difficulty[cx.level] += 1
        hours = cfg.hour_anchors.get(cx.level) if cfg.show_hours else None
        if hours is not None:
            total_hours += hours

        rows.append(
            WorkflowSize(
                workflow_name=a.workflow_name,
                file_name=Path(a.file_path).name,
                node_count=a.node_count,
                connection_count=a.connection_count,
                unique_tool_types=cx.unique_tool_types,
                coverage_percentage=a.coverage.coverage_percentage,
                complexity_level=cx.level,
                complexity_score=cx.total_score,
                unsupported_count=cx.unsupported_count,
                expression_count=cx.expression_count,
                max_dag_depth=cx.max_dag_depth,
                has_macros=cx.has_macro_refs,
                migration_priority=a.migration_priority,
                estimated_effort=a.estimated_effort,
                estimated_hours=hours,
            )
        )

    n = len(rows)
    total_tools = sum(w.node_count for w in rows)
    max_tools_row = max(rows, key=lambda w: w.node_count, default=None)
    max_depth_row = max(rows, key=lambda w: w.max_dag_depth, default=None)

    return EstateProfile(
        workflows=sorted(rows, key=lambda w: w.complexity_score, reverse=True),
        total_workflows=n,
        total_tools=total_tools,
        total_connections=sum(w.connection_count for w in rows),
        total_expressions=sum(w.expression_count for w in rows),
        total_data_sources=total_data_sources,
        workflows_with_macros=sum(1 for w in rows if w.has_macros),
        unique_tool_types=len(unique_types),
        avg_tools_per_workflow=(total_tools / n) if n else 0.0,
        max_tools=max_tools_row.node_count if max_tools_row else 0,
        max_tools_workflow=max_tools_row.file_name if max_tools_row else "",
        avg_dag_depth=(sum(w.max_dag_depth for w in rows) / n) if n else 0.0,
        max_dag_depth=max_depth_row.max_dag_depth if max_depth_row else 0,
        max_dag_depth_workflow=max_depth_row.file_name if max_depth_row else "",
        difficulty_distribution={lvl: difficulty.get(lvl, 0) for lvl in TIER_ORDER},
        tool_tier_counts=dict(tier_counts),
        tool_tier_types={t: sorted(tier_types[t]) for t in TIER_ORDER},
        total_hours=round(total_hours, 1) if cfg.show_hours else None,
    )


def to_csv_rows(profile: EstateProfile) -> list[list[str]]:
    """Return CSV rows (header first) for the per-workflow profiler records."""
    header = [
        "workflow_name",
        "file_name",
        "node_count",
        "connection_count",
        "unique_tool_types",
        "coverage_percentage",
        "complexity_level",
        "complexity_score",
        "unsupported_count",
        "expression_count",
        "max_dag_depth",
        "has_macros",
        "migration_priority",
        "estimated_effort",
        "estimated_hours",
    ]
    rows = [header]
    for w in profile.workflows:
        rows.append(
            [
                w.workflow_name,
                w.file_name,
                str(w.node_count),
                str(w.connection_count),
                str(w.unique_tool_types),
                f"{w.coverage_percentage:.1f}",
                w.complexity_level,
                f"{w.complexity_score:.1f}",
                str(w.unsupported_count),
                str(w.expression_count),
                str(w.max_dag_depth),
                "yes" if w.has_macros else "no",
                w.migration_priority,
                w.estimated_effort,
                "" if w.estimated_hours is None else f"{w.estimated_hours:.1f}",
            ]
        )
    return rows

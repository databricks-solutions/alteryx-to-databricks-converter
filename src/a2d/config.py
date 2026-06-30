"""Configuration data classes for the Alteryx-to-Databricks conversion pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

# Cloud-specific driver/worker node_type_id values for the auto-generated cluster.
# Used by both the Workflow JSON and DAB generators so the produced job can run on
# the user's actual Databricks workspace cloud. The defaults below match what
# Databricks' "Create Job" UI suggests as a small all-purpose starter:
#   aws  -> i3.xlarge       (general-purpose, NVMe-backed)
#   azure-> Standard_DS3_v2 (general-purpose)
#   gcp  -> n1-highmem-4    (general-purpose)
# Users should review these against their workspace policies before deploying.
CLOUD_NODE_TYPE_IDS: dict[str, str] = {
    "aws": "i3.xlarge",
    "azure": "Standard_DS3_v2",
    "gcp": "n1-highmem-4",
}

CloudName = Literal["aws", "azure", "gcp"]


class OutputFormat(Enum):
    """Target output format for code generation."""

    PYSPARK = "pyspark"
    DLT = "dlt"
    SQL = "sql"
    LAKEFLOW = "lakeflow"


class CatalogMode(Enum):
    """Databricks catalog mode."""

    UNITY_CATALOG = "unity_catalog"
    HIVE_METASTORE = "hive_metastore"


@dataclass(frozen=True)
class ConversionConfig:
    """Settings that govern how Alteryx nodes are converted to IR and then to code.

    Attributes:
        input_path: Path to the .yxmd file (or directory of files).
        output_dir: Where generated code is written.
        output_format: Target code style (PySpark, DLT, SQL, Lakeflow).
        catalog_mode: Unity Catalog or legacy Hive metastore.
        catalog_name: Default catalog for Unity Catalog mode.
        schema_name: Default schema/database name.
        generate_orchestration: Whether to emit a DatabricksWorkflow YAML.
        include_comments: Add explanatory comments to generated code.
        spark_version: Target Apache Spark version string.
        dbr_version: Target Databricks Runtime version string.
        connection_overrides: Map of Alteryx connection names to Databricks equivalents.
        cloud: Target cloud for cluster sizing — drives ``node_type_id`` selection
            in the Workflow JSON and DAB generators. Defaults to ``"aws"``
            (i3.xlarge), the most common starter SKU. Use ``"azure"``
            (Standard_DS3_v2) or ``"gcp"`` (n1-highmem-4) for those clouds.
    """

    input_path: Path = field(default_factory=lambda: Path("."))
    output_dir: Path = field(default_factory=lambda: Path("./a2d-output"))
    output_format: OutputFormat = OutputFormat.PYSPARK
    catalog_mode: CatalogMode = CatalogMode.UNITY_CATALOG
    catalog_name: str = "main"
    schema_name: str = "default"
    generate_orchestration: bool = True
    include_comments: bool = True
    spark_version: str = "3.5"
    dbr_version: str = "14.3"
    verbose_unsupported: bool = False
    connection_overrides: dict[str, str] = field(default_factory=dict)
    connection_mapping_path: Path | None = None
    include_expression_audit: bool = True
    include_performance_hints: bool = True
    generate_ddl: bool = False
    generate_dab: bool = False
    expand_macros: bool = False
    cloud: CloudName = "aws"

    def __post_init__(self) -> None:
        if not isinstance(self.output_format, OutputFormat):
            raise ValueError(f"output_format must be an OutputFormat enum, got {type(self.output_format).__name__}")
        if not isinstance(self.catalog_mode, CatalogMode):
            raise ValueError(f"catalog_mode must be a CatalogMode enum, got {type(self.catalog_mode).__name__}")
        if not self.catalog_name.strip():
            raise ValueError("catalog_name must not be empty")
        if not self.schema_name.strip():
            raise ValueError("schema_name must not be empty")
        if self.cloud not in CLOUD_NODE_TYPE_IDS:
            raise ValueError(f"cloud must be one of {sorted(CLOUD_NODE_TYPE_IDS)}, got {self.cloud!r}")

    @property
    def node_type_id(self) -> str:
        """Return the cloud-appropriate driver/worker ``node_type_id``.

        Looked up from :data:`CLOUD_NODE_TYPE_IDS`. Used by the Workflow JSON
        and DAB generators to populate the auto-generated cluster spec.
        """
        return CLOUD_NODE_TYPE_IDS[self.cloud]

# Architecture Deep-Dive

This document explains the internal architecture of the `a2d` (Alteryx-to-Databricks) migration tool. It covers the end-to-end pipeline, each module's responsibilities, key data structures, and the design decisions behind them.

---

## Table of Contents

1. [Overall Pipeline Flow](#overall-pipeline-flow)
2. [Parser Module](#parser-module)
3. [Intermediate Representation (IR)](#intermediate-representation-ir)
4. [Converter Registry](#converter-registry)
5. [Expression Engine](#expression-engine)
6. [Code Generators](#code-generators)
7. [Observability & Quality](#observability--quality)
8. [Analyzer](#analyzer)
9. [Additional Modules](#additional-modules)
10. [Design Decisions](#design-decisions)

---

## Overall Pipeline Flow

Every conversion follows the same five-stage pipeline, orchestrated by `ConversionPipeline` in `src/a2d/pipeline.py`:

```
  .yxmd XML file
       |
       | (1) Parse
       v
  ParsedWorkflow
  (ParsedNode[] + ParsedConnection[])
       |
       | (2) Convert (per node)
       v
  IRNode instances
  (FilterNode, JoinNode, FormulaNode, ...)
       |
       | (3) Build DAG
       v
  WorkflowDAG
  (NetworkX DiGraph with IRNode data + EdgeInfo metadata)
       |
       | (4) Validate
       v
  Structural checks (cycles, disconnected components)
       |
       | (5) Generate
       v
  GeneratedOutput
  (GeneratedFile[] + warnings + stats)
```

Each stage is decoupled. The parser knows nothing about PySpark. The generators know nothing about XML. The IR is the single shared contract.

### Entry Points

- **CLI** (`src/a2d/cli.py`): `convert`, `analyze`, `validate`, `list-tools`, and `version`. `a2d convert` defaults to emitting ALL four formats (pyspark, dlt, sql, lakeflow) into per-format subdirectories of `--output-dir`; `--format` accepts a comma-separated filter (e.g. `pyspark,sql`). The single-file path parses the `.yxmd` and builds the IR DAG ONCE via `ConversionPipeline.convert_all_formats()`, then runs all four generators on the shared DAG (mirrors `server/services/conversion.py` so CLI and server share parse cost). After conversion the CLI prints a 3-tier deploy-readiness banner (Ready / Needs review / Cannot deploy as-is), a counts row (coverage · confidence · tools converted · review · blockers), and warnings grouped into categories (`Cannot convert`, `Manual review needed`, `Graph structure note`, `Other`) — same layout as the Convert page in the UI. The `--cloud {aws|azure|gcp}` flag (default `aws`) drives the auto-generated `node_type_id` in the Workflow JSON and DAB outputs via `CLOUD_NODE_TYPE_IDS` in `a2d/config.py`.
- **Server** (`server/main.py`): FastAPI app with REST routers (`health`, `tools`, `convert`, `analyze`, `history`, `validate`) and a WebSocket for batch progress. Run with `uvicorn server.main:app`. `POST /api/convert` always returns every output format in a single response (`ConversionResponse.formats: dict[str, FormatResultResponse]` plus a `best_format` string — see `server/models/responses.py`); the legacy `output_format` request parameter was removed. An SPA fallback route serves the React `index.html` for any unknown path so deep-link refreshes work, while `/api/*` and `/ws/*` continue to return JSON 404s.
- **Databricks App**: `databricks.yml` + `app.yaml` package the FastAPI server + React build for deployment via `make deploy-dev` / `make deploy-prod`. Optional Lakebase Postgres backend lives in `server/services/lakebase.py` and is selected via `A2D_DB_BACKEND=lakebase`.
- **Frontend**: React SPA served by the FastAPI server (the Settings page no longer has a default-output-format selector — every conversion produces all four formats).
- **Programmatic**: Import `ConversionPipeline` directly and call `.convert()` once per `OutputFormat`.

---

## Parser Module

**Location**: `src/a2d/parser/`

The parser reads Alteryx `.yxmd` files, which are XML documents with this structure:

```xml
<AlteryxDocument yxmdVer="2023.1">
  <Nodes>
    <Node ToolID="1">
      <GuiSettings Plugin="AlteryxBasePluginsGui.Formula.Formula">
        <Position x="300" y="200" />
      </GuiSettings>
      <Properties>
        <Configuration>
          <!-- tool-specific XML -->
        </Configuration>
        <Annotation DisplayMode="0">
          <Name>Calculate Tax</Name>
        </Annotation>
      </Properties>
    </Node>
    <!-- more nodes -->
  </Nodes>
  <Connections>
    <Connection>
      <Origin ToolID="1" Connection="Output" />
      <Destination ToolID="2" Connection="Input" />
    </Connection>
  </Connections>
  <Properties>
    <!-- workflow-level properties -->
  </Properties>
</AlteryxDocument>
```

### Components

| File | Responsibility |
|------|---------------|
| `workflow_parser.py` | Top-level parser. Uses `lxml.etree` to parse the XML tree. Delegates node and connection parsing to specialized sub-parsers. Detects macro references. |
| `node_parser.py` | Extracts a single `<Node>` element into a `ParsedNode`: tool ID, plugin name, position, configuration dict, and annotation. |
| `connection_parser.py` | Extracts `<Connection>` elements into `ParsedConnection` objects with origin/destination anchors. |
| `schema.py` | Data classes (`ParsedWorkflow`, `ParsedNode`, `ParsedConnection`, `FieldInfo`) and the **`PLUGIN_NAME_MAP`**. |

### PLUGIN_NAME_MAP

This is the Rosetta Stone of the tool. It maps the raw Alteryx plugin string (e.g., `"AlteryxBasePluginsGui.Filter.Filter"`) to a human-readable tuple:

```python
"AlteryxBasePluginsGui.Filter.Filter": ("Filter", "preparation")
```

The first element is the **tool type** (used to look up converters). The second is the **category** (used for reporting and the tool matrix).

The map contains 157 entries spanning IO, Preparation, Join, Parse, Transform, Developer, Spatial, Predictive, Reporting, and Interface categories. Many Alteryx tools have multiple plugin name variants (e.g., `Union.Union` vs `UnionV2.UnionV2`), all mapped to the same canonical tool type. A companion `TOOL_METADATA` dict (151 entries) provides display names, categories, and support status for each tool type.

### Configuration Extraction

Each Alteryx tool stores its settings in a `<Configuration>` XML block with tool-specific structure. The node parser converts this XML subtree into a Python dictionary using `xml_helpers.element_to_dict`. This dict is stored on `ParsedNode.configuration` and is interpreted later by each converter.

---

## Intermediate Representation (IR)

**Location**: `src/a2d/ir/`

The IR is the heart of the architecture. It provides a **typed, tool-agnostic** representation of workflow logic.

### Node Hierarchy

All IR nodes inherit from the abstract `IRNode` base class:

```
IRNode (abstract)                      60 concrete subclasses
  |
  +── IO ──────────────────────────────────────────────────────
  +-- ReadNode              # File/database input
  +-- WriteNode             # File/database output
  +-- LiteralDataNode       # Inline data (TextInput)
  +-- BrowseNode            # Preview/display
  +-- CloudStorageNode      # Cloud blob storage
  +-- DynamicInputNode      # Wildcard/dynamic file reads
  |
  +── Preparation ─────────────────────────────────────────────
  +-- SelectNode            # Column select/rename/retype
  +-- FilterNode            # Row filtering (True/False outputs)
  +-- FormulaNode           # Calculated columns
  +-- SortNode              # Row ordering
  +-- SampleNode            # Row limiting/sampling
  +-- UniqueNode            # Deduplication
  +-- RecordIDNode          # Sequential ID generation
  +-- MultiRowFormulaNode   # Window-based formulas
  +-- MultiFieldFormulaNode # Multi-column formulas
  +-- DataCleansingNode     # Trim, null handling, case
  +-- AutoFieldNode         # Type optimization (passthrough)
  +-- GenerateRowsNode      # Iterative row generation
  +-- ImputationNode        # Missing value imputation
  +-- OversampleNode        # Row oversampling
  |
  +── Join ────────────────────────────────────────────────────
  +-- JoinNode              # Two-input join
  +-- UnionNode             # Multi-input concatenation
  +-- FindReplaceNode       # Lookup-based replacement
  +-- AppendFieldsNode      # Cross join
  +-- JoinMultipleNode      # Multi-input join
  |
  +── Parse ───────────────────────────────────────────────────
  +-- RegExNode             # Regex parse/match/replace
  +-- TextToColumnsNode     # String splitting
  +-- DateTimeNode          # Date parsing/formatting
  +-- JsonParseNode         # JSON extraction
  +-- XmlParseNode          # XML extraction
  |
  +── Transform ───────────────────────────────────────────────
  +-- SummarizeNode         # Group-by aggregation
  +-- CrossTabNode          # Pivot
  +-- TransposeNode         # Unpivot
  +-- RunningTotalNode      # Window running calculations
  +-- CountRecordsNode      # Record counting
  +-- TileNode              # Quantile binning (ntile)
  |
  +── Developer ───────────────────────────────────────────────
  +-- PythonToolNode        # Embedded Python
  +-- DownloadNode          # HTTP requests
  +-- RunCommandNode        # External commands
  +-- BlockUntilDoneNode    # Synchronization barrier
  |
  +── Spatial (28 nodes) ──────────────────────────────────────
  +-- BufferNode, SpatialMatchNode, MakePointsNode, ...
  |
  +── Predictive ──────────────────────────────────────────────
  +-- (All ~28 predictive tool types map to UnsupportedNode via generic converter)
  |
  +── Meta ────────────────────────────────────────────────────
  +-- UnsupportedNode       # Fallback for unknown tools
  +-- CommentNode           # Canvas annotations
```

> The full list of 60 node types is defined in `src/a2d/ir/nodes.py`. Spatial nodes have typed IR nodes but generate `# TODO` placeholders at generation time. Predictive tools all route through a single generic converter to `UnsupportedNode` with `# TODO` placeholders.

Each node carries:
- `node_id`: The original Alteryx ToolID (integer)
- `original_tool_type` / `original_plugin_name`: For traceability
- `annotation`: User-supplied label from the Alteryx canvas
- `position`: Canvas coordinates
- `conversion_confidence`: 0.0-1.0 reliability score
- `conversion_notes`: Free-text warnings

Subclasses add semantics-specific fields. For example, `FilterNode` has `expression` and `mode`; `JoinNode` has `join_keys`, `join_type`, `select_left`, and `select_right`.

### WorkflowDAG

The `WorkflowDAG` class (`src/a2d/ir/graph.py`) wraps a NetworkX `DiGraph`:

- **Nodes** are keyed by `node_id` (int) and store the `IRNode` under the `"ir"` attribute.
- **Edges** carry `EdgeInfo` with `origin_anchor`, `destination_anchor`, and `is_wireless` flag.

Key operations:

| Method | Purpose |
|--------|---------|
| `topological_order()` | Returns nodes in dependency-respecting order for code generation |
| `get_predecessors(id)` | Input nodes for a given node |
| `get_successors(id)` | Downstream consumers |
| `get_source_nodes()` | Entry points (no predecessors) |
| `get_sink_nodes()` | Terminal points (no successors) |
| `get_connected_components()` | Identify disconnected subgraphs |
| `validate()` | Check for cycles, missing node references, disconnected components |

### Visitor Pattern

`src/a2d/ir/visitors.py` defines an `IRVisitor` base class with double-dispatch:

```python
class MyVisitor(IRVisitor):
    def visit_FilterNode(self, node: FilterNode) -> str:
        return f"WHERE {node.expression}"

visitor = MyVisitor()
result = visitor.visit(some_filter_node)
```

The dispatcher calls `visit_<ClassName>` on the visitor, falling back to `generic_visit`. This is used internally and is available for custom analysis passes.

### Type System

`AlteryxDataType` in `schema.py` maps Alteryx type strings (`"V_WString"`, `"Int32"`, `"DateTime"`, etc.) to a Python enum for downstream type conversion. Shared type utilities live in `src/a2d/utils/types.py`.

---

## Converter Registry

**Location**: `src/a2d/converters/`

### Pattern: Decorator-Based Registration

Every converter is a subclass of `ToolConverter` with two required members:

```python
class ToolConverter(ABC):
    @abstractmethod
    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        ...

    @property
    @abstractmethod
    def supported_tool_types(self) -> list[str]:
        ...
```

Registration uses a class decorator:

```python
@ConverterRegistry.register
class FilterConverter(ToolConverter):
    @property
    def supported_tool_types(self) -> list[str]:
        return ["Filter"]

    def convert(self, parsed_node, config):
        # Extract configuration, build FilterNode
        ...
```

At import time, `@ConverterRegistry.register`:
1. Instantiates the converter class
2. Iterates `supported_tool_types`
3. Maps each tool type string to the converter instance in `_converters` dict

### Lookup Flow

```
ConversionPipeline._build_dag()
  -> ConverterRegistry.convert_node(parsed_node, config)
    -> ConverterRegistry.get_converter(parsed_node.tool_type)
      -> converter.convert(parsed_node, config)
        -> returns IRNode subclass
```

If no converter is registered, `convert_node` returns an `UnsupportedNode` with the original configuration preserved for manual review.

### Converter Organization

62 converter files handling 112 tool types are organized across 8 categories:

```
converters/                          62 files total
  io/             (8)   input_data, output_data, text_input, browse,
                        cloud_storage, dynamic_input, tableau_publish, ...
  preparation/    (16)  filter, formula, select, sort, sample, unique,
                        record_id, multi_row_formula, multi_field_formula,
                        data_cleansing, auto_field, generate_rows, ...
  join/           (6)   join, union, find_replace, append_fields, join_multiple, ...
  parse/          (7)   regex, text_to_columns, datetime_tool, json_parse, xml_parse, ...
  transform/      (8)   summarize, cross_tab, transpose, running_total,
                        count_records, tile, ...
  developer/      (12)  python_tool, download, run_command, block_until_done, ...
  spatial/        (9)   buffer, spatial_match, make_points, distance, ...
  predictive/     (1)   generic.py (handles all ~28 predictive tool types)
```

Each `__init__.py` imports its submodules to trigger registration. Spatial converters produce typed IR nodes but generate `# TODO` placeholders since these tools require manual reimplementation in Databricks. Predictive tools all route through a single generic converter (`predictive/generic.py`) that maps every predictive tool type to `UnsupportedNode` with a `# TODO` placeholder.

### Coverage Tracking

`ConverterRegistry.supported_tools()` returns the set of all registered tool type strings. `coverage_for(tool_types)` computes the fraction of a given set that has converters. This powers the analyzer's coverage reports.

---

## Expression Engine

**Location**: `src/a2d/expressions/` (7 files: `base_translator.py`, `errors.py`, `functions.py`, `parser.py`, `sql_translator.py`, `tokenizer.py`, `translator.py`)

The expression engine handles Alteryx formula syntax (used in Formula, Filter, MultiRowFormula, and other expression-bearing tools). It follows a classic compiler pipeline:

```
  Alteryx expression string
  "[Amount] * 0.13 + IF [Status] = 'Active' THEN 10 ELSE 0 ENDIF"
       |
       | (1) Tokenize
       v
  Token stream
  [FIELD_REF:"Amount", OPERATOR:"*", NUMBER:"0.13", OPERATOR:"+",
   KEYWORD:"IF", FIELD_REF:"Status", COMPARISON:"=", STRING:"Active",
   KEYWORD:"THEN", NUMBER:"10", KEYWORD:"ELSE", NUMBER:"0",
   KEYWORD:"ENDIF", EOF]
       |
       | (2) Parse (recursive descent)
       v
  AST (Abstract Syntax Tree)
  BinaryOp(+,
    BinaryOp(*,
      FieldRef("Amount"),
      Literal(0.13)),
    IfExpr(
      condition=ComparisonOp(=, FieldRef("Status"), Literal("Active")),
      then_expr=Literal(10),
      else_expr=Literal(0)))
       |
       | (3) Translate
       v
  PySpark: (F.col("Amount") * 0.13) + F.when((F.col("Status") == F.lit("Active")), 10).otherwise(0)
  SQL:     (Amount * 0.13) + CASE WHEN Status = 'Active' THEN 10 ELSE 0 END
```

### Stage 1: Tokenizer

`AlteryxTokenizer` (`tokenizer.py`) scans the expression string character by character and produces `Token` objects with:

- `token_type`: One of `FIELD_REF`, `ROW_REF`, `STRING`, `NUMBER`, `OPERATOR`, `COMPARISON`, `LOGICAL`, `KEYWORD`, `FUNCTION`, `IDENTIFIER`, `LPAREN`, `RPAREN`, `COMMA`, `EOF`
- `value`: The token content
- `position`: Character offset for error reporting

Special handling:
- **Field references** `[FieldName]` -> `FIELD_REF` token
- **Row references** `[Row-1:FieldName]` -> `ROW_REF` token with `"offset:fieldname"` value
- **Function detection**: Identifiers followed by `(` are tagged as `FUNCTION` (unless they are keywords like `IF`)
- **Escaped strings**: Supports both backslash escaping and doubled-quote escaping

### Stage 2: Parser

`ExpressionParser` (`parser.py`) is a recursive descent parser that builds an AST from the token stream. Operator precedence (lowest to highest):

1. `OR`
2. `AND`
3. `NOT`
4. Comparisons: `=`, `!=`, `<`, `>`, `<=`, `>=`
5. `IN`
6. Addition, subtraction: `+`, `-`
7. Multiplication, division, modulo: `*`, `/`, `%`
8. Unary: `-`, `NOT`
9. Primary: literals, field refs, function calls, parenthesized exprs, `IF`

Grammar highlights:
- **IF blocks**: `IF cond THEN expr [ELSEIF cond THEN expr]* [ELSE expr] ENDIF`
- **IN expressions**: `expr IN (val1, val2, ...)`
- **Function calls**: `FunctionName(arg1, arg2, ...)` with variable arguments
- **Nested expressions**: Full recursion through parentheses

### Stage 3: AST

The AST nodes (`ast.py`) are dataclasses:

| Node | Semantics |
|------|-----------|
| `FieldRef` | Column reference `[Name]` |
| `RowRef` | Multi-row reference `[Row-1:Name]` |
| `Literal` | String, number, boolean, or null |
| `BinaryOp` | `left op right` (arithmetic) |
| `UnaryOp` | `-operand` |
| `ComparisonOp` | `left cmp right` |
| `LogicalOp` | `left AND/OR right` |
| `NotOp` | `NOT operand` |
| `FunctionCall` | `name(args...)` |
| `IfExpr` | `IF/THEN/ELSEIF/ELSE/ENDIF` |
| `InExpr` | `value IN (items...)` |

### Stage 4: Translators

Two translators walk the AST:

**`PySparkTranslator`** (`translator.py`):
- `FieldRef` -> `F.col("name")`
- `RowRef` -> `F.lag(F.col("name"), N).over(window)` or `F.lead(...)`
- `Literal` -> `F.lit(value)` for strings/booleans/null, raw for numbers
- `ComparisonOp` -> maps `=` to `==`, `<>` to `!=`
- `LogicalOp` -> `&` for AND, `|` for OR
- `IfExpr` -> `F.when(cond, then).when(elif_cond, elif_then).otherwise(else_val)`
- `InExpr` -> `.isin([items])`
- `FunctionCall` -> looks up `FunctionMapping` in the registry and substitutes args into template

**`SparkSQLTranslator`** (`sql_translator.py`):
- Same pattern but emits SQL syntax
- `FieldRef` -> backtick-quoted column name
- `IfExpr` -> `CASE WHEN ... THEN ... ELSE ... END`
- `FunctionCall` -> uses `sql_template` from the function registry

### Function Registry

`FUNCTION_REGISTRY` (`functions.py`) maps 141 function names (case-insensitive) to `FunctionMapping` objects:

```python
@dataclass
class FunctionMapping:
    alteryx_name: str
    pyspark_template: str   # e.g., "F.substring({0}, ({1}) + 1, {2})"
    sql_template: str       # e.g., "SUBSTRING({0}, ({1}) + 1, {2})"
    min_args: int
    max_args: int | None
    notes: str              # e.g., "Alteryx is 0-indexed, Spark is 1-indexed"
```

Templates use `{0}`, `{1}`, ... for positional arguments and `{args}` for variable-length argument lists (e.g., `Concat`, `Coalesce`).

---

## Code Generators

**Location**: `src/a2d/generators/`

Four code generators produce output in different formats, plus auxiliary generators for Workflow JSON, Unity Catalog DDL, and DAB configs (8 generator files total). All share a common base class and the same DAG traversal pattern.

### Base Class

All generators extend `CodeGenerator` (`base.py`):

```python
class CodeGenerator(ABC):
    def __init__(self, config: ConversionConfig):
        self.config = config

    @abstractmethod
    def generate(self, dag: WorkflowDAG, workflow_name: str) -> GeneratedOutput:
        ...
```

`GeneratedOutput` holds a list of `GeneratedFile` objects (filename + content + type), warnings, and statistics. The base class also performs `ast.parse()` syntax validation on generated Python code to catch generation bugs early.

### PySpark Generator

`PySparkGenerator` (`pyspark.py`) walks the DAG in topological order:

1. For each node, resolve input variable names from predecessors via `_resolve_input_vars`
2. Dispatch to `_generate_<NodeClassName>` method (visitor-like pattern via `getattr`)
3. Each method returns a `NodeCodeResult` with code lines, output variable mapping, imports, and warnings
4. Assemble cells with `# COMMAND ----------` separators into a Databricks notebook

Variable naming convention: `df_{node_id}` for single-output nodes, `df_{node_id}_true` / `df_{node_id}_false` for Filter, `df_{node_id}_join` / `df_{node_id}_left` / `df_{node_id}_right` for Join.

### Spark Declarative Pipelines Generator (internal id: `dlt`)

`DLTGenerator` (`dlt.py`) produces `@dlt.table` decorated functions for what
Databricks now calls **Lakeflow Spark Declarative Pipelines** (formerly
Delta Live Tables). The internal id, file name, and decorator surface remain
`dlt` for backward compatibility with DBR-hosted notebooks where `import dlt`
still works:

```python
@dlt.table(name="step_3_filter", comment="Filter active records")
def step_3_filter():
    return dlt.read("step_2_formula").filter(F.col("Status") == F.lit("Active"))
```

Each node becomes a named pipeline table. Upstream references use
`dlt.read("table_name")`.

> **Forward-compatibility note (2026-Q1+):** Databricks recommends migrating
> Python pipelines to `from pyspark import pipelines as dp` with
> `@dp.materialized_view` / `@dp.table` (streaming) and `@dp.expect(...)`.
> The `dlt` module still works but is on the deprecation track. We continue
> to emit `import dlt` because it remains the most broadly compatible import
> across DBR LTS versions in the field; revisit when `pyspark.pipelines` is
> available on all supported DBR LTS releases.

### SQL Generator

`SQLGenerator` (`sql.py`) produces CTE-based SQL:

```sql
WITH step_1_input AS (
    SELECT * FROM csv.`/data/sales.csv`
),
step_2_formula AS (
    SELECT *, Amount * 0.13 AS `TaxAmount` FROM step_1_input
),
step_3_filter AS (
    SELECT * FROM step_2_formula WHERE Amount > 100
)
SELECT * FROM step_3_filter;
```

### Lakeflow Generator

`LakeflowGenerator` (`lakeflow.py`, ~280 lines) inherits from `SQLGenerator` and overrides the output structure:

```sql
-- File-based sources become STREAMING TABLEs
CREATE OR REFRESH STREAMING TABLE step_1_input
AS SELECT * FROM STREAM read_files('/data/sales.csv', format => 'csv', header => true);

-- All transformations become MATERIALIZED VIEWs
CREATE OR REFRESH MATERIALIZED VIEW step_2_formula
AS SELECT *, Amount * 0.13 AS `TaxAmount` FROM LIVE.step_1_input;
```

Key differences from SQL generator:
- Each CTE becomes a standalone `CREATE OR REFRESH` statement (no `WITH` wrapper)
- Upstream references use `LIVE.` prefix for inter-view resolution (legacy publishing mode — see note below)
- `ReadNode` / `CloudStorageNode` / `DynamicInputNode` emit `STREAMING TABLE`
- All other nodes emit `MATERIALIZED VIEW`
- Filter fan-out: True/False branches become separate views (`step_N_filter_true`, `step_N_filter_false`)
- Produces a companion `_lakeflow_pipeline.json` with catalog, target schema, and cluster config

> **`LIVE.` prefix status (2026):** The `LIVE` virtual schema is a legacy
> feature of Lakeflow Spark Declarative Pipelines and is considered
> deprecated. In **default publishing mode** (the only mode available for
> new pipelines created via the UI since 2025-02-05), `LIVE.` is silently
> ignored — unqualified table refs resolve against the pipeline's catalog
> and schema. The generated SQL still includes `LIVE.` so it remains
> compatible with legacy-mode pipelines; for new pipelines you can remove
> it. We emit it for safety; tracked for removal once default-mode rollout
> is complete on customer fleets.

### Workflow JSON Generator

`WorkflowJsonGenerator` (`workflow_json.py`) produces a Lakeflow Jobs (Databricks Jobs API) compatible JSON definition with:
- Job name, description, and tags
- Notebook, Spark Declarative Pipelines pipeline, or Lakeflow pipeline task (depending on output format)
- A single auto-provisioned `job_clusters[]` entry keyed `"main"`; tasks reference it via `job_cluster_key: "main"` (mirrors DAB convention)
- Cloud-aware `node_type_id` selected from `CLOUD_NODE_TYPE_IDS` based on `ConversionConfig.cloud` (`aws=i3.xlarge`, `azure=Standard_DS3_v2`, `gcp=n1-highmem-4`)
- Top-level `queue: {enabled: true}` and `parameters: []` placeholder (Jobs API 2.2 best practice)
- Timeout and retry settings

The JSON is **strict** (no `//` comment headers — parses cleanly with `json.loads`, `jq`, third-party tools). Operator notes about intentionally-omitted fields (`run_as`, `webhook_notifications`) live in a sibling `*_workflow.README.md` markdown file generated alongside the JSON.

### Auxiliary Generators

| Generator | File | Purpose |
|-----------|------|---------|
| Unity Catalog DDL | `unity_catalog.py` | `CREATE TABLE` / `EXTERNAL TABLE` DDL from ReadNode/WriteNode. Non-Delta external tables (CSV/JSON/Parquet/Avro at a path) emit the `read_files()` pattern (`CREATE TABLE ... AS SELECT * FROM read_files(...)`) instead of `CREATE EXTERNAL TABLE` so the result is a Delta-managed table over a foreign format — this matches Unity Catalog's recommendation since 2024-Q4. |
| DAB | `dab.py` | Databricks Asset Bundle `databricks.yml` with job and environment config. `node_type_id` is cloud-aware (`--cloud aws|azure|gcp`). |

---

## Analyzer

**Location**: `src/a2d/analyzer/` (5 files: `batch.py`, `complexity.py`, `coverage.py`, `readiness.py`, `report.py`)

### Complexity Scoring

`ComplexityAnalyzer` (`complexity.py`) scores workflows on a 0-100 weighted scale across 7 dimensions:

| Dimension | Weight | Low (0) | High (100) |
|-----------|--------|---------|------------|
| Node count | 18% | <= 5 nodes | >= 30 nodes |
| Tool diversity | 13% | <= 3 types | >= 12 types |
| Expression count | 18% | 0 expressions | >= 10 expressions |
| Unsupported ratio | 23% | 0% | >= 50% |
| Macro references | 8% | None | >= 3 macros |
| DAG depth | 10% | <= 3 levels | >= 15 levels |
| Spatial tool count | 10% | 0 spatial tools | >= 5 spatial tools |

Thresholds: **Low** (0-25), **Medium** (25-50), **High** (50-75), **Very High** (75-100).

The analyzer exposes a `to_dict()` method for serialization and is accessible via `a2d analyze --complexity`.

Expressions are counted from `FormulaNode` (each formula field), `FilterNode`, `MultiRowFormulaNode`, `MultiFieldFormulaNode`, and `RegExNode`.

### Coverage Analysis

`CoverageAnalyzer` (`coverage.py`) computes:
- Set of unique tool types in the workflow
- Subset with registered converters (supported)
- Subset without converters (unsupported)
- Coverage percentage
- Per-tool frequency counts

### Report Generation

`ReportGenerator` (`report.py`) produces:
- **HTML report**: Styled dashboard with summary metrics, per-workflow tables, complexity breakdown, and coverage details
- **JSON report**: Machine-readable version for integration with project management tools

`BatchAnalyzer` (`batch.py`) orchestrates analysis across multiple files.

---

## Observability & Quality

**Location**: `src/a2d/observability/` (7 files: `confidence.py`, `errors.py`, `expression_audit.py`, `hints.py`, `performance_hints.py`, `batch.py`, `report.py`)

### Confidence Scoring

`ConfidenceScorer` (`confidence.py`) computes a 0-1 workflow-level confidence score across 5 weighted dimensions:

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| Tool coverage | 35% | Fraction of tools with registered converters |
| Expression fidelity | 25% | Fraction of expressions translated without fallback |
| Join completeness | 15% | Fraction of joins with fully resolved keys |
| Data type preservation | 15% | Fraction of columns with mapped Spark types |
| Generator warnings | 10% | Inverse of warning count (fewer = better) |

The score is attached to `ConversionResult.confidence` and displayed in CLI output, server responses, HTML reports, and the slide deck.

### Enriched Warnings

`hints.py` maps 50+ warning patterns to actionable remediation hints with categories. Each warning is enriched with:
- `hint`: A human-readable suggestion (e.g., "Replace ODBC DSN with Unity Catalog table reference")
- `category`: Classification (e.g., "connection", "expression", "unsupported_tool")

### Expression Audit

`expression_audit.py` walks the DAG and captures every expression from FormulaNode, FilterNode, MultiRowFormulaNode, etc., producing a CSV-exportable audit trail with original Alteryx expression and translated PySpark/SQL output.

### Performance Hints

`performance_hints.py` analyzes the DAG for performance anti-patterns:
- **Broadcast join candidates**: Small-table joins that should use `broadcast()`
- **Persist candidates**: DataFrames with multiple downstream consumers
- **Repartition candidates**: Post-join shuffles that would benefit from repartitioning
- **Sequential join detection**: Chains of joins that could be restructured

---

## Additional Modules

### Connection Mapping (`connections.py`)

YAML-based mapping of Alteryx connection strings (ODBC DSNs, file paths, `aka:` aliases) to Unity Catalog locations. Used by `--connection-map` CLI flag and the server's connection editor UI.

---

## Design Decisions

### Why a Typed IR?

A generic "dictionary of settings" would be faster to implement but fragile. The typed IR catches bugs at development time (mypy), makes generator code self-documenting, and allows multiple generators to share the same data contract without coupling to XML structure.

### Why Decorator-Based Registration?

The `@ConverterRegistry.register` pattern means adding a new converter requires zero changes to the registry itself -- just create a new file in the right directory and import it. This scales cleanly as tool coverage grows.

### Why Recursive Descent for Expressions?

Alteryx expressions have relatively simple grammar (no user-defined operators, no macros). A hand-written recursive descent parser is straightforward to debug, extend, and test. It handles all observed Alteryx expression patterns including nested IF/THEN/ELSE, IN expressions, and function calls with variable arguments.

### Why NetworkX for the DAG?

NetworkX provides battle-tested topological sort, cycle detection, path analysis, and connected component algorithms out of the box. The overhead is negligible compared to XML parsing and code generation.

### Why Topological Code Generation?

Walking the DAG in topological order guarantees that every input variable is defined before it is referenced. This is essential for generating valid sequential code (PySpark cells, SQL CTEs, DLT functions).

### Why Multiple Output Formats?

Different migration targets and team preferences. The CLI and server both produce all four formats per conversion by default; reviewers can compare them side-by-side and pick the one that fits the deployment story.

- **PySpark notebooks**: Easiest to review and debug interactively
- **Spark Declarative Pipelines (DLT)**: Production-ready with built-in data quality expectations (internal id `dlt`)
- **SQL**: Preferred by SQL-oriented teams and for simple transformations
- **Lakeflow Designer**: Native Databricks pipeline format with `STREAMING TABLE` / `MATERIALIZED VIEW`
- **Workflow JSON**: Automates the deployment step (generated alongside all formats)

### Why Separate PySpark and SQL Translators?

Although many Spark functions have identical names in PySpark and SQL, the code structure differs fundamentally (`F.col("x").method()` vs. bare SQL). Maintaining separate translators keeps each clean and independently testable.

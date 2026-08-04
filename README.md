# alteryx2databricks (a2d)

**Automatically convert Alteryx workflows into runnable Databricks code — no Alteryx license required.**

Upload a `.yxmd` file. Get back a PySpark notebook, Spark Declarative Pipelines (DLT) pipeline, Spark SQL script, and Lakeflow Designer pipeline — all in a single run, ready to run in Databricks.

---

> **Visual Guide:** Open [docs/a2d-guide.html](docs/a2d-guide.html) in your browser for a 56-slide interactive guide covering the entire product.

### Quick Start

```bash
git clone https://github.com/databricks-solutions/alteryx-to-databricks-converter.git
cd alteryx-to-databricks-converter
pip install "."
a2d convert my_workflow.yxmd -o output/                  # Emits ALL 4 formats (default)
a2d convert my_workflow.yxmd -o output/ -f pyspark       # Filter to PySpark only
a2d convert my_workflow.yxmd -o output/ -f pyspark,sql   # Filter to PySpark + SQL
```

Outputs land in per-format subdirectories: `output/pyspark/`, `output/dlt/`, `output/sql/`, `output/lakeflow/`.

## Table of Contents

1. [What is this?](#what-is-this)
2. [What can it convert?](#what-can-it-convert)
3. [What still needs manual work?](#what-still-needs-manual-work)
4. [Getting Started](#getting-started)
5. [Recent Improvements](#recent-improvements)
6. [How it works](#how-it-works)
7. [Quality & Observability](#quality--observability)
8. [CLI Reference](#cli-reference)
9. [Troubleshooting](#troubleshooting)
10. [Development](#development)
11. [License](#license)

---

## What is this?

Large organizations use Alteryx to build data pipelines visually. Moving those pipelines to Databricks usually means rewriting them from scratch — which takes months.

**a2d** reads your Alteryx `.yxmd` workflow files and automatically generates equivalent Databricks code:

- **What you save:** weeks of manual rewriting per workflow
- **What you get:** PySpark notebooks, Spark Declarative Pipelines (DLT), Databricks SQL, Lakeflow Designer pipelines, and Workflow JSON — every conversion produces all four formats in one run, available via CLI, web upload, or Databricks Apps deployment
- **What it handles:** 158 Alteryx tool types via 113 converters, 141 formula functions, 5 output formats, 12 CLI commands, database connections, expressions, joins, aggregations, and more

> **You do not need Alteryx installed** to run this tool.

---

## What can it convert?

The tool automatically converts the following Alteryx tools into equivalent Databricks / PySpark code:

### Reading and Writing Data

| Alteryx Tool | What it becomes in Databricks |
|---|---|
| Input Data (CSV, Parquet, JSON, Avro) | `spark.read.format(...).load(path)` |
| Input Data (database / ODBC query) | `spark.sql("""SELECT ...""")` with a TODO to map the connection |
| Output Data | `df.write.format(...).save(path)` |
| Text Input (inline data) | `spark.createDataFrame([...])` |
| Browse | `display(df)` |
| Dynamic Input (ModifySQL) | A Python loop that runs one parameterized SQL query per input row |

### Preparing Data

| Alteryx Tool | What it becomes in Databricks |
|---|---|
| Select (rename/drop columns) | `df.drop(...)` / `df.withColumnRenamed(...)` |
| Filter | `df.filter(condition)` — True/False outputs split into two DataFrames |
| Formula | `df.withColumn("field", expression)` |
| Multi-Field Formula | Multiple `withColumn` calls in one step |
| Multi-Row Formula | Window functions (`F.lag`, `F.lead`) |
| Sort | `df.orderBy(...)` |
| Sample (first N / random / percent) | `df.limit(n)` or `df.sample(fraction)` |
| Unique / Deduplicate | `df.dropDuplicates(key_fields)` |
| Data Cleansing | Trim, null handling, case conversion |
| Record ID | `F.monotonically_increasing_id()` |
| Imputation | Missing value fill logic |

### Combining Data

| Alteryx Tool | What it becomes in Databricks |
|---|---|
| Join (inner/left/right/full) | `df_left.join(df_right, condition, how=...)` |
| Union | `df1.unionByName(df2, allowMissingColumns=True)` |
| Append Fields | Cross join |
| Find Replace | Lookup-based replacement |

### Transforming Data

| Alteryx Tool | What it becomes in Databricks |
|---|---|
| Summarize (group + aggregate) | `df.groupBy(...).agg(F.sum(), F.avg(), ...)` |
| Cross Tab (Pivot) | `df.groupBy(...).pivot(...).agg(...)` |
| Transpose (Unpivot) | `stack()` expression |
| Running Total | Window function with cumulative sum |
| Tile / Quantile binning | `F.ntile(n).over(window)` |

### Parsing

| Alteryx Tool | What it becomes in Databricks |
|---|---|
| RegEx (match / replace / parse) | `F.rlike(...)` / `F.regexp_replace(...)` |
| Text to Columns | `F.split(col, delimiter)` |
| DateTime parse/format | `F.to_timestamp(...)` / `F.date_format(...)` |
| JSON Parse | `F.get_json_object(...)` |

### Formula Functions

The expression engine translates **141 Alteryx formula functions** to PySpark equivalents, including:

| Category | Examples |
|---|---|
| String (24) | `Contains`, `Left`, `Right`, `Trim`, `Replace`, `RegexMatch`, `Substring` |
| Math (21) | `Abs`, `Round`, `Ceil`, `Floor`, `Sqrt`, `Pow`, `Log`, `Mod`, `Rand` |
| Date/Time (15) | `DateTimeNow`, `DateTimeAdd`, `DateTimeDiff`, `DateTimeFormat`, `DateTimeParse` |
| Conversion (9) | `ToNumber`, `ToInteger`, `ToString`, `ToDate`, `ToDateTime` |
| Test / Null (8) | `IsNull`, `IsEmpty`, `IsNumber`, `Coalesce`, `IIF`, `Null`, `IfNull` |
| Conditional | `IF/THEN/ELSEIF/ELSE/ENDIF`, `IIF`, `Switch` |

---

## What still needs manual work?

Some Alteryx features cannot be automatically converted. The tool will always flag these clearly with a `# TODO` comment in the generated code — it will never silently skip them or produce broken code.

| Category | What you'll need to do |
|---|---|
| **Database connections** (ODBC/DSN) | The SQL is preserved; you replace the connection string with a Unity Catalog table name or Databricks JDBC URL |
| **Excel files** (`.xlsx` / `.xls`) | Upload the file to DBFS or a Unity Catalog Volume, then replace the placeholder with a proper read call |
| **Local / network paths** (`\\server\share\...`) | Upload files to cloud storage; the tool flags every occurrence with a `# WARNING` comment |
| **Predictive / ML tools** | Use MLflow + scikit-learn or Spark MLlib |
| **Spatial tools** | Use Sedona or Mosaic libraries |
| **Reporting / Layout tools** | Use Databricks AI/BI dashboards |
| **Email / Publish tools** | Use Lakeflow Jobs notification actions |
| **R Tool** | Rewrite R code in Python/PySpark |
| **Iterative macros** | Require manual rewrite as Lakeflow Jobs |
| **Custom third-party Alteryx tools** | Require bespoke conversion |

> **Tip:** After converting, search the output file for `# TODO` and `# WARNING` — every item that needs attention is marked there.

---

## Getting Started

Choose the option that matches your comfort level:

### Option A: Command Line

For users comfortable with a terminal.

```bash
# Install (CLI only — no web UI)
pip install "."

# Convert a single workflow — emits ALL 4 formats by default
# (output/pyspark/, output/dlt/, output/sql/, output/lakeflow/)
a2d convert my_workflow.yxmd -o output/

# Restrict to one or more formats
a2d convert my_workflow.yxmd -o output/ -f pyspark
a2d convert my_workflow.yxmd -o output/ -f pyspark,sql

# Convert all workflows in a folder (still all 4 formats)
a2d convert workflows/ -o output/

# Generate a migration readiness report
a2d analyze workflows/ -o report/
```

After conversion, the CLI prints (mirroring the Convert page in the web UI):

- a **deploy-readiness banner** — `Ready to deploy` / `Needs review` / `Cannot deploy as-is` — with a plain-English explanation
- a one-line counts row: coverage %, confidence /100, tools converted, nodes needing review, blockers
- warnings **grouped by category**: `Cannot convert` (blocker) · `Manual review needed` · `Graph structure note` · `Other` — instead of a flat dump
- per-format status table (PySpark / Spark Declarative Pipelines / SQL / Lakeflow) with the **best format** highlighted
- automatic Python syntax validation on every generated `.py`

To target a specific cloud for the auto-generated `node_type_id` in the
Workflow JSON / DAB, pass `--cloud aws` (default), `--cloud azure`, or
`--cloud gcp`.

> **Windows note:** If `a2d` is not on PATH, use `python -m a2d` instead.

---

### Option B: Advanced deployment

<details>
<summary><strong>Self-hosted (any Linux/macOS host)</strong></summary>

```bash
pip install -e ".[server]"
make frontend
PYTHONPATH=src:. uvicorn server.main:app --host 0.0.0.0 --port 8000
```
Open http://localhost:8000. For Postgres-backed history, set `A2D_DATABASE_URL=postgresql://...`.
</details>

<details>
<summary><strong>React Web UI (requires Node.js 18+)</strong></summary>

```bash
pip install ".[server]"
cd frontend && npm install && npm run build && cd ..
PYTHONPATH=src:. uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000. Includes DAG visualization, batch WebSocket progress, conversion history, and a tool support matrix.
</details>

<details>
<summary><strong>Databricks Apps</strong></summary>

The repo ships with a `databricks.yml` bundle and an `app.yaml` for one-command deploys via Databricks Asset Bundles:

```bash
# Build frontend + deploy to a target defined in databricks.yml
make deploy-dev      # → databricks bundle deploy -t dev
make deploy-prod     # → databricks bundle deploy -t prod
make bundle-validate # validate the bundle before deploying
```

If you need to deploy by hand instead, sync `src/`, `server/`, `frontend/dist/`, `demo/`, plus `app.yaml`, `pyproject.toml`, and `requirements.txt` to a workspace folder and run `databricks apps create` / `databricks apps deploy` against it.

**Environment variables** (all optional):

| Variable | Default | Description |
|---|---|---|
| `A2D_CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed CORS origins |
| `A2D_MAX_UPLOAD_SIZE_BYTES` | `52428800` (50 MB) | Max upload file size |
| `A2D_MAX_BATCH_FILES` | `50` | Max files per batch |
| `A2D_LOG_LEVEL` | `info` | Logging level |
| `A2D_DATABASE_URL` | `""` (disabled) | PostgreSQL URL for conversion history |
| `A2D_DB_BACKEND` | `""` | Set to `lakebase` to use Databricks Lakebase Postgres for history (see `server/services/lakebase.py`) |
| `PORT` | `8000` | Server port |
</details>

---

## Recent Improvements

See the full [CHANGELOG.md](CHANGELOG.md) for detailed release notes.

**v1.5** (latest) — Lakeflow Designer output, confidence scoring, complexity analysis, connection mapping, expression audit, performance hints, Unity Catalog DDL, DAB generation, multi-format default (every conversion emits all 4 formats), cloud-portable Workflow JSON / DAB via `--cloud aws|azure|gcp`, categorized warnings + 3-tier deploy-readiness banner, and more. 141 expression functions, 1006 tests.

---

## How it works

> This section is for the technically curious. You don't need to read it to use the tool.

### Architecture

Every conversion goes through two phases:

```
  .yxmd file
       │
       ▼
  ┌──────────┐     ┌──────────────────┐     ┌─────────────┐     ┌──────────────┐
  │  Parser  │────▶│  Converter + IR  │────▶│  Generator  │────▶│ Output files │
  │ XML→DAG  │     │ Tool-specific    │     │ Format-     │     │ .py / .sql / │
  │          │     │ ParsedNode→      │     │ specific    │     │ .json        │
  └──────────┘     │ IRNode           │     └─────────────┘     └──────────────┘
                   └──────────────────┘
```

**Phase 1 — Parse:** The `.yxmd` XML is read and turned into a typed `WorkflowDAG` of `ParsedNode` objects. Each Alteryx plugin name is mapped to a human-readable tool type via `PLUGIN_NAME_MAP`.

**Phase 2 — Convert → Generate:** Each node is converted to a typed IR node (e.g. `FilterNode`, `JoinNode`) by a tool-specific converter in `ConverterRegistry`. Expression strings are tokenized, parsed into an AST, and translated to PySpark or SQL. The IR DAG is then walked in topological order by the target generator (PySpark, DLT, SQL, Lakeflow, or Workflow JSON). The Lakeflow generator inherits from SQL — zero duplication for ~60 node handlers.

### Expression Engine

The expression engine is a full recursive-descent parser. It handles:
- All standard operators (`+`, `-`, `*`, `/`, `%`, `==`, `!=`, `<`, `>`, `AND`, `OR`, `NOT`)
- Field references (`[FieldName]`)
- Row references (`[Row-1:Field]`, `[Row+1:Field]`) → translated to `F.lag` / `F.lead` window functions
- `IF/THEN/ELSEIF/ELSE/ENDIF` → `F.when(...).when(...).otherwise(...)`
- `IN(val, list...)` → `.isin(...)`
- Nested function calls (141 functions — see [What can it convert?](#what-can-it-convert))
- `Switch` → chained `F.when` expressions

When an expression can't be translated, a `# TODO` placeholder is emitted with the original Alteryx expression preserved as a comment.

---

## Quality & Observability

### Confidence Scoring

Every conversion produces a **confidence score** (0–100%) measuring the quality of the output across 5 weighted dimensions:

| Dimension | Weight | What It Measures |
|---|---|---|
| Tool Coverage | 35% | % of nodes with supported converters |
| Expression Fidelity | 25% | % of expressions that translated cleanly |
| Join Completeness | 15% | Whether join keys were fully resolved |
| Data Type Preservation | 15% | Type casts preserved correctly |
| Generator Warnings | 10% | Inverse of warning count |

> **Rule of thumb:** 80%+ means minimal manual work. Below 50% means significant manual effort.

### Complexity Analysis

Workflows are scored on 7 factors to estimate migration effort:

| Factor | Weight |
|---|---|
| Node Count | 18% |
| Tool Diversity | 13% |
| Expression Complexity | 18% |
| Unsupported Tools | 23% |
| Macro Usage | 8% |
| DAG Depth | 10% |
| Spatial Tools | 10% |

Effort bands: **Low** (<30, ~2h) · **Medium** (30-50, ~8h) · **High** (50-70, ~16h) · **Very High** (>70, ~40h)

### Enriched Warnings

All warnings include remediation hints with 50+ specific recommendations. The JSON report includes `enriched_warnings` with `hint`, `category`, and actionable next steps for each warning.

### Additional Observability Tools

| Feature | Flag | Output |
|---|---|---|
| Expression Audit | `--expression-audit` | CSV of every expression translation (original → translated, pass/fail) |
| Performance Hints | `--performance-hints` | Broadcast join, persist, repartition, sequential join detection |
| Connection Mapping | `--connection-map FILE` | YAML-based Alteryx connection → Unity Catalog mapping |
| Unity Catalog DDL | `--generate-ddl` | `CREATE TABLE` / `CREATE EXTERNAL TABLE` statements |
| DAB Generation | `--generate-dab` | `databricks.yml` with job + cluster configuration |

---

## CLI Reference

a2d provides 12 commands. Run `a2d --help` for the full list, or `a2d <command> --help` for details on any command.

| Command | Purpose |
|---|---|
| `convert` | Convert workflows — emits PySpark, Spark Declarative Pipelines (DLT), SQL, Lakeflow and Designer code in one run; use `-f` to filter |
| `analyze` | Generate migration readiness reports (HTML/JSON) |
| `portfolio` | Analyze a whole estate — cross-workflow dependencies, shared macros, and a migration-wave plan |
| `validate` | Check generated Python syntax |
| `verify` | Check a workflow produces **semantically equivalent** results on sample data (see below) |
| `suggest` | Write AI suggestions for what the converter couldn't convert (opt-in; see [AI assistant](#ai-assistant-opt-in)) |
| `sync` | Incrementally re-convert a directory — only changed or new workflows |
| `advise` | Recommend a cluster size and surface Spark optimization hints |
| `profile` | Profile a sample-data CSV: per-column type, null rate, and range |
| `list-tools` | Show supported Alteryx tool matrix |
| `plugins` | List installed source frontends and converter plugins |
| `version` | Show a2d version |

**Example:** `a2d convert workflow.yxmd -o output/ --comments --expression-audit --performance-hints` (all 4 formats)
**Filter example:** `a2d convert workflow.yxmd -f pyspark,sql -o output/`
**Cloud target:** `a2d convert workflow.yxmd --cloud azure -o output/` (drives `node_type_id` in Workflow JSON / DAB; `aws|azure|gcp`, default `aws`)

### Semantic equivalence verification (`a2d verify`)

`convert` and `validate` tell you the output *parses*; `verify` tells you it *produces the
right answer*. It runs the workflow through an independent **pandas reference executor** over
your sample input data and compares the result — schema, row-set (order-insensitive), and
per-cell values (numeric tolerance) — against ground truth.

```bash
# Install the verification extra (adds pandas; pyspark optional)
pip install "alteryx2databricks[verify]"

# Golden mode — compare to expected output exported from Alteryx (true equivalence)
a2d verify workflow.yxmd -i sales=sales.csv -e expected.csv

# Reference-only — produce the reference result (no ground truth to diff against)
a2d verify workflow.yxmd -i sales=sales.csv

# Machine-readable report for CI
a2d verify workflow.yxmd -i sales=sales.csv -e expected.csv --json report.json
```

- `-i KEY=PATH.csv` supplies sample input per source (table name, file path, or node id); omit
  for workflows whose sources are embedded TextInput data.
- When a JVM is present (Databricks/CI), `verify` also **cross-checks** the pandas result
  against a real Spark execution; on a laptop without Java it skips that step cleanly.
- Exit code is non-zero only on an actual **FAIL**; an inconclusive run (no ground truth) exits 0.
- Workflows containing operators the reference executor doesn't model report a *partial* result
  (verified subset only) — never a false pass.

### AI assistant (opt-in)

**By default a2d never calls a language model.** Conversion is entirely
deterministic, and nothing here changes that.

If you configure a Databricks Foundation Model API endpoint, two advisory features
become available. They can only **suggest** and **explain** — an LLM never modifies
generated code, and its output arrives as a separate document you read and apply
yourself.

```bash
export A2D_FMAPI_ENDPOINT="https://<workspace>/serving-endpoints/<name>/invocations"
export A2D_FMAPI_TOKEN="..."   # optional — omit to use ambient workspace credentials

a2d suggest workflow.yxmd          # writes workflow_suggestions.md
```

- **`a2d suggest`** writes a Markdown report describing every gap the converter
  left — unsupported tools, TODO stubs, expression fallbacks, connection issues —
  with a suggested Databricks implementation for each. With no endpoint configured
  it still succeeds and still writes the deterministic gap list, just without
  suggestions.
- **The Assistant page** (`/chat` in the web UI) is a chatbot for discussing the
  migration: why the converter made the choices it did, how to handle a gap, and
  what the trade-offs are. It asks a few clarifying questions, then generates the
  same downloadable report.

To enable it in a Databricks Apps deployment, pass the endpoint at deploy time:

```bash
databricks bundle deploy --var fmapi_endpoint="https://<workspace>/serving-endpoints/<name>/invocations"
```

In-workspace serving endpoints need no token — the app's service principal
credentials are used. Leave `fmapi_endpoint` empty (the default) to keep AI off
entirely; the Assistant page then shows setup instructions instead of an upload
form.

---

## Troubleshooting

| Issue | Solution |
|---|---|
| `ModuleNotFoundError: a2d` | Run `pip install "."` or set `PYTHONPATH=src` |
| Syntax errors in generated output | Run `a2d validate output.py` — check expression TODOs |
| Low confidence score (<50%) | Run `a2d list-tools --supported` to check unsupported tools |
| WebSocket not connecting | Verify CORS origins in `A2D_CORS_ORIGINS` env var |
| Excel path placeholders | Upload `.xlsx` to DBFS or Volume, update the path in output |
| Network path warnings (`\\server\...`) | Upload files to cloud storage first |
| Empty expression errors | Check original workflow for blank formula fields |
| Missing join keys | Look for `# TODO: join keys` in the generated output |
| Server not starting | Use `PYTHONPATH=src:. uvicorn server.main:app` (not `a2d.server.main:app`) |

---

## Development

### Setup

```bash
# Install all dev dependencies (pytest, mypy, ruff, etc.)
make dev
# or: pip install -e ".[all]"
```

### Commands

```bash
make test        # Run all tests
make test-cov    # Run tests with coverage report
make lint        # Lint with ruff
make format      # Format with ruff
make typecheck   # Type check with mypy
make all         # Lint + typecheck + test
make serve       # Start dev server with hot-reload
make frontend    # Build React frontend (npm install + npm run build)
make clean       # Remove build artifacts
```

### Adding a New Tool Converter

1. Create a file in `src/a2d/converters/<category>/`
2. Add an IR node class in `src/a2d/ir/nodes.py` if needed
3. Implement a converter extending `ToolConverter` with `@ConverterRegistry.register`
4. Add the plugin name mapping in `src/a2d/parser/schema.py` → `PLUGIN_NAME_MAP`
5. Add a visitor method in each generator (`pyspark.py`, `dlt.py`, `sql.py`; Lakeflow inherits from SQL)
6. Add a unit test in `tests/unit/converters/`

### Project Structure

```
src/a2d/
  cli.py                   # Typer CLI (12 commands)
  config.py                # Configuration dataclasses
  pipeline.py              # Orchestration: Parse → Convert → Generate
  connections.py           # YAML connection mapping (Alteryx → Unity Catalog)
  parser/                  # .yxmd XML parsing
  ir/                      # Typed IR nodes + WorkflowDAG
  converters/              # 113 converters handling 158 tool types (8 categories)
  expressions/             # Expression engine (tokenizer → parser → AST → translator, 141 functions)
  generators/              # PySpark, DLT, SQL, Lakeflow, Designer, DDL, DAB, Workflow JSON
  frontends/               # Pluggable source frontends (Alteryx, dbt) — one IR, many sources
  analyzer/                # Complexity, coverage analysis
  observability/           # Confidence scoring, warning categorization, deploy status,
                           #   expression audit, performance hints
  verification/            # Semantic equivalence harness (pandas reference executor)
  advisor/                 # Cluster/cost advice + the opt-in advisory LLM (context, report, chat)
  portfolio/               # Estate-wide analysis, dependency graph, executive dashboard
  macro/                   # .yxmc macro expansion (inlined into the parent DAG)
  review/                  # Interactive review sessions (canvas ↔ generated code)
  bridges/                 # Spatial (ST/Sedona/H3) + AI/BI dashboard generation
  incremental/             # Manifest tracking for `a2d sync`
  sdk/                     # Stable public contract for converter plugins
  validation/              # Syntax validation

server/                    # FastAPI backend
  main.py                  # App entry point
  routers/                 # REST endpoints (analyze, convert, chat, health, history,
                           #   review, tools, validate)
  services/                # Business logic
  websocket/               # Real-time batch progress

frontend/                  # React 19 + TypeScript + Tailwind 4
  src/
    routes/                # 11 pages (convert, batch, analyze, history, tools,
                           #   validate, review, chat, settings, about, home)
    components/            # UI components (workflow graph, code viewer, etc.)
    stores/                # Zustand state management
    lib/                   # API client, utilities
  dist/                    # Pre-built assets (committed for Databricks App deployment)

demo/                      # Sample .yxmd workflows for testing
tests/                     # pytest suite (1500+ tests, 85%+ coverage)
  fixtures/shared/         # Cross-language contract fixture (Python + TS assert the same rules)
docs/                      # Architecture, expression reference, migration playbook,
                           # visual guide (a2d-guide.html), conversion mapping
```

---

## Disclaimer

This project is a Databricks field-engineering asset provided **as-is**, without
warranties or any official Databricks support or SLA. It is **not** a Databricks
product. It is maintained on a best-effort basis by its owners. Use at your own
risk and validate all generated code before running it in production. See
[SECURITY.md](SECURITY.md) for how to report vulnerabilities and
[CONTRIBUTING.md](CONTRIBUTING.md) to contribute.

## License

This project is licensed under the Databricks License. See [LICENSE.md](LICENSE.md)
for details, and [NOTICE](NOTICE) for third-party attributions.

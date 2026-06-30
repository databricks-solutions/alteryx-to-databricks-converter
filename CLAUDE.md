# Alteryx-to-Databricks Migration Accelerator (a2d)

## Project Overview
Production-grade Python CLI + FastAPI service that parses Alteryx .yxmd workflow files and generates equivalent PySpark notebooks, Spark Declarative Pipelines (DLT), Databricks SQL, Lakeflow Designer pipelines, and Workflow JSON. Also deployable as a Databricks App via `databricks.yml` / `app.yaml`.

## Architecture
- Two-phase: Parse → IR (intermediate representation) → Generate
- Converters: ParsedNode → IRNode (tool-specific, target-agnostic)
- Generators: IRNode → Code (format-specific, tool-agnostic)
- Expression engine: Alteryx expressions → PySpark/SQL via tokenizer → AST → translator
- 4 output formats: PySpark, DLT, SQL, Lakeflow (inherits from SQL). The CLI and server emit ALL four per call by default; `--format`/filter narrows the set. Internal id stays "dlt"; user-facing label is "Spark Declarative Pipelines".

## Key Commands
- `make dev` - Install with all dev dependencies
- `make test` - Run all tests
- `make lint` - Lint with ruff
- `make typecheck` - Type check with mypy
- `make all` - Lint + typecheck + test
- `make serve` - Start FastAPI dev server with hot-reload
- `make frontend` - Build React frontend (npm install + build)
- `make run` - Install deps, build frontend, start server
- `a2d convert <path>` - Convert workflow(s)
- `a2d analyze <path>` - Analyze and report
- `a2d list-tools` - Show supported tools

## Code Conventions
- Python 3.10+, type hints on all public functions
- dataclasses (not attrs/pydantic) for data models
- `@ConverterRegistry.register` decorator for new converters
- Tests mirror source structure under `tests/unit/`
- Fixtures in `tests/fixtures/`

## Adding a New Tool Converter
1. Create file in appropriate `src/a2d/converters/<category>/` directory
2. Add IR node class in `src/a2d/ir/nodes.py` if needed
3. Implement converter extending `ToolConverter` with `@ConverterRegistry.register`
4. Add plugin name mapping in `src/a2d/parser/schema.py` PLUGIN_NAME_MAP
5. Add visitor method in generators (PySpark, DLT, SQL; Lakeflow inherits SQL)
6. Add unit test in `tests/unit/converters/`

## Dependencies
- lxml: XML parsing
- networkx: DAG graph
- typer + rich: CLI
- sqlglot: SQL dialect handling
- pytest: Testing
- pydantic-settings: Server config

## Common Gotchas
- Server module: `server.main:app` (not `a2d.server.main:app` — server is a separate package)
- Run server with: `PYTHONPATH=src:. uvicorn server.main:app`
- Lakeflow generator inherits from SQL — most SQL handlers work automatically
- `WorkflowAnalysis.coverage` is a `CoverageReport` — access `.coverage.coverage_percentage`
- `observability/errors.ConversionError` is a dataclass, not an exception
- API contract: server `/api/convert` returns `ConversionResponse` with `formats: dict[str, FormatResultResponse]`, `best_format: str`, and a top-level `coverage` percentage derived server-side at `_serialize_format_result` (single source of truth — frontend reads `response.coverage` directly). The request param `output_format` was removed in the multi-format refactor (see `server/models/responses.py`, `server/models/requests.py`).
- CLI `a2d convert` defaults to all 4 formats and writes into per-format subdirs (`output/pyspark/`, `output/dlt/`, `output/sql/`, `output/lakeflow/`); `--format` is a comma-separated filter, not a single-format selector. Single-file path parses + builds the IR DAG ONCE via `pipeline.convert_all_formats()` and runs all 4 generators on it (mirrors `server/services/conversion.py:convert_file`).
- CLI prints a 3-tier deploy banner (Ready / Needs review / Cannot deploy as-is) via `observability/deploy_status.derive_deploy_status` and warnings grouped by category via `observability/warning_categorization.categorize_for_format` — same rules the React Convert page uses (7 regex templates: `unsupported_tool`, `missing_generator`, `expression_fallback`, `local_path`, `disconnected_components`, `dynamic_rename`, `join_no_keys`; ported in TS + Py).
- `--cloud {aws|azure|gcp}` (default `aws`) drives the auto-generated `node_type_id` in Workflow JSON / DAB outputs via `CLOUD_NODE_TYPE_IDS` in `a2d/config.py` (aws=`i3.xlarge`, azure=`Standard_DS3_v2`, gcp=`n1-highmem-4`). Workflow JSON uses `job_clusters[]` indirection (single cluster keyed `"main"`, tasks reference via `job_cluster_key: "main"`).
- Workflow JSON is **strict JSON** (no `//` headers — parses cleanly with `json.loads`/`jq`). Operator notes about intentionally-omitted fields (`run_as`, `webhook_notifications`) live in a sibling `*_workflow.README.md`.
- Expression registry: `ToNumber`/`ToInteger`/`ToDate`/`ToDateTime` (and `ToInt32`/`ToInt64`/`ToDouble`) translate to `try_cast`/`try_to_date`/`try_to_timestamp` so unparseable input returns NULL (matches Alteryx). Requires DBR 14+ / Spark 3.5+. Format-string args use `raw_string_args` so they're emitted as bare strings, not `F.col(...)`. `DateTimeFirstOfMonth` is now 0-arg (returns first-of-current-month).
- Join post-ops use `withColumnsRenamed({...})` (Spark 3.4+ batched rename) instead of chained `withColumnRenamed` for multi-column renames.
- Unity Catalog DDL emits `CREATE TABLE ... AS SELECT * FROM read_files(...)` for non-Delta external tables (CSV/JSON/Parquet/Avro at a path) instead of `CREATE EXTERNAL TABLE` — matches UC 2024-Q4+ guidance.
- `server/main.py` has an SPA fallback route that serves `index.html` for any unknown path so deep-link refreshes work; preserve `/api/*` and `/ws/*` JSON 404s when editing.
- Lakebase support lives in `server/services/lakebase.py` and is enabled via `A2D_DB_BACKEND=lakebase`. Connection params are read from native PG envs (`PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGSSLMODE`) auto-injected by the Databricks Apps `database` resource binding declared in `databricks.yml` (`apps.resources:` block). Legacy `A2D_PG_*` names are preserved as fallbacks via `AliasChoices` in `server/settings.py` — both paths work. `pg_user` reads from `PGUSER` / `A2D_PG_USER` / `DATABRICKS_CLIENT_ID` (last fallback covers Databricks Apps service-principal mode). The endpoint name (`A2D_LAKEBASE_ENDPOINT`) remains a2d-specific (set via the `lakebase_endpoint` deploy variable). Optional self-provisioning: pass `--var provision_lakebase=true` to `databricks bundle deploy` to have DAB create the Lakebase instance via the `database_instances:` resource. `databricks.yml` supports both Database Instance binding (commented stanza) and Autoscaling Postgres (default — env-var binding).
- Databricks Apps deploy: `make deploy-dev` / `make deploy-prod` wrap `databricks bundle deploy` against `databricks.yml`. Set `DATABRICKS_HOST=https://<your-workspace>.cloud.databricks.com` (or use a `~/.databrickscfg` profile) before deploying.
- Test suite: ~1006 tests; CLI alone has 56 tests covering single-file/batch/multi-format paths, deploy banner, and warning categorization.

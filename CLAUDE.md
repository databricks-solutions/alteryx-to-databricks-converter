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
- Semantic equivalence verification lives in `src/a2d/verification/` and is exposed as the `a2d verify` CLI command. It executes the IR DAG through an **independent pandas reference executor** (`reference.py`) — NOT the PySpark/SQL generators — and diffs the result with the pure-pandas parity engine (`parity.py`). Optional Spark backend (`spark_backend.py`) cross-checks against real Spark when a JVM is present and returns `available=False` otherwise (it runs `java -version`, since macOS ships a non-functional `java` stub on PATH). Three modes: `golden` (`--expected out.csv`), `cross_check` (pandas vs Spark), `reference_only` (inconclusive). Unsupported ops are recorded as skipped → partial coverage, never a false pass. Optional `verify` extra (`pandas`, `pyspark`); the CLI prints an install hint if pandas is missing. Non-zero exit only on FAIL. Reference-executor op coverage is the core native set (read, literal/TextInput, filter+fan-out, select, formula, sort, sample/limit, record id, count, union, join, summarize) — extend it (and mirror in `spark_backend.py`) when adding ops. Design note: `docs/equivalence-verification-design.md`.
- Test suite: ~1316 tests; CLI has 10 commands (`convert`, `analyze`, `portfolio`, `validate`, `verify`, `assist`, `feedback`, `profile`, `list-tools`, `version`); `tests/unit/verification/` covers the harness and `tests/fixtures/expected_outputs/` holds golden CSVs.
- Continuous/incremental migration (Q4): `src/a2d/incremental/` + `a2d sync <dir>`. `ManifestTracker` keeps a JSON manifest of per-file state (sha256 source hash + output fingerprint + timestamp); `needs_conversion` detects new/changed, `prune` drops deleted, atomic save, never raises on corrupt (degrades to full reconvert). `sync_directory(dir, convert_fn, tracker)` converts only changed/new files and isolates per-file failures (failed files aren't recorded → retried next run). CLI: `--manifest`, `-f`, `--no-prune`, `--json`; run on cron/loop for watch behavior.
- Cost & performance advisor (Q4): `src/a2d/advisor/` + `a2d advise <wf>`. `CostPerformanceAdvisor.analyze(dag, config)` returns an `AdvisorReport` with a `ClusterRecommendation` (tier single-node/small/medium/large from a workload score over node count/DAG depth/shuffle ops/spatial/ML; worker count, cloud node_type_id via CLOUD_NODE_TYPE_IDS, relative-DBU proxy, Photon flag, rationale) plus the existing `observability/performance_hints.PerformanceAnalyzer` hints rolled in. Works on Alteryx or dbt (frontend registry). `--cloud`, `--frontend`, `--json`.
- Converter SDK + plugins (Q4): `src/a2d/sdk/` is the stable public contract (`SDK_VERSION`) plugin authors import from — re-exports ToolConverter, ConverterRegistry, Parsed*, ConversionConfig, SourceFrontend, WorkflowDAG, common IR nodes. `sdk.discovery.load_plugins()` loads `a2d.converters` entry-point plugins (idempotent; failures recorded in `PluginInfo.error`, never fatal), hooked into `a2d.converters.__init__` after built-ins. `a2d plugins` lists frontends + converter-plugin outcomes. Docs: `docs/converter-sdk.md`.
- Pluggable source frontends (Q4): `src/a2d/frontends/`. `SourceFrontend.parse(path)->ParsedWorkflow` is the front half of the pipeline; everything downstream is source-agnostic (operates on WorkflowDAG). `AlteryxFrontend` (default) wraps WorkflowParser; `DbtFrontend` parses a dbt `manifest.json` (sources/seeds→Input, models→Output, depends_on→edges). `FrontendRegistry.resolve(path, name)` picks by `--frontend` name or auto-detects by file; 3rd-party frontends load via the `a2d.frontends` entry-point group (importlib.metadata). `ConversionPipeline(config, frontend=None)` parses via the frontend — **note `pipeline._frontend`, not the old `_parser`** (verification/runner.py depends on this). CLI: `a2d convert --frontend {alteryx|dbt}`.
- Interactive review workspace (Q3): `src/a2d/review/` + `POST /api/review`. `build_review_session(dag, name, output_format)` runs a generator once and splits its output on the per-node `# Step <id>:`/`-- Step <id>` markers to pair each IR node with its exact generated code cell, a `status` (auto_accepted/needs_review/cannot_convert via `node_review_status`), confidence, warnings, and mutable reviewer state (accept/edit/reject + `edited_code`; `effective_code`). Server: `server/routers/review.py` + `services/review.py` return `ReviewSession.to_dict()` (nodes+edges+summary). Frontend layer is specified in `docs/interactive-review-design.md` (repo has no FE test harness → backend fully tested, thin FE over the verified API).
- Spatial + reporting bridges (Q3): `src/a2d/bridges/`. `spatial.render_spatial_node(node, backend)` renders spatial IR nodes to `databricks` (native ST, default) / `sedona` / `h3`, converting distance units → metres (`metres_for`). `reporting.build_dashboard_spec(dag, name)` assembles Chart/Report/Browse nodes into a Databricks AI/BI (Lakeview) `.lvdash.json`; emitted via `a2d convert --generate-dashboard` as `<wf>.lvdash.json`. Both pure/offline.
- Feedback capture (Q3): `src/a2d/feedback/` learns conversion mappings from verified/accepted results. `LearnedMapping` is keyed by `config_signature(tool_type, config)` (tool + sorted config *key shape*, sha1 — generalises across differing literal values). `FeedbackStore` is JSON at `~/.a2d/feedback.json` (or `$A2D_FEEDBACK_STORE`); lazy-load, atomic save, never raises on missing/corrupt. `LearnedClient` is an `LLMClient` that proposes matching learned mappings first then defers to a fallback — learned mappings re-enter the SAME verification gate (a stale mapping is rejected, never trusted). CLI: `a2d assist --learn` records verified conversions, `--use-learned`/`--no-use-learned` toggles reuse, `a2d feedback [--clear]` inspects the store.
- LLM-assisted conversion (Q3): `src/a2d/llm/` + `a2d assist <wf>` proposes conversions for `UnsupportedNode`s and **gates them on the Q1 equivalence harness**. A proposal (`ConversionCandidate`) is a small graph of *already-supported* IR nodes only (allow-list in `builder.py`: Select/Filter/Formula/Sort/Sample) — never arbitrary code. `assist.LLMAssistedConverter` builds each candidate into a sub-DAG and, given a golden `sample_input`/`expected_output` pair, runs it through `ReferenceExecutor` + `compare_frames`: exact parity → `verified` (safe to adopt), mismatch → `rejected`, no golden → `unverified` (surfaced as a suggestion, never auto-merged). The default `StubLLMClient` is deterministic + offline (no model access needed in CI); `LLMClient` is a Protocol so a real model-serving client drops in behind `get_default_client()`. CLI: `-i KEY=in.csv` (sample data), `-g NODE_ID=golden.csv` (per-node golden), `--json`. `ConverterRegistry.convert_node` now preserves `original_configuration` on UnsupportedNode; `WorkflowDAG.has_cycle()` added. Fixtures in `tests/fixtures/assist/`.
- Portfolio analysis (Q2): `src/a2d/portfolio/` + `a2d portfolio <dir>` analyzes a whole estate — cross-workflow producer→consumer dependency graph (via normalized shared file/table artifacts), shared-macro and duplicate-subflow detection, plus a dependency-ordered migration-wave plan ranked by value×readiness÷effort. `PortfolioAnalyzer.analyze()` parses each file once and reuses `BatchAnalyzer.build_dag()`/`analyze_workflow()` (extracted so single-file and portfolio passes share one DAG build). Emits rich console + HTML + JSON. `a2d portfolio` also writes an **executive dashboard** (`portfolio/dashboard.py`, `executive_dashboard.html`, on by default via `--dashboard/--no-dashboard`): estate-wide coverage/effort/risk-tier rollups with inline-CSS charts, top-blocker table, and consolidation callout. Multi-workflow fixtures live in `tests/fixtures/portfolio/`.
- Macro expansion (Q2): `src/a2d/macro/` inlines referenced `.yxmc` macros into the parent IR DAG at the call site, replacing what would otherwise be an `UnsupportedNode`. Enabled by `--expand-macros` (or `config.expand_macros`), wired into `pipeline._build_dag` as a post-step; all generators then see the inlined DAG. Resolves the macro path (parent-relative / absolute / `search_paths`), maps MacroInput/MacroOutput boundaries to the parent's up/downstream, drops the boundary nodes, and re-bases macro node ids by a per-instance 1e6 band. Each distinct macro is captured once as a reusable `MacroDefinition`. Unresolvable macros are left in place and reported (never fatal). `WorkflowDAG.remove_node()` added for this. Fixtures in `tests/fixtures/macro/`.

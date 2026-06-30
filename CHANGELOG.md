# Changelog

All notable changes to this project are documented here. Follows [Keep a Changelog](https://keepachangelog.com/) format.

## [2.0.0] - 2026-04-28

> Major release — significant API and code-output changes since 1.5.0. Bumped from 1.5.0 directly to 2.0.0 to signal the breadth of breaking changes (Workflow JSON shape, expression registry semantics, generated-code patterns, deployment topology).

### Added
- **`--cloud aws|azure|gcp` flag** on `a2d convert` — drives `node_type_id` in Workflow JSON & DAB outputs (`i3.xlarge` / `Standard_DS3_v2` / `n1-highmem-4`). Default `aws`. Prior versions hard-coded the Azure-only `Standard_DS3_v2`, breaking AWS/GCP runs.
- **3-tier deploy-status banner** (CLI + UI): Ready / Needs review / Cannot deploy as-is, with plain-English explanation. Pure decision functions in `src/a2d/observability/deploy_status.py` and `frontend/src/lib/deploy-status.ts`.
- **Categorized warnings** in CLI + UI: 🚫 Cannot convert / ⚠ Manual review needed / ℹ Graph structure note / Other. Seven regex templates (unsupported_tool, missing_generator, expression_fallback, local_path, disconnected_components, dynamic_rename, join_no_keys) shared between Python and TS ports.
- **Multi-format batch path**: `BatchOrchestrator.convert_batch_multi_format` + `MultiFormatBatchResult`; `OutcomeReportGenerator.generate_{json,jsonl,html}_multi`. CLI `--batch -b` parses each file once, runs all 4 generators.
- **Per-format duration** populated by `pipeline.convert_all_formats()` and shown as real ms in the format status table (was a placeholder `0.0s`).
- **DataverseInput converter** for Microsoft Power Platform (versioned plugin regex `^DataverseInput(_\d+)*$`); generators emit a stub Spark read with TODO + ingest options.
- **DynamicRename SQL + DLT visitors** (was PySpark-only — generated cryptic comment placeholders for the other two formats).
- **Lakebase persistence** for conversion history: `server/services/lakebase.py` with `OAuthConnection` subclass, OAuth token rotation via `WorkspaceClient.postgres.generate_database_credential()`. Apps `DATABRICKS_CLIENT_ID` auto-injection wired into `pg_user` via pydantic `AliasChoices`.
- **Live Databricks Apps deployment** support with both Database Instance binding (commented in `databricks.yml`) and Autoscaling Postgres (default env-var binding).
- **CLI tests**: 4 → 56 covering help/discovery, every command's happy paths and edge cases, internal helpers.
- **`*_workflow.README.md` sidecar** generated alongside Workflow JSON with operator notes for `run_as` / `webhook_notifications` decisions.

### Changed
- **Workflow JSON is now strict JSON** (was `//`-comment header that broke `json.loads`/jq/CI tooling). Operator notes moved to sibling README.
- **Workflow JSON & DAB use `job_clusters[]` indirection** with shared `job_cluster_key: "main"`; dropped vestigial `"format": "MULTI_TASK"`; added `queue: {enabled: true}` and `parameters: []` for current Jobs API 2.2 alignment.
- **Generated PySpark uses `withColumnsRenamed({...})`** in Join post-ops (Spark 3.4+/DBR 14.3 LTS+).
- **Expression registry uses `try_cast`/`try_to_date`/`try_to_timestamp`** for `ToNumber/ToInteger/ToInt32/ToInt64/ToDouble/ToDate/ToDateTime/DateTimeParse` (10 entries) — matches Alteryx silent-null-on-bad-input semantics, requires DBR 14+/Spark 3.5+.
- **Unity Catalog non-Delta external tables** now emit `CREATE TABLE … USING DELTA AS SELECT * FROM read_files('...', format=>'csv')` (Volumes-friendly) instead of `CREATE EXTERNAL TABLE … USING CSV`.
- **`DateTimeFirstOfMonth()`** now zero-arg (defaults to `F.trunc(F.current_date(), 'month')`) — matches Alteryx semantics.
- **`ToDate` / `ToDateTime`** have `raw_string_args=frozenset({1})` so format strings convert from Alteryx tokens (`%Y-%m-%d`) to Spark tokens (`yyyy-MM-dd`).
- **Coverage display**: derived server-side at `_serialize_format_result`; top-level `ConversionResponse.coverage` is the single source of truth.
- **CLI single-file mode** parses IR once via `pipeline.convert_all_formats()` (was 4× re-parse — one per format).
- **`server/settings.py`** reads native `PGHOST`/`PGUSER`/`PGPORT`/`PGDATABASE`/`PGSSLMODE` first, falls back to legacy `A2D_PG_*` aliases via pydantic `AliasChoices`.
- **`databricks.yml`** drops `${var.workspace_host}` interpolation (bundle CLI doesn't allow vars in `workspace.host`); use `$DATABRICKS_HOST` or `~/.databrickscfg` profile instead.
- **JDBC TODO** in PySpark generator now recommends Lakehouse Federation first, JDBC fallback (with doc URL).
- **Workflow graph UI**: dagre auto-layout (was overlapping Alteryx-canvas positions); explicit `Position.Right`/`Left` handles; solid edges with arrowheads (was animated dashed, near-invisible on dark theme); 200 px nodes (was 180 px, clipped tool names like `DynamicRename`).
- **Dependency bumps**: `databricks-sdk>=0.105.0`, `psycopg[binary]>=3.2`, `psycopg_pool>=3.2`.
- **Naming sweep**: `Lakeview` → `Databricks AI/BI`, `Databricks Workflows` (product) → `Lakeflow Jobs`, `SQL endpoints` → `SQL Warehouse`. Internal `dlt` ids unchanged.

### Fixed
- **Filter expression fallbacks** (19 → 0 on customer files): rewrote `_build_simple_expression` for `Contains`/`NotContains`/`StartsWith`/`EndsWith`/`IsTrue`/`IsFalse` simple-mode operators.
- **Unsupported-warning regex mismatch**: unified `Unsupported node N (Tool): ...` format across all generators.
- **Headline counts contradicted per-format tabs**: now aggregates workflow + every per-format warning list, deduped by `(kind, node_id, generator, tool)`.
- **`Coverage = 0` UI bug**: generators don't emit `coverage_percentage`; server now derives it at the response boundary.
- **`bundle deploy` legacy CLI 0.18.0 shadow** in pyenv shims: documented `DATABRICKS_CLI_PATH` workaround.

### Removed
- Docker artifacts: `Dockerfile`, `.dockerignore`, CI docker job.
- Streamlit shims: `streamlit_app.py`, `README_STREAMLIT.md`.
- 28 individual predictive converter files consolidated into `predictive/generic.py`.
- `src/a2d/validation/{data,schema}_validator.py` (unused).
- Stale generated examples under `examples/generated/`.

## [1.5.0] - 2026-04-03

### Added
- **Lakeflow Designer** output format (`-f lakeflow`): `CREATE OR REFRESH MATERIALIZED VIEW` / `STREAMING TABLE` with `LIVE.` prefix, companion pipeline JSON
- **Confidence scoring** (0-100): 5-dimension weighted score per conversion (tool coverage, expression fidelity, join completeness, data types, warnings)
- **Complexity analysis**: 7-factor effort estimation with spatial tool weighting
- **Enriched warnings**: 50+ remediation hints with category, hint, and actionable next steps
- **Connection mapping**: YAML-based Alteryx connection to Unity Catalog resolution (`--connection-map`)
- **Expression audit**: CSV export tracking every expression translation (`--expression-audit`)
- **Performance hints**: broadcast join, persist, repartition, sequential join detection (`--performance-hints`)
- **Unity Catalog DDL**: `CREATE TABLE` / `CREATE EXTERNAL TABLE` generation (`--generate-ddl`)
- **DAB generation**: `databricks.yml` with job + cluster configuration (`--generate-dab`)
- **Portfolio scanner**: library module for batch analysis with effort estimation and wave grouping
- **Dependency analysis**: library module for shared macros, file overlaps, connection sharing, topological ordering
- **Progress tracking**: library module for JSON-based status persistence
- **Test scaffolding**: library module for sample DataFrames, schema assertions, row count checks
- **Plugin SDK**: library module for third-party converters via Python entry points
- **Equivalence framework**: library module for semantic comparison test notebook generation
- **Interactive Q&A**: library module for rule-based refinement from conversion context
- 15 new expression functions (141 total, 87.6% of Alteryx functions)
- Smoke test suite with YAML-driven parametrized tests
- Expression audit tab and performance hints panel in React frontend

### Fixed
- `ReplaceFirst` now uses locate+concat for literal first-only replacement
- Empty/whitespace expressions now raise `BaseTranslationError` instead of crashing
- Filter fan-out single-branch resolution (no false suffix when no fan-out)
- Server `_evict_expired_jobs()` wrapped in try-except to prevent silent crash
- WebSocket connection leak (close existing before reconnect)

## [1.3.0] - 2026-03-10

### Fixed
- AppendFields no longer crashes at runtime (`Targets` vs `Target` lookup)
- Formula constants wrapped in `F.lit()` (bare numbers like `500`)
- Sample tool no longer clashes with PySpark `min`/`max` builtins
- TextToColumns uses `withColumns({...})` (single plan node)
- FileGetFileName function translation
- Comment stripping in expressions
- Join converter handles old XML format
- Filter handles nested `Simple` conditions
- `TokenizerError` inherits from `BaseTranslationError`

### Added
- Directory converter, DynamicRename converter
- 7 alternate plugin name mappings

## [1.2.1] - 2026-03-08

### Changed
- MultiFieldFormula uses `withColumns({...})` (one Catalyst plan node)
- Select uses a single chained expression
- Join post-ops chained and drops batched
- Join with no parseable keys flagged with TODO
- AutoField is a true no-op (passes input directly)

## [1.2.0] - 2026-03-08

### Added
- DynamicInput (ModifySQL) support: Python loop + `spark.sql()` per row
- Automatic syntax validation with `ast.parse()`
- Fan-out caching (auto `.cache()` when node feeds 2+ downstream steps)

### Changed
- Unsupported tools pass through directly (no redundant DataFrame chains)
- No-op Select nodes pass through (zero-line output for reorder-only)
- Formula first expression chains directly from input (no dead init lines)

## [1.1.0] - 2026-03-07

### Added
- Database queries fully preserved (complete SQL in output)
- Multi-line annotation support (canvas notes to `#` comments)
- Date arithmetic (`DateTimeAdd` to `F.date_add()` / `F.add_months()`)
- `Null()` expression support
- Safe placeholders for untranslatable expressions
- Excel file handling with clear TODO
- Alteryx built-in macro recognition
- Windows network path warnings

## [1.0.0] - 2026-03-06

### Added
- Initial release: PySpark, DLT, and SQL output formats
- 62 converters covering 112 Alteryx tool types
- Expression engine with 92 formula functions
- CLI with `convert`, `analyze`, `validate`, `list-tools` commands
- React web UI with DAG visualization
- FastAPI server with WebSocket batch progress
- `--version` flag and error hints in CLI

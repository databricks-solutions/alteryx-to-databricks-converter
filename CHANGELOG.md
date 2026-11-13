# Changelog

All notable changes to this project are documented here. Follows [Keep a Changelog](https://keepachangelog.com/) format.

## [Unreleased]

### Changed
- **The web app is one project-centric flow.** Create a project, add its Alteryx files once on the **Workflows** step, then work through **Assess**, **Business case**, **Convert**, **Review** and the optional **AI completion** step from the sidebar, which is now the only navigation and shows each step's progress. Steps live under `/p/<project>/...`, so links to a project work and the URL always says which project you're in. No other screen takes an upload. Single and batch conversion are one **Convert** step; the Cost & Performance Advisor moved into **Review**; Tool coverage moved under Reference. The journey rail, the "next step" footers and the global History page are gone (each workflow's latest conversion is shown on its project). Old URLs redirect to the matching step of the last project opened.
- Without a database the app keeps the same flow with a project held in the browser tab (cleared on reload).
- Project stage moves are forward-only (re-converting a deployed workflow keeps it deployed); re-adding a file name replaces that workflow; workflows can be removed and projects renamed; per-workflow analysis is stored so the project's average coverage fills in.
- `POST /api/convert/batch` accepts `project_id` (and an optional `workflow_names` selection; every name must be in the project) and records each converted workflow on the project, only if it still holds the converted bytes. Project-sourced runs get the same file-count and size limits as uploads. A batch request with no files now answers 400 (was 422). Analysis and batch results carry `source_file_name`; analysis skips (and names, in `skipped_files`) a workflow it can't read instead of failing the whole estate.
- Project store: one row per file name per project (enforced by a unique index; older duplicates are cleaned up on start), identical re-uploads leave a workflow as it was, and a configured database that isn't responding answers 503 "temporarily unavailable" (distinct from 503 "not configured") instead of empty lists or 404s. Startup retries the database if it wasn't reachable at boot.
- Batch jobs are evicted after a period without progress, not a fixed time after they started, so a long run isn't cut off.
- The table location (catalog and schema) is per project, set on the Convert step; Settings holds the default for new projects.
- The syntax checker moved from Review to Reference; Review and AI completion list only converted workflows.
- The single-workflow steps (Convert's full result, Review, cluster sizing, AI completion) send a saved project's workflow by reference, so the server reads it with the project's macros instead of the browser downloading and re-uploading it. `POST /api/convert`, `/api/review` and `/api/advise` accept `project_id` + `workflow_id`, like `/api/ai/*` already did.
- `expand_macros` defaults to on for the API's conversion options.

- **AI completion gets each step's real inputs and columns.** The model is told every input a step has, by its Alteryx anchor (Left, Right, Targets, Source, #1...), with the columns arriving on it, and the columns the step should output. The columns come from the `<MetaInfo>` Designer saves after a run, and are worked out through tools whose effect on columns is known (Filter, Sort, Sample, Unique, Formula, Select, Record ID, Join, Summarize). Before, a step was only told about variables its placeholder code already read, so a Dynamic Rename never saw its mapping input. On 14 Packt workflows with Claude Opus 5.5, completed steps went from 57 of 73 to 70 of 71, and steps skipped before reaching the model from 15 to 0.
- A tool with no converter now gets its own output variable (`df_N = df_M`, a no-op in Spark) that later steps read, so its real code can go in later without touching the variable other steps read. A source the converter can't read assigns a marked placeholder instead of handing later steps a variable that doesn't exist.
- The parser keeps each tool's saved output columns (`ParsedNode.output_fields`, `IRNode.output_fields`); `a2d.ir.schema` resolves the columns on any input or output. The PySpark generator records each step's input and output variables (`GeneratedOutput.node_io`).
- SQL joins name every shared column like Alteryx (`Right_<name>`) when both inputs' columns are known.
- `make ci` runs what the CI workflow runs.

### Removed
- The `/api/chat` endpoints and their server session store. The app's chat page was already gone; AI completion replaces it. `a2d suggest` and the `a2d.advisor.chat` library are unchanged.
- The conversion History API (`GET /api/history`, `GET`/`DELETE /api/history/{id}`) and the write to the `conversion_history` table on every conversion. Nothing in the app read it any more; each workflow's latest conversion is on its project. The server's connection pool moved to `server/services/db.py`. An existing `conversion_history` table is left as it is; drop it by hand if you don't need the old records.
- The **Expand macros** setting. The app now always expands macros, so Assess, Convert, Review and AI completion all see the same steps (before, Assess expanded them and Convert didn't by default). The CLI keeps `--expand-macros`, and the API still takes `expand_macros=false`.

### Fixed
- **Joins with more than one key lost all their keys** and were generated as a cross join (`F.lit(True)`) with a TODO. Every key is now kept. Keys that don't pair up (different counts on each side) give no keys, so the join is flagged instead of joining on part of the key.
- **Join output column names now match Alteryx.** Alteryx names a right-side field that is also on the left `Right_<name>`, and the Join's Select settings use those names. PySpark and DLT kept both copies under one name, so later steps hit an ambiguous column and deselecting `Right_` fields did nothing. They now rename the right side the same way at run time, then apply the Select settings, including a deselected `*Unknown` (only listed fields come out). SQL now applies the Select settings too and handles the collisions it can see when converting (same-named keys and fields listed as `Right_<name>`); it says in the SQL that other shared columns come out twice.
- **Find Replace read setting names Alteryx doesn't write**, so every real Find Replace came out with placeholder fields, and the generators read the wrong inputs (`MISSING_TARGET` in PySpark, the lookup joined to itself in SQL). It now reads the real settings and inputs (F = Targets, R = Source) and supports entire-field and any-part finds, replace and append, case-insensitive and whole-word matching, and replacing every found item. SQL generates the entire-field case and flags the any-part case for the PySpark output.
- **One coverage figure.** Assess, Convert, the project list and the Business case showed different coverage for the same workflow. Coverage is now supported tools over all tools (canvas comments and containers not counted) everywhere, and Assess builds the workflow the same way conversion does. The Convert counts ("converted", "not converted", "converted, worth checking") add up.
- **Macros aren't counted as workflows.** They're listed in their own section on Workflows and left out of counts, averages, Convert all, Review and AI completion, while still resolving wherever they're called.
- **Business case** hides savings, payback and ROI while any money input is still a placeholder, names the ones left, and shows them once every cost is entered or confirmed.
- Review no longer shows a confidence percentage on a step the converter left unfinished. ToolContainer is no longer listed as an unsupported tool; unexpanded macros are listed by name with the reason. Every bar in Assess's tool chart is labelled. The AI completion panes wrap long lines. The home page no longer makes a failing `/api/projects` call without a database (new `GET /api/status`).
- The readiness report's summary said complexity "out of 10" on a 0–100 score; it now says "out of 100" and uses the 25/50/75 bands.
- **Macro calls in real Alteryx files weren't detected.** Alteryx saves a tool that runs a macro as `<EngineSettings Macro="...">` with no plugin, which parsed as an "Unknown" tool with no macro path. So macro expansion never ran on real files (`.yxzp` packages included), and the complexity score's macro factor and the portfolio's shared-macro list never counted them. They now parse as `Macro` calls with their path. `CountRecords.yxmc` (Alteryx's Count Records tool) maps to the Count Records converter, like `RandomRecords.yxmc` already mapped to Sample.
- Four source files that failed `ruff format --check` in CI.

### Added
- **Macros as project files.** A `.yxmc` added to a project is available to every workflow in it, in every step: Assess, Convert (one workflow, or a batch on any selection), Review, cluster sizing and AI completion. A macro is found by file name, ignoring case, wherever the reference pointed on the author's machine; a workflow's own folder (a `.yxzp`'s macros) is searched first. Macros that call macros expand too, up to 8 levels, and a macro that calls itself is reported. Batch and iterative macros aren't inlined, because one inlined pass can't reproduce their loop; a standard macro that takes settings from the tool that calls it is inlined with the values saved in the macro, plus a note to check them. Every macro left unexpanded becomes a conversion warning that says why, and the AI step names a missing macro instead of asking a model to guess it. Uploads can send extra `.yxmc` files in a `macros` field (single-workflow and batch endpoints). Library: `ConversionConfig.macro_search_paths` and `BatchAnalyzer(macro_search_paths=...)`.
- **AI completion** — `a2d complete <file>` (CLI), `POST /api/ai/complete` + `POST /api/ai/gaps` + `POST /api/ai/notes` (API), and the **AI completion** step (App). Writes a separate `<workflow>.ai-completed.py` where only the notebook cells the converter couldn't finish are filled in by the configured model, each marked as AI-generated; replies that don't parse or break variable wiring are rejected. Replaces the Assistant chat page in the app (the `/api/chat` endpoints and `a2d suggest` remain).
- **Migration savings / ROI estimator** — `a2d savings <path>` (CLI), `POST /api/savings` + `GET /api/savings/config-defaults` (API), and **Assess → Savings** (App). Combines facts derived from the estate (workflow count, per-workflow effort tier, coverage) with **configurable** cost assumptions — Alteryx licenses retired, developer rewrite time saved, Databricks run cost (subtracted, so the figure is net), and ongoing maintenance — into net annual savings, payback period, and ROI. New engine package `src/a2d/savings/` (`CostAssumptions` / `SavingsCalculator` / `SavingsReport`, with the same `default`/`from_mapping`/`from_file` config contract as `ProfilerConfig`). Deterministic and offline — a planning estimate, not a quote; money defaults are illustrative placeholders. CLI flags `--config`/`--rate`/`--seats`/`--automation`/`--horizon`.
- **Migration readiness questionnaire** — `a2d readiness` (CLI), `GET /api/readiness/questions` + `POST /api/readiness/score` + `POST /api/readiness/prefill` (API), and **Assess → Readiness** (App). A deterministic, weighted, Alteryx→Databricks-centric self-assessment across four dimensions (estate & workflow profile, people & skills, platform & data landscape, governance & sponsorship) that returns tailored, prioritized tips. New engine package `src/a2d/questionnaire/` (question bank + scoring + `QuestionnaireConfig`); can pre-answer the estate questions from an uploaded workflow set (`prefill_from_estate`). CLI supports `--answers`, `--dump-questions`, `--from-estate`, `--interactive`, `--config`. No language model involved — named distinctly from the file-based `analyzer/readiness.py`.

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

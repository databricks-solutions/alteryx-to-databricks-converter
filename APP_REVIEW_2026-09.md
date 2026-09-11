# a2d Full App Review: September 2026

**Scope:** bugs, UX, design, engineering excellence, and accuracy against Databricks and Alteryx specs, across the CLI, FastAPI server, React SPA, converters, expression engine, generators, and Databricks artifacts.

**Method:** three adversarial passes with Codex (backend correctness/security, frontend UX/design/a11y, conversion accuracy vs Alteryx + Databricks), each run triple-pass, then independent verification of every Critical/High finding against the actual code and a live PySpark 4.1.1 interpreter. Findings below are tagged **[VERIFIED]** (confirmed in-session) or **[REPORTED]** (from a pass, high-confidence, not independently reproduced here).

---

## 1. Executive summary

The product is broad and well-architected at the seam level (Parse to IR to Generate, source-agnostic frontends, a clean SDK). The problems are not structural. They cluster in two places that matter most for a migration accelerator:

1. **Generated code accuracy.** Several generators emit code that either fails at runtime or silently changes semantics versus Alteryx. The headline is that the PySpark generator calls `F.try_cast(...)`, which does not exist in Spark 3.5 / DBR 14+ (nor PySpark 4.1.1), so every workflow using `ToNumber`/`ToInteger` produces code that raises `AttributeError`. Others are silent-wrong: the Filter False output drops null-predicate rows, Summarize silently substitutes `COUNT` for `StdDev`/`Median`/`Percentile`, SQL Union ignores the configured mode, and the DAB output declares an invalid cluster runtime.

2. **Equivalence overclaim.** The `verify` "golden" mode is documented as "true equivalence," but it only executes the independent pandas reference, never the generated PySpark/SQL. So it cannot catch any of the codegen bugs above (it would pass a workflow whose generated PySpark cannot even import).

Security has two real issues for the hosted App: user-controlled macro paths can read arbitrary server files when macro expansion is on (and `.yxzp` uploads turn it on automatically), and batch uploads buffer entirely in memory.

The frontend is polished but has a few functional bugs (history capped at 50, batch-cancel state loss on error, review edits lost silently) and the usual accessibility gaps (click-only controls, non-modal dialogs).

### Severity rollup

| Severity | Count | Theme |
|---|---|---|
| Critical | 2 | Broken PySpark codegen (`try_cast`); equivalence overclaim |
| High | ~22 | Generator semantics, Databricks artifact validity, security, frontend functional bugs |
| Medium | ~12 | Expression edge cases, error-code hygiene, a11y, content |
| Low | ~5 | Copy accuracy, tool-map coverage, partial-extraction cleanup |

### What is correct (checked, not defects)

To keep the report honest: several plausible-looking areas were verified as **correct** and should not be touched. `Substring` correctly maps Alteryx 0-indexing to Spark 1-indexing (`+1`). Alteryx strftime tokens (`%Y-%m-%d`) are genuinely converted to Spark patterns (`yyyy-MM-dd`) via `alteryx_fmt_to_spark`. The Join tool's three-output L/J/R semantics use `left_anti` correctly and are gated on which anchors are actually consumed. `.yxzp` extraction has sound zip-slip / zip-bomb / member-count guards.

---

## 2. Critical

### C1. PySpark generator emits `F.try_cast(...)`, which does not exist: generated code crashes [VERIFIED]
- **Where:** `src/a2d/expressions/functions.py:168` (`ToNumber`), `:176` (`ToInteger`), and the `ToInt32`/`ToInt64`/`ToDouble` aliases.
- **What:** Templates emit `F.try_cast({0}, 'double')` / `F.try_cast({0}, 'int')`.
- **Why it is wrong:** `try_cast` is a `Column` method (`col.try_cast(...)`), not a function in `pyspark.sql.functions`. Verified against the installed interpreter: `pyspark 4.1.1 -> hasattr(F, 'try_cast') == False` (while `try_to_date`/`try_to_timestamp` do exist). Any generated PySpark using `ToNumber`/`ToInteger` raises `AttributeError: module 'pyspark.sql.functions' has no attribute 'try_cast'` before doing any work. The SQL path is fine (`TRY_CAST(... AS DOUBLE)` is valid Databricks SQL). This is PySpark-only.
- **Fix:** emit `({0}).try_cast("double")` (Column method, Spark 3.5+) or `F.expr("try_cast(... as double)")`. Add a generator test that actually imports/executes a snippet, not just string-compares.

### C2. `verify --expected` is documented as "true equivalence" but never runs the generated code [VERIFIED]
- **Where:** `src/a2d/verification/runner.py:10` ("This is true equivalence.").
- **What:** Golden mode compares the Alteryx-exported CSV against the **pandas reference executor** (`reference.py`), not against the generated PySpark/SQL/DLT.
- **Why it is wrong:** It proves the IR reference matches Alteryx, which is useful, but it says nothing about the artifact the user actually deploys. Concretely, C1 means a `ToNumber` workflow's PySpark cannot import, yet golden verify would report equivalence because it exercises the pandas path. The strongest claim in the tool is the one it cannot back.
- **Fix:** rename to "IR-reference parity," and reserve "equivalence" for a mode that executes each generated target (PySpark via the existing optional Spark backend; SQL via a warehouse) against the same inputs. If execution is unavailable, the verdict must be "inconclusive," never "equivalent."

---

## 3. High: conversion accuracy (Alteryx and Databricks semantics)

### H1. Filter False anchor drops rows where the predicate is NULL [VERIFIED]
- **Where:** `src/a2d/generators/pyspark.py:617` (and the equivalent SQL/Lakeflow paths).
- **What:** False output is `inp.filter(~(cond))`.
- **Why:** Spark uses three-valued logic: for a row where `cond` is NULL, `~NULL` is NULL and `.filter(NULL)` drops it. Alteryx routes rows whose predicate is false **or** null/error to the False anchor. Result: rows silently vanish from the False stream, and True + False no longer reconstruct the input.
- **Fix:** True = `cond == True`; False = `cond.isNull() | ~cond` (or `~coalesce(cond, lit(False))`). Mirror in SQL: `WHERE NOT COALESCE(cond, false)`.

### H2. Unique "Duplicate" output uses `subtract`, which has set semantics [VERIFIED]
- **Where:** `src/a2d/generators/pyspark.py:834`.
- **What:** `unique = inp.dropDuplicates(keys); dup = inp.subtract(unique)`.
- **Why:** `subtract` is a whole-row DISTINCT set difference. For fully-identical repeated rows, every copy equals the surviving unique row, so the Duplicate output is **empty** instead of holding the 2nd..nth occurrences. `dropDuplicates` also keeps an arbitrary survivor, whereas Alteryx keeps the first.
- **Fix:** window `row_number()` over the key with an explicit order; row 1 to Unique, rows > 1 to Duplicate.

### H3. Record ID uses `monotonically_increasing_id()`: not consecutive [VERIFIED]
- **Where:** `src/a2d/generators/pyspark.py:852`.
- **What:** `withColumn(field, F.monotonically_increasing_id() + start)`.
- **Why:** Those IDs are unique but large, partition-dependent, and non-consecutive. Alteryx Record ID is consecutive from the configured start. Any downstream logic assuming contiguous IDs breaks.
- **Fix:** `row_number()` over a required ordering (or `zipWithIndex` semantics); if no deterministic order exists, flag equivalence as unavailable rather than emitting misleading IDs.

### H4. SQL Formula duplicates a column when updating an existing field [VERIFIED]
- **Where:** `src/a2d/generators/sql.py:249`.
- **What:** `SELECT *, {expr} AS field FROM (...)`.
- **Why:** When the formula targets an existing field (a common Alteryx pattern), `SELECT *` keeps the old column and the alias adds a second with the same name, producing ambiguous references downstream.
- **Fix:** Databricks SQL `SELECT * REPLACE ({expr} AS field)` when the field exists; otherwise `SELECT *, {expr} AS field`.

### H5. SQL Select rename keeps the original column; drops ignored when any rename exists [REPORTED]
- **Where:** `src/a2d/generators/sql.py:263`.
- **What:** rename emits `SELECT *, old AS new`; the drop branch only runs when the rename list is empty.
- **Why:** `old` is retained (duplicate), and deselected fields survive whenever a rename is present. Diverges from Alteryx Select projection.
- **Fix:** build the explicit projected column list, or combine `* EXCEPT (dropped...)` with renamed expressions.

### H6. SQL Union is always positional `UNION ALL`, ignoring the configured mode [VERIFIED]
- **Where:** `src/a2d/generators/sql.py:372`.
- **What:** `" UNION ALL ".join("SELECT * FROM t" ...)`.
- **Why:** Alteryx Union defaults to "auto config by name"; the IR records name/position/manual, but the SQL generator ignores it and unions by position. If input schemas differ in column order, values land in the wrong columns. The PySpark generator unions by name, so the two targets disagree.
- **Fix:** honor the mode; emit explicit aligned projections before union.

### H7. Summarize silently substitutes `COUNT` for unsupported actions [VERIFIED]
- **Where:** `src/a2d/generators/sql.py:420` (the `else:` branch).
- **What:** any action not explicitly handled (StdDev, Variance, Median, Mode, Percentile, Concat, spatial combine) falls through to `COUNT(field)` with no warning.
- **Why:** produces plausible but entirely wrong numbers, with nothing flagging it. This is the most dangerous class of bug: a clean-looking result that is silently incorrect.
- **Fix:** implement each supported action; for the rest emit `NULL`/TODO plus a blocking warning. Never substitute `COUNT`.

### H8. PySpark Join post-ops rename/drop by unqualified name after the join [REPORTED]
- **Where:** `src/a2d/generators/pyspark.py:1123`.
- **What:** `withColumnsRenamed({...})` on the joined frame using bare column names.
- **Why:** same-named left/right columns are ambiguous post-join; a rename can hit both or the wrong side. Alteryx selects side-specifically.
- **Fix:** alias qualified `left`/`right` columns during the join, not after.

### H9. DLT generator invents data-quality expectations and embeds raw Alteryx syntax [REPORTED]
- **Where:** `src/a2d/generators/dlt.py:260`.
- **What:** adds `@dlt.expect` constraints (e.g. non-null) not present in the workflow and embeds Alteryx filter syntax like `[Age] > 5` as the expectation string.
- **Why:** Data Cleansing does not assert non-null; `[Age]` bracket syntax is not a Spark SQL expectation. Pipelines can fail validation or report invented DQ violations.
- **Fix:** emit expectations only for explicit Alteryx validation/Test semantics, and translate predicates to Spark SQL first.

### H10. DAB emits an invalid cluster runtime (`spark_version: "3.5"`) [VERIFIED]
- **Where:** `src/a2d/generators/dab.py:108`, using `config.spark_version` (default `"3.5"` in `config.py:74`).
- **Why:** Databricks clusters need a runtime key like `14.3.x-scala2.12`, not the bare Spark version. The sibling `workflow_json.py:100` already does this correctly with `f"{config.dbr_version}.x-scala2.12"`. DAB is inconsistent with it and will fail cluster creation.
- **Fix:** use `dbr_version` to build the runtime key in `dab.py`, matching `workflow_json.py`.

### H11. DAB runs SQL and DLT output as `spark_python_task` from a `.py` file [REPORTED]
- **Where:** `src/a2d/generators/dab.py:38`.
- **What:** all formats copied to `src/<workflow>.py` and launched as `spark_python_task`.
- **Why:** SQL text is not valid Python, and a declarative pipeline cannot run as an ordinary Spark Python task.
- **Fix:** per-format source extension and task type (`sql_task`, `pipeline_task`, `spark_python_task`).

### H12. Workflow JSON SQL task declares both `job_cluster_key` and `warehouse_id` [VERIFIED]
- **Where:** `src/a2d/generators/workflow_json.py:162` (`_build_sql_task`).
- **Why:** a SQL task runs on a SQL warehouse; also setting `job_cluster_key` is contradictory and can fail Jobs validation. The job still declares `job_clusters` even when no task legitimately uses one.
- **Fix:** drop `job_cluster_key` from SQL tasks; omit `job_clusters` when unused.

### H13. Per-format Workflow JSON is generated from the unchanged shared config [VERIFIED]
- **Where:** `src/a2d/pipeline.py:281`.
- **What:** inside the per-format loop, `WorkflowJsonGenerator(self.config)` is built with the shared config; its task-type selection reads `config.output_format`, which does not change per iteration.
- **Why:** the DLT and Lakeflow downloads can carry a PySpark notebook task instead of a pipeline/SQL task. Undermines the core "emit all formats correctly per call" promise.
- **Fix:** `dataclasses.replace(config, output_format=fmt)` per format for both generators and orchestration.

### H14. Alteryx literal `Replace` becomes `regexp_replace` [VERIFIED]
- **Where:** `src/a2d/expressions/functions.py:86`.
- **Why:** Alteryx `Replace` is literal. Search strings containing regex metacharacters (`. * $ [ ] \` etc.) are reinterpreted as Java regex, changing matches or erroring. The note claims "covers 99% of usage," but the failure is silent for the other cases.
- **Fix:** use a literal replace, or `Pattern.quote` the search value; warn when the argument is dynamic.

### H15. Regex functions pass PCRE patterns straight to Spark's Java regex [REPORTED]
- **Where:** `src/a2d/expressions/functions.py:123` (`REGEX_Match`, `REGEX_Replace`, `REGEX_CountMatches`, `REGEX_Extract`).
- **Why:** Alteryx uses PCRE; Spark uses `java.util.regex`. PCRE-only constructs fail or behave differently, and the optional case-insensitive argument to `REGEX_Match` is discarded.
- **Fix:** detect unsupported constructs, translate compatible inline flags, flag the rest for manual review.

### H16. `ToDateTime` passes its format as a bare string, not `F.lit(...)` [VERIFIED]
- **Where:** `src/a2d/expressions/functions.py:198`, `F.try_to_timestamp({0}, {1})`.
- **Why:** `try_to_timestamp`'s format parameter is a Column; a bare `"yyyy-MM-dd"` is read as a **column name**. `DateTimeParse` correctly wraps it in `F.lit(...)`; `ToDateTime` (and check `ToDate`) do not, so the two-arg form fails at runtime.
- **Fix:** `F.try_to_timestamp({0}, F.lit({1}))`; audit `ToDate` for the same.

### H17. `DateTimeAdd` on day/month/year drops the time component [REPORTED]
- **Where:** `src/a2d/expressions/translator.py:211` (`_translate_dateadd_pyspark`).
- **Why:** `date_add`/`add_months` return a DATE, discarding time-of-day. Alteryx `DateTimeAdd` preserves the full datetime, so adding 1 day to `2026-01-01 14:30:00` must keep `14:30:00`.
- **Fix:** use timestamp-preserving arithmetic (`timestampadd`) for all units.

---

## 4. High: security (hosted App)

### S1. User-controlled macro paths enable arbitrary server-file reads [VERIFIED]
- **Where:** `src/a2d/macro/engine.py:121` (`_resolve_path`).
- **What:** the resolver tries the raw path when `candidate.is_absolute()`, and `parent_dir / macro_path` with no containment check, then reads/parses whatever resolves to a file.
- **Why:** with macro expansion on, an uploaded workflow referencing `/etc/...` or `../../secret.yxmc` causes the server to open and parse that path. `.yxzp` uploads auto-enable expansion, and the convert UI exposes the toggle, so this is reachable on the hosted App. Even the `is_file()` probing is a filesystem-existence oracle.
- **Fix:** resolve every macro against an explicit allow-list of roots (the package/extraction dir, configured `search_paths`); reject absolute paths and any resolved path outside those roots.

### S2. Batch uploads are fully buffered in memory before work starts [VERIFIED]
- **Where:** `server/utils/validation.py:82` (reads each upload into `bytes`, appends to `file_data`).
- **Why:** `max_batch_files` times the per-file cap can total gigabytes held in memory (and retained by the background task), enough to exhaust a standard Databricks App and make DoS trivial.
- **Fix:** stream uploads to per-job temp storage, enforce a total-request-size ceiling, and hand workers paths, not `bytes`.

### S3. Batch-download ZIP paths use unsanitized workflow names [REPORTED]
- **Where:** `server/routers/convert.py:154` (`writestr(f"{workflow_folder}/...")` where `workflow_folder = fr["workflow_name"]`).
- **Why:** a workflow name of `..` (or containing `/`) writes archive entries like `../pyspark/x.py`, enabling traversal in vulnerable extractors on the client side.
- **Fix:** sanitize every archive path component; reject `.`/`..`; verify the final `PurePosixPath` has no absolute/parent parts.

### S4. `catalog_name`/`schema_name` are interpolated unvalidated into generated Python and YAML [VERIFIED]
- **Where:** `server/models/requests.py:29` (no validators); consumed by generators into `saveAsTable("{catalog}.{schema}...")` and DAB YAML.
- **Why:** values with quotes/newlines break generated code or inject extra YAML keys into the artifact the user then runs.
- **Fix:** validate against the UC identifier policy (`[A-Za-z0-9_]`), or quote/escape when serializing.

---

## 5. High: frontend functional

### F1. History can only ever show the first 50 conversions [VERIFIED]
- **Where:** `frontend/src/hooks/use-history.ts:4`, `api.history()` uses default `limit=50, offset=0`; static query key; the route paginates client-side over that partial slice.
- **Why:** conversion 51+ is unreachable in the UI even though the API supports offset/limit and returns `total`.
- **Fix:** pass page offset/limit, include them in the query key, drive pagination from `total`.

### F2. Failed batch-cancel still tears down local state [VERIFIED]
- **Where:** `frontend/src/routes/convert-batch.tsx:54`, the `finally` runs `disconnect(); reset(); setFiles([]); mutation.reset()` even when `api.batchCancel` throws.
- **Why:** the server job may still be running while the user loses the job ID, progress, and results. (Ironically this reintroduces the "claimed cancelled while server kept working" problem the surrounding comment says it fixed.)
- **Fix:** reset only after a confirmed cancel; on failure keep the job and offer retry.

### F3. Unsaved review edits are discarded silently [REPORTED]
- **Where:** `frontend/src/routes/review.tsx:116`.
- **Why:** selecting another node, resetting, or navigating away drops an in-progress code edit with no prompt; reviewers can lose real work.
- **Fix:** track a dirty flag; confirm before node switch, reset, and route change.

### F4. Batch results key on workflow name, so duplicate filenames collide [VERIFIED-pattern]
- **Where:** `frontend/src/components/convert/batch-results.tsx:101` (React keys and expand/tab state keyed by `workflow_name`).
- **Why:** two files with the same name expand/reuse each other's state and render the wrong rows. Same root cause as S3 on the backend.
- **Fix:** key on a stable per-file id or `index + filename`.

---

## 6. Medium

| ID | Where | Issue | Fix |
|---|---|---|---|
| M1 | `functions.py:57` `Contains` | 3rd (case-insensitive) arg silently ignored; warned but still emitted wrong | support case-insensitive compare; reject non-literal mode |
| M2 | `functions.py:184` `ToString` | 2nd arg (decimal places) ignored; `CAST AS STRING` does not format | implement the 2-arg numeric-format form |
| M3 | `unity_catalog.py:121` | non-Delta "external table" becomes a one-time CTAS Delta copy, not linked to source files | describe as ingestion or emit a view/refresh path; document the semantic |
| M4 | `analyzer/coverage.py:49` | coverage counts distinct tool *types*, so 1 vs 1000 unsupported nodes both read 50%; placeholder converters count as full | report instance-weighted structural coverage separately from semantic coverage |
| M5 | `analyzer/profiler.py:46` | semantically-incomplete converters (Unique, RecordID, Select, Union, AutoField) tiered Low via "preparation" default | base default tiers on verified converter capability, override these until H1..H6 fixed |
| M6 | `server/utils/package.py:38` | oversized-package returns HTTP 400, not 413 | distinct limit exception mapped to 413 |
| M7 | `server/utils/package.py:62` | multi-file endpoints silently drop unreadable packages; estate totals look complete | return per-file errors; never omit a submitted file without surfacing it |
| M8 | `server/routers/chat.py` / `services/chat.py` | concurrent turns on one session race on two transcript lists; `_evicted` set grows unbounded; TTL only enforced on create | per-session async lock (or 409); prune `_evicted`; prune on read |
| M9 | `ir/graph.py:43` | missing/duplicate `ToolID` defaults to 0 and overwrites nodes → corrupted DAG, still "succeeds" | require unique positive ToolID; reject duplicates |
| M10 | `assess.tsx:36` | CSV export uses `join(",")` with no escaping; commas/quotes/newlines in names corrupt columns | use the existing `lib/csv.ts` serializer |
| M11 | `assess.tsx:113` | "New" clears files/results but keeps hours, category tiers, tool overrides | reset all profiler state, or label that settings are retained |
| M12 | `file-dropzone.tsx:42` | rejected/duplicate files get no feedback | surface `fileRejections`; dedupe by name+size+mtime |

### Accessibility (all [REPORTED], standard fixes)
- `analyze/workflow-table.tsx:147` and history table: sortable headers are click-only, no `aria-sort` → put a `<button>` in the `<th>`, set `aria-sort`.
- `history.tsx:320` delete dialog and `sidebar.tsx:104` mobile drawer: no focus trap/restore, Escape unreliable, no dialog semantics → use Radix Dialog/AlertDialog.
- `batch-results.tsx:114`: expandable `<tr>` is pointer-only → real button with `aria-expanded`/`aria-controls`.
- `assess/profiler-settings.tsx:189` and the "Add a tool override" select: no programmatic labels → `aria-label` per control.
- `assess/tool-difficulty.tsx:31`: distribution graphic's accessible label omits counts → include the full distribution or a visually-hidden summary.
- `ui/badge.tsx`: success/warning/destructive text can fall below WCAG AA contrast in light mode → theme-specific darker foregrounds, verify 4.5:1.
- `page-header.tsx:11`: title + action groups never stack on narrow screens → column layout / wrap on small breakpoints.

---

## 7. Low

- **L1** `settings.tsx:18`, "Include comments" copy claims it also adds performance hints, which have their own toggle. Reword to "explanatory comments only."
- **L2** `settings.tsx:45`, UC DDL copy promises `CREATE TABLE / EXTERNAL TABLE`, but external file sources now emit `CREATE TABLE ... AS SELECT ... FROM read_files(...)`. Update copy to match.
- **L3** `parser/schema.py:116`, `PLUGIN_NAME_MAP` omits common tools (Select Records, Fuzzy Match, Create Samples, In-DB variants); they show as unknown plugins rather than recognized-but-unsupported, weakening inventory and profiler tiers. Add canonical mappings even before converters exist.
- **L4** `packaging.py:82`, a failed extraction (byte-limit hit mid-write) leaves partial files; harmless for temp-dir callers, misleading for a CLI extract-in-place. Stage to a private temp dir and move on success.
- **L5** `GetWord` splits on a single space only, whereas Alteryx splits on whitespace and punctuation. Minor divergence; note or broaden the delimiter.

---

## 8. Cross-cutting themes

1. **Silent-wrong beats loud-wrong, and there is too much silent-wrong.** H1, H7, H6, H14, C1-via-verify all produce output that looks fine and is not. The single highest-leverage policy change: any converter/generator path that cannot faithfully reproduce Alteryx semantics must emit a TODO plus a categorized warning, and `verify` must be able to catch it. The warning taxonomy already exists (`warning_categorization`); wire these paths into it.

2. **Two code paths for the same concept drift.** `dab.py` vs `workflow_json.py` disagree on the runtime key (H10). PySpark vs SQL disagree on Union (H6) and on `try_cast` validity (C1). A shared "Databricks target facts" module (runtime key, task-type-per-format, union strategy, cast strategy) that both generators consume would remove a whole class of these.

3. **Equivalence is the product's core claim and it is not yet earned.** C2 plus C1 mean the tool can currently certify a workflow whose generated PySpark cannot import. Fixing the verify wording is a one-line honesty fix; adding real generated-code execution is the credible-moat fix.

4. **Hosted-App threat model is under-enforced.** Uploads are attacker-controlled. S1/S2/S4 are the direct consequences of treating parse/convert as trusted-input code.

---

## 9. Prioritized remediation

**P0 (correctness/trust, do first):**
- C1 `try_cast` (fix template + add an execute-the-snippet test).
- C2 rename verify claim; scope real generated-code execution.
- H1 Filter null routing; H7 Summarize silent COUNT; H16 `ToDateTime`/`ToDate` format literal.
- S1 macro path containment.

**P1 (deployable-artifact validity):**
- H10 DAB runtime key; H11 DAB task types; H12/H13 workflow-JSON SQL task + per-format config.
- H2 Unique, H3 Record ID, H4 SQL Formula, H6 SQL Union.
- S2 batch memory; S4 identifier validation.

**P2 (accuracy hardening + hosted hygiene):**
- H5, H8, H9, H14, H15, H17; M3, M4, M6, M7, M8, M9, S3.

**P3 (frontend + a11y + content):**
- F1-F4; the accessibility set; M10-M12; L1-L5.

**P0-lite (ships today, buys honesty while fixes land):** add the "cannot faithfully convert -> TODO + blocking warning" rule to Filter-false, Summarize-unsupported, Union-mode, and literal-Replace paths, and correct the verify "true equivalence" wording. This converts the most dangerous silent-wrong cases into visible, reviewable gaps immediately.

---

## Appendix: verification ledger

**Independently verified in-session (code read and/or executed):** C1 (ran PySpark 4.1.1), C2, H1, H2, H3, H4, H6, H7, H10 (plus the `workflow_json` contrast), H12, H13, H14, H16, S1, S2, S4, F1, F2, F4, M7, M10, M11. Also verified as **correct / not defects:** Substring 0-index handling, `alteryx_fmt_to_spark` token conversion, Join L/J/R `left_anti` semantics, `.yxzp` extraction guards.

**Reported by the adversarial passes, high-confidence, not re-executed here:** H5, H8, H9, H11, H15, H17, M1-M6, M8, M9, S3, F3, the accessibility set, L1-L5.

*Generated 2026-09-11. Method: 3x Codex adversarial passes (backend, frontend, accuracy), each triple-pass, plus independent verification of every Critical/High item.*

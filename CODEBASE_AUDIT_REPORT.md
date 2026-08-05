# Alteryx-to-Databricks Migration Accelerator — Full Codebase Audit

**Audit date:** 2026-08-04  
**Scope:** Python CLI, parser/IR/converters/generators, FastAPI backend, React frontend, verification framework, tests, packaging, Databricks App runtime, Declarative Automation Bundle configuration, Lakebase, Lakeflow Jobs, and Spark Declarative Pipelines.  
**Audit mode:** Read-only review; no product code was changed.

## Remediation status (added 2026-08-05)

Every finding was independently verified against the code before being actioned —
one was overstated, two were already-documented decisions, and two turned out to be
worse than reported.

| ID | Outcome | Note |
|---|---|---|
| F-01 | Fixed (severity overstated) | The command now reads `DATABRICKS_APP_PORT` with fallbacks. Not release-blocking as claimed: 8000 is the documented Apps pattern and the live app was serving on it. |
| F-02 | **Fixed — real and serious** | The committed FMAPI endpoint was a regression from a prior deploy fix. It violated the documented "AI is opt-in" product rule: a fresh clone would call a model. Now empty, with a contract test. |
| F-03 | **Fixed — real** | Lakebase host/endpoint removed from source control. Another workspace deploying the repo would have connected to ours or failed. |
| F-04 | Fixed | Removed the bundle's competing `config:` block. app.yaml is the single source of truth; real values come from an untracked `.local/app.env.yaml` spliced in at deploy time. |
| F-05 | **Fixed — worse than reported** | The 4 escape warnings are gone. The new adversarial tests also found a hard `SyntaxError`: a backslash delimiter emitted `F.split(F.col("path"), "\")` — unparseable output — in *both* the PySpark and DLT generators. |
| F-06 | Fixed | The window-aggregate expectation is removed. Worth noting the body already did `dropDuplicates(key_fields)`, so it added risk and no semantics. |
| F-07 | Documented, not changed | Emitting legacy `dlt` is a deliberate DBR-LTS compatibility decision already recorded in docs/architecture.md. Generated output now states the choice and names the newer API. |
| F-08 | Fixed | The contradictory "slot is released" comment now says what the deadline actually bounds. A killable process pool remains the real fix. |
| F-09 | **Fixed — reproduced** | `sales@2024.yxmd` and `sales#2024.yxmd` both sanitize to one name and silently overwrote. Per-upload subdirectories; a test asserts the collision itself so the premise stays true. |
| F-10 | Partially fixed | Job ids are full-length now. Ownership binding is a product decision: history is intentionally a shared team log (see server/routers/history.py). |
| F-11 | Fixed | Subscriber queues bounded at 500 events. |
| F-12 | Fixed | Production CORS is `[]`, not `["*"]`. |
| F-19 | **Fixed — regression-verified** | The cap now counts uncompressed bytes. Pre-fix, a payload 10x over the limit returned 200 OK. |
| F-21 | Fixed | 17 stale "four formats" claims corrected to five, verified empirically first. architecture.md's CLI list was also stale (5 of 12 commands). |
| F-13, F-14, F-16, F-17, F-18, F-20, F-22, F-23 | Open | Real but larger scope: live Databricks execution suite, broader frontend tests, Shiki asset trimming, WebSocket generation tracking, dependency scanning, structured telemetry, a11y automation. |

Result: 1,532 → 1,599 Python tests, all lint/type gates clean, frontend clean.

## Executive summary

The repository is unusually well tested for a migration accelerator: all configured Python lint/type gates passed, 1,532 of 1,533 tests passed with one intentional skip, and the frontend typecheck, 14 tests, and production build passed. The architecture is clear, generated JSON is generally deterministic, XML external-entity defenses are tested, uploads are size-limited, and the advisory-LLM boundary is thoughtfully designed in code.

The codebase is not deployment-ready without corrections to its Databricks App manifests. The checked-in `app.yaml` hardcodes one workspace's FMAPI endpoint and Lakebase host, enables AI despite the documented opt-in default, and reads `PORT` rather than the Databricks Apps runtime port. `databricks.yml` independently fixes Uvicorn to port 8000, defaults Lakebase to placeholder/legacy configuration, and declares no bound Postgres or model-serving resource. Current Databricks guidance has also moved from Provisioned `database_instances`/`database` resources to Lakebase Autoscaling `postgres` resources.

Beyond deployment, the most important correctness risks are incomplete escaping in less-common PySpark/DLT generators, an invalid or unsafe DLT uniqueness expectation based on a window aggregate, misleading request-timeout semantics, collision-prone batch temp filenames, and app-wide in-memory state without user ownership. The frontend is functional but its test suite is very small relative to its routes, stores, downloads, WebSocket behavior, and deploy-status logic; the production build also ships several very large Shiki language chunks.

### Overall assessment

| Area | Assessment | Summary |
|---|---|---|
| Core architecture | Strong | Parse → IR → generate separation is coherent and extensible. |
| Automated quality | Strong | All configured gates pass; Python coverage threshold is 70%. |
| Generator correctness | Moderate | Broad coverage, but string escaping and SDP semantics have gaps. |
| Backend robustness | Moderate | Good input limits; process-local state, soft timeouts, and tenancy need work. |
| Frontend quality | Moderate | Builds cleanly; thin behavioral test coverage and oversized syntax assets. |
| Security/privacy | Moderate | XXE and error redaction are good; hardcoded environment data and shared state are concerns. |
| Databricks deployment | High risk | Runtime/bundle manifests conflict with current platform requirements. |

## Verification performed

| Check | Result |
|---|---|
| `ruff check src/ tests/ server/` | Passed |
| `mypy src/a2d/` | Passed (171 source files) |
| `mypy server/` | Passed (33 source files) |
| `pytest tests/ --no-cov -q` | 1,532 passed, 1 skipped, 8 warnings |
| `npm run typecheck` | Passed |
| `npm run test` | 1 file / 14 tests passed |
| `npm run build` | Passed with chunk-size warnings |
| Glean synthesized search | Attempted twice; all calls timed out after 300 seconds |
| Official Databricks documentation search | Completed; sources linked below |
| Live Databricks bundle/app validation | Not run: no profile was selected, per the required “never auto-select a profile” rule |
| Dependency CVE audit | Not completed; no configured `pip-audit`/Dependabot gate and no successful registry-backed audit in this environment |

The Python test run emitted `SyntaxWarning: invalid escape sequence '\\D'` eight times from generated Packt workflows. Those warnings are evidence of an output-quality defect even though the tests pass.

## Prioritized findings

### Critical / release-blocking

#### F-01 — Databricks App binds to the wrong port

**Evidence:** `app.yaml:4` reads `PORT` with an `8000` fallback; `databricks.yml:89-95` fixes Uvicorn to `8000`. Databricks Apps assigns the serving port through `DATABRICKS_APP_PORT` (and framework-specific runtime variables). A fixed port can cause a 502 or failed health check.

**Recommendation:** Use a single runtime command in both manifests, binding `0.0.0.0` and the literal `DATABRICKS_APP_PORT`, or have a Python entry point read `UVICORN_PORT`/`DATABRICKS_APP_PORT`. Add a manifest contract test that parses both YAML files and rejects fixed production ports.

#### F-02 — AI is enabled and workspace-specific despite the opt-in product rule

**Evidence:** `app.yaml:21-25` describes an empty endpoint as opt-in, then hardcodes `https://fevm-alteryx-to-dbx-converter.../databricks-claude-opus-5/invocations`. This makes `/api/chat/status` enabled in the checked-in deployment and contradicts the repository's stated “empty by default” policy.

**Impact:** Privacy, cost, portability, and governance risk; deploying this repository can call a model without the operator explicitly configuring one.

**Recommendation:** Remove the value from source control. Declare the endpoint as a Databricks App serving-endpoint resource with `CAN_QUERY`, inject it with `valueFrom`, and keep the resource/variable absent by default. Add a test that the default manifests contain no non-empty FMAPI endpoint or workspace hostname.

#### F-03 — Lakebase configuration is hardcoded, contradictory, and based partly on a retired model

**Evidence:** `app.yaml:30-35` hardcodes a production branch endpoint and physical PG host. `databricks.yml:30-44,60-86` retains Provisioned `database_instances`, `CU_1`, and legacy `database` resource guidance while also claiming Autoscaling is the default. Current Databricks guidance uses Lakebase Autoscaling projects and the `postgres` App resource with branch/database resource paths.

**Impact:** Cross-workspace deployment failure, accidental connection to the wrong database, missing service-principal grants, and imminent incompatibility as Provisioned resources are migrated.

**Recommendation:** Migrate entirely to Autoscaling resources (`postgres_projects`/branches/endpoints as applicable, and App `postgres` binding). Inject branch/database values through a declared resource; do not commit endpoint hosts. Remove `provision_lakebase`, `lakebase_capacity`, `database_instances`, and legacy `database` examples after a documented migration window.

#### F-04 — `app.yaml` and `databricks.yml` are competing sources of truth

**Evidence:** `app.yaml:12-19` explicitly says it shadows bundle configuration. The two files already disagree on port, FMAPI endpoint, Lakebase host/endpoint, and variable resolution.

**Recommendation:** Choose one generated source of truth. Prefer defining the App resource/config in the bundle and generating or minimally mirroring `app.yaml`; add CI that normalizes and compares command/env/resource declarations. Never rely on comments to keep duplicated production configuration synchronized.

### High priority

#### F-05 — Several generated Python strings bypass the common escaping helper

**Evidence:** `PySparkGenerator._esc` is correct at `src/a2d/generators/pyspark.py:107-110`, but `DynamicOutputNode` embeds `path` directly at `1772-1775`, `DirectoryNode` embeds `path` and pattern directly at `2117-2123`, and XML/XPath fields are interpolated directly around `1615-1618`. DLT repeats direct interpolation for annotations, field names, XPath, dynamic paths, cloud paths, and widget fields (`src/a2d/generators/dlt.py:202-215,714-720,753-797`).

**Observed failure:** Generated Packt Python raises invalid-escape warnings for Windows paths.

**Recommendation:** Centralize Python literal rendering with `json.dumps` or `repr` and apply it to every external IR value. Add property-based/adversarial tests containing backslashes, quotes, newlines, Unicode, triple quotes, and comment delimiters for every generator visitor.

#### F-06 — DLT uniqueness expectation uses a window aggregate as a row predicate

**Evidence:** `src/a2d/generators/dlt.py:226-230` emits `COUNT(*) OVER (PARTITION BY ...) = 1` inside `@dlt.expect_all_or_drop`.

**Risk:** Pipeline expectations are row-level SQL predicates and do not generally support arbitrary aggregates/window functions. Even where accepted, it imposes a full shuffle and silently drops duplicates rather than expressing the original Unique tool's multi-output semantics.

**Recommendation:** Implement uniqueness as an explicit grouped/windowed transform with deterministic duplicate routing, or emit a clearly marked manual-review stub. Do not advertise the current decorator as semantically equivalent. Add a Databricks execution test for generated SDP code.

#### F-07 — Generated SDP code remains on legacy `dlt` APIs

**Evidence:** `src/a2d/generators/dlt.py:140,215` emits `import dlt` and `@dlt.table` for every node. Repository docs acknowledge the newer `from pyspark import pipelines as dp`, `@dp.materialized_view`, and streaming `@dp.table` APIs but defer migration.

**Assessment:** This is compatibility debt, not an immediate outage: legacy DLT APIs remain supported. However, all outputs being decorated as tables obscures batch materialized-view versus streaming-table intent and conflicts with current naming/product direction.

**Recommendation:** Add an SDP API target/version setting. Default new deployments to `pyspark.pipelines` once the minimum supported DBR guarantees it; generate `@dp.materialized_view` for batch queries and `@dp.table` only for streaming tables. Keep `dlt` as an explicit legacy compatibility mode.

#### F-08 — Request deadlines do not release compute capacity

**Evidence:** `server/utils/deadline.py:34-38` correctly notes that `asyncio.wait_for(asyncio.to_thread(...))` cannot stop the thread, but settings/comments at `server/settings.py:45-49` say the slot is released. The thread continues consuming a worker after the 408. Batch conversion at `server/services/batch.py:310-315` has no per-file deadline at all.

**Impact:** A few pathological workflows can exhaust the default executor even though clients receive timely 408s.

**Recommendation:** Run conversions in a bounded process pool or isolated worker process with hard termination, cap concurrent conversions with a semaphore, apply the same bound to batch jobs, and return 429/503 under saturation. At minimum, correct the comments and instrument active/orphaned work.

#### F-09 — Batch uploads can overwrite one another after filename sanitization

**Evidence:** `server/utils/validation.py:13-27` maps different names to the same sanitized value; `server/services/batch.py:294-299` writes all files into one temp directory using that value.

**Example:** `sales@2024.yxmd` and `sales#2024.yxmd` both become `sales_2024.yxmd`; the second replaces the first and both entries then reference the same content.

**Recommendation:** Allocate a unique subdirectory or prefix per upload, retain the original display name separately, and reject or deterministically disambiguate duplicate sanitized names. Add a collision regression test.

#### F-10 — Batch/history/chat state is app-wide rather than user-owned

**Evidence:** Batch jobs use a module-global in-memory store (`server/services/batch.py:60-115`) and 48-bit truncated UUID identifiers (`:72`); status/download/WebSocket routes accept only `job_id` (`server/routers/convert.py:90-161`, `server/websocket/batch.py:17-69`). History and chat similarly rely on app-level storage/session IDs rather than an authenticated owner binding.

**Impact:** Any authorized App user who learns or guesses an ID can access another user's filenames, generated code, reports, or history. State also disappears on app restart and is inconsistent across multiple workers/replicas.

**Recommendation:** Bind every record/session/job to the Databricks user identity forwarded by the proxy (or explicitly document shared-SP behavior), verify ownership on every HTTP/WebSocket operation, use full random IDs, and move durable/coordination state to Lakebase. Treat WebSocket authentication/authorization as a first-class test surface.

#### F-11 — Subscriber queues and retained batch results can consume excessive memory

**Evidence:** WebSocket queues are unbounded (`server/websocket/batch.py:28-30`); each job retains full per-format code and DAGs in memory for up to an hour. Upload limits permit 50 × 50 MB inputs and ZIP configuration permits 500 MB, while Databricks Apps medium compute has 6 GB RAM.

**Recommendation:** Bound queues and drop/coalesce progress events, impose an aggregate batch-upload limit, store artifacts outside process memory, cap simultaneous jobs, and stream ZIP creation from persisted artifacts. Include memory-load tests near configured maxima.

### Medium priority

#### F-12 — Production CORS is unnecessarily wildcarded

**Evidence:** Both manifests set `A2D_CORS_ORIGINS='["*"]'` (`app.yaml:5-7`, `databricks.yml:111-112`). `server/main.py:92-114` safely disables credentialed wildcard requests, but the production SPA is same-origin and needs no cross-origin access.

**Recommendation:** Omit CORS in production or use explicit local origins only in a development target. This reduces accidental browser/API exposure and eliminates a misleading production warning.

#### F-13 — Model-serving permission/resource declaration is missing

**Evidence:** The FMAPI endpoint is injected as a URL string, but the App declares no serving endpoint resource with `CAN_QUERY`. The bundle's App resources block is commented and contains only a legacy database example.

**Recommendation:** Declare all Databricks resources used by the App—model endpoint, Postgres database, optional jobs/warehouses—with least-privilege permissions so deployment grants the App service principal correctly.

#### F-14 — Generated-output validation is mostly syntactic, not Databricks-executed

**Evidence:** Python syntax checks and pandas reference verification are strong, but the Spark backend is optional and one integration test is skipped. DLT/SDP decorators, expectations, UC DDL, Lakeflow Designer JSON, Workflow JSON, and DAB outputs are not routinely validated against an actual workspace/runtime.

**Recommendation:** Add a small profile-gated nightly Databricks integration suite: bundle validate, parse/compile SDP, run representative PySpark/SQL outputs on serverless compute, validate Jobs JSON, and smoke-test the deployed App. Keep it opt-in for contributors and required on protected release branches.

#### F-15 — Typechecking is configured to suppress important error classes

**Evidence:** `pyproject.toml` disables `arg-type`, `assignment`, `attr-defined`, `return-value`, missing imports, and other broad categories globally. Server functions may remain untyped.

**Recommendation:** Replace global suppression with narrow module overrides, then ratchet strictness by package. Start with IR/models, settings, services, and generator public interfaces; require new files to pass stricter settings.

#### F-16 — Frontend behavioral coverage is too small for its feature surface

**Evidence:** Only 14 Vitest tests run, while the frontend contains conversion, batch/WebSocket, analysis, portfolio, review/edit/export, history, advisor, chat/Markdown, settings, download, and deploy-status flows.

**Recommendation:** Add React Testing Library/MSW coverage for every route's loading/error/empty/success states, API contract tests, WebSocket reconnect and duplicate-event tests, download failures, review editing, chat-disabled behavior, and warning/deploy-tier parity. Add a Playwright smoke test for built SPA deep links and critical user journeys.

#### F-17 — Frontend production assets are oversized

**Evidence:** Vite reports chunks over 500 kB. The build contains `emacs-lisp` ~780 kB, C++/WASM ~620 kB each, and total `frontend/dist` is ~11 MB, despite the UI allowlisting only Python, SQL, and JSON in `CodeBlock` (`frontend/src/components/shared/code-block.tsx:7,41-46`).

**Recommendation:** Configure Shiki with only required languages/themes, verify route-level lazy loading, and set bundle budgets in CI. This improves App cold start, deployment upload, and first-use latency.

#### F-18 — WebSocket reconnect can create overlapping retries

**Evidence:** `frontend/src/stores/batch.ts:95-112` schedules retries from `onerror`, does not clear pending retry timers on disconnect/reset, and every closing socket sets `ws: null` even if a newer socket is active.

**Recommendation:** Track a connection generation and retry timer, reconnect from `onclose` once, cancel timers on reset/disconnect, and ignore events from stale sockets. Poll batch status as a recovery fallback after retry exhaustion.

#### F-19 — ZIP size enforcement observes compressed buffer size after writing each entry

**Evidence:** `server/routers/convert.py:124-155` checks `buf.tell()` after `writestr`. Highly compressible input can have a small archive but expand massively client-side, while a single oversized entry is fully allocated before rejection.

**Recommendation:** Enforce both cumulative uncompressed output bytes and compressed archive bytes before/while writing; set per-file limits and sanitize archive paths independently. Persist/stream large artifacts rather than assembling the entire ZIP in RAM.

#### F-20 — Dependency and supply-chain assurance is incomplete

**Evidence:** Python production dependencies use broad lower bounds; `requirements.lock` is not tracked. The frontend lockfile is tracked, but there is no visible automated CVE/license gate. Generated frontend assets are committed, making review diffs large and provenance harder to establish.

**Recommendation:** Generate a reproducible production lock or constraints file, add `pip-audit` and `npm audit`/OSV scanning in CI, configure Dependabot/Renovate, produce an SBOM for releases, and decide explicitly whether built assets are release artifacts or source-controlled inputs.

### Low priority / design wins

#### F-21 — “Four formats” documentation is stale after Lakeflow Designer was added

**Evidence:** The active pipeline priority has five formats (`src/a2d/pipeline.py:77-85`) and the frontend exposes Designer, while project-level documentation still repeatedly says four.

**Recommendation:** Define one format registry used by CLI, server schema, frontend labels, docs generation, and tests. Clarify that `dlt` remains the internal compatibility ID while “Spark Declarative Pipelines” is the user label.

#### F-22 — Logging/observability should include request and conversion correlation

**Evidence:** Logs include filenames and job IDs but no consistent request ID, user identity hash, queue time, active-work gauge, generator timing, memory, or artifact-size metrics.

**Recommendation:** Add structured JSON logs and OpenTelemetry-compatible metrics/traces. Avoid raw customer filenames where not needed; record hashed workflow IDs and explicit conversion/version/config dimensions.

#### F-23 — Accessibility and failure-state automation should be expanded

**Evidence:** Components use useful labels in several places, but no automated axe/keyboard/focus tests were found. Complex graph, tabs, code review, progress, and toast flows are particularly vulnerable.

**Recommendation:** Add `eslint-plugin-jsx-a11y`, axe tests, keyboard navigation tests, focus restoration for dialogs/downloads, reduced-motion coverage, and `aria-live` handling for async conversion/batch status.

## Positive findings worth preserving

- XML parser defenses have dedicated XXE tests.
- Upload reads are chunked and enforce per-file byte limits.
- API errors generally avoid returning stack traces or internal exception details.
- The parser/IR/generator separation, registry pattern, and source frontend abstraction are clean extension points.
- Single-file multi-format conversion parses and builds the DAG once.
- The independent pandas reference executor avoids circularly “verifying” generated code with the same implementation.
- Unsupported operations degrade to partial/inconclusive coverage rather than false semantic passes.
- Strict JSON workflow output and shared deploy-status/warning rules reduce frontend/backend drift.
- The advisory LLM subsystem is separated from generated-code writers by design and has byte-comparison tests; the manifest violation should be fixed without weakening this architecture.
- SPA fallback correctly preserves JSON 404s for `/api/*` and `/ws/*` and guards root static-file traversal.
- Frontend API calls are same-origin, avoiding Databricks Apps cross-origin proxy issues.

## Recommended remediation order

1. **Before the next deployment:** fix F-01 through F-04 and F-13; remove all checked-in workspace identifiers; migrate to an Autoscaling `postgres` resource; validate with an explicitly chosen profile.
2. **Before declaring production-ready:** fix F-05, F-06, F-08 through F-11, and add a minimal live Databricks execution suite.
3. **Next quality iteration:** expand frontend tests, reduce Shiki assets, harden WebSocket state, tighten mypy, and add dependency scanning.
4. **Architecture iteration:** durable user-owned job/session state, process isolation for conversion, structured telemetry, and a versioned SDP API target.

## Official references used

- [Databricks Apps runtime](https://docs.databricks.com/gcp/en/dev-tools/databricks-apps/app-runtime)
- [Databricks Apps system environment](https://docs.databricks.com/gcp/en/dev-tools/databricks-apps/system-env)
- [Databricks Apps resources](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/resources)
- [Databricks Apps environment variables](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/environment-variables)
- [Use Lakebase with Databricks Apps](https://docs.databricks.com/gcp/en/dev-tools/databricks-apps/lakebase)
- [Lakebase Provisioned to Autoscaling transition](https://docs.databricks.com/aws/en/oltp/instances/)
- [Update bundles to Lakebase Autoscaling](https://docs.databricks.com/aws/en/oltp/update-to-autoscaling-dabs)
- [What happened to Delta Live Tables](https://docs.databricks.com/aws/en/ldp/concepts/where-is-dlt)
- [`pyspark.pipelines` table reference](https://docs.databricks.com/gcp/en/ldp/developer/ldp-python-ref-table)
- [`pyspark.pipelines` materialized view reference](https://docs.databricks.com/gcp/en/ldp/developer/ldp-python-ref-materialized-view)
- [Lakeflow Jobs](https://docs.databricks.com/aws/en/jobs/)
- [Declarative Automation Bundles](https://docs.databricks.com/dev-tools/bundles/)

## Evidence limitations

Glean was explicitly queried for Databricks Apps, Lakebase, and Spark Declarative Pipelines guidance. Three advanced synthesized queries and three direct searches each timed out at the tool's 300-second limit, so no Glean result is represented as evidence in this report. The official public documentation and the locally installed current Databricks skills were used instead. No live workspace validation was performed because selecting or using a Databricks profile requires the user to choose one explicitly.

## Suggested exit criteria

The project should be considered deployment-ready when all critical findings are closed, generated adversarial strings compile without warnings, representative SDP/Jobs/DAB outputs validate in a selected Databricks workspace, app resources are injected rather than hardcoded, user ownership is enforced for stateful endpoints, and release CI includes backend/frontend tests plus dependency and bundle validation.

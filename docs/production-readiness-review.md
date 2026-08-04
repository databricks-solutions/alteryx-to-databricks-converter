# Production-Readiness Review — findings and outcomes

Date: 2026-08-04. Reviewed at commit `e82c4ab` (main, post PR #9).

> **Status: all findings resolved.** Every P0/P1/P2 item below was fixed and
> tested; P3 items were fixed, or closed as already-handled where verification
> showed the report was wrong (marked *not an issue*). Test count went 1440 →
> 1517 Python tests plus 14 new TypeScript tests. See the per-item **Outcome**
> lines and the [summary table](#outcome-summary).

Scope: full codebase — Python core (`src/a2d/`), server (`server/`), frontend
(`frontend/`), docs, CI and deploy config. Produced by three parallel review
passes, then **each finding below was independently verified against the code**
before being recorded. Claims that did not survive verification are listed in
[Rejected findings](#rejected-findings) so nobody re-litigates them.

Nothing here is fixed yet — this is the backlog for a follow-up pass.

**Baseline health (verified):** 1440 tests pass, 1 skipped, 85.6% coverage on
`src/a2d`; ruff + mypy clean on `src/` and `server/`; frontend `tsc -b` + build
clean; `npm audit` 0 vulnerabilities; XXE empirically blocked.

---

## Severity guide

| Level | Meaning |
|---|---|
| **P0** | Exploitable or data-corrupting in a realistic deployment. Fix before wider rollout. |
| **P1** | Real defect or meaningful risk gap. Fix soon. |
| **P2** | Correctness/robustness improvement, or a test gap over risky code. |
| **P3** | Polish, docs, consistency. |

---

## P0 — fix before wider rollout

### P0-1. CORS `allow_origins=["*"]` combined with `allow_credentials=True`
**Files:** `server/main.py:86-89`, `app.yaml:6`, `databricks.yml:111`

`A2D_CORS_ORIGINS` ships as `["*"]` and the middleware sets
`allow_credentials=True`. That pairing is invalid per the CORS spec and browsers
reject wildcard-with-credentials — but the deeper problem is intent: the app has
**no application-level authentication** (verified: no auth dependency on any
route; the only `Depends` is `conversion_options`, and chat's `_require_client`
checks *FMAPI config*, not the caller).

If the app is ever reachable outside the Databricks workspace proxy, any origin
can drive the API: upload workflows, read converted code, enumerate and delete
history.

**Failure scenario:** app exposed on a public URL; attacker page POSTs to
`/api/convert` and exfiltrates generated code, or walks `/api/history`.

**Fix:** set an explicit origin allowlist for prod (workspace URL) and keep
`["*"]` for local dev only; drop `allow_credentials` unless a cookie/session is
actually needed. Document that the app relies on the Databricks Apps proxy for
authn, and state that assumption in the README.

### P0-2. `DELETE /api/history/{id}` is unauthenticated and unscoped
**File:** `server/routers/history.py:36-44`

No authn, no ownership check — any caller who can reach the service deletes any
record by UUID. Combined with P0-1 this is remotely reachable.

**Fix:** decide the tenancy model and make it explicit. Either (a) record an
owner and enforce it, (b) add a read-only mode flag for shared deployments, or
(c) document single-tenant-by-design and gate mutations behind the proxy. Pick
one and write it down — the current state is an accident, not a decision.

---

## P1 — real defects and risk gaps

### P1-1. Designer generator swallows all translation errors, emitting untranslated Alteryx into generated code
**File:** `src/a2d/generators/designer.py:411`, `:719`

```python
try:
    condition = self._sql._translator.translate_string(node.expression)
except Exception:
    condition = node.expression   # raw Alteryx expression goes into the output
    warnings.append(f"Designer filter expression fallback for node {node.node_id}")
```

`except Exception` catches genuine translator bugs (`AttributeError`,
`TypeError`) identically to an expected unsupported-expression case, then writes
the **raw Alteryx expression** into generated code. This is the worst failure
class for this product: output looks successful, warning is generic, and the
code fails or misbehaves later at runtime. These are the only two bare
`except Exception` in all of `src/a2d/generators/` (24 exist across `src/a2d/`),
so the fix is contained.

**Fix:** catch the translator's own error type, include the cause in the warning,
and let unexpected exceptions propagate so they surface in CI.

### P1-2. `MISSING_RIGHT` / `MISSING_LEFT` sentinels are emitted into SQL
**File:** `src/a2d/generators/sql.py:348-349`

A join with a disconnected/mismatched anchor produces
`... INNER JOIN MISSING_RIGHT ON ...`. Conversion reports success; the SQL fails
at runtime with an unrelated-looking "table not found". **No test covers this
path** (verified: no test references the sentinels).

**Fix:** detect the missing input, emit an explicit blocker warning, and make the
generated cell obviously non-runnable (or fail the format). Add a test.

### P1-3. No timeout on conversion work
**Files:** `server/routers/convert.py`, `chat.py`, `analyze.py` (verified: no
`wait_for`/`timeout` anywhere in the routers)

CPU-bound conversion is correctly offloaded via `asyncio.to_thread`, but with no
deadline. A pathological or adversarial workflow that loops in the parser or a
generator occupies a thread-pool slot permanently; enough of them and the service
stops answering.

**Fix:** wrap with `asyncio.wait_for(...)` and return 408, with the limit as a
setting.

### P1-4. Batch ZIP is built entirely in memory, unbounded
**File:** `server/routers/convert.py:115-116` (`io.BytesIO` + `ZipFile`)

Batch allows up to 50 files × 50 MB, each fanning out to 5 formats plus optional
DDL/DAB. The whole archive is buffered in RAM with no cap.

**Fix:** cap total bytes (setting) and return 413 past the limit, or stream to a
temp file and serve with `FileResponse`.

### P1-5. Zero test coverage on the Lakebase/history data path
**Verified coverage:** `server/services/lakebase.py` **0%**,
`server/services/history.py` **17%**, `server/routers/history.py` **41%**

`lakebase.py` mints a fresh OAuth credential per connection with no retry — a
transient SDK error or rate-limit fails the pool, and nothing tests it. History
service catches broad `Exception` and returns defaults, so a malformed query
degrades silently rather than failing loudly.

**Fix:** unit-test with a mocked `WorkspaceClient` (connect, credential refresh,
failure path); add retry/backoff; narrow history's `except` to DB errors and
re-raise the rest.

### P1-6. Frontend has zero tests, including logic duplicated from Python
**Verified:** 0 test files under `frontend/src`; CI (`.github/workflows/ci.yml`)
runs `npm ci` + `typecheck` + build only.

`frontend/src/lib/warning-parsing.ts` (393 lines) and `deploy-status.ts` (141
lines) are **hand-ports of Python logic** (`observability/warning_categorization.py`,
`deploy_status.py`). Two implementations of the same rules with no test pinning
them together will drift, and drift means the UI states a different deploy verdict
than the CLI for the same workflow.

**Fix:** add Vitest, then test those two modules first — ideally against shared
fixtures so both languages assert the same expected outputs. Wire `npm test` into
CI.

---

## P2 — robustness and test gaps

### P2-1. Chat session eviction is silent and returns a misleading 404
**File:** `server/services/chat.py:71-79`

Past `MAX_SESSIONS = 200` the oldest sessions are dropped mid-conversation; the
next turn returns 404 "Unknown chat session", indistinguishable from a bad id.

**Fix:** return 410 Gone for evicted-but-known sessions, or tell the client to
restart; log evictions.

### P2-2. WebSocket broadcast has no per-subscriber error isolation
**File:** `server/services/batch.py:374` (`await q.put(msg)` inside a loop)

One failing queue aborts the loop, so later subscribers miss the update. The
outer handler catches it, but delivery is silently partial.

**Fix:** wrap each `put` in try/except and log.

### P2-3. Unmapped connection names fall back to defaults with no warning
**File:** `src/a2d/connections.py:41-52`

A typo'd connection key silently resolves to `default_catalog.default_schema`, so
generated code targets the wrong location with no signal.

**Fix:** warn on unmatched name (optionally `--strict-connections` to fail).

### P2-4. Reference executor passes through unsupported multi-input nodes
**File:** `src/a2d/verification/reference.py:96-103`

On an unsupported node it forwards the single available input. For a node that
*should* have several (join/union), this can feed downstream ops partial data
while the run still reports parity for the nodes that did execute — weakening the
verification guarantee the product leans on.

**Fix:** only pass through when the node genuinely has one input; otherwise mark
skipped and refuse to claim parity downstream.

### P2-5. Ambient-credential fallback is invisible
**File:** `src/a2d/advisor/llm_client.py:91-108`

A wrong/expired explicit token silently falls back to workspace credentials, so
the operator can't tell which identity was used.

**Fix:** log (INFO) which auth path was taken.

### P2-6. No explicit XXE regression test
Protection is real and empirically verified (`resolve_entities=False,
no_network=True` at `src/a2d/parser/workflow_parser.py:18`; a `file:///etc/passwd`
payload does not leak). But nothing pins it — a future parser refactor could
regress it silently.

**Fix:** add a test asserting an XXE payload never yields file contents.

### P2-7. Unbounded recursion in `element_to_dict`
**File:** `src/a2d/utils/xml_helpers.py`

Deeply nested XML can exhaust the stack. Low likelihood, trivially cheap to bound.

**Fix:** depth limit with a clear error.

### P2-8. Untested exception paths in conversion/batch services
DDL/DAB generation failures are caught and logged but never asserted in tests, so
partial-failure behavior is unverified.

**Fix:** force the generators to raise and assert the surfaced result.

### P2-9. Cluster-tier index has no bounds guard
**File:** `src/a2d/advisor/cost.py:158-166` — `_TIERS[idx]` after threshold
branches; extending the scoring without touching `_TIERS` raises `IndexError`.
**Fix:** clamp with `min(idx, len(_TIERS) - 1)`.

---

## P3 — docs, polish, consistency

### P3-1. README undercounts CLI commands in three places (verified)
**File:** `README.md:48` ("5 CLI commands"), `:343` ("a2d provides 6 commands"),
`:442` ("Typer CLI (5 commands)"). Actual: **12** — `convert, analyze, portfolio,
validate, verify, suggest, sync, advise, profile, list-tools, plugins, version`.
Users can't discover `portfolio`, `verify`, `sync`, `advise`, `suggest`,
`profile`, `plugins`.
**Fix:** list all 12 with one-line descriptions; refresh the module tree
(`advisor/`, `incremental/`, `portfolio/`, `frontends/`, `bridges/`, `sdk/`,
`review/`, `macro/` are missing).

### P3-2. Stale reference to the removed `assist` command
**File:** `docs/converter-sdk.md:18` still lists `assist` among downstream
consumers. `a2d assist` and `a2d feedback` were removed in PR #8.
**Fix:** replace with `suggest`.

### P3-3. Lazy routes have no chunk-load recovery
**File:** `frontend/src/app.tsx`

All routes are `lazy()` under one root `Suspense`. A transient chunk fetch failure
lands in the error boundary with a generic message and no retry.
**Fix:** retry-on-failure wrapper or a route-level error component with a reload
action.

### P3-4. Chat keeps the optimistic user message after a failed send
**File:** `frontend/src/routes/chat.tsx:65-77`

`onError` toasts but leaves the user's message in the transcript with no reply,
implying it was delivered.
**Fix:** mark it failed (or roll it back) and offer retry.

### P3-5. Batch keepalive echoes raw filenames
**File:** `server/websocket/batch.py:58-65` — `current_filename` is sent
verbatim every keepalive and lands in logs. Filenames can be sensitive
(`customer_pii_2024.yxmd`).
**Fix:** send the stem, or redact in logs.

### P3-6. Missing empty states
`/history` and `/analyze` render bare sections with no "nothing here yet" copy or
next action.

### P3-7. `sanitize_filename` silently rewrites names
**File:** `server/utils/validation.py:13-17` — `workflow@2024.yxmd` becomes
`workflow_2024.yxmd` with no note. Behavior is correct; just undocumented.

---

## Rejected findings

Reported by a review pass, **disproven on inspection** — do not act on these:

| Claim | Reality |
|---|---|
| react-markdown allows raw HTML → XSS | `rehype-raw` is not installed; v10 strips raw HTML by default. `markdown-block.tsx` is safe. |
| `localStorage` history grows unbounded | `MAX_ITEMS = 50` with `.slice()` at `stores/local-history.ts:23,36,64`. |
| `batch-results.tsx` renders null metrics → crash | Guarded: `if (status !== "completed" \|\| !batchMetrics) return null` (line 41). |
| Analyze button allows double-submit | Already `disabled={files.length === 0 \|\| mutation.isPending}` (`routes/analyze.tsx:95`). |
| WebSocket reconnect can attach to another job | `connectWs(jobId)` closes over the id and rebuilds the same URL; retry targets the same job. |
| Incremental tracker hash collides on `" ".join` | Empirically no collision for the cited inputs; ordering is stable. Non-issue at current call sites. |
| FMAPI endpoint is an SSRF vector | Endpoint comes only from operator env/settings — never from a request body, form or query. Hardening the URL is defense-in-depth (see P2-5 area), not a live vulnerability. |
| SQL injection in history service | Parameterized queries throughout `server/services/history.py`. |
| CLI has 13 commands | 12 (verified via `a2d --help`). |

---

## Outcome summary

Fixed across four commits on `fix/production-readiness`.

| ID | Outcome | Note |
|---|---|---|
| P0-1 | **Fixed** | Credentials only enabled for an explicit origin allowlist; warns on `"*"`. Same-origin in Apps, so this affects local dev only. |
| P0-2 | **Decided + documented** | History is a **shared team log** — one service principal, no per-user scoping. Recorded as an explicit decision with the access-control model. |
| P1-1 | **Fixed** | `designer.py` catches `BaseTranslationError` only, appends the cause; real bugs propagate. |
| P1-2 | **Fixed (wider than reported)** | The review found it in `sql.py`; `pyspark.py`, `dlt.py` and `AppendFields` had the same defect. All four now refuse to generate and name the missing side. |
| P1-3 | **Fixed** | `run_with_timeout` + `A2D_CONVERSION_TIMEOUT_SECONDS`; also fixed a latent bug where the broad `except` would have turned the 408 into a 500. |
| P1-4 | **Fixed** | `A2D_MAX_ZIP_SIZE_BYTES`, checked as entries are written, 413 past the limit. |
| P1-5 | **Fixed** | `lakebase.py` 0% → **100%**, `history.py` 17% → **48%**; error handling narrowed to psycopg errors. |
| P1-6 | **Fixed** | Vitest + a **shared cross-language fixture**: Python and TS assert the same rules, so one-sided drift fails the other suite. Verified by simulating drift. `npm test` in CI. |
| P2-1 | Fixed | Evicted sessions answer 410 Gone, not 404. |
| P2-2 | Fixed | Per-subscriber isolation on all three broadcast loops. |
| P2-3 | Fixed | Warns once per unmapped connection name. |
| P2-4 | Fixed | Passthrough restricted to genuinely single-predecessor nodes. |
| P2-5 | Fixed | Logs when ambient credentials are used. |
| P2-6 | Fixed | Dedicated XXE suite (file entity, billion laughs, remote entity). |
| P2-7 | Fixed | `MAX_XML_DEPTH = 100`, truncates with a warning. |
| P2-8 | Covered | Exception paths exercised via the new limits/history tests. |
| P2-9 | Fixed | Tier index clamped. |
| P3-1 | Fixed | README: 12 commands; corrected **158 tool types / 113 converters / 5 formats** (it understated); module tree refreshed. |
| P3-2 | Fixed | Stale `assist` → `suggest` in `docs/converter-sdk.md`. |
| P3-3 | Fixed | `lazyWithRetry` on all 11 routes. |
| P3-4 | Fixed | A failed send rolls the message back into the composer. |
| P3-5 | **Not an issue** | `current_filename` is never logged — it goes over the WebSocket to the uploader's own browser, showing their own filename. |
| P3-6 | **Not an issue** | History already has a full empty state; Analyze is upload-driven, where the dropzone *is* the empty state. |
| P3-7 | Fixed | `sanitize_filename` documents both path stripping and character rewriting. |

Also added a README **AI assistant (opt-in)** section documenting `a2d suggest`,
the `/chat` page, and how to enable FMAPI at deploy time — the feature existed but
was undocumented for end users.

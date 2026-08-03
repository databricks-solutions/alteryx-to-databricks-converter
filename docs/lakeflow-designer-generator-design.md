# Design note: native Lakeflow Designer (`.designer.ipynb`) generator

**Status:** Implemented (July 2026) — `designer` is now the 5th output format.
See `src/a2d/generators/designer.py` and `tests/unit/generators/test_designer.py`.
**Author:** drafted from a format-contract investigation (July 2026).
**Validation still recommended:** import one generated `.designer.ipynb` into a live
Designer canvas to confirm the contract against the current Designer build (§6, step 1).

---

## 1. Problem statement

a2d's current `lakeflow` format is **mislabeled**. Internally the format id is `lakeflow`, but
the CLI and frontend present it as **"Lakeflow Designer"** (see `_FORMAT_LABELS` in `src/a2d/cli.py`
and `FORMAT_LABELS`/`FORMAT_ORDER` in `frontend/src/lib/constants.ts`). What it actually emits is
**Lakeflow Declarative Pipelines (LDP/SDP) SQL** — a `.sql` file of `CREATE OR REFRESH MATERIALIZED
VIEW` / `STREAMING TABLE` statements plus a companion pipeline JSON. That is **not** a Designer
visual-ETL file and cannot be opened as draggable nodes on the Designer canvas.

Two things make this worth fixing:

1. **Accuracy.** As of ~early 2026 the Designer backend moved from SQL codegen to **Python**
   codegen (to support side-effects: email, API calls, file writes). Our SQL output is not even
   Designer's current runtime. Presenting it as "Lakeflow Designer" overclaims.
2. **Demand.** Field + customers (see the `#alteryx2databricks-converter` thread) specifically want
   the **visual** Designer artifact for business users — the closest analog to the Alteryx Designer
   experience. Databricks positions Designer as the Alteryx-replacement play.

## 2. Why this fits a2d specifically

a2d is a **deterministic** Parse → IR → Generate pipeline (no LLM). That is the exact
differentiator vs. the existing Alteryx→Designer efforts:

- `brickify/tools/lakeflow_designer_native` uses an **LLM agent** for per-node operator selection.
- The first-party product effort (JIRA **LAKEBLDR-1671**) is **Genie-Code/LLM-driven**, ~90%
  automation, and explicitly **rejected** deterministic rule-based conversion.

A deterministic `.designer.ipynb` generator is the one approach that preserves a2d's
reproducibility guarantee (same input → same output, testable in CI). The format is also a
near-perfect structural match: Designer's file model is **a graph of typed operator cells**
(`id`, `template`, `config`, `input[]` wiring, `position:{x,y}`), and a2d's IR is **already** a
typed DAG with topological order, per-node config, and edge/anchor wiring. Targeting Designer is
arguably *easier* than SQL (no DAG→CTE flattening needed).

## 3. The format contract (de-risked)

Findings below come from two field-eng repos and one real Designer export:
- `databricks-field-eng/brickify` — `src/brickify/tools/lakeflow_designer_native/`
  (`cell_emitter.py`, `converter.py`, `decisions.py`, `operator_catalog.py`, `catalog/*.json`).
  The **assembler half is fully deterministic and directly portable** (the LLM is only used for
  operator selection, which we replace with our own mapping table).
- `databricks-field-eng/geniecodeskills-alteryxmigration` —
  `Skills/alteryxToLakeflowDesigner/SKILL.md` (full Alteryx→Designer operator mapping) +
  `Samples/RetailAnalyticsComplex/RetailAnalyticsComplex.designer.ipynb` (a real Designer export =
  ground truth).

### 3.1 File shape

A `.designer.ipynb` is a standard Jupyter notebook (`nbformat: 4`, `nbformat_minor: 0`) where
**each operator = one code cell**. Required wrappers (import fails to render the DAG without them):

- Notebook-level metadata key `application/vnd.databricks.v1+notebook`
  (`notebookName`, `language: python`, `widgets: {}`, …), plus `kernelspec` / `language_info`.
- Per-cell metadata key `application/vnd.databricks.v1+cell` with a **unique `nuid`** (uuid4),
  `cellMetadata`, `inputWidgets`, `showTitle: false`, `tableResultSettingsMap`, `title`.

Each cell's `source` is: a **triple-quoted YAML docstring** (the "annotation") + a fixed
per-template `run(config, inputs, spark)` body + a wiring block.

### 3.2 YAML annotation fields

Always emit, in this order: `id`, `template`, `templateVersion`, `name`, `position:{x,y}`,
`description:{text, hash}`, `previewCodeHash`, `previewMode` (always `"1000"`), `config`, `input`.

- **`template`** = bare catalog id (`filter`, not `filter_cell`). REQUIRED.
- **`templateVersion`** = pinned version, e.g. `2.0.0`. Include it (real export + brickify both do;
  SKILL.md examples sometimes omit it — follow the export).
- **`parentId`** — only for children of a `group` container. Omit otherwise.
- **`dimensions`** — only for `markdown`/`group`. Omit otherwise.
- **`input`** — YAML list of `{node, input_port, output_port}` (or `[]` when no upstream).
  `node` = upstream cell's id/name; ports per §3.5.

### 3.3 `previewCodeHash` / `description.hash` — RESOLVED (was the key risk)

- These are Designer-internal content hashes (`previewCodeHash` = 16-hex/64-bit;
  `description.hash` = 8-hex/32-bit). The **algorithm lives in Designer's frontend and is not
  recoverable** from these repos (md5/sha1/sha256/crc32/adler32 all fail to reproduce it).
- **We do not need to compute them.** brickify ships `previewCodeHash: ""` and `hash: ""`
  (empty strings) on every cell, and Designer imports cleanly and recomputes on open. The real
  export even **omits `previewCodeHash` entirely** on some cell types (join/output/python).
- **Decision:** emit `previewCodeHash: ""` and `description.hash: ""`. No hashing code required.

### 3.4 Operator template versioning (maintenance tax lives here)

Pin exactly one version per operator (prod-latest), matching brickify's hand-maintained catalog:

```
source@2.0.0    output@1.0.0    transform@2.0.0   ai_function@3.0.0
filter@2.0.0    sort@1.0.0      limit@1.0.0       aggregate@2.0.0
prepare@1.0.0   combine@2.0.0   join@1.0.0        pivot@1.0.0
python@1.0.0    sql@1.0.0
```

- **Why versions matter:** version bumps that change **ports** are the hazard. `filter@2` adds an
  `excluded_data` output; `combine@2` replaces fixed `data_0/data_1` with a variadic `data`.
- `join` held at **v1** (v2 split_join / tripartite output only in staging).
- This catalog is a **hand-maintained stopgap** until Databricks ships a served catalog
  (LAKEBLDR-1760). Track it as an explicit maintenance item — this is the one recurring cost a2d's
  other four formats don't carry.

### 3.5 Wiring / ports

`input[]` entries = `{node: <upstream cell id>, input_port: <this cell's port>, output_port:
<upstream's port>}`. Map by **originating Alteryx node id, not list position** (brickify PR #120
fixed a positional-zip bug that scrambled every wire).

Port translation from Alteryx anchors:
- Alteryx `filter`: `True`→`filtered_data`, `False`→`excluded_data` (**only if filter@2.0.0**).
- Alteryx `join`: `Join`→`joined_data`; `Left`/`Right` outputs → dropped (join@1 is single-output;
  recreate L/R via left+null-check / `LEFT ANTI` / `RIGHT ANTI` in a `sql` cell).
- Join **inputs**: `Left`→`left`, `Right`→`right`.
- `combine` / `python` inputs: single variadic `data` port (python wraps all upstreams as a list).
- Multi-output cells (e.g. filter@2) must store **all** output ports into the context so downstream
  wires to the secondary port don't dangle.

### 3.6 Layout (must be implemented — no reusable code exists)

brickify does **not** compute layout; it reuses the Alteryx node coordinates verbatim. For clean
Designer canvases we implement the SKILL.md convention ourselves:
- **x** from topological tier: sources at x=0, then step **≈260px** per tier left→right.
- **y** per parallel branch lane: step **≈145px** top→bottom. (Negative y allowed for header notes.)

### 3.7 YAML quoting rules (silent-failure landmines)

- Double-quote any scalar containing `" \ : # { } [ ] , & * ! | > % @ \``, or with leading/trailing
  whitespace, or that lowercases to `true/false/null/yes/no`. Escape `\`→`\\` then `"`→`\"`.
- **`description.text`** must escape `\n`→`\\n`, `\r`→`\\r`, `\t`→`\\t`. A raw newline (or an
  unescaped colon) makes Designer **silently drop the cell** from the dataflow graph — surfaces
  downstream as a misleading `'<x>.<port>' data is missing` error.
- Multi-line config (python `code`, `sql` `query`) → YAML **block literal (`|`)**, never
  double-quoted (double-quote folds newlines and corrupts code).
- Empty collections → `[]` / `{}` in flow style (so JSON-schema validators see array/object),
  never the strings `"[]"`/`"{}"`.

## 4. Operator coverage vs. a2d's IR

Designer exposes ~14 templates: `source, output, ai_function, aggregate, combine, filter, join,
limit, pivot, sort, sql, transform, python, markdown` (+ `group` container). a2d has **59 IR node
types** (`src/a2d/ir/nodes.py`). Mapping strategy (full table in SKILL.md):

- **Native/high-fidelity** (direct template): Read→`source`, Write→`output`, Filter→`filter`,
  Formula/Select/DataCleansing/DateTime→`transform`, Sort→`sort`, Sample/first-N→`limit`,
  Join→`join`, Union→`combine`, Summarize/CountRecords→`aggregate`, CrossTab/Transpose→`pivot`.
- **SQL escape hatch** (`sql` cell): RecordID (ROW_NUMBER), Unique, RunningTotal (SUM OVER),
  Tile (NTILE), MultiRowFormula (LAG/LEAD), TextToColumns, WeightedAverage, etc.
- **Python escape hatch** (`python` cell): PythonTool, XMLParse, spatial (Sedona `ST_*`),
  predictive (MLflow).
- **AI functions**: sentiment/classify/extract/mask/translate/summarize/grammar/similarity.
- **Manual / omit**: reporting (→ Lakeview), interface tools (→ job params), macros
  (iterative → MANUAL), Browse/Throttle/BlockUntilDone → omit; Comment→`markdown`,
  ToolContainer→`group`.

**Coverage ceiling is inherently lower than PySpark/SQL** (~100%): Designer has fewer primitives,
so the Designer format legitimately shows more `sql`/`python`/MANUAL fallbacks. Internal analysis
cites ~90% of Alteryx workflows as Designer-expressible. Set expectations accordingly in the
coverage banner.

## 5. Integration points in a2d (all confirmed)

Adding the 5th format is mostly one-liners; the effort is the generator + tests.

| File | Change |
|---|---|
| `src/a2d/config.py` | add `DESIGNER = "designer"` to `OutputFormat` |
| `src/a2d/generators/designer.py` | **NEW** generator (implements `CodeGenerator.generate`) |
| `src/a2d/generators/__init__.py` | import + `__all__` |
| `src/a2d/pipeline.py` | add to `_GENERATOR_CLASSES` and `_FORMAT_PRIORITY`; `convert_all_formats` already iterates the enum |
| `src/a2d/cli.py` | `_FORMAT_LABELS["designer"] = "Lakeflow Designer"`; help text |
| `src/a2d/observability/warning_categorization.py` | add label |
| `server/services/conversion.py` | make the hardcoded format list dynamic (1 line) |
| `frontend/src/lib/constants.ts` + `api.ts` | `FORMAT_ORDER`, `FORMAT_LABELS`, `FormatId` |
| `tests/unit/generators/test_designer.py` | **NEW** |
| `tests/smoke/*designer*.yml` | **NEW** per-scenario fixtures |

The generator implements the standard interface: `generate(dag, workflow_name) -> GeneratedOutput`
(`files`, `warnings`, `stats`), walking `dag.topological_order()` and dispatching per IR node type —
same shape as the existing four generators.

### Relabel decision

Once `designer` exists as the real Designer target, **rename the current `lakeflow` label** away
from "Lakeflow Designer" (e.g. "Spark Declarative Pipelines (SQL)") so the two formats aren't
confused. Until then, the current label is inaccurate.

## 6. Recommended path

1. **Validation spike (small).** Export one real `.designer.ipynb` from a Designer canvas;
   hand-assemble a 2–3 operator file per §3 and confirm it imports as editable nodes. (brickify's
   validated runs — 280/280, 68/68 cells — strongly suggest it will.) This confirms the contract on
   the *current* Designer build before committing the full build.
2. **Build the deterministic generator** (~4–6 weeks): `designer.py` + operator mapping table +
   layout pass + tests. Bounded because the format is documented, hashing is a non-issue, and
   brickify de-risks the assembler gotchas.
3. **Track the version catalog** (§3.4) as an explicit maintenance item.

## 7. Strategic caveat (read before building)

Databricks is building a **first-party** Alteryx→Designer importer (LAKEBLDR-1671, LLM-driven),
and field already has two tools (brickify + Daphne's Genie-Code skill). a2d's durable edge is
**determinism**; its risk is **redundancy**. The build-vs-converge decision should be made
consciously with the Designer PM/field owners — a deterministic generator has a real place in the
gap today and a lasting reproducibility advantage, but this should not be a siloed effort.

## References

- Public: docs.databricks.com `/designer/built-in-operators`, `/designer/build-transformation`,
  `/designer/operators-yaml-ref`, `/designer/production`.
- Internal spec (LakeBuilder): `tech-docs.dev.databricks.com/product/lakeflow-designer/parsing`,
  `/operators`.
- `databricks-field-eng/brickify` PRs #117, #120; `src/brickify/tools/lakeflow_designer_native/`.
- `databricks-field-eng/geniecodeskills-alteryxmigration` `Skills/alteryxToLakeflowDesigner/SKILL.md`.
- JIRA: LAKEBLDR-1671 (product importer), LAKEBLDR-1760 (served catalog), LAKEBLDR-803 (prior POC).

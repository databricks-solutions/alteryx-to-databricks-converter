# Design note: semantic equivalence verification (`a2d verify`)

**Status:** Implemented (July 2026). See `src/a2d/verification/` and
`tests/unit/verification/`.

## Problem

`convert` proves the generated code is *syntactically* valid and estimates a heuristic
*confidence* score. Neither answers the question that actually gates an enterprise migration:
**does the generated pipeline produce the same result as the original Alteryx workflow?**

## Approach

Verification without an Alteryx license, runnable on a laptop:

1. **Pandas reference executor** (`reference.py`) — an *independent* second implementation of
   the IR semantics in pandas. It shares nothing with the PySpark/SQL generators, so its
   agreement with them (or with a golden output) is genuine equivalence signal. Runs everywhere
   (no JVM).
2. **Parity engine** (`parity.py`) — pure-pandas DataFrame diff: column set + dtype family,
   row count, order-insensitive row-multiset equality, per-cell comparison with numeric
   tolerance and null-aware equality. Returns a structured `ParityReport` with a `passed`
   verdict and a `parity_score`.
3. **Spark backend** (`spark_backend.py`) — mirrors the same op set through PySpark. Used for a
   pandas-vs-Spark cross-check when a JVM is present (Databricks/CI); returns
   `available=False` with a reason otherwise (it actually runs `java -version`, because on macOS
   `java` is often a non-functional stub on PATH).
4. **Runner + CLI** (`runner.py`, `a2d verify`) — parse → DAG → execute → compare.

### Modes (auto-selected)

| Mode | When | Verdict source |
|---|---|---|
| `golden` | `--expected out.csv` supplied | reference result vs. Alteryx-exported ground truth |
| `cross_check` | no golden, JVM present | pandas result vs. Spark result |
| `reference_only` | no golden, no JVM | reference produced, nothing to diff → `inconclusive` |

Never a false pass: a workflow with operators the reference executor doesn't model reports a
*partial* result (verified subset only), and any unsupported node downgrades a `pass` to
`inconclusive`.

## Op coverage (first pass)

Native: read, literal/TextInput, filter (incl. True/False fan-out), select (drop/rename),
formula (via an independent pandas expression evaluator over the shared AST), sort, sample/limit,
record id, count records, union, join (inner/left/right/full), summarize
(group-by + sum/count/min/max/avg/first/last/count-distinct).

Anything else → clean "skipped". Follow-on: the parse/transform tail (datetime, regex,
text-to-columns, crosstab/transpose, running total, tile) and a data-profiling pass.

## Packaging

Optional `verify` extra (`pip install 'alteryx2databricks[verify]'`) adds `pandas` (required)
and `pyspark` (optional, cross-check only). `a2d verify` prints a clear install hint if the
extra is missing.

## Exit codes

Non-zero only on an actual comparison **FAIL** (so CI can gate). `inconclusive` and `pass`
exit 0.

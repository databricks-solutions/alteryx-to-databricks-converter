# Alteryx → Databricks Conversion Mapping

How each Alteryx tool maps to generated Databricks code across all 4 output formats (PySpark, DLT, SQL, Lakeflow). 62 converters covering 112 tool types across 157 plugin name variants.

---

## Output Formats

`a2d convert` emits all four formats by default into per-format subdirectories of `--output-dir` (`output/pyspark/`, `output/dlt/`, `output/sql/`, `output/lakeflow/`). The server's `POST /api/convert` likewise returns every format in a single `ConversionResponse.formats` map (no `output_format` request parameter). Use `-f` (CLI, comma-separated) to restrict to a subset.

| Format | Filter flag | Generated Files | Best For |
|--------|-------------|----------------|----------|
| PySpark | `-f pyspark` | `.py` notebook + `_workflow.json` + `_workflow.README.md` | Interactive development, debugging |
| Spark Declarative Pipelines (DLT) | `-f dlt` | `_dlt.py` notebook + `_workflow.json` + `_workflow.README.md` | Production pipelines with data quality |
| SQL | `-f sql` | `.sql` script + `_workflow.json` + `_workflow.README.md` | SQL-oriented teams, simple transforms |
| Lakeflow Designer | `-f lakeflow` | `.sql` statements + `_lakeflow_pipeline.json` + `_workflow.json` + `_workflow.README.md` | Native Databricks pipeline format |

> **Workflow JSON is strict JSON** — no `//` comment headers. Operator notes (intentionally-omitted `run_as` / `webhook_notifications` etc.) live in the sibling `*_workflow.README.md` so the JSON file is parseable by `json.loads`, `jq`, and CI tooling without preprocessing.

---

## Fully Converted Tools

These tools are automatically converted with high confidence (≥ 0.9).

### IO Tools

| Alteryx Tool | PySpark Equivalent | Notes |
|---|---|---|
| **Input Data** (CSV, TSV, TXT) | `spark.read.format("csv").option(...).load(path)` | Header, delimiter, encoding preserved |
| **Input Data** (Parquet) | `spark.read.format("parquet").load(path)` | |
| **Input Data** (JSON) | `spark.read.format("json").load(path)` | |
| **Input Data** (Avro) | `spark.read.format("avro").load(path)` | |
| **Input Data** (SAS `.sas7bdat`) | `spark.read.format("sas")...` | Requires `spark-sas7bdat` library |
| **Input Data** (Database) | `spark.sql("""SELECT ...""")` | SQL query preserved; connection needs remapping |
| **Output Data** (CSV, Parquet, etc.) | `df.write.format(...).mode(...).save(path)` | Overwrite/append mode preserved |
| **Text Input** | `spark.createDataFrame(data)` | Inline data preserved as Python literals |
| **Browse** | `df.show()` / `display(df)` | Preview-only; no downstream effect |
| **Dynamic Input** | `spark.read.format(...).load(path)` | Mode and ModifySQL fields preserved |
| **Cloud Storage** | `spark.read.format(...).load(cloud_path)` | S3/ADLS/GCS paths preserved |

### Preparation Tools

| Alteryx Tool | PySpark Equivalent | Notes |
|---|---|---|
| **Select** | `df.drop(...)` / `df.withColumnRenamed(...)` | Deselected and renamed columns applied |
| **Filter** | `df_pass = df.filter(expr)` / `df_fail = df.filter(~expr)` | True/False anchors split into separate DataFrames |
| **Formula** | `df.withColumn("field", expr)` | Expression translated via 141-function engine |
| **Sort** | `df.orderBy(...)` | Ascending/descending per field |
| **Sample** (First N) | `df.limit(n)` | |
| **Sample** (Random N / %) | `df.sample(fraction, seed)` | Seed from Alteryx deterministic setting |
| **Unique** (Dedup) | `df.dropDuplicates(key_fields)` | Key fields from configuration |
| **Data Cleansing** | `F.trim(col)` / `F.when(col.isNull(), ...)` | Null replace, trim, case normalization |
| **Record ID** | `F.monotonically_increasing_id()` | Sequential numbering approximated |
| **Auto Field** | Passthrough (no-op) | Type optimization not needed in Spark |
| **Multi-Field Formula** | Multiple `df.withColumn(...)` calls | One per formula expression |
| **Multi-Row Formula** | `F.lag(col, n).over(window)` / `F.lead(...)` | Row references translated via window functions |
| **Generate Rows** | `spark.range(start, end, step)` | |

### Join Tools

| Alteryx Tool | PySpark Equivalent | Notes |
|---|---|---|
| **Join** (Inner / Left / Right / Full) | `df_left.join(df_right, cond, how=...)` | Join keys extracted from XML |
| **Union** | `df1.unionByName(df2, allowMissingColumns=True)` | All inputs merged; column alignment handled |
| **Append Fields** | `df_left.crossJoin(df_right)` | Broadcast hint added for small tables |
| **Find Replace** | `df.join(lookup, ...)` | Lookup join with replacement logic |
| **Join Multiple** | Chained `df.join(...)` calls | Multiple inputs joined sequentially |

### Parse Tools

| Alteryx Tool | PySpark Equivalent | Notes |
|---|---|---|
| **RegEx** (Parse/Match/Replace) | `F.regexp_extract(...)` / `F.rlike(...)` / `F.regexp_replace(...)` | |
| **Text To Columns** | `F.split(col, delimiter)[index]` | Multi-column split via explode |
| **DateTime** (Parse / Format) | `F.to_timestamp(col, fmt)` / `F.date_format(col, fmt)` | Format strings preserved |
| **DateTime Add** | `F.date_add(col, n)` / `F.add_months(col, n)` | Days/months/years mapped natively |
| **JSON Parse** | `F.get_json_object(col, path)` | JSON path extraction |

### Transform Tools

| Alteryx Tool | PySpark Equivalent | Notes |
|---|---|---|
| **Summarize** (GroupBy + Agg) | `df.groupBy(...).agg(F.sum(), ...)` | Count, Sum, Avg, Min, Max, CountDistinct |
| **Cross Tab** | `df.groupBy(...).pivot(...).agg(...)` | Pivot key columns must be known at runtime |
| **Transpose** | Stack/unpivot pattern | Column-to-row transformation |
| **Running Total** | `F.sum(col).over(Window.rowsBetween(...))` | |
| **Count Records** | `df.count()` | |
| **Tile** | `F.ntile(n).over(window)` | Quantile/equal-count tiles |

### Developer Tools

| Alteryx Tool | PySpark Equivalent | Notes |
|---|---|---|
| **Python Tool** | Original code preserved in comment block | Manual adaptation to PySpark/pandas API required |
| **Download** | `# TODO: implement HTTP request` | Replace with `requests` UDF or external access |
| **Run Command** | `# TODO: implement shell command` | Replace with `%sh` magic or `dbutils.notebook.run` |
| **Block Until Done** | Passthrough (synchronization point) | |

### Other

| Alteryx Tool | PySpark Equivalent | Notes |
|---|---|---|
| **Comment / Annotation** | `# comment text` in notebook cell | Canvas annotations preserved as code comments |
| **Tool Container** | Skipped (layout-only) | |

---

## Partially Converted Tools (Review Required)

These tools are converted but the output needs manual review before running in Databricks.

| Alteryx Tool | Generated Code | What to Review |
|---|---|---|
| **Join** (with Select post-join) | `df.drop(...)` / `df.withColumnsRenamed({...})` appended after join (Spark 3.4+ batched rename — `withColumnRenamed` only used for single-column renames) | Verify selected/dropped columns match intent |
| **Formula with complex expressions** | `F.lit(None)  # PLACEHOLDER` with `# TODO` block | Review expressions containing unsupported functions |
| **Filter with complex expressions** | `F.lit(True)  # PLACEHOLDER` with `# TODO` block | Replace placeholder with correct PySpark condition |
| **Summarize (Concatenate)** | `F.concat_ws(sep, col)` | Multi-row string concat may need `groupBy` + `agg` pattern |
| **Summarize (Count Missing)** | `F.sum(F.when(col.isNull(), 1).otherwise(0))` | Verify null semantics match Alteryx behavior |
| **Cross Tab** | `df.groupBy(...).pivot(...).agg(...)` | Pivot key columns must be known at runtime |
| **DateTime (edge cases)** | `F.expr(f"dateadd({unit}, {n}, col)")` | Non-standard units (quarters, weeks) use SQL fallback |

---

## Manual Conversion Required

The following Alteryx tools or configurations **cannot be automatically converted** and require manual implementation in Databricks. The converter emits `# TODO` placeholder blocks with the original Alteryx expression preserved.

### Input Sources

| Scenario | Generated Output | Manual Steps |
|---|---|---|
| **Non-Delta external tables (CSV/JSON/Parquet/Avro at a path)** in `--generate-ddl` output | `CREATE TABLE ... AS SELECT * FROM read_files('...', format => '...')` (Delta-managed table over the foreign format, per Unity Catalog 2024-Q4+ guidance) | Adjust the `read_files()` options (`header`, `inferSchema`, `multiLine`, etc.) to match the source layout |
| **ODBC / DSN connections** | `spark.sql("""SELECT ...""")  # TODO: replace DSN with catalog.schema.table` | Replace DSN connection with Unity Catalog table reference or JDBC connection string |
| **Excel files (`.xlsx`, `.xls`)** | `# TODO: manual conversion required` + `df = None  # PLACEHOLDER` | Use `openpyxl` / `pandas` bridge or mount file to DBFS; consider converting to CSV/Parquet first |
| **Alteryx DB format (`.yxdb`)** | Low confidence warning emitted | Convert `.yxdb` to Parquet or Delta using Alteryx export before migrating |
| **Local / UNC network paths** | `# WARNING: local/network path detected` + escaped path in comment | Upload file to DBFS, Unity Catalog Volume, or cloud storage; update path in generated code |
| **`aka:` named connections** | `spark.sql("""...""")  # TODO: map connection alias` | Map Alteryx connection alias to Databricks catalog/schema or JDBC URL |

### Expression Engine Limitations

| Alteryx Feature | Behavior | Manual Steps |
|---|---|---|
| **Unknown / custom functions** | `F.expr('FunctionName(args)')`  + warning logged | Implement equivalent PySpark UDF or SQL function |
| **Complex multi-row formulas** | Window function emitted; window spec may be incorrect | Verify `PARTITION BY` / `ORDER BY` in generated window spec |
| **String interpolation in expressions** | Translated literally; dynamic field names not supported | Refactor to explicit column references |

### Output Targets

| Scenario | Generated Output | Manual Steps |
|---|---|---|
| **Excel output (`.xlsx`)** | `# TODO: manual conversion required` | Use `pandas` `.to_excel()` with Databricks file download, or export as CSV |
| **Local / UNC output paths** | `# WARNING: local/network path detected` | Change output path to DBFS (`/dbfs/...`) or Unity Catalog Volume (`/Volumes/...`) |
| **Database / ODBC output** | Basic `df.write` with warning | Configure JDBC sink or Delta table as replacement |

### Tools with Typed IR but No Code Generation

These tools have dedicated converters that extract configuration into typed IR nodes, but generate `# TODO` placeholders because they require manual reimplementation:

| Category | Tools (count) | Recommended Databricks Alternative |
|---|---|---|
| **Predictive** (1 generic converter handling ~35 types) | Linear Regression, Decision Tree, Random Forest, Logistic Regression, K-Means, Neural Network, etc. | MLflow + scikit-learn / Spark MLlib |
| **Spatial** (9) | Spatial Match, Make Points, Buffer, Distance, Trade Area, etc. | Apache Sedona / Mosaic / H3 |

### Tools Not Yet Supported

| Alteryx Tool | Status | Recommended Databricks Alternative |
|---|---|---|
| **Reporting / Layout tools** (Report Header, Table, etc.) | Not converted | Use Databricks AI/BI dashboards |
| **Publish to Tableau Server** | Converter exists; emits passthrough | Use Databricks Partner Connect (Tableau) |
| **Salesforce Connector** | Not converted | Use `databricks-sdk` + Salesforce REST API or Fivetran |
| **Snowflake Connector** | Not converted | Use Databricks native Snowflake connector |
| **PowerBI Connector** | Not converted | Use Power BI Databricks connector (partner integration) |
| **Google connectors** (Analytics, BigQuery, Sheets) | Not converted | Use Databricks Partner Connect or direct SDK |
| **Email tools** | Not converted | Use Lakeflow Jobs notification actions |
| **R Tool** | Not converted | Rewrite in Python / PySpark |

---

## Expression Function Mapping

See [expression-reference.md](expression-reference.md) for the full list of 141 supported Alteryx formula functions and their PySpark/SQL equivalents.

---

## Confidence Scores

### Per-Node Confidence

Each converter attaches a `conversion_confidence` score (0–1) to its IR node:

| Score | Meaning |
|---|---|
| **1.0** | Fully converted, no known issues |
| **0.8–0.9** | Converted with minor caveats (e.g. `.yxdb` format, approximated semantics) |
| **0.7** | Database connection detected — SQL preserved but source needs remapping |
| **0.5** | Expression partially translated — `# TODO` block emitted |
| **0.0** | Tool not supported — passthrough skeleton only |

### Workflow-Level Confidence

`ConfidenceScorer` computes a weighted aggregate across 5 dimensions:

| Dimension | Weight | Description |
|---|---|---|
| Tool coverage | 35% | Fraction of tools with registered converters |
| Expression fidelity | 25% | Fraction of expressions translated without fallback |
| Join completeness | 15% | Fraction of joins with fully resolved keys |
| Data type preservation | 15% | Fraction of columns with mapped Spark types |
| Generator warnings | 10% | Inverse of warning count |

The score appears in CLI output, server API responses, and HTML reports.

---

## Post-Conversion Checklist

After running `a2d convert`:

1. **Search for `# TODO`** in the generated notebook — each block describes what needs manual attention.
2. **Search for `# WARNING`** — flags local paths and network shares that are unreachable from Databricks.
3. **Search for `PLACEHOLDER`** — marks expressions or DataFrames that were not converted and will cause runtime errors if left unchanged.
4. **Replace ODBC `spark.sql()`** blocks with Unity Catalog table references (`catalog.schema.table`) or configure JDBC connections via Databricks secrets.
5. **Upload local files** referenced in `# WARNING: local/network path detected` blocks to DBFS or Unity Catalog Volumes.
6. **Test each DataFrame** with `.show(5)` or `.count()` before wiring up downstream nodes.

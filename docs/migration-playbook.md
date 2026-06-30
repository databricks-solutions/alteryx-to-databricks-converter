# Migration Playbook

A practical guide for running an Alteryx-to-Databricks migration engagement using the `a2d` tool. This playbook covers the full lifecycle from initial assessment through production deployment.

---

## Table of Contents

1. [Engagement Overview](#engagement-overview)
2. [Phase 1: Assessment](#phase-1-assessment)
3. [Phase 2: Priority Planning](#phase-2-priority-planning)
4. [Phase 3: Conversion](#phase-3-conversion)
5. [Phase 4: Validation](#phase-4-validation)
6. [Phase 5: Deployment](#phase-5-deployment)
7. [Tips and Common Patterns](#tips-and-common-patterns)
8. [Handling Special Cases](#handling-special-cases)
9. [Success Metrics](#success-metrics)

---

## Engagement Overview

A typical enterprise migration follows five phases:

```
  Assessment  -->  Planning  -->  Conversion  -->  Validation  -->  Deployment
    (1-2 wk)      (1 wk)        (2-8 wk)        (2-4 wk)        (1-2 wk)
```

The `a2d` tool accelerates the Conversion phase by automating 60-80% of the mechanical translation work. The remaining effort goes into manual review, connection remapping, and validation.

### Team Roles

| Role | Responsibility |
|------|---------------|
| Migration Lead | Overall coordination, stakeholder communication, wave planning |
| Data Engineer | Run conversions, review generated code, handle manual items |
| Alteryx SME | Explain business logic, validate correctness, identify edge cases |
| Databricks Admin | Set up workspaces, clusters, Unity Catalog, Lakeflow Jobs |
| QA Engineer | Design validation tests, compare output datasets |

---

## Phase 1: Assessment

**Goal**: Understand the scope, identify risks, and produce a migration readiness report.

### Step 1.1: Collect All Workflows

Gather all `.yxmd` files from the Alteryx Server or shared drives. Organize them by department or business unit:

```bash
# Example directory structure
migration_assessment/
  finance/
    monthly_close.yxmd
    revenue_forecast.yxmd
    ...
  operations/
    supply_chain_report.yxmd
    inventory_reconciliation.yxmd
    ...
  marketing/
    campaign_analytics.yxmd
    ...
```

### Step 1.2: Run Batch Analysis

```bash
# Standard analysis
a2d analyze migration_assessment/ -o assessment_report/ --format both

# With complexity breakdown
a2d analyze migration_assessment/ -o assessment_report/ --format both --complexity
```

This produces:
- `assessment_report/migration_report.html` -- visual dashboard with confidence scores and enriched warnings
- `assessment_report/migration_report.json` -- machine-readable data with per-workflow metrics

### Step 1.3: Review the Report

The report includes for each workflow:

| Metric | What It Tells You |
|--------|-------------------|
| **Complexity Score** (0-100) | How hard the workflow is to migrate (7 weighted dimensions: nodes, diversity, expressions, unsupported ratio, macros, DAG depth, spatial tools) |
| **Complexity Level** | Low / Medium / High / Very High |
| **Coverage %** | Percentage of tool types that have automated converters |
| **Unsupported Tools** | List of tools that need manual conversion |
| **Expression Count** | Number of formula/filter expressions (proxy for business logic density) |
| **Macro References** | External macros that need separate treatment |

### Step 1.4: Effort Estimation (Optional)

For large estates (50+ workflows), use batch analysis with complexity breakdowns for effort estimation and wave grouping:

```bash
# Analyze entire estate with per-workflow complexity breakdown
a2d analyze migration_assessment/ -o portfolio_report/ --format both --complexity
```

Use the complexity scores and coverage percentages from the report to group workflows into migration phases (Quick Wins, Core Business, Complex, Manual) and estimate effort per workflow (Low=2h, Medium=8h, High=16h, Very High=40h).

### Step 1.5: Identify Blockers

Flag workflows that contain:
- **Spatial tools**: Need geospatial library (Sedona, H3) or alternative architecture
- **Predictive/ML tools**: Need reimplementation in MLflow/Spark MLlib
- **Heavy macro usage**: Each macro is effectively a separate workflow
- **In-database tools**: Need connection mapping and potentially different patterns
- **Reporting tools**: Need Databricks dashboards or alternative reporting

### Step 1.6: Estimate Effort

Use this rough sizing model:

| Complexity Level | Automated % | Manual Hours per Workflow | Validation Hours |
|-----------------|-------------|--------------------------|-----------------|
| Low (0-25) | 80-95% | 2-4 hours | 1-2 hours |
| Medium (25-50) | 60-80% | 4-8 hours | 2-4 hours |
| High (50-75) | 40-60% | 8-16 hours | 4-8 hours |
| Very High (75-100) | 20-40% | 16-40 hours | 8-16 hours |

---

## Phase 2: Priority Planning

**Goal**: Order workflows into migration waves based on business value, complexity, and dependencies.

### Step 2.1: Scoring Matrix

Create a prioritization spreadsheet:

| Workflow | Department | Complexity | Coverage | Business Value | Schedule Freq | Wave |
|----------|-----------|-----------|----------|---------------|--------------|------|
| monthly_close.yxmd | Finance | Medium (38) | 92% | Critical | Monthly | 2 |
| campaign_analytics.yxmd | Marketing | Low (18) | 100% | Nice-to-have | Ad-hoc | 3 |
| supply_chain_report.yxmd | Operations | High (62) | 75% | High | Daily | 1 |

### Step 2.2: Wave Strategy

**Wave 1 -- Quick Wins** (weeks 1-2):
- Low complexity, high coverage workflows
- Proves the pipeline and builds team confidence
- Target: 10-20 workflows

**Wave 2 -- Core Business** (weeks 3-6):
- Medium complexity, business-critical workflows
- Requires Alteryx SME involvement for logic validation
- Target: 20-50 workflows

**Wave 3 -- Complex & Edge Cases** (weeks 7-10):
- High complexity, macro-heavy, or partially unsupported workflows
- May require architectural redesign (not just 1:1 translation)
- Target: remaining workflows

### Step 2.3: Dependency Mapping

Manually identify workflows that share:
- Common data sources (same database connections, file paths)
- Macro libraries (shared `.yxmc` files)
- Chained scheduling (output of one is input of another)

Review the analysis report's macro references and connection details to find overlaps. Use a spreadsheet or Jira board to track cross-workflow dependencies. Group dependent workflows into the same wave.

---

## Phase 3: Conversion

**Goal**: Convert each workflow and produce review-ready Databricks code.

### Step 3.1: Run the Converter

`a2d convert` emits all four formats by default (PySpark, Spark Declarative Pipelines a.k.a. DLT, SQL, Lakeflow Designer) into per-format subdirectories of `--output-dir`. Use `-f` to restrict to a subset.

```bash
# Single workflow — produces output/finance/{pyspark,dlt,sql,lakeflow}/
a2d convert finance/monthly_close.yxmd -o output/finance/

# Restrict to one or more formats
a2d convert finance/monthly_close.yxmd -o output/finance/ -f pyspark
a2d convert finance/monthly_close.yxmd -o output/finance/ -f pyspark,sql

# With Unity Catalog + connection mapping (still all 4 formats unless filtered)
a2d convert wave1/ -o output/wave1/ \
  --catalog prod_catalog --schema finance \
  --connection-map connections.yml

# Target a specific cloud for the auto-generated node_type_id in Workflow JSON / DAB
# (default: aws → i3.xlarge; azure → Standard_DS3_v2; gcp → n1-highmem-4)
a2d convert wave1/ -o output/wave1/ --cloud azure

# With all observability features
a2d convert wave1/ -o output/wave1/ \
  --expression-audit \
  --performance-hints \
  --generate-ddl \
  --generate-dab
```

### Step 3.2: Review Generated Code

The converter produces (depending on format):
- `{workflow_name}.py` -- PySpark notebook, `_dlt.py`, or `.sql` script
- `{workflow_name}_workflow.json` -- Databricks Workflow definition (strict JSON, no `//` headers)
- `{workflow_name}_workflow.README.md` -- operator notes for fields a2d intentionally omits (e.g. `run_as`, `webhook_notifications`)
- `{workflow_name}_lakeflow_pipeline.json` -- Lakeflow pipeline config (if `-f lakeflow`)
- `{workflow_name}_ddl.sql` -- Unity Catalog DDL (if `--generate-ddl`); non-Delta external tables emit `CREATE TABLE ... AS SELECT * FROM read_files(...)` so the result is a Delta-managed table over the foreign format
- `{workflow_name}_dab/` -- Databricks Asset Bundle project (if `--generate-dab`)
- `expression_audit.csv` -- Expression translation audit (if `--expression-audit`)

Review each generated file for:

1. **TODO comments**: These indicate unsupported tools or expressions that need manual implementation
2. **Warnings**: Printed during conversion and embedded as comments
3. **Connection mappings**: Replace Alteryx file paths/ODBC connections with Databricks-native sources
4. **Expression accuracy**: Verify translated formulas match business intent

The CLI also prints (mirroring the web UI's Convert page):

- A **deploy-readiness banner**: `Ready to deploy` (clean) / `Needs review` (warnings non-blocking) / `Cannot deploy as-is` (blockers present)
- A **counts row**: coverage %, confidence /100, tools converted, nodes needing review, blocker count
- Warnings **grouped by category** rather than dumped flat:
  - `Cannot convert` — unsupported tools, missing generators (blockers)
  - `Manual review needed` — expression fallbacks, local paths, dynamic-rename caveats, joins missing keys
  - `Graph structure note` — disconnected components, etc.
  - `Other` — anything that didn't match the 7 known templates

The same status logic powers the API response — `response.deploy_status` and the per-format `categorized_warnings` field — so the CLI and UI agree.

### Step 3.3: Handle Manual Items

For each `# TODO` or `# UNSUPPORTED` block in the generated code:

| Item Type | Resolution |
|-----------|-----------|
| Unsupported tool (spatial, reporting, etc.) | Implement equivalent Databricks logic; consult the Alteryx SME |
| Expression fallback (`F.expr(...)`) | The expression engine could not fully translate; verify the fallback SQL expression works |
| Connection string | Replace with `spark.table("catalog.schema.table")` or `spark.read.format("delta").load("path")` |
| Macro reference | Convert the macro separately, then inline or call as a reusable function |
| Python Tool passthrough | Review the original Python code and adapt to PySpark/pandas API |
| Download Tool | Replace with `requests` UDF or Databricks external access |

### Step 3.4: Apply Connection Mappings

Create a connection mapping document:

| Alteryx Connection | Databricks Equivalent |
|-------------------|----------------------|
| `ODBC:SQL Server:Production` | `prod_catalog.dbo.table_name` |
| `\\\\server\\share\\data.csv` | `/Volumes/prod_catalog/raw/data.csv` |
| `C:\\Users\\analyst\\data.xlsx` | `/Volumes/prod_catalog/uploads/data.xlsx` |
| `https://api.example.com/data` | External access via Unity Catalog connection |

Apply these mappings to the generated code, replacing `UNKNOWN_PATH` and hardcoded file paths.

---

## Phase 4: Validation

**Goal**: Confirm that the migrated code produces identical results to the original Alteryx workflow.

### Step 4.1: Prepare Test Data

For each workflow:
1. Run the original Alteryx workflow on a known dataset
2. Save the Alteryx output as CSV or Parquet
3. Upload to Databricks (DBFS or Unity Catalog Volume)

### Step 4.2: Run Generated Code

Upload the generated notebook to Databricks and run it:

```bash
# Validate syntax first
a2d validate output/monthly_close.py

# Then execute in Databricks
# (upload via workspace UI, Repos, or REST API)
```

### Step 4.3: Compare Outputs

Compare the Databricks output with the Alteryx baseline:

```python
# In a Databricks notebook
import datacompy

alteryx_df = spark.read.format("csv").option("header", "true").load("/baseline/alteryx_output.csv")
databricks_df = df_final  # the last DataFrame from the migrated workflow

compare = datacompy.SparkCompare(spark, alteryx_df, databricks_df, join_columns=["key_column"])
compare.report()
```

Key checks:
- **Row count match**: Same number of rows
- **Column match**: Same columns present (accounting for renames)
- **Value match**: Values match within tolerance (especially for floating-point)
- **NULL handling**: NULLs in the same places

### Step 4.4: Document Differences

Some differences are expected:
- **Floating-point precision**: Spark uses IEEE 754 doubles; Alteryx may use different precision
- **Sort order**: Ties may sort differently
- **NULL behavior**: Spark NULLs propagate differently in some edge cases
- **Record IDs**: `monotonically_increasing_id` produces different values than Alteryx RecordID

Document these as accepted differences vs. actual bugs.

### Step 4.5: Sign-Off

Get sign-off from the Alteryx SME and business owner for each workflow:

| Workflow | Test Status | Differences | Sign-Off |
|----------|-----------|-------------|----------|
| monthly_close | Pass | Float precision (< 0.01) | Approved |
| supply_chain_report | Pass with notes | 2 rows with NULL handling | Approved with workaround |

---

## Phase 5: Deployment

**Goal**: Put the migrated workflows into production on Databricks.

### Step 5.1: Set Up Databricks Environment

- **Unity Catalog**: Create catalogs, schemas, and tables for the migrated workflows
- **Volumes**: Create Volumes for file-based data sources
- **Secrets**: Set up Databricks secret scopes for credentials
- **Clusters**: Configure job clusters with appropriate sizing

### Step 5.2: Deploy Notebooks

Options for deploying generated code:

| Method | Best For |
|--------|---------|
| Databricks Repos (Git) | Teams using Git workflow; version control |
| Workspace folders | Quick deployment; ad-hoc workflows |
| Databricks Asset Bundles | Infrastructure-as-code; CI/CD pipelines |
| REST API upload | Automated deployment scripts |

### Step 5.3: Import Workflow JSON

The generated `_workflow.json` can be imported via:

```bash
# Using Databricks CLI (v0.205+, unified CLI)
databricks jobs create --json @output/monthly_close_workflow.json

# Or via REST API (Jobs 2.2)
curl -X POST "https://<workspace>/api/2.2/jobs/create" \
  -H "Authorization: Bearer <token>" \
  -d @output/monthly_close_workflow.json
```

Review and adjust:
- **Cluster configuration**: Match to your workspace's available instance types
- **Schedule**: Set the cron schedule to match the original Alteryx Server schedule
- **Notifications**: Configure email/Slack alerts for failures

### Step 5.4: Spark Declarative Pipelines / Lakeflow Pipeline Setup

**For Spark Declarative Pipelines format** (`-f dlt`, file `_dlt.py`):
1. Create a new Lakeflow pipeline in the Databricks UI (Workflows → Pipelines)
2. Point it to the generated `_dlt.py` notebook
3. Configure target catalog and schema
4. Set pipeline mode (Triggered or Continuous)
5. Add data quality expectations if needed

> Generated code uses `import dlt` and `@dlt.table` — these still run on
> current DBR. For new pipelines, Databricks recommends the
> `from pyspark import pipelines as dp` API; the generated code remains
> compatible until `pyspark.pipelines` is GA on all supported DBR LTS releases.

**For Lakeflow format** (`-f lakeflow`):
1. Import the `_lakeflow_pipeline.json` via the Databricks REST API or CLI
2. The pipeline config includes catalog, target schema, and cluster settings
3. Each file source becomes a `STREAMING TABLE`; each transformation becomes a `MATERIALIZED VIEW`
4. Upstream references use the `LIVE.` prefix (legacy publishing mode). In
   default publishing mode (mandatory for new pipelines created via the UI
   since 2025-02-05), `LIVE.` is silently ignored and table refs resolve
   against the pipeline catalog/schema — the generated SQL works in both
   modes.

### Step 5.5: Track Progress

Use a spreadsheet, Jira board, or other project management tool to maintain per-workflow migration status.

Recommended status lifecycle: `not_started` -> `in_progress` -> `converted` -> `validated` -> `deployed`.

### Step 5.6: Parallel Run

Run the Databricks workflow in parallel with the original Alteryx workflow for 1-2 cycles:
- Compare outputs after each run
- Monitor for performance differences
- Verify scheduling works correctly

### Step 5.7: Cutover

Once parallel runs are validated:
1. Disable the Alteryx Server schedule
2. Enable the Databricks Workflow schedule
3. Update downstream consumers to read from the new location
4. Monitor for the first 2-3 scheduled runs

---

## Tips and Common Patterns

### Connection Mapping

Use `a2d`'s built-in connection mapping feature to apply centralized mappings across all workflows. Create a YAML file (see `examples/connection_mapping.yml`):

```yaml
connections:
  "ODBC:SQL_Server_Prod":
    type: "table"
    target: "prod_catalog.source_db.{table_name}"
  "\\\\fileserver\\data\\":
    type: "volume"
    target: "/Volumes/prod_catalog/raw_data/"
  "C:\\Data\\":
    type: "volume"
    target: "/Volumes/prod_catalog/local_uploads/"
```

Apply during conversion:

```bash
a2d convert wave1/ -o output/ --connection-map connections.yml
```

The Web UI also includes a visual connection mapping editor under Settings.

### Handling Macros

Alteryx macros (`.yxmc` files) are effectively reusable sub-workflows. Strategies:

| Macro Type | Strategy |
|-----------|---------|
| **Standard macro** | Convert to a Python function that takes and returns DataFrames |
| **Batch macro** | Convert to a function called in a loop or `foreach` pattern |
| **Iterative macro** | Convert to a `while` loop with explicit convergence check |
| **Community macros** | Find the equivalent Spark/Python library |

### Dealing with Spatial Tools

Spatial tools (Buffer, SpatialMatch, Distance, etc.) have no direct Spark equivalent. Options:

1. **Apache Sedona**: Full geospatial support for Spark (`pip install apache-sedona`)
2. **H3**: Uber's hierarchical geospatial indexing (good for proximity/aggregation)
3. **Mosaic**: Databricks Labs geospatial project (community-supported)
4. **PostGIS**: Run spatial operations in a database and read results into Spark

### Handling Large Workflows

For workflows with 50+ tools:

1. Consider breaking into smaller, modular notebooks
2. Use the Spark Declarative Pipelines format for built-in dependency management
3. Use the Workflow JSON to create multi-task jobs

### Expression Debugging

If a translated expression produces wrong results:

```python
# Compare Alteryx vs PySpark expression on sample data
alteryx_expr = "[Amount] * 0.13 + IF [Status] = 'Active' THEN 10 ELSE 0 ENDIF"

# Test in a Databricks notebook
from a2d.expressions.translator import PySparkTranslator
translator = PySparkTranslator()
pyspark_code = translator.translate_string(alteryx_expr)
print(pyspark_code)
# -> (F.col("Amount") * 0.13) + F.when(...).otherwise(...)
```

---

## Handling Special Cases

### Workflows with Multiple Outputs

Alteryx workflows can have multiple Output tools. The generated code produces separate DataFrames for each output. Map them to separate tables or files in Databricks.

### Workflows Using Alteryx Gallery/Server APIs

Replace Gallery API calls with Databricks REST API equivalents:
- **Schedule triggers** -> Lakeflow Jobs triggers
- **API endpoints** -> Databricks SQL Warehouse or REST API
- **Shared credentials** -> Databricks secret scopes

### Workflows with Email Output

Replace Alteryx EmailOutput with:
- Databricks notification destinations (email, Slack, webhook)
- Custom Python email via `smtplib` in a notebook cell
- Azure Logic Apps or AWS SNS for cloud-native notifications

### Performance-Sensitive Workflows

If the Alteryx workflow was optimized for in-memory processing:
1. Use `.cache()` or `.persist()` for DataFrames reused multiple times
2. Consider `broadcast` joins for small lookup tables
3. Tune `spark.sql.shuffle.partitions` for the data volume
4. Use Delta Lake Z-ordering for frequently filtered columns

---

## Success Metrics

Track these metrics across the migration:

| Metric | Target |
|--------|--------|
| **Workflows converted** | 100% of in-scope workflows |
| **Automated conversion rate** | 60-80% of code lines generated automatically |
| **Validation pass rate** | 95%+ workflows pass output comparison |
| **Average conversion time** | < 4 hours per Low complexity workflow |
| **Production incidents post-migration** | < 5% of workflows need fixes in first month |
| **Schedule adherence** | All critical workflows run on time in first week |
| **Cost savings** | Reduction in Alteryx license + Server costs |

### Reporting Template

Track per-workflow status in a table:

| Workflow | Wave | Status | Converter Coverage | Manual Items | Validation | Production |
|----------|------|--------|-------------------|--------------|-----------|-----------|
| monthly_close | 2 | Deployed | 92% | 2 items | Passed | Live |
| supply_chain | 1 | Validating | 75% | 5 items | In progress | -- |
| campaign_analytics | 3 | Queued | 100% | 0 items | -- | -- |

# Databricks notebook source
# MAGIC %md
# MAGIC # Alteryx → Databricks Migration Snippet Library — Unity Catalog Workspace
# MAGIC
# MAGIC This notebook contains copy-paste-ready code snippets for the patterns that the
# MAGIC **Alteryx-to-Databricks Migration Accelerator** tool cannot convert automatically,
# MAGIC written for **Unity Catalog (UC) enabled** Databricks workspaces.
# MAGIC
# MAGIC **Use this notebook if:** your workspace has Unity Catalog enabled (you can run
# MAGIC `spark.sql("SHOW CATALOGS")` and see catalogs beyond `hive_metastore`).
# MAGIC For non-UC workspaces, use `alteryx_migration_snippets_non_uc.py` instead.
# MAGIC
# MAGIC Each section corresponds to a `# TODO` or `# WARNING` comment in the generated notebook.
# MAGIC Find the matching section, copy the relevant cell, and adapt names to your environment.
# MAGIC
# MAGIC **Sections:**
# MAGIC 1. Data Source Connections (`aka:`, ODBC, DSN → UC tables / JDBC)
# MAGIC 2. File I/O — Unity Catalog Volumes (replaces UNC/Windows paths)
# MAGIC 3. Excel Files (read and write via UC Volumes)
# MAGIC 4. DynamicInput — Parameterized SQL per Row
# MAGIC 5. Stored Procedures (PostSQL blocks)
# MAGIC 6. Date & Type Coercion
# MAGIC 7. HTTP / DownloadTool
# MAGIC 8. RunCommand → Shell
# MAGIC 9. Iterative Macros → Python Loops
# MAGIC 10. Two-Part SQL Table Names → UC Three-Part Names

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1 — Data Source Connections
# MAGIC
# MAGIC **Converter flag:** `# TODO: map to Unity Catalog` on Input tool steps
# MAGIC
# MAGIC Alteryx uses named connections (`aka:UUID|||schema.table`), ODBC DSNs, and connection
# MAGIC strings that are not accessible in Databricks. Replace with one of the patterns below.
# MAGIC
# MAGIC **UC table names use three parts: `catalog.schema.table`**

# COMMAND ----------

# 1a. UC managed or external table (most common — use this first)
# If the source table has already been onboarded to Unity Catalog / Rahona:
df = spark.table("catalog_name.schema_name.table_name")

# 1b. Inline SQL query against a UC table
df = spark.sql("""
    SELECT *
    FROM catalog_name.schema_name.table_name
    WHERE date_col >= '2024-01-01'
""")

# COMMAND ----------

# 1c. JDBC — source is still in an on-prem/cloud database (not yet in UC)
# Requires: JDBC driver on cluster + network access + Databricks secret scope for credentials.
jdbc_url = "jdbc:sqlserver://hostname:1433;databaseName=your_db"
conn_props = {
    "user": dbutils.secrets.get(scope="your-scope", key="db-user"),
    "password": dbutils.secrets.get(scope="your-scope", key="db-password"),
    "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
}
df = spark.read.jdbc(url=jdbc_url, table="schema_name.table_name", properties=conn_props)

# Filtered read (avoids full table scan):
df = spark.read.jdbc(
    url=jdbc_url,
    table="(SELECT * FROM schema_name.table_name WHERE year_col = 2024) AS t",
    properties=conn_props,
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 2 — File I/O: Unity Catalog Volumes
# MAGIC
# MAGIC **Converter flag:** `# WARNING: local/network path detected` / `# TODO: /Volumes/...`
# MAGIC
# MAGIC UNC paths (`\\server\share\...`) and Windows paths (`C:\Users\...`) are not accessible
# MAGIC from Databricks. Upload files to a **Unity Catalog Volume** first, then use the Volume path.
# MAGIC
# MAGIC **Path mapping:**
# MAGIC ```
# MAGIC \\nasoc01\share\dept\reports\file.csv  →  /Volumes/catalog/schema/volume/reports/file.csv
# MAGIC C:\Users\analyst\data\input.xlsx       →  /Volumes/catalog/schema/volume/input.xlsx
# MAGIC ```
# MAGIC
# MAGIC Upload files via: Catalog Explorer → Volumes → your volume → Upload to this Volume

# COMMAND ----------

# 2a. Read CSV from UC Volume
df = (spark.read
    .format("csv")
    .option("header", "true")
    .option("inferSchema", "true")
    .load("/Volumes/catalog/schema/volume/filename.csv"))

# Read multiple CSVs matching a pattern:
df = (spark.read
    .format("csv")
    .option("header", "true")
    .option("inferSchema", "true")
    .load("/Volumes/catalog/schema/volume/reports/*.csv"))

# COMMAND ----------

# 2b. Read Parquet from UC Volume
df = spark.read.parquet("/Volumes/catalog/schema/volume/filename.parquet")

# COMMAND ----------

# 2c. Write CSV to UC Volume (single file output)
(df.coalesce(1)
    .write
    .format("csv")
    .option("header", "true")
    .mode("overwrite")
    .save("/Volumes/catalog/schema/volume/output/"))

# COMMAND ----------

# 2d. Write as Delta table — recommended over CSV/Parquet for analytical workloads
# Overwrite:
df.write.format("delta").mode("overwrite").saveAsTable("catalog.schema.table_name")

# Append:
df.write.format("delta").mode("append").saveAsTable("catalog.schema.table_name")

# Append with schema evolution (safe when adding new columns):
(df.write
    .format("delta")
    .mode("append")
    .option("mergeSchema", "true")
    .saveAsTable("catalog.schema.table_name"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3 — Excel Files
# MAGIC
# MAGIC **Converter flag:** `# TODO: Excel write not supported natively in Databricks`
# MAGIC
# MAGIC Databricks does not have a built-in Excel reader/writer. Use pandas for small files
# MAGIC (the pandas path `/Volumes/...` works directly on the driver node in UC workspaces)
# MAGIC or `com.crealytics.spark.excel` for large files (requires cluster library install).

# COMMAND ----------

# 3a. Read Excel from UC Volume via pandas
import pandas as pd

pdf = pd.read_excel(
    "/Volumes/catalog/schema/volume/file.xlsx",
    sheet_name="Sheet1",   # or sheet index 0
    dtype=str,             # read all as string first, then cast types in Spark
)
df = spark.createDataFrame(pdf)

# COMMAND ----------

# 3b. Write Excel to UC Volume via pandas (small DataFrames only — collects to driver)
pdf = df.toPandas()
pdf.to_excel(
    "/Volumes/catalog/schema/volume/output.xlsx",
    sheet_name="Data",
    index=False,
)

# COMMAND ----------

# 3c. Read/write Excel with com.crealytics library (large files — requires cluster install)
# Maven: com.crealytics:spark-excel_2.12:3.4.1_0.20.3

# Read:
df = (spark.read
    .format("com.crealytics.spark.excel")
    .option("header", "true")
    .option("inferSchema", "true")
    .option("dataAddress", "'Sheet1'!A1")
    .load("/Volumes/catalog/schema/volume/file.xlsx"))

# Write:
(df.write
    .format("com.crealytics.spark.excel")
    .option("header", "true")
    .option("dataAddress", "'Data'!A1")
    .mode("overwrite")
    .save("/Volumes/catalog/schema/volume/output.xlsx"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 4 — DynamicInput (ModifySQL)
# MAGIC
# MAGIC **Converter flag:** `# TODO: DynamicInput (ModifySQL) cannot be represented as static SQL`
# MAGIC
# MAGIC DynamicInput in ModifySQL mode executes a SQL template once per row of an input DataFrame,
# MAGIC substituting field values into the SQL at runtime. The PySpark output handles this
# MAGIC automatically — **use PySpark output for workflows containing DynamicInput**.
# MAGIC
# MAGIC In UC workspaces, update all `FROM`/`JOIN` table references to three-part UC names.

# COMMAND ----------

from pyspark.sql import functions as F
from pyspark.sql.types import StructType


def _to_iso_date(val):
    """Normalize a date value to ISO yyyy-MM-dd string for SQL substitution.

    Handles common formats produced by Alteryx DateTimeFormat:
    dd-MMM-yyyy (e.g. 08-Apr-2026), mm/dd/yyyy, yyyymmdd, ISO (pass-through).
    """
    if val is None:
        return "NULL"
    s = str(val)
    if len(s) == 10 and s[4:5] == "-" and s[7:8] == "-":
        return s  # already ISO yyyy-MM-dd
    from datetime import datetime
    for fmt in ("%d-%b-%Y", "%b-%d-%Y", "%m/%d/%Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return s  # return as-is if no format matched


# -- Adapt these to your workflow -----------------------------------------------
_sql_template = """
    SELECT *
    FROM your_catalog.schema_name.source_table     -- UC three-part name
    WHERE report_date = '2024-01-01'
      AND region = 'PLACEHOLDER_REGION'
"""

_rows = df_input.collect()
_dfs = []

for _row in _rows:
    _sql = _sql_template
    _sql = _sql.replace("2024-01-01", _to_iso_date(_row["ReportDate"]))   # date placeholder
    _sql = _sql.replace("PLACEHOLDER_REGION", str(_row["Region"]))        # string placeholder
    _dfs.append(spark.sql(_sql))

df_result = _dfs[0] if _dfs else spark.createDataFrame([], StructType([]))
for _df in _dfs[1:]:
    df_result = df_result.unionByName(_df, allowMissingColumns=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 5 — Stored Procedures (PostSQL)
# MAGIC
# MAGIC **Converter flag:** PostSQL blocks are silently skipped — no TODO is emitted.
# MAGIC Check your original Alteryx workflow for PostSQL tools and implement the equivalent.

# COMMAND ----------

# 5a. Call a stored procedure via JDBC and capture the result set
jdbc_url = "jdbc:sqlserver://hostname:1433;databaseName=your_db"
conn_props = {
    "user": dbutils.secrets.get(scope="your-scope", key="db-user"),
    "password": dbutils.secrets.get(scope="your-scope", key="db-password"),
    "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
}
df_sp_result = spark.read.jdbc(
    url=jdbc_url,
    table="(EXEC your_schema.your_stored_procedure @param1='value', @param2=123) AS sp_result",
    properties=conn_props,
)

# COMMAND ----------

# 5b. Rewrite SP insert/update logic as Databricks SQL (preferred — native UC)
spark.sql("""
    INSERT INTO your_catalog.schema_name.target_table
    SELECT col1, col2, CURRENT_DATE() AS load_date
    FROM your_catalog.schema_name.source_table
    WHERE status = 'PENDING'
""")

# COMMAND ----------

# 5c. Rewrite SP logic as PySpark
from pyspark.sql import functions as F

df_transformed = (df_source
    .filter(F.col("status") == "PENDING")
    .withColumn("load_date", F.current_date())
    .select("col1", "col2", "load_date"))

df_transformed.write.format("delta").mode("append").saveAsTable("your_catalog.schema_name.target_table")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 6 — Date & Type Coercion
# MAGIC
# MAGIC **Converter flag:** Type mismatches in `IF/THEN` expressions involving DateType columns.
# MAGIC These require manual fixes — the converter cannot resolve them without schema information.

# COMMAND ----------

from pyspark.sql import functions as F

# 6a. "Is today?" — DateType column vs formatted string (converter output is always false)
#
# BEFORE (wrong — string vs DateType comparison):
#   F.when(F.date_format(F.current_timestamp(), "yyyy-MM-dd") == F.col("DateType"), ...)
#
# AFTER — compare DateType to DateType directly:
df = df.withColumn(
    "DateCheck",
    F.when(F.current_date() == F.col("DateType"), F.col("DateType"))
     .otherwise(F.lit(None).cast("date"))
)

# COMMAND ----------

# 6b. String sentinel "0" in ELSE of a DateType WHEN (type mismatch)
#
# BEFORE: F.when(condition, F.col("DateType")).otherwise(F.lit("0"))
#
# Option A — null as sentinel (cleanest):
df = df.withColumn(
    "DateCheck",
    F.when(F.current_date() == F.col("DateType"), F.col("DateType"))
     .otherwise(F.lit(None).cast("date"))
)

# Option B — keep "0" sentinel by casting the DateType branch to string:
df = df.withColumn(
    "DateCheck",
    F.when(F.current_date() == F.col("DateType"), F.col("DateType").cast("string"))
     .otherwise(F.lit("0"))
)

# COMMAND ----------

# 6c. DateTimeNow() — timestamp vs date
# Alteryx DateTimeNow() → F.current_timestamp() (TimestampType).
# Use F.current_date() when only the date is needed:
df = df.withColumn("today", F.current_date())                                     # DateType
df = df.withColumn("now_ts", F.current_timestamp())                               # TimestampType
df = df.withColumn("today_str", F.date_format(F.current_date(), "yyyy-MM-dd"))   # StringType

# COMMAND ----------

# 6d. Concatenating a DateType column with strings
# DateType must be cast to string before F.concat():
df = df.withColumn(
    "FilePath",
    F.concat(
        F.lit("/Volumes/catalog/schema/volume/report_"),
        F.date_format(F.col("DateType"), "yyyyMMdd"),   # → "20240408"
        F.lit(".csv")
    )
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 7 — HTTP Requests (DownloadTool)
# MAGIC
# MAGIC **Converter flag:** `# TODO: Replace with requests/urllib UDF or Databricks external access`
# MAGIC
# MAGIC Requires: External network access allowlisted for the target host in your UC workspace.
# MAGIC In UC workspaces this is configured via **Network Policies** — contact your workspace admin.

# COMMAND ----------

import requests
import pandas as pd
from pyspark.sql.functions import pandas_udf
from pyspark.sql import functions as F


@pandas_udf("string")
def fetch_url(urls: pd.Series) -> pd.Series:
    """Fetch the HTTP response body for each URL. Returns an error string on failure."""
    def get(url):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            return f"ERROR: {exc}"
    return urls.apply(get)


df_with_response = df.withColumn("response_body", fetch_url(F.col("url_column")))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 8 — Shell Commands (RunCommand)
# MAGIC
# MAGIC **Converter flag:** `# TODO: Replace with subprocess or %sh magic in Databricks`

# COMMAND ----------

# Option 1: %sh magic — interactive notebooks only (not in Jobs)
# %sh
# cp /Volumes/catalog/schema/volume/input.csv /tmp/staging/input.csv

# Option 2: subprocess — works in Jobs too
import subprocess

result = subprocess.run(
    ["cp", "/Volumes/catalog/schema/volume/input.csv", "/tmp/staging/input.csv"],
    capture_output=True,
    text=True,
)
if result.returncode != 0:
    raise RuntimeError(f"Shell command failed:\n{result.stderr}")

# Option 3: dbutils.fs for Volume/DBFS file operations
dbutils.fs.cp(
    "dbfs:/Volumes/catalog/schema/volume/input.csv",
    "dbfs:/tmp/staging/input.csv",
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 9 — Iterative Macros → Python Loops
# MAGIC
# MAGIC **Converter flag:** Iterative macros are unsupported — no code is generated.
# MAGIC Implement the loop logic manually using a Python `for`/`while` loop.

# COMMAND ----------

from pyspark.sql import functions as F

max_iterations = 100
df_current = df_seed  # adapt to your starting DataFrame

for iteration in range(max_iterations):
    df_next = (df_current
        .withColumn("status", F.when(F.col("value") > 100, F.lit("DONE")).otherwise(F.col("status")))
        .withColumn("value", F.col("value") * 1.1)
    )
    if df_next.filter(F.col("status") != "DONE").count() == 0:
        print(f"Converged after {iteration + 1} iterations")
        break
    df_current = df_next
else:
    print(f"Warning: reached max_iterations ({max_iterations}) without converging")

df_result = df_current

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 10 — Two-Part SQL Table Names → UC Three-Part Names
# MAGIC
# MAGIC **Converter flag:** DynamicInput SQL templates use two-part names (`SCHEMA.TABLE`)
# MAGIC which fail in Unity Catalog — three-part names are required (`CATALOG.SCHEMA.TABLE`).
# MAGIC
# MAGIC Update all `FROM` and `JOIN` table references in the generated SQL template strings.

# COMMAND ----------

# Pattern:
#   BEFORE: FROM RRDW_DLV.V_DLV_DEP_AGMT A
#   AFTER:  FROM your_catalog.RRDW_DLV.V_DLV_DEP_AGMT A

# Discover available catalogs:
spark.sql("SHOW CATALOGS").show()

# Find a table in a known schema:
spark.sql("SHOW TABLES IN RRDW_DLV").show()

# Inspect a specific table:
spark.sql("DESCRIBE TABLE EXTENDED your_catalog.RRDW_DLV.V_DLV_DEP_AGMT").show(truncate=False)

# Quick access check:
spark.table("your_catalog.RRDW_DLV.V_DLV_DEP_AGMT").limit(1).display()

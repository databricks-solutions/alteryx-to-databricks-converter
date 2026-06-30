# Databricks notebook source
# MAGIC %md
# MAGIC # Alteryx → Databricks Migration Snippet Library — Non-UC Workspace
# MAGIC
# MAGIC This notebook contains copy-paste-ready code snippets for the patterns that the
# MAGIC **Alteryx-to-Databricks Migration Accelerator** tool cannot convert automatically,
# MAGIC written for **non-Unity Catalog** Databricks workspaces (Hive Metastore + DBFS).
# MAGIC
# MAGIC **Use this notebook if:** your workspace does NOT have Unity Catalog enabled — tables live
# MAGIC in `hive_metastore` and files are stored on DBFS or mounted network shares.
# MAGIC For UC-enabled workspaces, use `alteryx_migration_snippets_uc.py` instead.
# MAGIC
# MAGIC Each section corresponds to a `# TODO` or `# WARNING` comment in the generated notebook.
# MAGIC Find the matching section, copy the relevant cell, and adapt names to your environment.
# MAGIC
# MAGIC **Sections:**
# MAGIC 1. Data Source Connections (`aka:`, ODBC, DSN → Hive tables / JDBC)
# MAGIC 2. File I/O — DBFS Mounts (replaces UNC/Windows paths)
# MAGIC 3. Excel Files (read and write via DBFS)
# MAGIC 4. DynamicInput — Parameterized SQL per Row
# MAGIC 5. Stored Procedures (PostSQL blocks)
# MAGIC 6. Date & Type Coercion
# MAGIC 7. HTTP / DownloadTool
# MAGIC 8. RunCommand → Shell
# MAGIC 9. Iterative Macros → Python Loops
# MAGIC 10. Two-Part SQL Table Names in DynamicInput Templates

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 1 — Data Source Connections
# MAGIC
# MAGIC **Converter flag:** `# TODO: map to Unity Catalog` on Input tool steps
# MAGIC
# MAGIC In non-UC workspaces, tables live in `hive_metastore`. Use two-part names (`schema.table`)
# MAGIC or the explicit three-part form `hive_metastore.schema.table`.

# COMMAND ----------

# 1a. Hive Metastore table (most common in non-UC workspaces)
df = spark.table("schema_name.table_name")

# Explicit three-part form (equivalent — useful when mixing catalogs):
df = spark.table("hive_metastore.schema_name.table_name")

# 1b. Inline SQL query against a Hive table
df = spark.sql("""
    SELECT *
    FROM schema_name.table_name
    WHERE date_col >= '2024-01-01'
""")

# COMMAND ----------

# 1c. JDBC — source is still in an on-prem/cloud database
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
# MAGIC ## Section 2 — File I/O: DBFS Mounts
# MAGIC
# MAGIC **Converter flag:** `# WARNING: local/network path detected` / `# TODO: /Volumes/...`
# MAGIC
# MAGIC UNC paths (`\\server\share\...`) and Windows paths (`C:\Users\...`) are not accessible
# MAGIC from Databricks. In non-UC workspaces, mount the network share to DBFS and use the
# MAGIC mount path instead.
# MAGIC
# MAGIC **Path mapping:**
# MAGIC ```
# MAGIC \\nasoc01\share\dept\reports\file.csv  →  dbfs:/mnt/mountname/reports/file.csv
# MAGIC C:\Users\analyst\data\input.xlsx       →  dbfs:/mnt/mountname/input.xlsx  (upload first)
# MAGIC ```
# MAGIC
# MAGIC **Two path formats in non-UC Databricks:**
# MAGIC - `dbfs:/mnt/mountname/...` — used by Spark (spark.read, df.write)
# MAGIC - `/dbfs/mnt/mountname/...` — used by Python/pandas (local filesystem access on driver)

# COMMAND ----------

# 2a. Mount a network share or blob storage to DBFS (run once, persists across restarts)
# Example: Azure Data Lake Storage Gen2
configs = {
    "fs.azure.account.auth.type": "OAuth",
    "fs.azure.account.oauth.provider.type": "org.apache.hadoop.fs.azurebfs.oauth2.ClientCredsTokenProvider",
    "fs.azure.account.oauth2.client.id": dbutils.secrets.get(scope="your-scope", key="client-id"),
    "fs.azure.account.oauth2.client.secret": dbutils.secrets.get(scope="your-scope", key="client-secret"),
    "fs.azure.account.oauth2.client.endpoint": "https://login.microsoftonline.com/<tenant-id>/oauth2/token",
}
dbutils.fs.mount(
    source="abfss://container@storageaccount.dfs.core.windows.net/",
    mount_point="/mnt/mountname",
    extra_configs=configs,
)

# List mounted paths:
display(dbutils.fs.mounts())

# COMMAND ----------

# 2b. Read CSV from DBFS mount
df = (spark.read
    .format("csv")
    .option("header", "true")
    .option("inferSchema", "true")
    .load("dbfs:/mnt/mountname/reports/filename.csv"))

# Read multiple CSVs matching a pattern:
df = (spark.read
    .format("csv")
    .option("header", "true")
    .option("inferSchema", "true")
    .load("dbfs:/mnt/mountname/reports/*.csv"))

# COMMAND ----------

# 2c. Read Parquet from DBFS mount
df = spark.read.parquet("dbfs:/mnt/mountname/filename.parquet")

# COMMAND ----------

# 2d. Write CSV to DBFS mount (single file output)
(df.coalesce(1)
    .write
    .format("csv")
    .option("header", "true")
    .mode("overwrite")
    .save("dbfs:/mnt/mountname/output/"))

# COMMAND ----------

# 2e. Write as Delta table in Hive Metastore — recommended over CSV
# Overwrite:
df.write.format("delta").mode("overwrite").saveAsTable("schema_name.table_name")

# Append:
df.write.format("delta").mode("append").saveAsTable("schema_name.table_name")

# Append with schema evolution:
(df.write
    .format("delta")
    .mode("append")
    .option("mergeSchema", "true")
    .saveAsTable("schema_name.table_name"))

# Write to a specific DBFS path (without registering in Hive):
df.write.format("delta").mode("overwrite").save("dbfs:/mnt/mountname/delta/table_name")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 3 — Excel Files
# MAGIC
# MAGIC **Converter flag:** `# TODO: Excel write not supported natively in Databricks`
# MAGIC
# MAGIC Databricks does not have a built-in Excel reader/writer. In non-UC workspaces, pandas
# MAGIC accesses DBFS via the `/dbfs/...` local path prefix on the driver node.

# COMMAND ----------

# 3a. Read Excel from DBFS mount via pandas
# Note: use /dbfs/mnt/... (local path) for pandas, NOT dbfs:/mnt/... (Spark path)
import pandas as pd

pdf = pd.read_excel(
    "/dbfs/mnt/mountname/file.xlsx",
    sheet_name="Sheet1",   # or sheet index 0
    dtype=str,             # read all as string first, then cast types in Spark
)
df = spark.createDataFrame(pdf)

# COMMAND ----------

# 3b. Write Excel to DBFS mount via pandas (small DataFrames only — collects to driver)
pdf = df.toPandas()
pdf.to_excel(
    "/dbfs/mnt/mountname/output.xlsx",
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
    .load("dbfs:/mnt/mountname/file.xlsx"))

# Write:
(df.write
    .format("com.crealytics.spark.excel")
    .option("header", "true")
    .option("dataAddress", "'Data'!A1")
    .mode("overwrite")
    .save("dbfs:/mnt/mountname/output.xlsx"))

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
# MAGIC In non-UC workspaces, table references use two-part names (`schema.table`).

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
    FROM schema_name.source_table              -- two-part Hive Metastore name
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

# 5b. Rewrite SP insert/update logic as Spark SQL (Hive Metastore)
spark.sql("""
    INSERT INTO schema_name.target_table
    SELECT col1, col2, CURRENT_DATE() AS load_date
    FROM schema_name.source_table
    WHERE status = 'PENDING'
""")

# COMMAND ----------

# 5c. Rewrite SP logic as PySpark
from pyspark.sql import functions as F

df_transformed = (df_source
    .filter(F.col("status") == "PENDING")
    .withColumn("load_date", F.current_date())
    .select("col1", "col2", "load_date"))

df_transformed.write.format("delta").mode("append").saveAsTable("schema_name.target_table")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 6 — Date & Type Coercion
# MAGIC
# MAGIC **Converter flag:** Type mismatches in `IF/THEN` expressions involving DateType columns.
# MAGIC These require manual fixes — the converter cannot resolve them without schema information.
# MAGIC The patterns are identical between UC and non-UC workspaces.

# COMMAND ----------

from pyspark.sql import functions as F

# 6a. "Is today?" — DateType column vs formatted string (converter output is always false)
#
# BEFORE (wrong — string vs DateType):
#   F.when(F.date_format(F.current_timestamp(), "yyyy-MM-dd") == F.col("DateType"), ...)
#
# AFTER — compare DateType to DateType:
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
df = df.withColumn("today", F.current_date())                                     # DateType
df = df.withColumn("now_ts", F.current_timestamp())                               # TimestampType
df = df.withColumn("today_str", F.date_format(F.current_date(), "yyyy-MM-dd"))   # StringType

# COMMAND ----------

# 6d. Concatenating a DateType column with strings
# DateType must be cast to string before F.concat():
df = df.withColumn(
    "FilePath",
    F.concat(
        F.lit("dbfs:/mnt/mountname/report_"),
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
# MAGIC Requires: network access from the cluster to the target host. In non-UC workspaces,
# MAGIC this is typically managed via cluster network configuration or VPN — contact your admin.

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
# cp /dbfs/mnt/mountname/input.csv /tmp/staging/input.csv

# Option 2: subprocess — works in Jobs too
import subprocess

result = subprocess.run(
    ["cp", "/dbfs/mnt/mountname/input.csv", "/tmp/staging/input.csv"],
    capture_output=True,
    text=True,
)
if result.returncode != 0:
    raise RuntimeError(f"Shell command failed:\n{result.stderr}")

# Option 3: dbutils.fs for DBFS file operations
dbutils.fs.cp(
    "dbfs:/mnt/mountname/input.csv",
    "dbfs:/tmp/staging/input.csv",
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Section 9 — Iterative Macros → Python Loops
# MAGIC
# MAGIC **Converter flag:** Iterative macros are unsupported — no code is generated.
# MAGIC Implement the loop logic manually using a Python `for`/`while` loop.
# MAGIC The pattern is identical between UC and non-UC workspaces.

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
# MAGIC ## Section 10 — Two-Part SQL Table Names in DynamicInput Templates
# MAGIC
# MAGIC **Converter flag:** DynamicInput SQL templates use two-part names (`SCHEMA.TABLE`).
# MAGIC In non-UC workspaces, two-part names work directly against Hive Metastore — no change
# MAGIC needed unless you are mixing sources from different catalogs.

# COMMAND ----------

# Two-part names work as-is in non-UC workspaces:
#   FROM RRDW_DLV.V_DLV_DEP_AGMT A   ← valid in hive_metastore

# Discover available databases/schemas:
spark.sql("SHOW DATABASES").show()
spark.sql("SHOW TABLES IN RRDW_DLV").show()

# Inspect a specific table:
spark.sql("DESCRIBE TABLE EXTENDED RRDW_DLV.V_DLV_DEP_AGMT").show(truncate=False)

# Quick access check:
spark.table("RRDW_DLV.V_DLV_DEP_AGMT").limit(1).display()

# If you need to prefix with hive_metastore explicitly (e.g. after a partial UC migration):
spark.table("hive_metastore.RRDW_DLV.V_DLV_DEP_AGMT").limit(1).display()

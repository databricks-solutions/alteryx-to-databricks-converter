# Expression Function Reference (141 functions)

Complete reference of all Alteryx expression functions supported by the a2d expression engine, with their PySpark and Spark SQL equivalents.

---

## Table of Contents

1. [String Functions](#string-functions)
2. [Math Functions](#math-functions)
3. [Conversion Functions](#conversion-functions)
4. [DateTime Functions](#datetime-functions)
5. [Test / Null Functions](#test--null-functions)
6. [Scalar Min/Max](#scalar-minmax)
7. [Null Literal](#null-literal)
8. [Operators](#operators)
9. [Conditional Expressions](#conditional-expressions)
10. [Spatial Functions (Stubs)](#spatial-functions-stubs)
11. [Behavioral Differences](#behavioral-differences)

---

## String Functions

| Alteryx Function | PySpark Column Expression | Spark SQL | Args | Notes |
|-----------------|--------------------------|-----------|------|-------|
| `Contains(s, sub)` | `(s).contains(sub)` | `s LIKE CONCAT('%', sub, '%')` | 2 | |
| `EndsWith(s, suffix)` | `(s).endswith(suffix)` | `s LIKE CONCAT('%', suffix)` | 2 | |
| `StartsWith(s, prefix)` | `(s).startswith(prefix)` | `s LIKE CONCAT(prefix, '%')` | 2 | |
| `FindString(s, sub)` | `(F.locate(sub, s) - 1)` | `(LOCATE(sub, s) - 1)` | 2 | Returns 0-indexed position; -1 if not found |
| `Left(s, n)` | `F.substring(s, 1, n)` | `LEFT(s, n)` | 2 | |
| `Right(s, n)` | `F.expr(f'RIGHT({s}, {n})')` | `RIGHT(s, n)` | 2 | Uses SQL expr for PySpark |
| `Length(s)` | `F.length(s)` | `LENGTH(s)` | 1 | |
| `LowerCase(s)` | `F.lower(s)` | `LOWER(s)` | 1 | |
| `Uppercase(s)` | `F.upper(s)` | `UPPER(s)` | 1 | |
| `TitleCase(s)` | `F.initcap(s)` | `INITCAP(s)` | 1 | |
| `Trim(s)` | `F.trim(s)` | `TRIM(s)` | 1-2 | Alteryx optional 2nd arg (trim char) not fully mapped |
| `TrimLeft(s)` | `F.ltrim(s)` | `LTRIM(s)` | 1-2 | |
| `TrimRight(s)` | `F.rtrim(s)` | `RTRIM(s)` | 1-2 | |
| `Replace(s, find, repl)` | `F.regexp_replace(s, find, repl)` | `REGEXP_REPLACE(s, find, repl)` | 3 | |
| `ReplaceFirst(s, find, repl)` | `F.when(F.locate(find, s) > 0, F.concat(...)).otherwise(s)` | `CASE WHEN LOCATE(find, s) > 0 THEN CONCAT(LEFT(s, ...), repl, SUBSTRING(s, ...)) ELSE s END` | 3 | Uses locate+concat to replace only the first occurrence (literal, not regex) |
| `PadLeft(s, len, char)` | `F.lpad(s, len, char)` | `LPAD(s, len, char)` | 3 | |
| `PadRight(s, len, char)` | `F.rpad(s, len, char)` | `RPAD(s, len, char)` | 3 | |
| `Substring(s, start, len)` | `F.substring(s, (start) + 1, len)` | `SUBSTRING(s, (start) + 1, len)` | 3 | Alteryx is 0-indexed, Spark is 1-indexed |
| `ReverseString(s)` | `F.reverse(s)` | `REVERSE(s)` | 1 | |
| `CountWords(s)` | `F.size(F.split(F.trim(s), r'\s+'))` | `SIZE(SPLIT(TRIM(s), '\\s+'))` | 1 | |
| `GetWord(s, n)` | `F.split(s, F.lit(' '))[n]` | `SPLIT(s, ' ')[n]` | 2 | 0-indexed |
| `REGEX_Match(s, pattern)` | `(s).rlike(pattern)` | `s RLIKE pattern` | 2 | |
| `REGEX_Replace(s, pattern, repl)` | `F.regexp_replace(s, pattern, repl)` | `REGEXP_REPLACE(s, pattern, repl)` | 3 | |
| `REGEX_CountMatches(s, pattern)` | `F.size(F.expr(f'regexp_extract_all({s}, {pattern})'))` | `SIZE(REGEXP_EXTRACT_ALL(s, pattern))` | 2 | |
| `Concat(args...)` | `F.concat(args...)` | `CONCAT(args...)` | 1+ | Variable argument count |

---

## Math Functions

| Alteryx Function | PySpark Column Expression | Spark SQL | Args | Notes |
|-----------------|--------------------------|-----------|------|-------|
| `ABS(x)` | `F.abs(x)` | `ABS(x)` | 1 | |
| `CEIL(x)` | `F.ceil(x)` | `CEIL(x)` | 1 | |
| `FLOOR(x)` | `F.floor(x)` | `FLOOR(x)` | 1 | |
| `Round(x, n)` | `F.round(x, n)` | `ROUND(x, n)` | 1-2 | `n` defaults to 0 |
| `POW(x, y)` | `F.pow(x, y)` | `POWER(x, y)` | 2 | |
| `SQRT(x)` | `F.sqrt(x)` | `SQRT(x)` | 1 | |
| `LOG(x)` | `F.log(x)` | `LN(x)` | 1 | Natural logarithm; SQL uses `LN` not `LOG` |
| `LOG10(x)` | `F.log10(x)` | `LOG10(x)` | 1 | |
| `LOG2(x)` | `F.log2(x)` | `LOG2(x)` | 1 | |
| `EXP(x)` | `F.exp(x)` | `EXP(x)` | 1 | |
| `Mod(x, y)` | `(x % y)` | `(x % y)` | 2 | Modulo operator |
| `RAND()` | `F.rand()` | `RAND()` | 0 | |
| `RandInt(max)` | `F.floor(F.rand() * max)` | `FLOOR(RAND() * max)` | 1 | |
| `PI()` | `F.lit(3.141592653589793)` | `3.141592653589793` | 0 | Constant value |
| `SIN(x)` | `F.sin(x)` | `SIN(x)` | 1 | |
| `COS(x)` | `F.cos(x)` | `COS(x)` | 1 | |
| `TAN(x)` | `F.tan(x)` | `TAN(x)` | 1 | |
| `ASIN(x)` | `F.asin(x)` | `ASIN(x)` | 1 | |
| `ACOS(x)` | `F.acos(x)` | `ACOS(x)` | 1 | |
| `ATAN(x)` | `F.atan(x)` | `ATAN(x)` | 1 | |
| `ATAN2(y, x)` | `F.atan2(y, x)` | `ATAN2(y, x)` | 2 | |

---

## Conversion Functions

| Alteryx Function | PySpark Column Expression | Spark SQL | Args | Notes |
|-----------------|--------------------------|-----------|------|-------|
| `ToNumber(s)` | `F.try_cast(s, 'double')` | `TRY_CAST(s AS DOUBLE)` | 1 | Returns NULL on bad input (matches Alteryx); requires DBR 14+ / Spark 3.5+ |
| `ToInteger(s)` | `F.try_cast(s, 'int')` | `TRY_CAST(s AS INT)` | 1 | Returns NULL on bad input |
| `ToString(x)` | `(x).cast('string')` | `CAST(x AS STRING)` | 1-2 | Alteryx optional format arg not mapped |
| `ToDate(s, fmt)` | `F.try_to_date(s, fmt)` | `TRY_TO_DATE(s, fmt)` | 1-2 | Format-string arg passed as a raw string (not wrapped in `F.col`); returns NULL on unparseable input |
| `ToDateTime(s, fmt)` | `F.try_to_timestamp(s, fmt)` | `TRY_TO_TIMESTAMP(s, fmt)` | 1-2 | Format-string arg passed as a raw string; returns NULL on unparseable input |
| `ToInt32(s)` | `F.try_cast(s, 'int')` | `TRY_CAST(s AS INT)` | 1 | Alteryx int alias |
| `ToInt64(s)` | `F.try_cast(s, 'long')` | `TRY_CAST(s AS BIGINT)` | 1 | Alteryx long alias |
| `ToDouble(s)` | `F.try_cast(s, 'double')` | `TRY_CAST(s AS DOUBLE)` | 1 | Alteryx double alias |
| `CharToInt(s)` | `F.ascii(s)` | `ASCII(s)` | 1 | Returns ASCII code of first character |
| `IntToChar(n)` | `F.chr(n)` | `CHR(n)` | 1 | |
| `HexToNumber(s)` | `F.conv(s, 16, 10)` | `CONV(s, 16, 10)` | 1 | |
| `BinToInt(s)` | `F.conv(s, 2, 10)` | `CONV(s, 2, 10)` | 1 | |

---

## DateTime Functions

| Alteryx Function | PySpark Column Expression | Spark SQL | Args | Notes |
|-----------------|--------------------------|-----------|------|-------|
| `DateTimeNow()` | `F.current_timestamp()` | `CURRENT_TIMESTAMP()` | 0 | |
| `DateTimeToday()` | `F.current_date()` | `CURRENT_DATE()` | 0 | |
| `DateTimeYear(dt)` | `F.year(dt)` | `YEAR(dt)` | 1 | |
| `DateTimeMonth(dt)` | `F.month(dt)` | `MONTH(dt)` | 1 | |
| `DateTimeDay(dt)` | `F.dayofmonth(dt)` | `DAYOFMONTH(dt)` | 1 | |
| `DateTimeHour(dt)` | `F.hour(dt)` | `HOUR(dt)` | 1 | |
| `DateTimeMinutes(dt)` | `F.minute(dt)` | `MINUTE(dt)` | 1 | |
| `DateTimeSeconds(dt)` | `F.second(dt)` | `SECOND(dt)` | 1 | |
| `DateTimeAdd(dt, n, unit)` | `F.expr(f'dateadd({unit}, {n}, {dt})')` | `DATEADD(unit, n, dt)` | 3 | Args: datetime, count, interval type |
| `DateTimeDiff(start, end, unit)` | `F.datediff(start, end)` | `DATEDIFF(unit, start, end)` | 2-3 | PySpark `datediff` returns days only; SQL version supports unit parameter |
| `DateTimeFormat(dt, fmt)` | `F.date_format(dt, fmt)` | `DATE_FORMAT(dt, fmt)` | 2 | |
| `DateTimeParse(s, fmt)` | `F.to_timestamp(s, fmt)` | `TO_TIMESTAMP(s, fmt)` | 2 | |
| `DateTimeTrim(dt, unit)` | `F.date_trunc(unit, dt)` | `DATE_TRUNC(unit, dt)` | 2 | Note: argument order differs from Alteryx |
| `DateTimeFirstOfMonth()` | `F.trunc(F.current_date(), 'month')` | `TRUNC(CURRENT_DATE, 'month')` | 0 | Alteryx semantics: returns the first day of the current month (0-arg) |
| `DateTimeDayOfWeek(dt)` | `F.dayofweek(dt)` | `DAYOFWEEK(dt)` | 1 | Spark returns 1=Sunday, Alteryx returns 1=Sunday |

---

## Test / Null Functions

| Alteryx Function | PySpark Column Expression | Spark SQL | Args | Notes |
|-----------------|--------------------------|-----------|------|-------|
| `IsNull(x)` | `F.isnull(x)` | `x IS NULL` | 1 | |
| `IsEmpty(x)` | `(F.isnull(x) \| (F.trim(x) == F.lit('')))` | `(x IS NULL OR TRIM(x) = '')` | 1 | Checks null OR blank string |
| `IsNumber(x)` | `(x).cast('double').isNotNull()` | `CAST(x AS DOUBLE) IS NOT NULL` | 1 | Attempt cast; non-null means numeric |
| `IsInteger(x)` | `(x).cast('int').isNotNull()` | `CAST(x AS INT) IS NOT NULL` | 1 | |
| `IsString(x)` | `F.lit(True)` | `TRUE` | 1 | In Spark, everything can be cast to string |
| `Coalesce(args...)` | `F.coalesce(args...)` | `COALESCE(args...)` | 1+ | Variable argument count |
| `IIF(cond, true_val, false_val)` | `F.when(cond, true_val).otherwise(false_val)` | `CASE WHEN cond THEN true_val ELSE false_val END` | 3 | Inline if |
| `IFNULL(x, default)` | `F.coalesce(x, default)` | `COALESCE(x, default)` | 2 | |

---

## Conditional / Lookup Functions

| Alteryx Function | PySpark Column Expression | Spark SQL | Args | Notes |
|-----------------|--------------------------|-----------|------|-------|
| `Switch(val, def, v1, r1, ...)` | `F.when(val==v1, r1).when(...).otherwise(def)` | `CASE WHEN val=v1 THEN r1 ... ELSE def END` | 2+ | Variable pairs; special-cased in translators |
| `IIF(cond, true, false)` | `F.when(cond, true_val).otherwise(false_val)` | `CASE WHEN cond THEN true ELSE false END` | 3 | Inline if |

---

## File Functions

| Alteryx Function | PySpark Column Expression | Spark SQL | Args | Notes |
|-----------------|--------------------------|-----------|------|-------|
| `FileGetFileName(path)` | `F.element_at(F.split(path, r'[/\\\\]'), -1)` | `ELEMENT_AT(SPLIT(path, '[/\\\\]'), -1)` | 1 | Extracts filename from a file path |

---

## Scalar Min/Max

| Alteryx Function | PySpark Column Expression | Spark SQL | Args | Notes |
|-----------------|--------------------------|-----------|------|-------|
| `Min(a, b)` | `F.least(a, b)` | `LEAST(a, b)` | 2 | Scalar minimum (not aggregate) |
| `Max(a, b)` | `F.greatest(a, b)` | `GREATEST(a, b)` | 2 | Scalar maximum (not aggregate) |

---

## Null Literal

| Alteryx Function | PySpark Column Expression | Spark SQL | Args | Notes |
|-----------------|--------------------------|-----------|------|-------|
| `Null()` | `F.lit(None)` | `NULL` | 0 | Produces a null value |

---

## Operators

The expression engine translates all standard Alteryx operators:

### Arithmetic Operators

| Alteryx | PySpark | SQL | Notes |
|---------|---------|-----|-------|
| `+` | `+` | `+` | Addition |
| `-` | `-` | `-` | Subtraction |
| `*` | `*` | `*` | Multiplication |
| `/` | `/` | `/` | Division |
| `%` | `%` | `%` | Modulo |
| `-x` (unary) | `-x` | `-x` | Negation |

### Comparison Operators

| Alteryx | PySpark | SQL | Notes |
|---------|---------|-----|-------|
| `=` | `==` | `=` | Equality |
| `!=` | `!=` | `!=` | Inequality |
| `<>` | `!=` | `!=` | Inequality (alternative) |
| `>` | `>` | `>` | Greater than |
| `<` | `<` | `<` | Less than |
| `>=` | `>=` | `>=` | Greater than or equal |
| `<=` | `<=` | `<=` | Less than or equal |

### Logical Operators

| Alteryx | PySpark | SQL | Notes |
|---------|---------|-----|-------|
| `AND` | `&` | `AND` | Logical and |
| `OR` | `\|` | `OR` | Logical or |
| `NOT` | `~()` | `NOT` | Logical negation |
| `&&` | `&` | `AND` | C-style and |
| `\|\|` | `\|` | `OR` | C-style or |

---

## Conditional Expressions

### IF / THEN / ELSE / ENDIF

Alteryx:
```
IF [Amount] > 1000 THEN "High"
ELSEIF [Amount] > 100 THEN "Medium"
ELSE "Low"
ENDIF
```

PySpark:
```python
F.when((F.col("Amount") > 1000), F.lit("High"))
 .when((F.col("Amount") > 100), F.lit("Medium"))
 .otherwise(F.lit("Low"))
```

Spark SQL:
```sql
CASE WHEN Amount > 1000 THEN 'High'
     WHEN Amount > 100 THEN 'Medium'
     ELSE 'Low'
END
```

### IN Expression

Alteryx:
```
[Region] IN ("East", "West", "Central")
```

PySpark:
```python
F.col("Region").isin([F.lit("East"), F.lit("West"), F.lit("Central")])
```

Spark SQL:
```sql
Region IN ('East', 'West', 'Central')
```

### Field References

Alteryx:
```
[FieldName]
```

PySpark:
```python
F.col("FieldName")
```

Spark SQL:
```sql
`FieldName`
```

### Row References (Multi-Row Formula)

Alteryx:
```
[Row-1:Amount]    -- previous row
[Row+1:Amount]    -- next row
```

PySpark:
```python
F.lag(F.col("Amount"), 1).over(window)     # previous row
F.lead(F.col("Amount"), 1).over(window)    # next row
```

---

## Spatial Functions (Stubs)

| Alteryx Function | PySpark | Notes |
|-----------------|---------|-------|
| `Distance(...)` | `F.lit('UNSUPPORTED: Distance')` | Spatial functions are not natively supported in Spark. Consider Apache Sedona or H3 for geospatial workloads. |

---

## Behavioral Differences

Important cases where Alteryx and Spark behavior differs:

| Function | Difference |
|----------|-----------|
| `Substring` | Alteryx uses 0-based indexing; Spark uses 1-based. The translator adds +1 to the start position. |
| `ReplaceFirst` | Alteryx replaces only the first occurrence. The translator now correctly uses `locate`+`concat` to replace only the first match (literal, not regex). No manual post-processing needed. |
| `LOG` | Alteryx `LOG` is natural log. Spark SQL uses `LN` for natural log (`LOG` defaults to base-10 in some SQL dialects). The translator maps to `LN`. |
| `DateTimeDiff` | Alteryx supports arbitrary units (days, hours, months). PySpark `datediff` only returns days. The SQL version uses Databricks `DATEDIFF` with unit parameter. |
| `DateTimeTrim` | Argument order is reversed: Alteryx is `DateTimeTrim(dt, unit)`, Spark is `date_trunc(unit, dt)`. The translator handles this swap. |
| `FindString` | Both Alteryx and the translated PySpark return 0-based index. `LOCATE` in Spark SQL returns 1-based, so -1 is applied. |
| `IsString` | Always returns `True` in Spark because all values can be cast to string. The Alteryx version checks the field's metadata type. |
| `Trim` | Alteryx `Trim` can accept an optional second argument for the trim character. The PySpark mapping only handles the single-arg (whitespace) version. |
| `ToString` | Alteryx `ToString` can accept a format string as a second argument for date formatting. The PySpark mapping only handles the single-arg version. |
| `ToNumber` / `ToInteger` / `ToDate` / `ToDateTime` | Translated to `try_cast` / `try_to_date` / `try_to_timestamp` so unparseable input returns `NULL` (matches Alteryx) instead of throwing. Requires DBR 14+ / Spark 3.5+. Format-string arguments are passed as raw strings (the translator marks them via `raw_string_args` in the function registry) so `F.try_to_date(F.col("d"), "yyyy-MM-dd")` is emitted, not `F.try_to_date(F.col("d"), F.col("yyyy-MM-dd"))`. |
| `DateTimeFirstOfMonth` | 0-arg in Alteryx (returns first-of-current-month). The translator emits `F.trunc(F.current_date(), 'month')` so the generated code runs without the user filling in a placeholder. |

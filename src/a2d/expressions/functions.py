"""Alteryx-to-PySpark function mapping registry.

Maps 135+ Alteryx expression functions to their PySpark column-expression
and Spark SQL equivalents.  Each mapping includes argument count constraints
and optional translator notes.

Templates use ``{0}``, ``{1}``, ... for positional arguments and the
special ``{args}`` placeholder for variable-length argument lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FunctionMapping:
    """Maps an Alteryx function to PySpark equivalent."""

    alteryx_name: str
    pyspark_template: str  # Template with {0}, {1}, etc. for args
    sql_template: str | None = None  # Spark SQL equivalent
    min_args: int = 0
    max_args: int | None = None
    notes: str = ""
    raw_string_args: frozenset[int] = field(default_factory=frozenset)
    """Argument positions that must be emitted as plain Python strings (not F.lit())."""


FUNCTION_REGISTRY: dict[str, FunctionMapping] = {}


def _register(
    name: str,
    pyspark: str,
    sql: str | None = None,
    min_args: int = 0,
    max_args: int | None = None,
    notes: str = "",
    raw_string_args: frozenset[int] | None = None,
) -> None:
    """Register a function mapping in the global registry."""
    FUNCTION_REGISTRY[name.lower()] = FunctionMapping(
        alteryx_name=name,
        pyspark_template=pyspark,
        sql_template=sql,
        min_args=min_args,
        max_args=max_args,
        notes=notes,
        raw_string_args=raw_string_args or frozenset(),
    )


# ---------------------------------------------------------------------------
# String functions (25+)
# ---------------------------------------------------------------------------
_register("Contains", "({0}).contains({1})", "{0} LIKE CONCAT('%', {1}, '%')", 2, 2)
_register("EndsWith", "({0}).endswith({1})", "{0} LIKE CONCAT('%', {1})", 2, 2)
_register("StartsWith", "({0}).startswith({1})", "{0} LIKE CONCAT({1}, '%')", 2, 2)
_register("FindString", "(F.locate({1}, {0}) - 1)", "(LOCATE({1}, {0}) - 1)", 2, 2)
_register(
    "position",
    "(F.locate({1}, {0}) - 1)",
    "(LOCATE({1}, {0}) - 1)",
    2,
    2,
    notes="Alias for FindString — 0-based position of target in string",
)
_register("Left", "F.substring({0}, 1, {1})", "LEFT({0}, {1})", 2, 2)
_register("Right", "F.substring({0}, F.length({0}) - ({1}) + F.lit(1), {1})", "RIGHT({0}, {1})", 2, 2)
_register("Length", "F.length({0})", "LENGTH({0})", 1, 1)
_register("LowerCase", "F.lower({0})", "LOWER({0})", 1, 1)
_register("Uppercase", "F.upper({0})", "UPPER({0})", 1, 1)
_register("TitleCase", "F.initcap({0})", "INITCAP({0})", 1, 1)
_register(
    "Trim",
    "F.trim({0})",
    "TRIM({0})",
    1,
    1,
    notes="2-arg form (trim character) not supported; use REGEX_Replace as workaround",
)
_register("TrimLeft", "F.ltrim({0})", "LTRIM({0})", 1, 1, notes="2-arg form (trim character) not supported")
_register("TrimRight", "F.rtrim({0})", "RTRIM({0})", 1, 1, notes="2-arg form (trim character) not supported")
_register(
    "Replace",
    "F.regexp_replace({0}, {1}, {2})",
    "REPLACE({0}, {1}, {2})",
    3,
    3,
    notes="Alteryx Replace() is literal string replacement. Uses regexp_replace which is "
    "equivalent for non-regex characters (covers 99% of usage). If the search string "
    "contains regex metacharacters (.*+?[]{}^$|\\), manual escaping may be needed.",
)
_register(
    "ReplaceFirst",
    "F.when(F.locate({1}, {0}) > 0, F.concat(F.substring({0}, F.lit(1), F.locate({1}, {0}) - 1), {2}, F.substring({0}, F.locate({1}, {0}) + F.length({1}), F.length({0})))).otherwise({0})",
    "CASE WHEN LOCATE({1}, {0}) > 0 THEN CONCAT(LEFT({0}, LOCATE({1}, {0}) - 1), {2}, SUBSTRING({0}, LOCATE({1}, {0}) + LENGTH({1}))) ELSE {0} END",
    3,
    3,
    notes="Replaces only the first occurrence of a literal string (not regex). Uses locate+concat to avoid regexp_replace replacing all occurrences.",
)
_register("PadLeft", "F.lpad({0}, {1}, {2})", "LPAD({0}, {1}, {2})", 3, 3)
_register("PadRight", "F.rpad({0}, {1}, {2})", "RPAD({0}, {1}, {2})", 3, 3)
_register(
    "Substring",
    "F.substring({0}, ({1}) + 1, {2})",
    "SUBSTRING({0}, ({1}) + 1, {2})",
    3,
    3,
    notes="Alteryx is 0-indexed, Spark is 1-indexed",
)
_register("ReverseString", "F.reverse({0})", "REVERSE({0})", 1, 1)
_register("Reverse", "F.reverse({0})", "REVERSE({0})", 1, 1, notes="Alias for ReverseString")
_register(
    "CountWords",
    "F.size(F.split(F.trim({0}), r'\\s+'))",
    "SIZE(SPLIT(TRIM({0}), '\\\\s+'))",
    1,
    1,
)
_register("GetWord", "F.split({0}, F.lit(' '))[{1}]", "SPLIT({0}, ' ')[{1}]", 2, 2)
_register("REGEX_Match", "({0}).rlike({1})", "{0} RLIKE {1}", 2, 2)
_register("REGEX_Replace", "F.regexp_replace({0}, {1}, {2})", "REGEXP_REPLACE({0}, {1}, {2})", 3, 3)
_register(
    "REGEX_CountMatches",
    "(F.size(F.split({0}, {1})) - F.lit(1))",
    "SIZE(REGEXP_EXTRACT_ALL({0}, {1}))",
    2,
    2,
    notes="Counts non-overlapping regex matches via split-and-count",
)
_register("Concat", "F.concat({args})", "CONCAT({args})", 1, None, notes="Variable args")

# ---------------------------------------------------------------------------
# Math functions (20+)
# ---------------------------------------------------------------------------
_register("ABS", "F.abs({0})", "ABS({0})", 1, 1)
_register("CEIL", "F.ceil({0})", "CEIL({0})", 1, 1)
_register("FLOOR", "F.floor({0})", "FLOOR({0})", 1, 1)
_register("Round", "F.round({0}, {1})", "ROUND({0}, {1})", 1, 2)
_register("POW", "F.pow({0}, {1})", "POWER({0}, {1})", 2, 2)
_register("SQRT", "F.sqrt({0})", "SQRT({0})", 1, 1)
_register("LOG", "F.log({0})", "LN({0})", 1, 1)
_register("LOG10", "F.log10({0})", "LOG10({0})", 1, 1)
_register("LOG2", "F.log2({0})", "LOG2({0})", 1, 1)
_register("EXP", "F.exp({0})", "EXP({0})", 1, 1)
_register("Mod", "({0} % {1})", "({0} % {1})", 2, 2)
_register("RAND", "F.rand()", "RAND()", 0, 0)
_register("RandInt", "F.floor(F.rand() * {0})", "FLOOR(RAND() * {0})", 1, 1)
_register("PI", "F.lit(3.141592653589793)", "3.141592653589793", 0, 0)
_register("SIN", "F.sin({0})", "SIN({0})", 1, 1)
_register("COS", "F.cos({0})", "COS({0})", 1, 1)
_register("TAN", "F.tan({0})", "TAN({0})", 1, 1)
_register("ASIN", "F.asin({0})", "ASIN({0})", 1, 1)
_register("ACOS", "F.acos({0})", "ACOS({0})", 1, 1)
_register("ATAN", "F.atan({0})", "ATAN({0})", 1, 1)
_register("ATAN2", "F.atan2({0}, {1})", "ATAN2({0}, {1})", 2, 2)

# ---------------------------------------------------------------------------
# Conversion functions (10+)
#
# Note: Alteryx's ToNumber/ToInteger/ToDate/ToDateTime/DateTimeParse silently
# return NULL on unparseable input. Spark's plain CAST / to_date / to_timestamp
# THROW on bad input. We use try_cast / try_to_date / try_to_timestamp
# (Databricks Runtime 14+, Spark 3.5+) to match Alteryx semantics.
# ---------------------------------------------------------------------------
_register(
    "ToNumber",
    "F.try_cast({0}, 'double')",
    "TRY_CAST({0} AS DOUBLE)",
    1,
    1,
    notes="Returns NULL on unparseable input (matches Alteryx); requires DBR 14+ / Spark 3.5+",
)
_register(
    "ToInteger",
    "F.try_cast({0}, 'int')",
    "TRY_CAST({0} AS INT)",
    1,
    1,
    notes="Returns NULL on unparseable input (matches Alteryx); requires DBR 14+ / Spark 3.5+",
)
_register("ToString", "({0}).cast('string')", "CAST({0} AS STRING)", 1, 2)
_register(
    "ToDate",
    "F.try_to_date({0}, {1})",
    "TRY_TO_DATE({0}, {1})",
    1,
    2,
    # Arg 1 is the format string — convert Alteryx tokens (%Y-%m-%d) to
    # Spark/Java tokens (yyyy-MM-dd) before substitution. Without this, the
    # generated code would pass an Alteryx-style format that Spark can't parse.
    raw_string_args=frozenset({1}),
    notes="Returns NULL on unparseable input (matches Alteryx); requires DBR 14+ / Spark 3.5+",
)
_register(
    "ToDateTime",
    "F.try_to_timestamp({0}, {1})",
    "TRY_TO_TIMESTAMP({0}, {1})",
    1,
    2,
    raw_string_args=frozenset({1}),
    notes="Returns NULL on unparseable input (matches Alteryx); requires DBR 14+ / Spark 3.5+",
)
_register("CharToInt", "F.ascii({0})", "ASCII({0})", 1, 1)
_register("IntToChar", "F.chr({0})", "CHR({0})", 1, 1)
_register("HexToNumber", "F.conv({0}, 16, 10)", "CONV({0}, 16, 10)", 1, 1)
_register("BinToInt", "F.conv({0}, 2, 10)", "CONV({0}, 2, 10)", 1, 1)

# ---------------------------------------------------------------------------
# DateTime functions (15+)
# ---------------------------------------------------------------------------
_register("DateTimeNow", "F.current_timestamp()", "CURRENT_TIMESTAMP()", 0, 0)
_register("DateTimeToday", "F.current_date()", "CURRENT_DATE()", 0, 0)
_register("DateTimeYear", "F.year({0})", "YEAR({0})", 1, 1)
_register("DateTimeMonth", "F.month({0})", "MONTH({0})", 1, 1)
_register("DateTimeDay", "F.dayofmonth({0})", "DAYOFMONTH({0})", 1, 1)
_register("DateTimeHour", "F.hour({0})", "HOUR({0})", 1, 1)
_register("DateTimeMinutes", "F.minute({0})", "MINUTE({0})", 1, 1)
_register("DateTimeMinute", "F.minute({0})", "MINUTE({0})", 1, 1, notes="Singular alias for DateTimeMinutes")
_register("DateTimeSeconds", "F.second({0})", "SECOND({0})", 1, 1)
_register("DateTimeSecond", "F.second({0})", "SECOND({0})", 1, 1, notes="Singular alias for DateTimeSeconds")
_register(
    "DateTimeAdd",
    "__DATEADD__",
    "DATEADD({2}, {1}, {0})",
    3,
    3,
    notes="Args: datetime, interval_count, interval_type — special-cased in translator",
    raw_string_args=frozenset({2}),
)
_register(
    "DateTimeDiff",
    "__DATEDIFF__",
    "DATEDIFF({2}, {0}, {1})",
    2,
    3,
    notes="Args: start, end, unit — special-cased in PySpark translator for unit support",
    raw_string_args=frozenset({2}),
)
_register("DateTimeFormat", "F.date_format({0}, {1})", "DATE_FORMAT({0}, {1})", 2, 2, raw_string_args=frozenset({1}))
_register(
    "DateTimeParse",
    "F.try_to_timestamp({0}, F.lit({1}))",
    "TRY_TO_TIMESTAMP({0}, {1})",
    2,
    2,
    raw_string_args=frozenset({1}),
    notes="Returns NULL on unparseable input (matches Alteryx); requires DBR 14+ / Spark 3.5+",
)
_register("DateTimeTrim", "F.date_trunc({1}, {0})", "DATE_TRUNC({1}, {0})", 2, 2)
# Alteryx ``DateTimeFirstOfMonth()`` is 0-arg — returns the first day of the
# current month. We default to current_date() so generated code runs without
# the user having to fill in a placeholder.
_register(
    "DateTimeFirstOfMonth",
    "F.trunc(F.current_date(), 'month')",
    "TRUNC(CURRENT_DATE, 'month')",
    0,
    0,
)
_register("DateTimeDayOfWeek", "F.dayofweek({0})", "DAYOFWEEK({0})", 1, 1)

# ---------------------------------------------------------------------------
# Test / Null functions (10+)
# ---------------------------------------------------------------------------
_register("IsNull", "F.isnull({0})", "{0} IS NULL", 1, 1)
_register(
    "IsEmpty",
    "(F.isnull({0}) | (F.trim({0}) == F.lit('')))",
    "({0} IS NULL OR TRIM({0}) = '')",
    1,
    1,
)
_register(
    "IsNumber",
    "({0}).cast('double').isNotNull()",
    "CAST({0} AS DOUBLE) IS NOT NULL",
    1,
    1,
)
_register(
    "IsInteger",
    "({0}).cast('int').isNotNull()",
    "CAST({0} AS INT) IS NOT NULL",
    1,
    1,
)
_register(
    "IsString",
    "F.lit(True)",
    "TRUE",
    1,
    1,
    notes="In Spark everything can be treated as string",
)
_register("Coalesce", "F.coalesce({args})", "COALESCE({args})", 1, None, notes="Variable args")
_register("IIF", "F.when({0}, {1}).otherwise({2})", "CASE WHEN {0} THEN {1} ELSE {2} END", 3, 3)
_register("IFNULL", "F.coalesce({0}, {1})", "COALESCE({0}, {1})", 2, 2)

# ---------------------------------------------------------------------------
# Min / Max (scalar)
# ---------------------------------------------------------------------------
_register("Min", "F.least({args})", "LEAST({args})", 2, None, notes="Variadic: Min(a, b, c, ...)")
_register("Max", "F.greatest({args})", "GREATEST({args})", 2, None, notes="Variadic: Max(a, b, c, ...)")

# ---------------------------------------------------------------------------
# Null handling
# ---------------------------------------------------------------------------
_register("Null", "F.lit(None)", "NULL", 0, 0)

# ---------------------------------------------------------------------------
# Spatial (stub)
# ---------------------------------------------------------------------------
_register(
    "Distance",
    "F.lit('UNSUPPORTED: Distance')",
    "'UNSUPPORTED: Distance'",
    2,
    4,
    notes="Spatial functions not supported in Spark natively",
)

# ---------------------------------------------------------------------------
# Conditional functions
# ---------------------------------------------------------------------------
_register(
    "Switch",
    "__SWITCH__",
    "__SWITCH__",
    2,
    None,
    notes="Special-cased in translators: Switch(value, default, val1, result1, val2, result2, ...)",
)

# ---------------------------------------------------------------------------
# Additional string functions
# ---------------------------------------------------------------------------
_register(
    "Mid",
    "F.substring({0}, ({1}) + 1, {2})",
    "SUBSTRING({0}, ({1}) + 1, {2})",
    3,
    3,
    notes="Alias for Substring; Alteryx is 0-indexed, Spark is 1-indexed",
)

# ---------------------------------------------------------------------------
# Additional test / validation functions
# ---------------------------------------------------------------------------
_register(
    "IsAlpha",
    "({0}).rlike('^[A-Za-z]+$')",
    "{0} RLIKE '^[A-Za-z]+$'",
    1,
    1,
)
_register(
    "IsUpperCase",
    "({0} == F.upper({0}))",
    "({0} = UPPER({0}))",
    1,
    1,
)
_register(
    "IsLowerCase",
    "({0} == F.lower({0}))",
    "({0} = LOWER({0}))",
    1,
    1,
)

# ---------------------------------------------------------------------------
# Additional null handling
# ---------------------------------------------------------------------------
_register(
    "NullIf",
    "F.when({0} == {1}, F.lit(None)).otherwise({0})",
    "NULLIF({0}, {1})",
    2,
    2,
)

# ---------------------------------------------------------------------------
# Conversion aliases
# ---------------------------------------------------------------------------
_register("CharFromInt", "F.chr({0})", "CHR({0})", 1, 1, notes="Alias for IntToChar")

# ---------------------------------------------------------------------------
# File functions
# ---------------------------------------------------------------------------
_register(
    "FileGetFileName",
    "F.element_at(F.split(F.regexp_replace({0}, '\\\\\\\\', '/'), '/'), -1)",
    "ELEMENT_AT(SPLIT(REGEXP_REPLACE({0}, '\\\\\\\\', '/'), '/'), -1)",
    1,
    1,
    notes="Extracts filename from a path; normalizes backslash to forward-slash first",
)


# ---------------------------------------------------------------------------
# Additional conversion functions
# ---------------------------------------------------------------------------
_register("IntToHex", "F.hex({0})", "HEX({0})", 1, 1)
_register("IntToBin", "F.bin({0})", "BIN({0})", 1, 1)

# ---------------------------------------------------------------------------
# Additional DateTime functions
# ---------------------------------------------------------------------------
_register("DateTimeLastOfMonth", "F.last_day({0})", "LAST_DAY({0})", 1, 1)

# ---------------------------------------------------------------------------
# Additional string functions
# ---------------------------------------------------------------------------
_register(
    "ReplaceChar",
    "F.translate({0}, {1}, {2})",
    "TRANSLATE({0}, {1}, {2})",
    3,
    3,
    notes="Replaces each character in arg2 with corresponding character in arg3",
)
_register(
    "StripQuotes",
    r"F.regexp_replace(F.regexp_replace({0}, F.lit('^[\"\\']'), F.lit('')), F.lit('[\"\\']$'), F.lit(''))",
    r"REGEXP_REPLACE(REGEXP_REPLACE({0}, '^[\"'']', ''), '[\"'']$', '')",
    1,
    1,
    notes="Removes leading/trailing single or double quotes",
)
_register(
    "STRCHR",
    "F.substring({0}, {1}, 1)",
    "SUBSTRING({0}, {1}, 1)",
    2,
    2,
    notes="Returns single character at the given position",
)

# ---------------------------------------------------------------------------
# Hashing functions
# ---------------------------------------------------------------------------
_register("MD5_ASCII", "F.md5({0})", "MD5({0})", 1, 1)
_register("SHA1_ASCII", "F.sha1({0})", "SHA1({0})", 1, 1)
_register("UUID", "F.expr('uuid()')", "UUID()", 0, 0)

# ---------------------------------------------------------------------------
# Additional math functions
# ---------------------------------------------------------------------------
_register("SoundEx", "F.soundex({0})", "SOUNDEX({0})", 1, 1)
_register("Cosh", "((F.exp({0}) + F.exp(-({0}))) / F.lit(2))", "COSH({0})", 1, 1)
_register("Sinh", "((F.exp({0}) - F.exp(-({0}))) / F.lit(2))", "SINH({0})", 1, 1)
_register("Tanh", "((F.exp({0}) - F.exp(-({0}))) / (F.exp({0}) + F.exp(-({0}))))", "TANH({0})", 1, 1)
_register(
    "Bound",
    "F.greatest({1}, F.least({2}, {0}))",
    "GREATEST({1}, LEAST({2}, {0}))",
    3,
    3,
    notes="Clamps value between min and max: Bound(value, min, max)",
)


# ---------------------------------------------------------------------------
# Additional file functions
# ---------------------------------------------------------------------------
_register(
    "FileGetDirectory",
    r"F.regexp_replace({0}, F.lit('[^/\\\\]+$'), F.lit(''))",
    r"REGEXP_REPLACE({0}, '[^/\\\\]+$', '')",
    1,
    1,
    notes="Extracts directory path from a file path; strips trailing filename",
)
_register(
    "FileGetExtension",
    "F.regexp_extract({0}, r'(\\.[^.]+)$', 1)",
    "REGEXP_EXTRACT({0}, '(\\\\.[^.]+)$', 1)",
    1,
    1,
    notes="Extracts file extension including the dot (e.g. '.csv')",
)
_register(
    "FileExists",
    "F.lit(True)",
    "TRUE",
    1,
    1,
    notes="Cannot check filesystem at column level; always returns True. Check manually.",
)

# ---------------------------------------------------------------------------
# Additional DateTime functions
# ---------------------------------------------------------------------------
_register("DateTimeQuarter", "F.quarter({0})", "QUARTER({0})", 1, 1)
_register("DateTimeDayOfYear", "F.dayofyear({0})", "DAYOFYEAR({0})", 1, 1)
_register("DateTimeWeekOfYear", "F.weekofyear({0})", "WEEKOFYEAR({0})", 1, 1)

# ---------------------------------------------------------------------------
# Additional math functions
# ---------------------------------------------------------------------------
_register("GCD", "__SQLEXPR__gcd({0}, {1})", "GCD({0}, {1})", 2, 2)
_register("LCM", "__SQLEXPR__({0} * {1}) / gcd({0}, {1})", "({0} * {1}) / GCD({0}, {1})", 2, 2)
_register("Factorial", "__SQLEXPR__factorial({0})", "FACTORIAL({0})", 1, 1)
_register("Sign", "F.signum({0})", "SIGN({0})", 1, 1)
_register("SmallestInteger", "F.ceil({0})", "CEIL({0})", 1, 1, notes="Alias for CEIL — smallest integer >= value")
_register("LargestInteger", "F.floor({0})", "FLOOR({0})", 1, 1, notes="Alias for FLOOR — largest integer <= value")

# ---------------------------------------------------------------------------
# Finance functions (PySpark UDF required)
# ---------------------------------------------------------------------------
_register(
    "PV",
    "__SQLEXPR__(-{2} * ((1 - power(1 + {0}, -{1})) / {0}))",
    "(-{2} * ((1 - POWER(1 + {0}, -{1})) / {0}))",
    3,
    5,
    notes="Present Value: PV(rate, nper, pmt, [fv], [type]). Simplified — fv/type args ignored.",
)
_register(
    "FV",
    "__SQLEXPR__({2} * ((power(1 + {0}, {1}) - 1) / {0}))",
    "({2} * ((POWER(1 + {0}, {1}) - 1) / {0}))",
    3,
    5,
    notes="Future Value: FV(rate, nper, pmt, [pv], [type]). Simplified — pv/type args ignored.",
)
_register(
    "PMT",
    "__SQLEXPR__({2} * {0} / (1 - power(1 + {0}, -{1})))",
    "({2} * {0} / (1 - POWER(1 + {0}, -{1})))",
    3,
    5,
    notes="Payment amount: PMT(rate, nper, pv, [fv], [type]). Simplified — fv/type args ignored.",
)

# ---------------------------------------------------------------------------
# Additional string functions
# ---------------------------------------------------------------------------
_register(
    "Levenshtein", "F.levenshtein({0}, {1})", "LEVENSHTEIN({0}, {1})", 2, 2, notes="Edit distance between two strings"
)
_register("SHA256_ASCII", "F.sha2({0}, 256)", "SHA2({0}, 256)", 1, 1)
_register(
    "REGEX_Extract",
    "F.regexp_extract({0}, {1}, 1)",
    "REGEXP_EXTRACT({0}, {1}, 1)",
    2,
    2,
    notes="Extracts first matching group from regex pattern",
)

# ---------------------------------------------------------------------------
# Aliases for common alternate function names
# ---------------------------------------------------------------------------
_register("Lower", "F.lower({0})", "LOWER({0})", 1, 1, notes="Alias for LowerCase")
_register("Upper", "F.upper({0})", "UPPER({0})", 1, 1, notes="Alias for Uppercase")
_register(
    "Proper",
    "F.initcap({0})",
    "INITCAP({0})",
    1,
    1,
    notes="Alias for TitleCase — capitalizes first letter of each word",
)
_register("IF", "F.when({0}, {1}).otherwise({2})", "CASE WHEN {0} THEN {1} ELSE {2} END", 3, 3, notes="Alias for IIF")
_register(
    "ToInt32",
    "F.try_cast({0}, 'int')",
    "TRY_CAST({0} AS INT)",
    1,
    1,
    notes="Alias for ToInteger; null-on-failure (Alteryx semantics)",
)
_register(
    "ToInt64", "F.try_cast({0}, 'long')", "TRY_CAST({0} AS BIGINT)", 1, 1, notes="null-on-failure (Alteryx semantics)"
)
_register(
    "ToDouble",
    "F.try_cast({0}, 'double')",
    "TRY_CAST({0} AS DOUBLE)",
    1,
    1,
    notes="Alias for ToNumber; null-on-failure (Alteryx semantics)",
)

# ---------------------------------------------------------------------------
# Base conversion functions
# ---------------------------------------------------------------------------
_register(
    "ConvertFromBase",
    "F.conv({0}, {1}, 10)",
    "CONV({0}, {1}, 10)",
    2,
    2,
    notes="Convert number from given base to base-10",
)
_register(
    "ConvertToBase", "F.conv({0}, 10, {1})", "CONV({0}, 10, {1})", 2, 2, notes="Convert base-10 number to target base"
)
_register(
    "HexToBinary",
    "F.bin(F.conv({0}, 16, 10).cast('long'))",
    "BIN(CONV({0}, 16, 10))",
    1,
    1,
    notes="Convert hexadecimal string to binary string",
)
_register(
    "BinaryToHex",
    "F.hex(F.conv({0}, 2, 10).cast('long'))",
    "HEX(CONV({0}, 2, 10))",
    1,
    1,
    notes="Convert binary string to hexadecimal string",
)

# ---------------------------------------------------------------------------
# Additional string functions
# ---------------------------------------------------------------------------
_register(
    "StripAccents",
    "F.translate({0}, F.lit('àáâãäåèéêëìíîïòóôõöùúûüýñçÀÁÂÃÄÅÈÉÊËÌÍÎÏÒÓÔÕÖÙÚÛÜÝÑÇ'), F.lit('aaaaaaeeeeiiiioooooouuuuyncAAAAAAEEEEIIIIOOOOOUUUUYNC'))",
    "TRANSLATE({0}, 'àáâãäåèéêëìíîïòóôõöùúûüýñçÀÁÂÃÄÅÈÉÊËÌÍÎÏÒÓÔÕÖÙÚÛÜÝÑÇ', 'aaaaaaeeeeiiiioooooouuuuyncAAAAAAEEEEIIIIOOOOOUUUUYNC')",
    1,
    1,
    notes="Removes diacritics by translating accented characters to ASCII equivalents. Covers common Latin accents only.",
)

# ---------------------------------------------------------------------------
# Additional math functions — combinatorics
# ---------------------------------------------------------------------------
_register(
    "BinomCoeff",
    "__SQLEXPR__factorial({0}) / (factorial({1}) * factorial({0} - {1}))",
    "(FACTORIAL({0}) / (FACTORIAL({1}) * FACTORIAL({0} - {1})))",
    2,
    2,
    notes="Binomial coefficient C(n, k) = n! / (k! * (n-k)!). Alteryx name: BinomCoeff.",
)
_register(
    "Comb",
    "__SQLEXPR__factorial({0}) / (factorial({1}) * factorial({0} - {1}))",
    "(FACTORIAL({0}) / (FACTORIAL({1}) * FACTORIAL({0} - {1})))",
    2,
    2,
    notes="Combinations C(n, k) — alias for BinomCoeff",
)
_register(
    "Perm",
    "__SQLEXPR__factorial({0}) / factorial({0} - {1})",
    "(FACTORIAL({0}) / FACTORIAL({0} - {1}))",
    2,
    2,
    notes="Permutations P(n, k) = n! / (n-k)!",
)


def get_function_mapping(name: str) -> FunctionMapping | None:
    """Look up a function mapping by (case-insensitive) Alteryx name.

    Returns ``None`` when the function is not in the registry.
    """
    return FUNCTION_REGISTRY.get(name.lower())

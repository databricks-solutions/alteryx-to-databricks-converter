"""CLI entry point for the Alteryx-to-Databricks migration tool."""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.console import Console
from rich.table import Table

from a2d.__about__ import __version__
from a2d.config import ConversionConfig, OutputFormat
from a2d.utils.logging import setup_logging

if TYPE_CHECKING:
    from a2d.analyzer.readiness import WorkflowAnalysis
    from a2d.observability.batch import BatchConversionResult
    from a2d.pipeline import ConversionResult


# User-friendly labels for output format IDs (mirrors frontend FORMAT_LABELS).
_FORMAT_LABELS: dict[str, str] = {
    "pyspark": "PySpark",
    "dlt": "Spark Declarative Pipelines",
    "sql": "Spark SQL",
    "lakeflow": "Lakeflow Designer",
}


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"a2d v{__version__}")
        raise typer.Exit()


app = typer.Typer(
    name="a2d",
    add_completion=True,
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Show version and exit",
    ),
) -> None:
    """Alteryx to Databricks migration accelerator.

    Quick-start examples:

      a2d analyze  workflows/                  # Migration readiness report

      a2d convert  my.yxmd                     # Emit ALL 4 formats (default)

      a2d convert  my.yxmd -f pyspark          # Filter to PySpark only

      a2d convert  my.yxmd -f pyspark,sql      # Filter to PySpark + SQL

      a2d convert  workflows/ -b               # Batch all formats with progress

      a2d list-tools --supported               # Show supported tool matrix

      a2d version                              # Print a2d version
    """


@app.command()
def convert(
    # -- Core I/O --
    input_path: Path = typer.Argument(..., help="Path to .yxmd/.yxmc file or directory"),
    output_dir: Path = typer.Option(
        "./a2d-output", "--output-dir", "-o", help="Output directory", rich_help_panel="Core Options"
    ),
    format: str = typer.Option(
        "all",
        "--format",
        "-f",
        help=(
            "Comma-separated formats: 'all' (default — emits all 4), or any of "
            "pyspark,dlt,sql,lakeflow "
            "(dlt = Spark Declarative Pipelines, lakeflow = Lakeflow Designer)"
        ),
        rich_help_panel="Core Options",
    ),
    # -- Databricks target --
    catalog: str = typer.Option("main", help="Unity Catalog name", rich_help_panel="Databricks Target"),
    schema: str = typer.Option("default", help="Schema name", rich_help_panel="Databricks Target"),
    connection_map: Path | None = typer.Option(
        None, "--connection-map", help="Path to connection mapping YAML", rich_help_panel="Databricks Target"
    ),
    cloud: str = typer.Option(
        "aws",
        "--cloud",
        help=(
            "Target cloud for cluster sizing (aws|azure|gcp) [default: aws]. "
            "Drives the auto-generated `node_type_id` in the Workflow JSON and "
            "DAB outputs (aws=i3.xlarge, azure=Standard_DS3_v2, gcp=n1-highmem-4)."
        ),
        rich_help_panel="Databricks Target",
    ),
    # -- Code generation options --
    orchestration: bool = typer.Option(
        True, "--orchestration/--no-orchestration", help="Generate workflow JSON", rich_help_panel="Code Generation"
    ),
    comments: bool = typer.Option(
        True, "--comments/--no-comments", help="Include explanatory comments", rich_help_panel="Code Generation"
    ),
    verbose_unsupported: bool = typer.Option(
        False,
        "--verbose-unsupported",
        help="Emit detailed TODO stubs for unsupported nodes",
        rich_help_panel="Code Generation",
    ),
    expand_macros: bool = typer.Option(
        False, "--expand-macros", help="Expand macro references as functions", rich_help_panel="Code Generation"
    ),
    # -- Observability --
    expression_audit: bool = typer.Option(
        True,
        "--expression-audit/--no-expression-audit",
        help="Generate expression audit CSV",
        rich_help_panel="Observability",
    ),
    performance_hints: bool = typer.Option(
        True,
        "--performance-hints/--no-performance-hints",
        help="Include performance optimization hints",
        rich_help_panel="Observability",
    ),
    # -- Extra artefacts --
    generate_ddl: bool = typer.Option(
        False,
        "--generate-ddl",
        help="Generate Unity Catalog DDL (requires --connection-map)",
        rich_help_panel="Extra Artifacts",
    ),
    generate_dab: bool = typer.Option(
        False, "--generate-dab", help="Generate Databricks Asset Bundle project", rich_help_panel="Extra Artifacts"
    ),
    # -- Batch mode --
    batch: bool = typer.Option(
        False, "--batch", "-b", help="Enable batch mode with structured error tracking", rich_help_panel="Batch Mode"
    ),
    report_format: str = typer.Option(
        "html", "--report-format", help="Batch report format: json, jsonl, html, all", rich_help_panel="Batch Mode"
    ),
    # -- Debugging --
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress info messages (warnings only)"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
) -> None:
    """Convert Alteryx workflows to Databricks code.

    By default emits ALL four output formats (pyspark, dlt, sql, lakeflow) into
    per-format subdirectories. Use --format to restrict to a subset, e.g.
    --format pyspark or --format pyspark,sql.

    After conversion the CLI prints (mirroring the web UI's Convert page):

      - a deploy-status banner (Ready to deploy / Needs review / Cannot deploy
        as-is) with a plain-English explanation,
      - a one-line counts row (coverage, confidence, nodes converted, nodes
        needing review, nodes that cannot convert),
      - warnings grouped by category — Cannot convert (blocker), Manual
        review needed, Graph structure note — instead of a flat dump.
    """
    setup_logging(quiet=quiet, debug=debug)

    # Resolve --format into a list of OutputFormat values
    try:
        formats = _parse_formats(format)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from None

    # Validate --cloud up front so users get a clear error before we touch IO.
    cloud_normalized = (cloud or "").strip().lower()
    if cloud_normalized not in ("aws", "azure", "gcp"):
        console.print(f"[red]Invalid --cloud value: {cloud!r}. Valid: aws, azure, gcp[/red]")
        raise typer.Exit(code=1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Warn about flags that only apply to single-file mode
    if input_path.is_dir() and not batch:
        ignored = []
        if generate_ddl:
            ignored.append("--generate-ddl")
        if generate_dab:
            ignored.append("--generate-dab")
        if expression_audit:
            ignored.append("--expression-audit")
        if ignored:
            console.print(
                f"[yellow]Warning: {', '.join(ignored)} ignored in directory mode (use --batch for structured output)[/yellow]"
            )

    # Show active optional features
    features = []
    if expression_audit:
        features.append("expression audit")
    if performance_hints:
        features.append("performance hints")
    if generate_ddl:
        features.append("DDL generation")
    if generate_dab:
        features.append("DAB generation")
    if features:
        console.print(f"[dim]Active: {', '.join(features)}[/dim]")

    fmt_list = ", ".join(f.value for f in formats)
    console.print(f"[dim]Formats: {fmt_list}[/dim]")

    def _build_config(fmt: OutputFormat) -> ConversionConfig:
        return ConversionConfig(
            input_path=input_path,
            output_dir=output_dir,
            output_format=fmt,
            catalog_name=catalog,
            schema_name=schema,
            generate_orchestration=orchestration,
            include_comments=comments,
            verbose_unsupported=verbose_unsupported,
            connection_mapping_path=connection_map,
            include_expression_audit=expression_audit,
            include_performance_hints=performance_hints,
            generate_ddl=generate_ddl,
            generate_dab=generate_dab,
            expand_macros=expand_macros,
            cloud=cloud_normalized,  # type: ignore[arg-type]
        )

    if batch and input_path.is_dir():
        # Batch mode: parse each .yxmd ONCE and run all requested generators
        # in a single pass via BatchOrchestrator.convert_batch_multi_format.
        # Mirrors server/services/batch.py:_run_batch. The multi-format path
        # keeps the legacy single-format `convert_batch` intact for back-compat.
        shared_cfg = _build_config(OutputFormat.PYSPARK)
        try:
            per_format_results = _run_batch_multi_format(shared_cfg, input_path, output_dir, report_format, formats)
        except Exception as e:
            console.print(f"[red]Batch failed: {e}[/red]")
            raise typer.Exit(code=1) from e
        _print_format_status_table(per_format_results, output_dir)
        if all(not ok for _, ok, _ in per_format_results):
            raise typer.Exit(code=1)
    elif input_path.is_file():
        # Single-file path: parse + build DAG once, then run all 4 generators.
        # This mirrors server/services/conversion.py:convert_file and avoids the
        # ~4x cost of re-parsing IR for each format.
        from a2d.pipeline import ConversionPipeline, ConversionResult

        # One ConversionConfig is enough — convert_all_formats picks the
        # generator class per-format, so config.output_format is only used by
        # the orchestration WorkflowJsonGenerator (which switches on it).
        # PYSPARK is a sensible default, mirroring server/services/conversion.py.
        shared_cfg = _build_config(OutputFormat.PYSPARK)

        t_total = time.monotonic()
        try:
            with console.status(f"[bold]Converting {input_path.name} (all formats)...[/bold]"):
                pipeline = ConversionPipeline(shared_cfg)
                multi_result = pipeline.convert_all_formats(input_path)
        except Exception as e:
            elapsed_total = time.monotonic() - t_total
            console.print(f"[red]Failed to parse {input_path.name} after {elapsed_total:.1f}s: {e}[/red]")
            raise typer.Exit(code=1) from e
        elapsed_total = time.monotonic() - t_total

        # DDL/DAB are format-agnostic — generate ONCE and append into each
        # successful format's output subdir, mirroring the server path.
        ddl_extra = []
        if generate_ddl:
            try:
                from a2d.generators.unity_catalog import UnityCatalogGenerator

                ddl_gen = UnityCatalogGenerator(shared_cfg)
                ddl_extra = ddl_gen.generate_ddl(multi_result.dag)
            except Exception as e:
                console.print(f"[yellow]DDL generation failed: {e}[/yellow]")

        # Filter to user-requested formats; warn if some requested formats
        # aren't in the result (shouldn't happen — convert_all_formats always
        # returns all 4 — but be defensive).
        per_format: list[tuple[OutputFormat, bool, str, ConversionResult | None, float]] = []
        succeeded_formats: list[OutputFormat] = []

        for fmt in formats:
            fr = multi_result.formats.get(fmt.value)
            if fr is None:
                per_format.append((fmt, False, "format not produced", None, 0.0))
                continue

            sub_out = output_dir / fmt.value
            sub_out.mkdir(parents=True, exist_ok=True)

            # Per-format duration is recorded inside MultiFormatConversionResult
            # by convert_all_formats — covers the generator + post-processing
            # only, NOT the shared parse / DAG-build (that's reported as
            # "Total wall-clock" further down). Fall back to total/N if a
            # FormatConversionResult lacks duration_ms (older fixtures, etc.).
            fmt_elapsed = fr.duration_ms / 1000.0 if fr.duration_ms else elapsed_total / max(len(formats), 1)

            if fr.status == "success" and fr.output is not None:
                succeeded_formats.append(fmt)
                # Build a ConversionResult-shaped wrapper so existing helpers
                # (_write_output, _print_conversion_summary, _print_performance_hints)
                # work unchanged.
                wrapped = ConversionResult(
                    output=fr.output,
                    dag=multi_result.dag,
                    parsed_workflow=multi_result.parsed_workflow,
                    warnings=list(fr.warnings),
                    confidence=fr.confidence,
                    expression_audit=multi_result.expression_audit,
                    performance_hints=multi_result.performance_hints,
                )
                _write_output(wrapped.output, sub_out)
                _print_conversion_summary(
                    wrapped,
                    input_path,
                    fmt_elapsed,
                    fmt=fmt.value,
                    workflow_warnings=list(multi_result.warnings),
                )

                # Expression audit CSV — emit per-format (audit data is shared)
                if multi_result.expression_audit:
                    from a2d.observability.expression_audit import write_audit_csv

                    audit_path = sub_out / f"{input_path.stem}_expression_audit.csv"
                    write_audit_csv(multi_result.expression_audit, audit_path)
                    console.print(f"  Expression audit: {audit_path}")

                # DDL files (generated once, copied into every successful format)
                for f in ddl_extra:
                    path = sub_out / f.filename
                    path.write_text(f.content)
                    console.print(f"  DDL: {path}")

                # DAB files: generated per-format using that format's output
                if generate_dab:
                    try:
                        from a2d.generators.dab import DABGenerator

                        dab_gen = DABGenerator(shared_cfg)
                        dab_files = dab_gen.generate(multi_result.dag, input_path.stem, fr.output)
                        dab_dir = sub_out / f"{input_path.stem}_dab"
                        dab_dir.mkdir(parents=True, exist_ok=True)
                        for f in dab_files:
                            path = dab_dir / f.filename
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text(f.content)
                            console.print(f"  DAB: {path}")
                    except Exception as e:
                        console.print(f"[yellow]DAB generation failed for {fmt.value}: {e}[/yellow]")

                per_format.append((fmt, True, "", wrapped, fmt_elapsed))
            else:
                err = fr.error or "unknown error"
                console.print(f"[red]Failed to generate {fmt.value}: {err}[/red]")
                per_format.append((fmt, False, err, None, fmt_elapsed))

        # Print performance hints once (shared across formats)
        if multi_result.performance_hints:
            _print_performance_hints(multi_result.performance_hints)

        # Compute top-level coverage from best_format (mirrors server
        # response.coverage). Fall back to the first successful format if
        # best_format wasn't selected.
        top_coverage = _compute_top_coverage(multi_result, succeeded_formats)

        # Final summary table across formats
        _print_multi_format_summary(
            per_format,
            output_dir,
            total_elapsed=elapsed_total,
            best_format=multi_result.best_format,
            top_coverage=top_coverage,
            workflow_warnings=list(multi_result.warnings),
        )

        if all(not ok for _, ok, _, _, _ in per_format):
            raise typer.Exit(code=1)

    elif input_path.is_dir():
        yxmd_files = sorted(input_path.glob("**/*.yxmd"))
        yxmd_count = len(yxmd_files)
        if yxmd_count == 0:
            console.print(f"[yellow]No .yxmd files found in {input_path}[/yellow]")
            console.print("[dim]Ensure the directory contains Alteryx .yxmd workflow files.[/dim]")
            raise typer.Exit(code=1)

        console.print(f"Found {yxmd_count} .yxmd file{'s' if yxmd_count != 1 else ''} in {input_path}.")
        console.print(
            "[dim]Tip: Use -b (--batch) for per-file error tracking, coverage reports, and HTML summaries.[/dim]"
        )

        from a2d.pipeline import ConversionPipeline

        # Single shared config — convert_all_formats is format-agnostic.
        shared_cfg = _build_config(OutputFormat.PYSPARK)
        pipeline = ConversionPipeline(shared_cfg)

        # Per-format success counts so the final status table is accurate.
        per_format_counts: dict[str, int] = {f.value: 0 for f in formats}
        per_format_errors: dict[str, list[str]] = {f.value: [] for f in formats}
        files_processed = 0
        files_failed = 0

        for yxmd in yxmd_files:
            try:
                multi_result = pipeline.convert_all_formats(yxmd)
            except Exception as e:
                files_failed += 1
                console.print(f"[red]Failed to parse {yxmd.name}: {e}[/red]")
                for fmt in formats:
                    per_format_errors[fmt.value].append(yxmd.name)
                continue

            files_processed += 1
            for fmt in formats:
                fr = multi_result.formats.get(fmt.value)
                if fr is None or fr.status != "success" or fr.output is None:
                    err = fr.error if fr and fr.error else "no output"
                    per_format_errors[fmt.value].append(f"{yxmd.name}: {err}")
                    continue
                sub_out = output_dir / fmt.value / yxmd.stem
                sub_out.mkdir(parents=True, exist_ok=True)
                _write_output(fr.output, sub_out)
                per_format_counts[fmt.value] += 1

        console.print(f"\n[green]Processed {files_processed}/{len(yxmd_files)} workflow(s).[/green]")

        per_format_results = []
        for fmt in formats:
            ok_count = per_format_counts[fmt.value]
            errs = per_format_errors[fmt.value]
            ok = ok_count > 0
            note = f"{ok_count} file(s) ok"
            if errs:
                note += f"; {len(errs)} failed"
            per_format_results.append((fmt, ok, note))

        _print_format_status_table(per_format_results, output_dir)
        if all(not ok for _, ok, _ in per_format_results):
            raise typer.Exit(code=1)
    else:
        console.print(f"[red]Error: {input_path} not found[/red]")
        console.print(
            "[dim]Check the path and ensure the .yxmd file exists. Run 'a2d list-tools' to verify your installation.[/dim]"
        )
        raise typer.Exit(code=1)


def _parse_formats(spec: str) -> list[OutputFormat]:
    """Parse the --format CLI value into a list of OutputFormat enum values.

    Accepts:
      - "all"                       → all 4 formats
      - "pyspark"                   → single format
      - "pyspark,sql"               → comma-separated subset
      - "pyspark, dlt , lakeflow"   → whitespace tolerated
    Duplicates are de-duplicated; original order preserved.
    """
    if not spec or not spec.strip():
        raise ValueError("--format must be a non-empty value")

    raw = [t.strip().lower() for t in spec.split(",") if t.strip()]
    if not raw:
        raise ValueError("--format must contain at least one format name")

    if any(t == "all" for t in raw):
        if len(raw) > 1:
            console.print("[yellow]Note: 'all' specified alongside other formats — emitting all 4.[/yellow]")
        return list(OutputFormat)

    valid = {f.value for f in OutputFormat}
    seen: set[str] = set()
    formats: list[OutputFormat] = []
    invalid: list[str] = []
    for tok in raw:
        if tok not in valid:
            invalid.append(tok)
            continue
        if tok in seen:
            continue
        seen.add(tok)
        formats.append(OutputFormat(tok))

    if invalid:
        valid_str = ", ".join(sorted(valid)) + ", all"
        raise ValueError(f"Invalid format(s): {', '.join(invalid)}. Valid: {valid_str}")
    return formats


@app.command()
def analyze(
    input_path: Path = typer.Argument(..., help="Path to .yxmd file or directory"),
    output_dir: Path = typer.Option("./a2d-report", "--output-dir", "-o", help="Report output directory"),
    format: str = typer.Option("html", help="Report format: html, json, both"),
    complexity: bool = typer.Option(False, "--complexity", help="Show per-workflow complexity breakdown"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress info messages (warnings only)"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
) -> None:
    """Analyze Alteryx workflows and generate migration readiness report."""
    setup_logging(quiet=quiet, debug=debug)

    from a2d.analyzer.batch import BatchAnalyzer
    from a2d.analyzer.report import ReportGenerator

    output_dir.mkdir(parents=True, exist_ok=True)

    analyzer = BatchAnalyzer()
    if input_path.is_file():
        results = analyzer.analyze_files([input_path])
    elif input_path.is_dir():
        files = sorted(input_path.glob("**/*.yxmd"))
        results = analyzer.analyze_files(files)
    else:
        console.print(f"[red]Error: {input_path} not found[/red]")
        console.print("[dim]Check the path and ensure it points to a .yxmd file or directory.[/dim]")
        raise typer.Exit(code=1)

    report_gen = ReportGenerator()
    if format in ("html", "both"):
        report_gen.generate_html(results, output_dir / "migration_report.html")
    if format in ("json", "both"):
        report_gen.generate_json(results, output_dir / "migration_report.json")

    if complexity:
        _print_complexity_breakdown(results)

    console.print(f"\n[bold green]Report generated[/bold green] at {output_dir}")


@app.command()
def validate(
    generated_code: Path = typer.Argument(..., help="Generated .py file to validate"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress info messages (warnings only)"),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging"),
) -> None:
    """Validate generated code syntax."""
    setup_logging(quiet=quiet, debug=debug)

    from a2d.validation.syntax_validator import SyntaxValidator

    validator = SyntaxValidator()
    result = validator.validate_file(generated_code)

    if result.is_valid:
        console.print(f"[bold green]Valid[/bold green]: {generated_code}")
    else:
        console.print(f"[bold red]Invalid[/bold red]: {generated_code}")
        for error in result.errors:
            console.print(f"  - {error}")
        raise typer.Exit(code=1)


@app.command(name="list-tools")
def list_tools(
    supported_only: bool = typer.Option(False, "--supported", "-s", help="Show only supported tools"),
) -> None:
    """List all known Alteryx tools and their conversion status."""
    from a2d.converters.registry import ConverterRegistry
    from a2d.parser.schema import PLUGIN_NAME_MAP, TOOL_METADATA

    supported = ConverterRegistry.supported_tools()

    table = Table(title="Alteryx Tool Support Matrix")
    table.add_column("Tool Type", style="cyan")
    table.add_column("Category", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Method", style="blue")
    table.add_column("Description", style="white", max_width=55)

    seen: set[str] = set()
    for _plugin, (tool_type, category) in sorted(PLUGIN_NAME_MAP.items(), key=lambda x: (x[1][1], x[1][0])):
        if tool_type in seen:
            continue
        seen.add(tool_type)
        is_supported = tool_type in supported
        if supported_only and not is_supported:
            continue
        status = "[green]Supported[/green]" if is_supported else "[yellow]Unsupported[/yellow]"
        meta = TOOL_METADATA.get(tool_type)
        method = meta.conversion_method if meta else "-"
        desc = meta.short_description if meta else "-"
        table.add_row(tool_type, category, status, method, desc)

    console.print(table)
    console.print(
        f"\n{len(supported)} of {len(set(t for t, _ in PLUGIN_NAME_MAP.values()))} unique tool types supported"
    )


@app.command()
def version() -> None:
    """Show version."""
    console.print(f"a2d v{__version__}")


# ── Helper functions ──────────────────────────────────────────────────

_FILE_DESCRIPTIONS: dict[str, str] = {
    "_workflow.json": "Databricks workflow definition",
    "_expression_audit.csv": "Expression transformation audit",
    "_lakeflow_pipeline.json": "Lakeflow pipeline config",
    ".py": "PySpark notebook",
    ".sql": "SQL script",
}


def _describe_file(filename: str) -> str:
    for suffix, desc in _FILE_DESCRIPTIONS.items():
        if filename.endswith(suffix):
            return desc
    return ""


# ── Categorized warnings + deploy banner (mirror of UI Convert page) ────


def _print_deploy_banner(
    *,
    workflow_warnings: list[str],
    best_format_warnings: list[str],
    formats_status: dict[str, str],
    best_format: str | None,
    coverage: float | None,
    confidence: float | None,
) -> None:
    """Print the 3-tier deploy-readiness banner (Ready / Needs review / Cannot deploy).

    Calls into :func:`a2d.observability.deploy_status.derive_deploy_status` so
    the CLI uses the exact same rule the UI does.
    """
    from a2d.observability.deploy_status import (
        deploy_status_explanation,
        derive_deploy_status,
    )

    status = derive_deploy_status(
        coverage=coverage,
        confidence=confidence,
        formats_status=formats_status,
        workflow_warnings=workflow_warnings,
        best_format_warnings=best_format_warnings,
        best_format=best_format,
    )
    explanation = deploy_status_explanation(status)
    if status == "ready":
        console.print(f"[bold green]✓ Ready to deploy[/bold green]  {explanation}")
    elif status == "needs_review":
        console.print(f"[bold yellow]⚠ Needs review[/bold yellow]  {explanation}")
    else:
        console.print(f"[bold red]✗ Cannot deploy as-is[/bold red]  {explanation}")


def _print_counts_row(
    *,
    coverage: float | None,
    confidence: float | None,
    supported: int,
    total: int,
    workflow_warnings: list[str],
    best_format_warnings: list[str],
    best_format_label: str | None = None,
    all_format_warnings: list[list[str]] | None = None,
) -> None:
    """Print the single-line counts row: coverage · confidence · review · blockers.

    Counts aggregate across workflow + every per-format warning list (deduped
    by node id) so the row doesn't contradict the per-format tabs. If
    ``all_format_warnings`` is omitted, falls back to workflow + best-format
    only (legacy behaviour for callers that don't have all formats handy).
    """
    from a2d.observability.warning_categorization import (
        categorize_across_all_formats,
        categorize_for_format,
    )

    if all_format_warnings is not None:
        cats = categorize_across_all_formats(workflow_warnings, all_format_warnings)
    else:
        cats = categorize_for_format(workflow_warnings, best_format_warnings)
    blocker_n = len({w.node_id for w in cats.unsupported if w.node_id is not None})
    review_n = cats.manual_review_node_count - blocker_n
    if review_n < 0:
        review_n = 0

    parts: list[str] = []
    if coverage is not None:
        parts.append(f"Coverage [bold]{coverage:.0f}%[/bold]")
    if confidence is not None:
        parts.append(f"Confidence [bold]{confidence:.0f}/100[/bold]")
    if total > 0:
        parts.append(f"[bold]{supported}/{total}[/bold] tools converted")
    review_color = "yellow" if review_n else "dim"
    parts.append(f"[{review_color}]{review_n} nodes need review[/{review_color}]")
    blocker_color = "red" if blocker_n else "dim"
    parts.append(f"[{blocker_color}]{blocker_n} cannot convert[/{blocker_color}]")

    console.print("  " + " · ".join(parts))
    if best_format_label:
        console.print(f"  [dim]Best format: {best_format_label}[/dim]")


def _print_categorized_warnings(
    *,
    workflow_warnings: list[str],
    format_warnings: list[str],
    format_label: str | None = None,
) -> None:
    """Print warnings grouped into Cannot convert / Manual review / Graph note buckets."""
    from a2d.observability.warning_categorization import categorize_for_format

    cats = categorize_for_format(workflow_warnings, format_warnings)
    if cats.total == 0:
        return

    suffix = f" (best format: {format_label})" if format_label else ""

    # 1. Cannot convert (blockers).
    if cats.unsupported:
        console.print(f"\n[bold red]✗ Cannot convert ({len(cats.unsupported)})[/bold red]")
        for w in cats.unsupported[:12]:
            console.print(f"  [red]•[/red] {w.title}")
            console.print(f"    [dim]{w.detail}[/dim]")
        if len(cats.unsupported) > 12:
            console.print(f"  [dim]… and {len(cats.unsupported) - 12} more blocker(s)[/dim]")

    # 2. Manual review needed.
    if cats.review:
        console.print(f"\n[bold yellow]⚠ Manual review needed ({len(cats.review)}){suffix}[/bold yellow]")
        for w in cats.review[:15]:
            console.print(f"  [yellow]•[/yellow] {w.title}")
        if len(cats.review) > 15:
            console.print(f"  [dim]… and {len(cats.review) - 15} more review item(s)[/dim]")

    # 3. Graph structure note.
    if cats.graph:
        console.print("\n[bold blue]ℹ Graph structure note[/bold blue]")
        for w in cats.graph:
            console.print(f"  [blue]•[/blue] {w.title}")
            if w.components:
                preview = ", ".join(
                    "[" + ", ".join(str(n) for n in comp[:5]) + ("…" if len(comp) > 5 else "") + "]"
                    for comp in w.components[:3]
                )
                more = f" (+{len(w.components) - 3} more)" if len(w.components) > 3 else ""
                console.print(f"    [dim]Components: {preview}{more}[/dim]")
            console.print(f"    [dim]{w.detail}[/dim]")

    # 4. Other / unrecognised.
    if cats.other:
        console.print(f"\n[bold]Other warnings ({len(cats.other)})[/bold]")
        for w in cats.other[:8]:
            console.print(f"  • {w.raw}")
        if len(cats.other) > 8:
            console.print(f"  [dim]… and {len(cats.other) - 8} more[/dim]")


def _write_output(output, output_dir: Path) -> None:
    """Write all generated files to the output directory and validate Python syntax."""
    from a2d.validation.syntax_validator import SyntaxValidator

    validator = SyntaxValidator()
    for f in output.files:
        path = output_dir / f.filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f.content)
        desc = _describe_file(f.filename)
        label = f" — {desc}" if desc else ""
        console.print(f"  Written: {path}{label}")
        if path.suffix == ".py":
            result = validator.validate_file(path)
            if not result.is_valid:
                console.print(f"  [red]x Python syntax error[/red]: {path.name}")
                for err in result.errors:
                    console.print(f"    {err}")


def _run_batch_conversion(config: ConversionConfig, input_path: Path, output_dir: Path, report_format: str) -> None:
    """Run batch conversion with structured error tracking and outcome reports."""
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn

    from a2d.observability.batch import BatchOrchestrator
    from a2d.observability.report import OutcomeReportGenerator

    file_paths = sorted(input_path.glob("**/*.yxmd"))
    if not file_paths:
        console.print(f"[yellow]No .yxmd files found in {input_path}[/yellow]")
        return

    orchestrator = BatchOrchestrator(config)

    with Progress(
        SpinnerColumn(),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Converting...", total=len(file_paths))

        def on_progress(current: int, total: int, filename: str) -> None:
            progress.update(task, completed=current, description=f"Converting {filename}")

        batch_result = orchestrator.convert_batch(file_paths, progress_callback=on_progress)

    # Write output files for successful conversions
    for fr in batch_result.file_results:
        if fr.success and fr.conversion_result:
            name = fr.workflow_name
            subdir = output_dir / name
            subdir.mkdir(parents=True, exist_ok=True)
            _write_output(fr.conversion_result.output, subdir)

    # Generate outcome reports
    report_gen = OutcomeReportGenerator()
    if report_format in ("json", "all"):
        report_gen.generate_json(batch_result, output_dir / "batch_report.json")
    if report_format in ("jsonl", "all"):
        report_gen.generate_jsonl(batch_result, output_dir / "batch_report.jsonl")
    if report_format in ("html", "all"):
        report_gen.generate_html(batch_result, output_dir / "batch_report.html")

    _print_batch_summary(batch_result, output_dir)


def _run_batch_multi_format(
    config: ConversionConfig,
    input_path: Path,
    output_dir: Path,
    report_format: str,
    formats: list[OutputFormat],
) -> list[tuple[OutputFormat, bool, str]]:
    """Run multi-format batch conversion (parse each file once, run all generators).

    Returns the per-format ``(fmt, ok, note)`` tuple list expected by
    ``_print_format_status_table`` so the caller's exit-code logic stays put.
    """
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
    )

    from a2d.observability.batch import BatchOrchestrator
    from a2d.observability.report import OutcomeReportGenerator

    file_paths = sorted(input_path.glob("**/*.yxmd"))
    if not file_paths:
        console.print(f"[yellow]No .yxmd files found in {input_path}[/yellow]")
        return [(fmt, False, "no files") for fmt in formats]

    orchestrator = BatchOrchestrator(config)

    with Progress(
        SpinnerColumn(),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Converting...", total=len(file_paths))

        def on_progress(current: int, total: int, filename: str) -> None:
            progress.update(task, completed=current, description=f"Converting {filename}")

        batch_result = orchestrator.convert_batch_multi_format(file_paths, progress_callback=on_progress)

    # Write output files: ALL requested formats per file, into per-format subdirs.
    requested = {f.value for f in formats}
    for fr in batch_result.file_results:
        if fr.multi_result is None:
            continue
        for fmt_key, fmt_res in fr.multi_result.formats.items():
            if fmt_key not in requested:
                continue
            if fmt_res.status != "success" or fmt_res.output is None:
                continue
            subdir = output_dir / fmt_key / fr.workflow_name
            subdir.mkdir(parents=True, exist_ok=True)
            _write_output(fmt_res.output, subdir)

    # Generate outcome reports — at the top level (covers all formats).
    report_gen = OutcomeReportGenerator()
    if report_format in ("json", "all"):
        report_gen.generate_json_multi(batch_result, output_dir / "batch_report.json")
    if report_format in ("jsonl", "all"):
        report_gen.generate_jsonl_multi(batch_result, output_dir / "batch_report.jsonl")
    if report_format in ("html", "all"):
        report_gen.generate_html_multi(batch_result, output_dir / "batch_report.html")

    # Mirror under each per-format subdir so existing batch test contracts
    # (e.g. ``out/pyspark/batch_report.json``) keep finding a report there.
    # These are duplicates of the top-level report — the multi-format report
    # is intrinsically the same regardless of which format subdir you look in.
    for fmt in formats:
        sub = output_dir / fmt.value
        sub.mkdir(parents=True, exist_ok=True)
        if report_format in ("json", "all"):
            report_gen.generate_json_multi(batch_result, sub / "batch_report.json")
        if report_format in ("jsonl", "all"):
            report_gen.generate_jsonl_multi(batch_result, sub / "batch_report.jsonl")
        if report_format in ("html", "all"):
            report_gen.generate_html_multi(batch_result, sub / "batch_report.html")

    _print_multi_batch_summary(batch_result, output_dir)

    # Build the per-format (fmt, ok, note) tuples for the caller.
    per_fmt_counts = batch_result.per_format_success_counts()
    out: list[tuple[OutputFormat, bool, str]] = []
    for fmt in formats:
        ok_count = per_fmt_counts.get(fmt.value, 0)
        total = len(batch_result.file_results)
        ok = ok_count > 0
        note = f"{ok_count}/{total} file(s) ok"
        out.append((fmt, ok, note))
    return out


def _print_multi_batch_summary(result, output_dir: Path) -> None:
    """Print a summary table for multi-format batch conversion."""
    bm = result.batch_metrics

    console.print("\n[bold]Multi-Format Batch Conversion Summary[/bold]")

    summary_table = Table(show_header=False, box=None)
    summary_table.add_column("Key", style="cyan")
    summary_table.add_column("Value")
    summary_table.add_row("Total files", str(bm.total_files))
    summary_table.add_row("All formats OK", f"[green]{bm.successful_files}[/green]")
    summary_table.add_row("Partial", f"[yellow]{bm.partial_files}[/yellow]")
    summary_table.add_row("Failed", f"[red]{bm.failed_files}[/red]")
    summary_table.add_row("Duration", f"{bm.duration_seconds:.2f}s")
    summary_table.add_row("Avg coverage", f"{bm.avg_coverage_percentage:.0f}%")
    summary_table.add_row("Total errors", str(bm.total_errors))
    summary_table.add_row("Total warnings", str(bm.total_warnings))
    console.print(summary_table)

    per_fmt_counts = result.per_format_success_counts()
    file_table = Table(title="Per-File x Per-Format Outcomes")
    file_table.add_column("Workflow", style="cyan")
    file_table.add_column("PySpark", justify="center")
    file_table.add_column("DLT", justify="center")
    file_table.add_column("SQL", justify="center")
    file_table.add_column("Lakeflow", justify="center")
    file_table.add_column("Best", justify="left")
    file_table.add_column("Coverage", justify="right")
    file_table.add_column("Duration", justify="right")
    for fr in result.file_results:
        cells: list[str] = []
        for fmt_key in ("pyspark", "dlt", "sql", "lakeflow"):
            status = fr.format_status(fmt_key)
            if status == "success":
                cells.append("[green]OK[/green]")
            elif status == "failed":
                cells.append("[red]FAIL[/red]")
            else:
                cells.append("[dim]-[/dim]")
        best = fr.multi_result.best_format if fr.multi_result is not None and fr.multi_result.best_format else "-"
        file_table.add_row(
            fr.workflow_name,
            *cells,
            best,
            f"{fr.metrics.coverage_percentage:.0f}%",
            f"{fr.metrics.duration_seconds:.2f}s",
        )
    console.print(file_table)

    counts_line = " · ".join(
        f"[bold]{fmt}[/bold] {per_fmt_counts.get(fmt, 0)}/{bm.total_files}"
        for fmt in ("pyspark", "dlt", "sql", "lakeflow")
    )
    console.print(f"  {counts_line}")
    console.print(f"\n[bold green]Output written to {output_dir}[/bold green]")


def _print_batch_summary(result: BatchConversionResult, output_dir: Path) -> None:
    """Print a summary table of batch conversion results."""
    bm = result.batch_metrics

    console.print("\n[bold]Batch Conversion Summary[/bold]")

    summary_table = Table(show_header=False, box=None)
    summary_table.add_column("Key", style="cyan")
    summary_table.add_column("Value")
    summary_table.add_row("Total files", str(bm.total_files))
    summary_table.add_row("Successful", f"[green]{bm.successful_files}[/green]")
    summary_table.add_row("Partial", f"[yellow]{bm.partial_files}[/yellow]")
    summary_table.add_row("Failed", f"[red]{bm.failed_files}[/red]")
    summary_table.add_row("Duration", f"{bm.duration_seconds:.2f}s")
    summary_table.add_row("Avg coverage", f"{bm.avg_coverage_percentage:.0f}%")
    summary_table.add_row("Total errors", str(bm.total_errors))
    summary_table.add_row("Total warnings", str(bm.total_warnings))
    console.print(summary_table)

    # Per-file results table
    if result.file_results:
        file_table = Table(title="Per-File Results")
        file_table.add_column("Workflow", style="cyan")
        file_table.add_column("Status")
        file_table.add_column("Coverage", justify="right")
        file_table.add_column("Errors", justify="right")
        file_table.add_column("Duration", justify="right")
        file_table.add_column("Reason", max_width=60)

        for fr in result.file_results:
            status = "[green]OK[/green]" if fr.success else "[red]FAIL[/red]"
            if fr.success and fr.errors:
                status = "[yellow]PARTIAL[/yellow]"
            error_count = sum(1 for e in fr.errors if e.severity.value == "error")
            # Show first error message for failed/partial conversions
            reason = ""
            if not fr.success and fr.errors:
                first_err = next((e for e in fr.errors if e.severity.value == "error"), fr.errors[0])
                reason = first_err.message[:60] + ("..." if len(first_err.message) > 60 else "")
            file_table.add_row(
                fr.workflow_name,
                status,
                f"{fr.metrics.coverage_percentage:.0f}%",
                str(error_count),
                f"{fr.metrics.duration_seconds:.2f}s",
                reason,
            )
        console.print(file_table)

    console.print(f"\n[bold green]Output written to {output_dir}[/bold green]")


def _print_conversion_summary(
    result,
    input_path: Path,
    elapsed: float | None = None,
    fmt: str | None = None,
    *,
    workflow_warnings: list[str] | None = None,
) -> None:
    """Print a per-format conversion summary with deploy banner + categorized warnings.

    Used for both single-format runs and as the per-format detail block within
    a multi-format run. Mirrors the layout of the Convert page in the UI.

    ``result.warnings`` are treated as the format-specific warnings;
    ``workflow_warnings`` are workflow-level (DAG / parser) warnings that apply
    to every format. The latter is keyword-only because most callers don't have
    them broken out — they degrade gracefully to an empty list.
    """
    dag = result.dag
    output = result.output

    timing = f" ({elapsed:.1f}s)" if elapsed is not None else ""
    fmt_label = f" [{fmt}]" if fmt else ""
    console.print(f"\n[bold]Conversion Summary for {input_path.name}{fmt_label}{timing}[/bold]")

    # `result.warnings` may already include workflow-level entries (legacy
    # single-format pipeline) or only format ones (multi-format wrapper). We
    # union both inputs and dedupe so the same line never prints twice.
    fmt_warnings = list(output.warnings or [])
    for w in result.warnings or []:
        if w not in fmt_warnings:
            fmt_warnings.append(w)
    workflow_warnings_list = list(workflow_warnings or [])

    # Compute the metrics we need for the deploy banner / counts row.
    stats = output.stats
    total = stats.get("total_nodes", 0) or 0
    supported = stats.get("supported_nodes", 0) or 0
    coverage_pct = (supported / total * 100.0) if total > 0 else None
    confidence = result.confidence.overall if result.confidence else None

    # Single-format deploy banner — treat the rendered format as the "best".
    if fmt:
        _print_deploy_banner(
            workflow_warnings=workflow_warnings_list,
            best_format_warnings=fmt_warnings,
            formats_status={fmt: "success"},
            best_format=fmt,
            coverage=coverage_pct,
            confidence=confidence,
        )

    # Counts row.
    _print_counts_row(
        coverage=coverage_pct,
        confidence=confidence,
        supported=supported,
        total=total,
        workflow_warnings=workflow_warnings_list,
        best_format_warnings=fmt_warnings,
        best_format_label=_FORMAT_LABELS.get(fmt, fmt) if fmt else None,
    )

    # Structural details (kept for users who want the raw DAG numbers).
    console.print(
        f"  [dim]DAG: {dag.node_count} nodes, {dag.edge_count} edges · {len(output.files)} files generated[/dim]"
    )

    if result.confidence:
        c = result.confidence
        for dim in c.dimensions:
            label = dim.name.replace("_", " ").title()
            console.print(f"    [dim]{label}: {dim.score:.0f} — {dim.details}[/dim]")

    # Categorized warnings — workflow + format combined, like the UI tabs.
    _print_categorized_warnings(
        workflow_warnings=workflow_warnings_list,
        format_warnings=fmt_warnings,
    )


def _compute_top_coverage(multi_result, succeeded_formats: list[OutputFormat]) -> float | None:
    """Compute top-level coverage from a MultiFormatConversionResult.

    Mirrors `server/services/conversion.py:convert_file` — pulls coverage from
    the best_format's stats. Falls back to the first successful format in
    canonical order if `best_format` wasn't selected.
    """
    if not succeeded_formats:
        return None

    def _coverage_for(fmt_key: str) -> float | None:
        fr = multi_result.formats.get(fmt_key)
        if fr is None or fr.status != "success" or fr.output is None:
            return None
        stats = fr.output.stats
        total = stats.get("total_nodes")
        supported = stats.get("supported_nodes")
        if isinstance(total, int) and total > 0 and isinstance(supported, int):
            return supported / total * 100.0
        return None

    if multi_result.best_format:
        cov = _coverage_for(multi_result.best_format)
        if cov is not None:
            return cov

    for fmt in succeeded_formats:
        cov = _coverage_for(fmt.value)
        if cov is not None:
            return cov
    return None


def _print_multi_format_summary(
    per_format: list[tuple[OutputFormat, bool, str, ConversionResult | None, float]],
    output_dir: Path,
    *,
    total_elapsed: float | None = None,
    best_format: str = "",
    top_coverage: float | None = None,
    workflow_warnings: list[str] | None = None,
) -> None:
    """Print the summary block after a multi-format single-file conversion.

    Layout (mirrors the UI Convert page):
      1. Deploy-status banner + plain-English explanation
      2. Counts row (coverage · confidence · tools converted · review · blocker)
      3. Per-format status table
      4. Categorized warnings (combined workflow + best-format)
      5. Output footer

    Keyword-only args (``total_elapsed``, ``best_format``, ``top_coverage``,
    ``workflow_warnings``) carry the headline data computed from
    ``MultiFormatConversionResult`` so callers can render without re-deriving.
    """
    console.print("\n[bold]Multi-Format Conversion Summary[/bold]")

    # Build the formats_status map needed for the deploy banner.
    formats_status: dict[str, str] = {}
    best_result_obj = None
    for fmt, ok, _err, result_obj, _elapsed in per_format:
        formats_status[fmt.value] = "success" if ok and result_obj is not None else "failed"
        if best_format and fmt.value == best_format and ok and result_obj is not None:
            best_result_obj = result_obj
    # Fallback: use the first successful result if best_format unset.
    if best_result_obj is None:
        for fmt, ok, _err, result_obj, _elapsed in per_format:
            if ok and result_obj is not None:
                best_result_obj = result_obj
                if not best_format:
                    best_format = fmt.value
                break

    best_confidence: float | None = None
    best_format_warnings: list[str] = []
    if best_result_obj is not None:
        best_confidence = best_result_obj.confidence.overall if best_result_obj.confidence else None
        best_format_warnings = list(best_result_obj.output.warnings or [])

    workflow_warnings_list = list(workflow_warnings or [])

    # 1. Deploy banner.
    _print_deploy_banner(
        workflow_warnings=workflow_warnings_list,
        best_format_warnings=best_format_warnings,
        formats_status=formats_status,
        best_format=best_format or None,
        coverage=top_coverage,
        confidence=best_confidence,
    )

    # 2. Counts row.
    if best_result_obj is not None:
        stats = best_result_obj.output.stats
        total_nodes = stats.get("total_nodes", 0) or 0
        supported_nodes = stats.get("supported_nodes", 0) or 0
    else:
        total_nodes = 0
        supported_nodes = 0
    # Aggregate per-format warnings so the headline counts include
    # expression fallbacks and per-format unsupported entries that don't
    # bubble up to workflow-level — otherwise the row contradicts the
    # per-format tabs.
    all_format_warnings = [list(r.output.warnings or []) for _, ok, _, r, _ in per_format if ok and r is not None]
    _print_counts_row(
        coverage=top_coverage,
        confidence=best_confidence,
        supported=supported_nodes,
        total=total_nodes,
        workflow_warnings=workflow_warnings_list,
        best_format_warnings=best_format_warnings,
        all_format_warnings=all_format_warnings,
        best_format_label=_FORMAT_LABELS.get(best_format, best_format) if best_format else None,
    )

    # 3. Per-format status table.
    table = Table(show_header=True, header_style="bold")
    table.add_column("Format", style="cyan")
    table.add_column("Label", style="dim")
    table.add_column("Status")
    table.add_column("Files", justify="right")
    table.add_column("Coverage", justify="right")
    table.add_column("Confidence", justify="right")
    table.add_column("Duration", justify="right")
    table.add_column("Notes", max_width=40)

    succeeded = 0
    failed = 0
    for fmt, ok, err, result_obj, elapsed in per_format:
        label = _FORMAT_LABELS.get(fmt.value, fmt.value)
        if ok and result_obj is not None:
            succeeded += 1
            status = "[green]✓ OK[/green]"
            stats = result_obj.output.stats
            total = stats.get("total_nodes", 0) or 0
            supported = stats.get("supported_nodes", 0) or 0
            cov = (supported / total * 100) if total > 0 else 0.0
            cov_str = f"{cov:.0f}%"
            conf_str = f"{result_obj.confidence.overall:.0f}/100" if result_obj.confidence else "-"
            files_n = str(len(result_obj.output.files))
            note = ""
            # Mark the best format
            if fmt.value == best_format:
                status = "[bold green]★ BEST[/bold green]"
        else:
            failed += 1
            status = "[red]✗ FAIL[/red]"
            cov_str = "-"
            conf_str = "-"
            files_n = "0"
            note = (err[:37] + "...") if len(err) > 40 else err
        # Per-format generator time is typically tens of milliseconds — render
        # in ms when sub-second so users see real numbers instead of "0.0s".
        duration_str = f"{elapsed * 1000:.0f}ms" if elapsed < 1.0 else f"{elapsed:.1f}s"
        table.add_row(fmt.value, label, status, files_n, cov_str, conf_str, duration_str, note)
    console.print(table)

    if total_elapsed is not None:
        console.print(f"[dim]Total wall-clock: {total_elapsed:.1f}s (single parse, all formats)[/dim]")

    # 4. Categorized warnings — combined workflow + best-format.
    _print_categorized_warnings(
        workflow_warnings=workflow_warnings_list,
        format_warnings=best_format_warnings,
        format_label=_FORMAT_LABELS.get(best_format, best_format) if best_format else None,
    )

    # 5. Output footer.
    if succeeded:
        console.print(f"\n[bold green]Output written to {output_dir}[/bold green]")
        console.print(f"[dim]Per-format subdirs: {', '.join(f.value for f, ok, *_ in per_format if ok)}[/dim]")
    if failed and succeeded:
        console.print(f"[yellow]{failed} format(s) failed; {succeeded} succeeded.[/yellow]")
    elif failed and not succeeded:
        console.print(f"[red]All {failed} format(s) failed.[/red]")


def _print_format_status_table(
    per_format_results: list[tuple[OutputFormat, bool, str]],
    output_dir: Path,
) -> None:
    """Print a per-format status table for batch / directory conversion."""
    console.print("\n[bold]Per-Format Status[/bold]")

    succeeded = sum(1 for _, ok, _ in per_format_results if ok)
    failed = sum(1 for _, ok, _ in per_format_results if not ok)
    if failed and not succeeded:
        console.print("[bold red]✗ Cannot deploy as-is[/bold red]  Every format failed — see the error column below.")
    elif failed:
        console.print(
            "[bold yellow]⚠ Needs review[/bold yellow]  "
            f"{failed} format(s) failed; {succeeded} succeeded — review the error notes below."
        )
    else:
        console.print(
            "[bold green]✓ All formats generated[/bold green]  "
            "Per-file deploy readiness is recorded in batch_report.html."
        )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Format", style="cyan")
    table.add_column("Label", style="dim")
    table.add_column("Status")
    table.add_column("Notes", max_width=60)

    for fmt, ok, note in per_format_results:
        status = "[green]✓ OK[/green]" if ok else "[red]✗ FAIL[/red]"
        label = _FORMAT_LABELS.get(fmt.value, fmt.value)
        table.add_row(fmt.value, label, status, note[:58])
    console.print(table)
    console.print(f"\n[bold green]Output written to {output_dir}[/bold green]")


def _print_performance_hints(hints) -> None:
    """Print performance optimization hints, grouped by severity (high → low)."""
    if not hints:
        return
    # Group by severity so "high" hints don't get buried under cosmetic ones.
    buckets: dict[str, list] = {"high": [], "medium": [], "low": []}
    for h in hints:
        sev = h.priority.value if hasattr(h.priority, "value") else str(h.priority)
        buckets.setdefault(sev, []).append(h)

    console.print(f"\n[bold blue]Performance Hints ({len(hints)}):[/bold blue]")
    severity_meta = (
        ("high", "red", "▲ High"),
        ("medium", "yellow", "● Medium"),
        ("low", "dim", "· Low"),
    )
    for sev_key, color, header in severity_meta:
        items = buckets.get(sev_key, [])
        if not items:
            continue
        console.print(f"  [{color}]{header} ({len(items)})[/{color}]")
        for h in items[:8]:
            console.print(f"    [{color}]•[/{color}] {h.suggestion}")
            if h.code_snippet:
                console.print(f"      [dim]{h.code_snippet}[/dim]")
        if len(items) > 8:
            console.print(f"    [dim]… and {len(items) - 8} more {sev_key} hint(s)[/dim]")


def _print_complexity_breakdown(results: list[WorkflowAnalysis]) -> None:
    """Print per-workflow complexity breakdown to the console."""
    table = Table(title="Complexity Breakdown")
    table.add_column("Workflow", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Level")
    table.add_column("Nodes", justify="right")
    table.add_column("Depth", justify="right")
    table.add_column("Expressions", justify="right")
    table.add_column("Unsupported", justify="right")
    table.add_column("Spatial", justify="right")

    for a in results:
        c = a.complexity
        level_color = {"Low": "green", "Medium": "yellow", "High": "red", "Very High": "bold red"}.get(c.level, "white")
        table.add_row(
            a.workflow_name,
            f"{c.total_score:.1f}",
            f"[{level_color}]{c.level}[/{level_color}]",
            str(c.node_count),
            str(c.max_dag_depth),
            str(c.expression_count),
            str(c.unsupported_count),
            str(c.spatial_tool_count),
        )

    console.print(table)


def _generate_ddl(result, config, output_dir: Path) -> None:
    """Generate DDL files for Unity Catalog."""
    from a2d.generators.unity_catalog import UnityCatalogGenerator

    ddl_gen = UnityCatalogGenerator(config)
    ddl_files = ddl_gen.generate_ddl(result.dag)
    for f in ddl_files:
        path = output_dir / f.filename
        path.write_text(f.content)
        console.print(f"  DDL: {path}")


def _generate_dab(result, config, input_path: Path, output_dir: Path) -> None:
    """Generate Databricks Asset Bundle project."""
    from a2d.generators.dab import DABGenerator

    dab_gen = DABGenerator(config)
    dab_files = dab_gen.generate(result.dag, input_path.stem, result.output)
    dab_dir = output_dir / f"{input_path.stem}_dab"
    dab_dir.mkdir(parents=True, exist_ok=True)
    for f in dab_files:
        path = dab_dir / f.filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f.content)
        console.print(f"  DAB: {path}")


if __name__ == "__main__":
    app()

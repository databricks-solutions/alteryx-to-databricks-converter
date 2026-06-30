"""Conversion service — wraps ConversionPipeline (multi-format)."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from a2d.config import ConversionConfig, OutputFormat
from a2d.ir.graph import WorkflowDAG
from a2d.pipeline import (
    ConversionPipeline,
    FormatConversionResult,
    MultiFormatConversionResult,
)
from server.utils.validation import sanitize_filename

logger = logging.getLogger("a2d.server.services.conversion")


def generate_ddl_dab_files(
    config: ConversionConfig,
    result: MultiFormatConversionResult,
    workflow_stem: str,
    *,
    generate_ddl: bool,
    generate_dab: bool,
) -> tuple[list[dict], list[str]]:
    """Generate DDL/DAB files once for a multi-format result.

    Returns ``(extra_files, warnings)`` — both empty when neither flag is set.
    Extra files are intended to be appended into every successful format so
    each download remains self-contained. Failures are non-fatal and surface
    as warnings.
    """
    extra_files: list[dict] = []
    warnings: list[str] = []

    if generate_ddl:
        try:
            from a2d.generators.unity_catalog import UnityCatalogGenerator

            ddl_gen = UnityCatalogGenerator(config)
            ddl_files = ddl_gen.generate_ddl(result.dag)
            for f in ddl_files:
                extra_files.append({"filename": f.filename, "content": f.content, "file_type": "sql"})
        except Exception:
            logger.warning("DDL generation failed", exc_info=True)
            warnings.append("DDL generation failed — check server logs for details")

    if generate_dab:
        ref_output = None
        for fmt_key in ("pyspark", "dlt", "sql", "lakeflow"):
            fr = result.formats.get(fmt_key)
            if fr and fr.status == "success" and fr.output is not None:
                ref_output = fr.output
                break
        if ref_output is not None:
            try:
                from a2d.generators.dab import DABGenerator

                dab_gen = DABGenerator(config)
                dab_files = dab_gen.generate(result.dag, workflow_stem, ref_output)
                for f in dab_files:
                    extra_files.append({"filename": f.filename, "content": f.content, "file_type": f.file_type})
            except Exception:
                logger.warning("DAB generation failed", exc_info=True)
                warnings.append("DAB generation failed — check server logs for details")

    return extra_files, warnings


def _serialize_dag(dag: WorkflowDAG) -> dict:
    """Serialize WorkflowDAG into a JSON-friendly dict for the frontend."""
    nodes = []
    for ir_node in dag.all_nodes():
        nodes.append(
            {
                "node_id": ir_node.node_id,
                "tool_type": ir_node.original_tool_type,
                "annotation": ir_node.annotation,
                "position_x": ir_node.position[0],
                "position_y": ir_node.position[1],
                "conversion_confidence": ir_node.conversion_confidence,
                "conversion_method": ir_node.conversion_method,
            }
        )

    edges = []
    for source_id, target_id, edge_info in dag.all_edges():
        edges.append(
            {
                "source_id": source_id,
                "target_id": target_id,
                "origin_anchor": edge_info.origin_anchor,
                "destination_anchor": edge_info.destination_anchor,
            }
        )

    return {"nodes": nodes, "edges": edges}


def _serialize_format_result(fr: FormatConversionResult) -> dict:
    """Serialize a per-format result into the response dict shape.

    Generators emit `total_nodes`/`supported_nodes` in their stats dict but
    historically did not emit a derived `coverage_percentage` — so the
    frontend (which keys off `coverage_percentage`) used to read undefined
    and render 0. We compute it here so every successful format exposes a
    consistent `coverage_percentage` field.
    """
    if fr.status == "success" and fr.output is not None:
        files = [{"filename": f.filename, "content": f.content, "file_type": f.file_type} for f in fr.output.files]
        stats = dict(fr.output.stats)
        # Derive coverage_percentage if generators didn't already populate it.
        # Coverage = supported / total. Matches the CLI header line.
        if "coverage_percentage" not in stats:
            total = stats.get("total_nodes")
            supported = stats.get("supported_nodes")
            if isinstance(total, int) and total > 0 and isinstance(supported, int):
                stats["coverage_percentage"] = round(supported / total * 100.0, 1)
            else:
                stats["coverage_percentage"] = None
    else:
        files = []
        stats = {}

    return {
        "format": fr.format,
        "status": fr.status,
        "files": files,
        "stats": stats,
        "warnings": list(fr.warnings),
        "confidence": fr.confidence.to_dict() if fr.confidence else None,
        "error": fr.error,
    }


def convert_file(
    file_bytes: bytes,
    filename: str,
    *,
    catalog_name: str = "main",
    schema_name: str = "default",
    include_comments: bool = True,
    include_expression_audit: bool = False,
    include_performance_hints: bool = False,
    generate_ddl: bool = False,
    generate_dab: bool = False,
    expand_macros: bool = False,
) -> dict:
    """Convert a single uploaded .yxmd file into ALL output formats.

    Returns a response dict matching ``ConversionResponse``.
    """
    safe_name = sanitize_filename(filename)
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / safe_name
        file_path.write_bytes(file_bytes)

        # OutputFormat.PYSPARK is a placeholder — convert_all_formats does not
        # consult config.output_format; it iterates over all four formats.
        config = ConversionConfig(
            input_path=file_path,
            output_format=OutputFormat.PYSPARK,
            generate_orchestration=True,
            catalog_name=catalog_name,
            schema_name=schema_name,
            include_comments=include_comments,
            include_expression_audit=include_expression_audit,
            include_performance_hints=include_performance_hints,
            generate_ddl=generate_ddl,
            generate_dab=generate_dab,
            expand_macros=expand_macros,
        )
        pipeline = ConversionPipeline(config)
        result: MultiFormatConversionResult = pipeline.convert_all_formats(file_path)

        # DDL/DAB are independent of format. Generate ONCE here, then append the
        # generated files into EVERY successful format so each format download
        # is self-contained.
        top_warnings: list[str] = list(result.warnings)
        extra_files, ddl_dab_warnings = generate_ddl_dab_files(
            config,
            result,
            Path(filename).stem,
            generate_ddl=generate_ddl,
            generate_dab=generate_dab,
        )
        top_warnings.extend(ddl_dab_warnings)

    formats_dict: dict[str, dict] = {}
    for fmt_key, fr in result.formats.items():
        serialized = _serialize_format_result(fr)
        # Append DDL/DAB files into every successful format so each download is self-contained
        if extra_files and fr.status == "success":
            serialized["files"] = serialized["files"] + extra_files
        formats_dict[fmt_key] = serialized

    # Top-level coverage: mirror the best-format's coverage so the frontend
    # has one canonical headline number to render. The per-format coverage in
    # `formats[fmt].stats.coverage_percentage` still drives per-tab display.
    top_coverage: float | None = None
    if result.best_format and result.best_format in formats_dict:
        bf_stats = formats_dict[result.best_format].get("stats") or {}
        cov = bf_stats.get("coverage_percentage")
        if isinstance(cov, (int | float)):
            top_coverage = float(cov)

    response: dict = {
        "workflow_name": Path(filename).stem,
        "node_count": result.dag.node_count,
        "edge_count": result.dag.edge_count,
        "warnings": top_warnings,
        "dag_data": _serialize_dag(result.dag),
        "best_format": result.best_format,
        "formats": formats_dict,
        "coverage": top_coverage,
    }

    # Format-agnostic enrichments
    if result.expression_audit:
        from a2d.observability.expression_audit import audit_to_dicts

        response["expression_audit"] = audit_to_dicts(result.expression_audit)
    else:
        response["expression_audit"] = None

    if result.performance_hints:
        from a2d.observability.performance_hints import hints_to_dicts

        response["performance_hints"] = hints_to_dicts(result.performance_hints)
    else:
        response["performance_hints"] = None

    # Per-format status logging
    for fmt_key, fr in result.formats.items():
        if fr.status == "success":
            assert fr.output is not None
            logger.info(
                "Converted %s [%s]: %d files, %d nodes, %d edges",
                filename,
                fmt_key,
                len(fr.output.files),
                result.dag.node_count,
                result.dag.edge_count,
            )
        else:
            logger.warning(
                "Conversion failed for %s [%s]: %s",
                filename,
                fmt_key,
                fr.error,
            )

    # Save to history (non-blocking — multi-format records use output_format="multi")
    try:
        from server.services.history import is_available, save_conversion

        if is_available():
            history_record = {
                "workflow_name": response["workflow_name"],
                "output_format": "multi",
                "node_count": response["node_count"],
                "edge_count": response["edge_count"],
                "warnings": response["warnings"],
                "files": [],  # aggregate metadata only — full files live in the per-format response
                "dag_data": response["dag_data"],
                "stats": _aggregate_stats(result.formats),
            }
            save_conversion(history_record)
    except Exception:
        logger.warning("History save failed", exc_info=True)

    return response


def _aggregate_stats(formats: dict[str, FormatConversionResult]) -> dict:
    """Aggregate stats across formats. Coverage is averaged over successful formats."""
    coverages: list[float] = []
    for fr in formats.values():
        if fr.status != "success" or fr.output is None:
            continue
        # Generators emit total_nodes/supported_nodes; derive coverage here
        # to mirror what _serialize_format_result publishes.
        stats = fr.output.stats
        cov = stats.get("coverage_percentage")
        if not isinstance(cov, (int | float)):
            total = stats.get("total_nodes")
            supported = stats.get("supported_nodes")
            if isinstance(total, int) and total > 0 and isinstance(supported, int):
                cov = supported / total * 100.0
        if isinstance(cov, (int | float)):
            coverages.append(float(cov))
    avg_cov = sum(coverages) / len(coverages) if coverages else None
    return {
        "coverage_percentage": avg_cov,
        "successful_formats": [k for k, fr in formats.items() if fr.status == "success"],
        "failed_formats": [k for k, fr in formats.items() if fr.status == "failed"],
    }

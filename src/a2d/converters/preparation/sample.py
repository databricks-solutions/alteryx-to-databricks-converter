"""Converter for Alteryx Sample tool -> SampleNode."""

from __future__ import annotations

import contextlib

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.converters.utils import ensure_list, safe_get
from a2d.ir.nodes import IRNode, SampleNode
from a2d.parser.schema import ParsedNode


@ConverterRegistry.register
class SampleConverter(ToolConverter):
    """Converts Alteryx Sample to :class:`SampleNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Sample"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        mode = safe_get(cfg, "Mode", default="")
        n_str = safe_get(cfg, "N")
        n_records = int(n_str) if n_str and n_str.isdigit() else None

        pct_str = safe_get(cfg, "Percent")
        percentage = None
        if pct_str:
            with contextlib.suppress(ValueError):
                percentage = float(pct_str)

        # Handle macro-style config (RandomRecords.yxmc) where settings are stored as
        # a list of <Value name="..."> elements rather than top-level keys.
        if not mode and isinstance(cfg.get("Value"), list):
            values = {v.get("@name", ""): v.get("#text", "") for v in cfg.get("Value", []) if isinstance(v, dict)}
            is_percent = values.get("Percent", "False").lower() == "true"
            is_deterministic = values.get("Deterministic", "False").lower() == "true"
            if is_percent:
                mode = "Random Percent"
                try:
                    percentage = float(values.get("NPercent", "10"))
                except ValueError:
                    percentage = 10.0
            elif is_deterministic:
                mode = "First"
                try:
                    n_records = int(values.get("NNumber", "100"))
                except ValueError:
                    n_records = 100
            else:
                mode = "Random N"
                try:
                    n_records = int(values.get("NNumber", "100"))
                except ValueError:
                    n_records = 100

        if not mode:
            mode = "First"

        # Extract seed for deterministic random sampling
        seed_str = safe_get(cfg, "Seed") or safe_get(cfg, "RandomSeed")
        seed: int | None = None
        if seed_str:
            with contextlib.suppress(ValueError):
                seed = int(seed_str)

        # Map Alteryx mode strings to IR sample_method
        mode_map = {
            "First": "first",
            "Last": "last",
            "Random N": "random",
            "Random Percent": "percent",
            "Every Nth": "every_nth",
            "1 in N": "every_nth",
        }
        sample_method = mode_map.get(mode, mode.lower())

        # Group fields (Alteryx supports grouped sampling)
        group_fields_section = cfg.get("GroupFields", {})
        group_fields: list[str] = []
        if isinstance(group_fields_section, dict):
            raw = ensure_list(group_fields_section.get("Field", []))
            for f in raw:
                if isinstance(f, dict):
                    group_fields.append(f.get("@field", f.get("@name", "")))
                elif isinstance(f, str):
                    group_fields.append(f)

        return SampleNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            sample_method=sample_method,
            n_records=n_records,
            percentage=percentage,
            group_fields=group_fields,
            seed=seed,
        )

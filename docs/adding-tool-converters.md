# Adding a New Tool Converter

This guide walks through the end-to-end process of adding support for a new Alteryx tool. By the end, the tool will be parsed, converted to an IR node, and generated into all four output formats: PySpark, Spark Declarative Pipelines (DLT), SQL, and Lakeflow Designer. (Lakeflow inherits from SQL, so most new tools need no Lakeflow-specific code.)

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Step 1: Identify the Alteryx Plugin Name](#step-1-identify-the-alteryx-plugin-name)
3. [Step 2: Add to PLUGIN_NAME_MAP](#step-2-add-to-plugin_name_map)
4. [Step 3: Create or Extend an IR Node](#step-3-create-or-extend-an-ir-node)
5. [Step 4: Create the Converter Class](#step-4-create-the-converter-class)
6. [Step 5: Add Generation Logic](#step-5-add-generation-logic)
7. [Step 6: Write Tests](#step-6-write-tests)
8. [Step 7: Verify End-to-End](#step-7-verify-end-to-end)
9. [Worked Example: Adding the Tile Tool](#worked-example-adding-the-tile-tool)
10. [Checklist](#checklist)

---

## Prerequisites

- Python 3.10+
- Development dependencies installed: `make dev`
- Familiarity with the [architecture](architecture.md)
- A sample `.yxmd` file containing the target tool (for testing)

---

## Step 1: Identify the Alteryx Plugin Name

Open a `.yxmd` file containing the tool in a text editor or XML viewer. Find the `<Node>` element for that tool and look at the `Plugin` attribute in `<GuiSettings>`:

```xml
<Node ToolID="5">
  <GuiSettings Plugin="AlteryxBasePluginsGui.Tile.Tile">
    <Position x="500" y="300" />
  </GuiSettings>
  <Properties>
    <Configuration>
      <TileMethod>EqualRecords</TileMethod>
      <NumTiles>5</NumTiles>
      <FieldName>Amount</FieldName>
      <OutputFieldName>Tile_Num</OutputFieldName>
      <!-- more config -->
    </Configuration>
  </Properties>
</Node>
```

The plugin name is `"AlteryxBasePluginsGui.Tile.Tile"`.

---

## Step 2: Add to PLUGIN_NAME_MAP

**File**: `src/a2d/parser/schema.py`

Add an entry mapping the plugin string to a `(tool_type, category)` tuple:

```python
PLUGIN_NAME_MAP: dict[str, tuple[str, str]] = {
    # ... existing entries ...

    # ── Transform ───────────────────────────────────────────────────────
    "AlteryxBasePluginsGui.Tile.Tile": ("Tile", "transform"),
}
```

Guidelines:
- `tool_type` should be a concise, PascalCase name matching the Alteryx tool name
- `category` should be one of: `io`, `preparation`, `join`, `parse`, `transform`, `developer`, `spatial`, `reporting`, `interface`
- If the plugin name is already in the map, you are updating an existing tool -- skip this step

---

## Step 3: Create or Extend an IR Node

**File**: `src/a2d/ir/nodes.py`

If an existing IR node type captures the semantics, you can reuse it. Otherwise, create a new dataclass.

For the Tile tool, no existing node fits, so create a new one:

```python
@dataclass
class TileNode(IRNode):
    """Assign tile numbers (quantile bins) to rows.

    Attributes:
        tile_method: Algorithm -- "EqualRecords", "EqualSum", "SmartTile", "Manual"
        num_tiles: Number of tiles/bins to create.
        field_name: Field to tile by.
        output_field_name: Name of the output tile column.
        order_fields: Fields to sort by before tiling.
        unique_tile_field: Optional field for unique-value tiling.
    """
    tile_method: str = "EqualRecords"
    num_tiles: int = 5
    field_name: str = ""
    output_field_name: str = "Tile_Num"
    order_fields: list[str] = field(default_factory=list)
    unique_tile_field: str = ""
```

Rules:
- Inherit from `IRNode`
- Use `@dataclass`
- Provide sensible defaults for all fields
- Add a docstring explaining the tool's semantics
- Use primitive types and lists -- avoid complex objects unless necessary

Note: There is no separate `visitors.py` file. The generators discover node types via `isinstance` checks in their handler methods, so no visitor registration is needed.

---

## Step 4: Create the Converter Class

**File**: Create `src/a2d/converters/transform/tile.py` (or the appropriate category directory)

```python
"""Converter for Alteryx Tile tool -> TileNode."""

from __future__ import annotations

from a2d.config import ConversionConfig
from a2d.converters.registry import ConverterRegistry, ToolConverter
from a2d.ir.nodes import IRNode, TileNode
from a2d.parser.schema import ParsedNode


def _safe_get(d: object, key: str, default: str = "") -> str:
    """Safely extract a string from a dict-like configuration."""
    if isinstance(d, dict):
        val = d.get(key, default)
        return str(val) if val is not None else default
    return default


@ConverterRegistry.register
class TileConverter(ToolConverter):
    """Converts Alteryx Tile to :class:`TileNode`."""

    @property
    def supported_tool_types(self) -> list[str]:
        return ["Tile"]

    def convert(self, parsed_node: ParsedNode, config: ConversionConfig) -> IRNode:
        cfg = parsed_node.configuration

        tile_method = _safe_get(cfg, "TileMethod", default="EqualRecords")
        num_tiles_str = _safe_get(cfg, "NumTiles", default="5")
        num_tiles = int(num_tiles_str) if num_tiles_str.isdigit() else 5
        field_name = _safe_get(cfg, "FieldName")
        output_field_name = _safe_get(cfg, "OutputFieldName", default="Tile_Num")

        return TileNode(
            node_id=parsed_node.tool_id,
            original_tool_type=parsed_node.tool_type,
            original_plugin_name=parsed_node.plugin_name,
            annotation=parsed_node.annotation,
            position=parsed_node.position,
            tile_method=tile_method,
            num_tiles=num_tiles,
            field_name=field_name,
            output_field_name=output_field_name,
        )
```

Key patterns:
- Always use `@ConverterRegistry.register` as a class decorator
- `supported_tool_types` returns a list of tool type strings (matching the values in `PLUGIN_NAME_MAP`)
- Extract configuration from `parsed_node.configuration` (a dict built from XML)
- Always set `node_id`, `original_tool_type`, `original_plugin_name`, `annotation`, and `position` on the IR node
- Use `_safe_get` helpers for robust extraction from the config dict

Then register the import in the category's `__init__.py`:

```python
# src/a2d/converters/transform/__init__.py
from a2d.converters.transform.summarize import SummarizeConverter
from a2d.converters.transform.cross_tab import CrossTabConverter
from a2d.converters.transform.transpose import TransposeConverter
from a2d.converters.transform.running_total import RunningTotalConverter
from a2d.converters.transform.count_records import CountRecordsConverter
from a2d.converters.transform.tile import TileConverter  # <-- ADD THIS
```

This import triggers the `@register` decorator at module load time.

---

## Step 5: Add Generation Logic

You need to add generation code in **three** generators (PySpark, DLT, SQL). The Lakeflow generator inherits from SQL, so most SQL handlers are automatically available in Lakeflow. Optionally handle it in the workflow JSON generator.

### PySpark Generator

**File**: `src/a2d/generators/pyspark.py`

Add a `_generate_TileNode` method:

```python
def _generate_TileNode(
    self, node: TileNode, input_vars: dict[str, str]
) -> NodeCodeResult:
    inp = self._get_single_input(input_vars)
    out_var = f"df_{node.node_id}"

    if node.tile_method == "EqualRecords":
        lines = [
            f"# Tile: {node.num_tiles} equal-record tiles on '{node.field_name}'",
            f'_window_{node.node_id} = Window.orderBy(F.col("{node.field_name}"))',
            f'{out_var} = {inp}.withColumn(',
            f'    "{node.output_field_name}",',
            f'    F.ntile({node.num_tiles}).over(_window_{node.node_id})',
            f')',
        ]
    else:
        lines = [
            f"# Tile method '{node.tile_method}' -- manual conversion may be needed",
            f'{out_var} = {inp}.withColumn(',
            f'    "{node.output_field_name}",',
            f'    F.ntile({node.num_tiles}).over(Window.orderBy(F.col("{node.field_name}")))',
            f')',
        ]

    return NodeCodeResult(
        code_lines=lines,
        output_vars={"Output": out_var},
    )
```

Also add the import of `TileNode` at the top of the file:

```python
from a2d.ir.nodes import (
    # ... existing imports ...
    TileNode,
)
```

### DLT Generator

**File**: `src/a2d/generators/dlt.py`

Add a handler in the `_node_body` method (inside the isinstance chain):

```python
if isinstance(node, TileNode):
    inp = self._get_single_input_read(input_tables)
    return [
        f"return {inp}.withColumn("
        f'"{node.output_field_name}", '
        f'F.ntile({node.num_tiles}).over(Window.orderBy(F.col("{node.field_name}"))))',
    ], warnings
```

### SQL Generator

**File**: `src/a2d/generators/sql.py`

Add a handler in the `_generate_cte_body` method:

```python
if isinstance(node, TileNode):
    inp = self._get_single_input(input_ctes)
    return (
        f"SELECT *, NTILE({node.num_tiles}) OVER (ORDER BY `{node.field_name}`) "
        f"AS `{node.output_field_name}` FROM {inp}"
    ), warnings
```

### Lakeflow Generator

**File**: `src/a2d/generators/lakeflow.py`

`LakeflowGenerator` extends `SQLGenerator`, so your SQL handler above is automatically inherited. You only need to add Lakeflow-specific logic if the node requires different treatment (e.g., `STREAMING TABLE` vs `MATERIALIZED VIEW`). Most new tools need no changes here.

If the node represents a streaming source, add it to `_PASSTHROUGH_TYPES` or override `_is_streaming_source`:

```python
_PASSTHROUGH_TYPES = frozenset({"ReadNode", "CloudStorageNode", "DynamicInputNode", "YourNewNode"})
```

---

## Step 6: Write Tests

Create a test file at `tests/unit/converters/transform/test_tile.py` (or appropriate location):

```python
"""Tests for Tile tool converter."""

import pytest

from a2d.converters.registry import ConverterRegistry
from a2d.config import ConversionConfig
from a2d.ir.nodes import TileNode
from a2d.parser.schema import ParsedNode


def test_tile_converter_registered():
    """Tile converter should be in the registry."""
    assert "Tile" in ConverterRegistry.supported_tools()


def test_tile_converter_basic():
    """Convert a basic Tile node."""
    parsed = ParsedNode(
        tool_id=5,
        plugin_name="AlteryxBasePluginsGui.Tile.Tile",
        tool_type="Tile",
        category="transform",
        configuration={
            "TileMethod": "EqualRecords",
            "NumTiles": "4",
            "FieldName": "Revenue",
            "OutputFieldName": "Quartile",
        },
    )

    config = ConversionConfig()
    result = ConverterRegistry.convert_node(parsed, config)

    assert isinstance(result, TileNode)
    assert result.node_id == 5
    assert result.tile_method == "EqualRecords"
    assert result.num_tiles == 4
    assert result.field_name == "Revenue"
    assert result.output_field_name == "Quartile"


def test_tile_pyspark_generation():
    """Generated PySpark code should use ntile window function."""
    from a2d.generators.pyspark import PySparkGenerator
    from a2d.ir.graph import WorkflowDAG

    node = TileNode(
        node_id=5,
        original_tool_type="Tile",
        tile_method="EqualRecords",
        num_tiles=4,
        field_name="Revenue",
        output_field_name="Quartile",
    )

    dag = WorkflowDAG()
    dag.add_node(node)

    config = ConversionConfig()
    gen = PySparkGenerator(config)
    output = gen.generate(dag, "test_tile")

    assert len(output.files) == 1
    content = output.files[0].content
    assert "ntile(4)" in content
    assert "Quartile" in content
```

Run the tests:

```bash
pytest tests/unit/converters/transform/test_tile.py -v
```

---

## Step 7: Verify End-to-End

1. Create or find a `.yxmd` file that uses the Tile tool
2. Run: `a2d convert test_tile.yxmd -o /tmp/tile_test/` — emits all 4 formats by default into `pyspark/`, `dlt/`, `sql/`, `lakeflow/` subdirs
3. Verify the generated code in each subdir contains the expected `ntile` logic (PySpark / DLT / SQL / Lakeflow flavors)
4. Confirm the CLI deploy-readiness banner reports `Ready to deploy` and that the per-format status table shows `OK` for all four formats — flag the best-format star (`★`)
5. Run: `a2d list-tools --supported` and confirm "Tile" appears
6. Run: `make all` to ensure lint, typecheck, and tests pass

---

## Worked Example: Adding the Tile Tool

Here is the complete summary of all files touched:

| Step | File | Change |
|------|------|--------|
| 2 | `src/a2d/parser/schema.py` | Add `"AlteryxBasePluginsGui.Tile.Tile": ("Tile", "transform")` to `PLUGIN_NAME_MAP` |
| 3 | `src/a2d/ir/nodes.py` | Add `TileNode` dataclass |
| 4 | `src/a2d/converters/transform/tile.py` | Create `TileConverter` with `@register` |
| 4 | `src/a2d/converters/transform/__init__.py` | Add import of `TileConverter` |
| 5 | `src/a2d/generators/pyspark.py` | Add `_generate_TileNode` method + import |
| 5 | `src/a2d/generators/dlt.py` | Add `TileNode` handler in `_node_body` + import |
| 5 | `src/a2d/generators/sql.py` | Add `TileNode` handler in `_generate_cte_body` + import |
| 5 | `src/a2d/generators/lakeflow.py` | Usually no change needed (inherits from SQL) |
| 6 | `tests/unit/converters/transform/test_tile.py` | Create test file |

Total: 7-8 files touched (Lakeflow usually inherits SQL handler automatically). The pattern is consistent across all tools, making it easy to parallelize converter development.

---

## Checklist

Use this checklist when adding any new converter:

- [ ] Plugin name identified from a `.yxmd` file
- [ ] Entry added to `PLUGIN_NAME_MAP` in `schema.py`
- [ ] IR node class created in `nodes.py` (or existing node reused)
- [ ] Converter class created with `@ConverterRegistry.register`
- [ ] Converter imported in category `__init__.py`
- [ ] PySpark generator method added
- [ ] DLT generator handler added
- [ ] SQL generator handler added
- [ ] Lakeflow generator verified (inherits SQL; override only if needed)
- [ ] Unit tests written and passing
- [ ] `a2d list-tools --supported` shows the tool
- [ ] `make all` passes (lint + typecheck + tests)
- [ ] End-to-end test with a real `.yxmd` file

# a2d Converter & Frontend SDK

Extend a2d **without editing core** by shipping a small package that declares an
entry point. a2d discovers it at import time and registers your converter or
frontend alongside the built-ins. Everything you build against lives in one
stable module: **`a2d.sdk`**.

Check the contract version with `a2d.sdk.SDK_VERSION` (currently `1.0`). We keep
the `a2d.sdk` surface backwards-compatible within a major version; internal
module layout may change, so always import from `a2d.sdk`.

Run `a2d plugins` to see every installed frontend and converter plugin (and any
that failed to load, with the error).

## Writing a converter plugin

A converter turns one source `ParsedNode` into an `IRNode`. Everything
downstream (all generators, `verify`, `portfolio`, `advise`, `suggest`, the
bridges, the review workspace) then works on your node for free.

```python
# my_pkg/converters.py
from a2d.sdk import ConverterRegistry, ToolConverter, ParsedNode, ConversionConfig
from a2d.sdk import IRNode, FilterNode

@ConverterRegistry.register
class MyToolConverter(ToolConverter):
    @property
    def supported_tool_types(self) -> list[str]:
        return ["MyTool"]

    def convert(self, node: ParsedNode, config: ConversionConfig) -> IRNode:
        return FilterNode(
            node_id=node.tool_id,
            original_tool_type=node.tool_type,
            expression=node.configuration.get("Expression", ""),
        )
```

Declare the entry point so a2d imports the module (which runs the
`@ConverterRegistry.register` decorator):

```toml
# my_pkg's pyproject.toml
[project.entry-points."a2d.converters"]
my_tool = "my_pkg.converters"
```

The entry-point *value* may be either a module (imported for its registration
side effects, as above) or a `ToolConverter` subclass (registered directly).

## Writing a frontend plugin

A frontend parses a new *source format* into a `ParsedWorkflow`. Add one and a2d
can convert that source into any output format.

```python
# my_pkg/frontend.py
from pathlib import Path
from a2d.sdk import SourceFrontend, ParsedWorkflow, ParsedNode

class TalendFrontend(SourceFrontend):
    name = "talend"

    @property
    def supported_extensions(self) -> list[str]:
        return [".item"]

    def parse(self, path: Path) -> ParsedWorkflow:
        ...  # build ParsedNode/ParsedConnection lists from the Talend job
        return ParsedWorkflow(file_path=str(path), alteryx_version="talend")
```

```toml
[project.entry-points."a2d.frontends"]
talend = "my_pkg.frontend:TalendFrontend"
```

Then: `a2d convert job.item --frontend talend`.

## Contract guarantees

* **Stable imports** — everything in `a2d.sdk.__all__` is part of the contract.
* **Isolation** — a plugin that raises on import is logged and skipped; it never
  breaks a conversion run (`a2d plugins` shows the failure).
* **Same pipeline** — plugin converters/frontends go through the identical IR
  build, generation and verification path as the built-ins, so `a2d verify`
  validates plugin output the same way.
```

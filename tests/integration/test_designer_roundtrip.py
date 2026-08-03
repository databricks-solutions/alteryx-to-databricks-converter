"""Designer round-trip integration test — import a generated .designer.ipynb
into a live Databricks workspace.

This is the online half of Q1 "Designer round-trip validation". It is
**skip-guarded**: it only runs when a Databricks workspace is configured
(``DATABRICKS_HOST`` + auth, or a default profile) AND opting in via
``A2D_RUN_DESIGNER_ROUNDTRIP=1``. On a laptop / in ordinary CI it skips cleanly,
so it never blocks the suite. The offline structural contract is covered
exhaustively by ``tests/unit/generators/test_designer_validation.py``.

When it does run it:
  1. generates a .designer.ipynb from a fixture,
  2. imports it into the workspace under a temp path,
  3. reads it back and asserts the content round-trips,
  4. cleans up.
"""

from __future__ import annotations

import base64
import contextlib
import os
import uuid
from pathlib import Path

import pytest

from a2d.config import ConversionConfig
from a2d.generators.designer import DesignerGenerator
from a2d.generators.designer_validation import validate_designer_notebook
from a2d.pipeline import ConversionPipeline

WORKFLOWS_DIR = Path(__file__).parent.parent / "fixtures" / "workflows"

_OPT_IN = os.environ.get("A2D_RUN_DESIGNER_ROUNDTRIP") == "1"


def _workspace_client():
    """Return a WorkspaceClient if a workspace is reachable, else None."""
    try:
        from databricks.sdk import WorkspaceClient

        return WorkspaceClient()
    except Exception:
        return None


def _generate_designer_ipynb(name: str) -> str:
    cfg = ConversionConfig(input_path=WORKFLOWS_DIR / f"{name}.yxmd", output_dir=Path("."))
    pipeline = ConversionPipeline(cfg)
    parsed = pipeline._parser.parse(WORKFLOWS_DIR / f"{name}.yxmd")
    dag = pipeline._build_dag(parsed)
    out = DesignerGenerator(cfg).generate(dag, name)
    return next(f.content for f in out.files if f.filename.endswith(".designer.ipynb"))


@pytest.mark.skipif(
    not _OPT_IN,
    reason="set A2D_RUN_DESIGNER_ROUNDTRIP=1 (and configure a Databricks workspace) to run",
)
class TestDesignerRoundTrip:
    def test_import_and_read_back(self):
        client = _workspace_client()
        if client is None:
            pytest.skip("no Databricks workspace configured")

        from databricks.sdk.service.workspace import ImportFormat

        content = _generate_designer_ipynb("join_and_summarize")
        # Sanity: it must pass the offline contract before we bother importing.
        assert validate_designer_notebook(content).is_valid

        me = client.current_user.me()
        remote = f"/Users/{me.user_name}/.a2d_roundtrip_{uuid.uuid4().hex[:8]}.designer.ipynb"
        try:
            client.workspace.import_(
                path=remote,
                content=base64.b64encode(content.encode()).decode(),
                format=ImportFormat.JUPYTER,
                overwrite=True,
            )
            exported = client.workspace.export(path=remote, format=ImportFormat.JUPYTER)
            round_tripped = base64.b64decode(exported.content).decode()
            # The imported file must still be a structurally valid Designer file.
            assert validate_designer_notebook(round_tripped).is_valid
        finally:
            with contextlib.suppress(Exception):
                client.workspace.delete(path=remote)

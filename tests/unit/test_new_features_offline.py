"""Guard: the savings and questionnaire features are pure/offline.

The product rule (see CLAUDE.md) is that a2d calls no language model outside the
opt-in advisory subsystem. These two new features are deterministic — this test
fails if either package grows an import of the advisor LLM client or a network
library, which would silently break that invariant.
"""

from __future__ import annotations

import ast
from pathlib import Path

import a2d.questionnaire as questionnaire_pkg
import a2d.savings as savings_pkg

_FORBIDDEN_MODULES = {
    "a2d.advisor",
    "a2d.advisor.llm_client",
    "requests",
    "httpx",
    "urllib.request",
    "openai",
}


def _imports_in_files(paths) -> set[str]:
    """Collect every module imported by the given .py files."""
    imported: set[str] = set()
    for py in paths:
        tree = ast.parse(Path(py).read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    return imported


def _imported_modules(pkg) -> set[str]:
    """Collect every module imported by any .py file in a package."""
    root = Path(pkg.__file__).parent
    return _imports_in_files(root.rglob("*.py"))


def test_savings_is_offline():
    assert not (_imported_modules(savings_pkg) & _FORBIDDEN_MODULES)


def test_questionnaire_is_offline():
    assert not (_imported_modules(questionnaire_pkg) & _FORBIDDEN_MODULES)


def test_server_feature_layer_is_offline():
    """The server-side savings/readiness code must not reach for an LLM either.

    The engine-package scans above miss the FastAPI service/router layer, so a
    later edit there could break the no-LLM rule without tripping a test. Scan the
    feature-specific server files by path to close that gap.
    """
    repo_root = Path(__file__).resolve().parents[2]
    server_files = [
        repo_root / "server" / "services" / "savings.py",
        repo_root / "server" / "services" / "readiness.py",
        repo_root / "server" / "routers" / "readiness.py",
    ]
    assert all(f.exists() for f in server_files), "server feature files moved — update this guard"
    assert not (_imports_in_files(server_files) & _FORBIDDEN_MODULES)

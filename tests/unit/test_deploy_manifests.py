"""Contract tests for the deployment manifests.

These exist because a real deployment exposed two classes of defect that no other
test could catch:

1. A deployed ``app.yaml`` shadows ``resources.apps.<app>.config`` in
   ``databricks.yml``. Having both meant the two files silently disagreed on port,
   CORS, the Lakebase host and the FMAPI endpoint, and ``--var`` overrides looked
   like no-ops.
2. Fixing that by hardcoding one workspace's endpoint/host into ``app.yaml`` made
   the repo non-portable and — for the FMAPI endpoint — turned AI on for anyone who
   cloned it, contradicting the documented opt-in product rule.

Both are cheap to assert and expensive to rediscover.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="PyYAML needed to parse the manifests")

REPO_ROOT = Path(__file__).parent.parent.parent
APP_YAML = REPO_ROOT / "app.yaml"
BUNDLE_YAML = REPO_ROOT / "databricks.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _env(manifest: dict) -> dict[str, str]:
    return {e["name"]: str(e.get("value", "")) for e in manifest.get("env", [])}


@pytest.fixture(scope="module")
def app_manifest() -> dict:
    return _load(APP_YAML)


@pytest.fixture(scope="module")
def bundle_manifest() -> dict:
    return _load(BUNDLE_YAML)


class TestSingleSourceOfTruth:
    def test_bundle_declares_no_app_config_block(self, bundle_manifest):
        """app.yaml shadows it, so a bundle `config:` block is a silent trap."""
        app = bundle_manifest["resources"]["apps"]["a2d_app"]
        assert "config" not in app, (
            "databricks.yml declares resources.apps.a2d_app.config, which the Apps "
            "runtime ignores in favour of app.yaml. Put command/env in app.yaml."
        )

    def test_app_yaml_defines_the_command(self, app_manifest):
        assert app_manifest.get("command"), "app.yaml must define the run command"


class TestNoCommittedDeploymentIdentifiers:
    """No workspace-specific values in source control — the repo must be portable."""

    # Substrings that only ever appear in one workspace's configuration.
    FORBIDDEN_FRAGMENTS = (
        ".cloud.databricks.com",
        ".database.us-east-1",
        "ep-",  # Lakebase endpoint host prefix
        "fevm-",
    )

    @pytest.mark.parametrize("path", [APP_YAML, BUNDLE_YAML], ids=lambda p: p.name)
    def test_no_workspace_hostnames_committed(self, path):
        text = path.read_text()
        # Documentation/examples are fine; only *values* matter. Check lines that
        # assign a value and aren't comments.
        offenders: list[str] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#") or "value:" not in stripped:
                continue
            if any(frag in stripped for frag in self.FORBIDDEN_FRAGMENTS):
                offenders.append(f"{path.name}:{lineno}: {stripped}")
        assert not offenders, "workspace-specific values committed:\n" + "\n".join(offenders)


class TestAiStaysOptIn:
    """`AI is opt-in and advisory-only` is a product rule, so the default must be empty."""

    def test_fmapi_endpoint_is_empty_by_default(self, app_manifest):
        env = _env(app_manifest)
        assert env.get("A2D_FMAPI_ENDPOINT", "") == "", (
            "A2D_FMAPI_ENDPOINT must be empty in source control: a committed value "
            "enables the assistant for everyone who clones or deploys the repo."
        )

    def test_bundle_fmapi_variable_defaults_empty(self, bundle_manifest):
        var = bundle_manifest["variables"]["fmapi_endpoint"]
        assert str(var.get("default", "")) == ""


class TestHistoryDefaultsOff:
    """History needs a database the operator has to provide, so default to off."""

    def test_db_backend_empty_by_default(self, app_manifest):
        assert _env(app_manifest).get("A2D_DB_BACKEND", "") == ""

    def test_no_lakebase_host_committed(self, app_manifest):
        env = _env(app_manifest)
        assert env.get("PGHOST", "") == ""
        assert env.get("A2D_LAKEBASE_ENDPOINT", "") == ""


class TestRuntimePort:
    def test_command_honours_the_apps_runtime_port(self, app_manifest):
        """Bind what the runtime asks for rather than assuming a fixed port."""
        command = " ".join(app_manifest["command"])
        assert "DATABRICKS_APP_PORT" in command, (
            "the run command should read DATABRICKS_APP_PORT (with a fallback) so the "
            "app binds whatever port the Apps runtime assigns"
        )


class TestProductionCors:
    def test_cors_is_not_wildcarded(self, app_manifest):
        """The SPA is same-origin in Apps, so a wildcard is needless exposure."""
        assert "*" not in _env(app_manifest).get("A2D_CORS_ORIGINS", "")

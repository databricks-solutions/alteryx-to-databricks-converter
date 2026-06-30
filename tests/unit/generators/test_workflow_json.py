"""Tests for the Databricks Workflow JSON generator."""

from __future__ import annotations

import json

import pytest

from a2d.config import CLOUD_NODE_TYPE_IDS, ConversionConfig, OutputFormat
from a2d.generators.workflow_json import WorkflowJsonGenerator
from a2d.ir.graph import WorkflowDAG
from a2d.ir.nodes import ReadNode, WriteNode


def _strip_header(content: str) -> str:
    """Strip the leading ``//`` comment block so we can ``json.loads`` the body."""
    lines = content.splitlines(keepends=True)
    body = [ln for ln in lines if not ln.lstrip().startswith("//")]
    return "".join(body)


def _load_job(content: str) -> dict:
    return json.loads(_strip_header(content))


@pytest.fixture
def dag() -> WorkflowDAG:
    """Simple 2-node DAG: Read → Write."""
    d = WorkflowDAG()
    d.add_node(
        ReadNode(
            node_id=1,
            original_tool_type="Input",
            original_plugin_name="Input",
            file_path="/data/input.csv",
            file_format="csv",
        )
    )
    d.add_node(
        WriteNode(
            node_id=2,
            original_tool_type="Output",
            original_plugin_name="Output",
            file_path="/data/output.csv",
            file_format="csv",
        )
    )
    d.add_edge(1, 2)
    return d


class TestWorkflowJsonPySpark:
    @pytest.fixture
    def gen(self) -> WorkflowJsonGenerator:
        config = ConversionConfig(output_format=OutputFormat.PYSPARK)
        return WorkflowJsonGenerator(config)

    def test_generates_json_and_readme(self, gen: WorkflowJsonGenerator, dag: WorkflowDAG):
        result = gen.generate(dag, "my_workflow")
        # Strict JSON file + sibling README with operator notes (replaces the
        # old `//`-comment header that broke `json.loads` for downstream tools).
        assert len(result.files) == 2
        json_file = next(f for f in result.files if f.file_type == "json")
        readme_file = next(f for f in result.files if f.file_type == "markdown")
        assert json_file.filename == "my_workflow_workflow.json"
        assert readme_file.filename == "my_workflow_workflow.README.md"

    def test_json_is_valid(self, gen: WorkflowJsonGenerator, dag: WorkflowDAG):
        result = gen.generate(dag, "my_workflow")
        job = _load_job(result.files[0].content)
        assert isinstance(job, dict)

    def test_job_name_and_tags(self, gen: WorkflowJsonGenerator, dag: WorkflowDAG):
        result = gen.generate(dag, "my_workflow")
        job = _load_job(result.files[0].content)
        assert job["name"] == "a2d_my_workflow"
        assert job["tags"]["source"] == "alteryx"
        assert job["tags"]["migrated_by"] == "a2d"
        assert "my_workflow.yxmd" in job["tags"]["original_workflow"]

    def test_notebook_task_for_pyspark(self, gen: WorkflowJsonGenerator, dag: WorkflowDAG):
        result = gen.generate(dag, "my_workflow")
        job = _load_job(result.files[0].content)
        task = job["tasks"][0]
        assert task["task_key"] == "my_workflow_main"
        assert "notebook_task" in task
        assert task["notebook_task"]["notebook_path"] == "/Workspace/Shared/a2d/my_workflow"

    def test_stats(self, gen: WorkflowJsonGenerator, dag: WorkflowDAG):
        result = gen.generate(dag, "my_workflow")
        assert result.stats["total_tasks"] == 1
        assert "notebook_path" in result.stats


class TestWorkflowJsonDLT:
    @pytest.fixture
    def gen(self) -> WorkflowJsonGenerator:
        config = ConversionConfig(output_format=OutputFormat.DLT)
        return WorkflowJsonGenerator(config)

    def test_dlt_task_uses_pipeline(self, gen: WorkflowJsonGenerator, dag: WorkflowDAG):
        result = gen.generate(dag, "my_wf")
        job = _load_job(result.files[0].content)
        task = job["tasks"][0]
        assert task["task_key"] == "my_wf_dlt_pipeline"
        assert "pipeline_task" in task
        assert task["pipeline_task"]["full_refresh"] is False


class TestWorkflowJsonLakeflow:
    @pytest.fixture
    def gen(self) -> WorkflowJsonGenerator:
        config = ConversionConfig(output_format=OutputFormat.LAKEFLOW)
        return WorkflowJsonGenerator(config)

    def test_lakeflow_task_uses_sql(self, gen: WorkflowJsonGenerator, dag: WorkflowDAG):
        result = gen.generate(dag, "my_wf")
        job = _load_job(result.files[0].content)
        task = job["tasks"][0]
        assert task["task_key"] == "my_wf_lakeflow"
        assert "sql_task" in task
        assert task["sql_task"]["file"]["path"].endswith("_lakeflow.sql")


class TestWorkflowJsonSQL:
    @pytest.fixture
    def gen(self) -> WorkflowJsonGenerator:
        config = ConversionConfig(output_format=OutputFormat.SQL)
        return WorkflowJsonGenerator(config)

    def test_sql_falls_through_to_notebook(self, gen: WorkflowJsonGenerator, dag: WorkflowDAG):
        """SQL format uses the default notebook task (not sql_task)."""
        result = gen.generate(dag, "my_wf")
        job = _load_job(result.files[0].content)
        task = job["tasks"][0]
        assert "notebook_task" in task

    def test_cluster_config_present(self, gen: WorkflowJsonGenerator, dag: WorkflowDAG):
        result = gen.generate(dag, "my_wf")
        job = _load_job(result.files[0].content)
        assert len(job["job_clusters"]) == 1
        cluster = job["job_clusters"][0]
        # Tasks reference job_clusters via "main"; we used to call this
        # "default_cluster" but renamed to align with the DAB generator.
        assert cluster["job_cluster_key"] == "main"
        assert "new_cluster" in cluster
        # Tasks must reference the job_cluster_key (not embed an inline cluster).
        task = job["tasks"][0]
        assert task["job_cluster_key"] == "main"

    def test_modern_jobs_api_shape(self, gen: WorkflowJsonGenerator, dag: WorkflowDAG):
        """Modern Jobs API (2.1+): no `format` key, queue+parameters present."""
        result = gen.generate(dag, "my_wf")
        job = _load_job(result.files[0].content)
        # `format: MULTI_TASK` was vestigial since 2.1 — should be omitted.
        assert "format" not in job
        # Concurrency control + parameters placeholder for users to populate.
        assert job["queue"] == {"enabled": True}
        assert job["parameters"] == []
        assert job["max_concurrent_runs"] == 1


# ── Cloud portability ─────────────────────────────────────────────────


class TestWorkflowJsonCloudPortability:
    @pytest.mark.parametrize(
        "cloud,expected_node_type",
        [
            ("aws", "i3.xlarge"),
            ("azure", "Standard_DS3_v2"),
            ("gcp", "n1-highmem-4"),
        ],
    )
    def test_node_type_id_matches_cloud(self, dag: WorkflowDAG, cloud: str, expected_node_type: str):
        config = ConversionConfig(output_format=OutputFormat.PYSPARK, cloud=cloud)  # type: ignore[arg-type]
        result = WorkflowJsonGenerator(config).generate(dag, "wf")
        job = _load_job(result.files[0].content)
        cluster = job["job_clusters"][0]
        assert cluster["new_cluster"]["node_type_id"] == expected_node_type
        # Stats expose the cloud + node_type_id for downstream telemetry.
        assert result.stats["cloud"] == cloud
        assert result.stats["node_type_id"] == expected_node_type

    def test_default_cloud_is_aws(self, dag: WorkflowDAG):
        """Backward compat: omitting `cloud` should produce i3.xlarge (AWS)."""
        config = ConversionConfig(output_format=OutputFormat.PYSPARK)
        result = WorkflowJsonGenerator(config).generate(dag, "wf")
        job = _load_job(result.files[0].content)
        assert job["job_clusters"][0]["new_cluster"]["node_type_id"] == "i3.xlarge"

    def test_cloud_table_covers_all_clouds(self):
        """Sanity: every supported cloud has a node_type_id mapping."""
        assert set(CLOUD_NODE_TYPE_IDS) == {"aws", "azure", "gcp"}

    def test_readme_documents_run_as_and_webhooks(self, dag: WorkflowDAG):
        """Sibling README must point operators at the run_as / webhook decisions.

        Notes live in the README (not the JSON) so the JSON file stays strict-
        parseable for downstream tooling (jq, json.loads, CI linters).
        """
        config = ConversionConfig(output_format=OutputFormat.PYSPARK)
        result = WorkflowJsonGenerator(config).generate(dag, "wf")
        readme = next(f for f in result.files if f.file_type == "markdown")
        assert "run_as" in readme.content
        assert "webhook_notifications" in readme.content
        # And the JSON itself is strict — no `//` comment lines.
        json_file = next(f for f in result.files if f.file_type == "json")
        assert not json_file.content.lstrip().startswith("//")

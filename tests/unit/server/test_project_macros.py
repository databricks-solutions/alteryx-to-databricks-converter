"""A macro uploaded as its own file resolves for every workflow that calls it.

In a project (or one upload), ``.yxmc`` files form a shared macro library: the
single-workflow steps (convert, review, advise, AI gaps), batch convert (even on
a selection that leaves the macro out) and the estate passes all expand the
calls against it, and a macro that's still missing is reported, not guessed.
"""

from __future__ import annotations

import json
import uuid

import pytest
from server.services import batch as batch_service
from server.services import project as project_service
from server.utils.package import _library_name, write_macro_library

from tests.unit.macro.builders import BATCH, formula_macro, workflow_calling

PID = str(uuid.uuid4())
WID = str(uuid.uuid4())

# The reference points at the author's machine, in Windows form and case.
MAIN = ("main.yxmd", workflow_calling(r"C:\Users\analyst\Macros\standard cleanse.yxmc").encode())
MACRO = ("Standard Cleanse.yxmc", formula_macro().encode())


@pytest.fixture()
def saved(monkeypatch):
    """A saved project holding MAIN and, unless a test drops it, MACRO."""
    state = {"macros": [MACRO]}
    monkeypatch.setattr(project_service, "is_available", lambda: True)

    def get_with_macros(pid, wid):
        return (MAIN, list(state["macros"])) if (pid, wid) == (PID, WID) else None

    def get_files(pid):
        return [MAIN, *state["macros"]] if pid == PID else None

    monkeypatch.setattr(project_service, "get_workflow_with_macros", get_with_macros)
    monkeypatch.setattr(project_service, "get_project_files", get_files)
    return state


def _tool_types(response_json) -> list[str]:
    return [n["tool_type"] for n in response_json["dag_data"]["nodes"]]


def _macro_warnings(response_json) -> list[str]:
    return [w for w in response_json["warnings"] if "wasn't expanded" in w]


class TestSingleWorkflow:
    def test_convert_from_a_project_uses_its_macros(self, client, saved):
        resp = client.post("/api/convert", data={"project_id": PID, "workflow_id": WID})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "Formula" in _tool_types(body)
        assert "Unknown" not in _tool_types(body)
        assert _macro_warnings(body) == []

    def test_a_macro_missing_from_the_project_is_a_warning(self, client, saved):
        saved["macros"] = []
        body = client.post("/api/convert", data={"project_id": PID, "workflow_id": WID}).json()
        (warning,) = _macro_warnings(body)
        assert "standard cleanse.yxmc" in warning and "tool 10" in warning

    def test_convert_upload_with_macros_field(self, client):
        resp = client.post(
            "/api/convert",
            files=[("file", MAIN), ("macros", MACRO)],
        )
        assert resp.status_code == 200, resp.text
        assert "Formula" in _tool_types(resp.json())

    def test_macros_field_only_takes_macros(self, client):
        resp = client.post("/api/convert", files=[("file", MAIN), ("macros", MAIN)])
        assert resp.status_code == 422
        assert "Only .yxmc" in resp.json()["detail"]

    def test_project_and_uploaded_macros_together_are_rejected(self, client, saved):
        resp = client.post("/api/convert", data={"project_id": PID, "workflow_id": WID}, files=[("macros", MACRO)])
        assert resp.status_code == 422

    def test_review_from_a_project_uses_its_macros(self, client, saved):
        resp = client.post("/api/review", data={"project_id": PID, "workflow_id": WID})
        assert resp.status_code == 200, resp.text
        types = [n["tool_type"] for n in resp.json()["nodes"]]
        assert "Formula" in types and "Unknown" not in types

    def test_advise_from_a_project(self, client, saved):
        resp = client.post("/api/advise", data={"project_id": PID, "workflow_id": WID, "cloud": "aws"})
        assert resp.status_code == 200, resp.text

    def test_unknown_project_workflow_is_404(self, client, saved):
        resp = client.post("/api/convert", data={"project_id": PID, "workflow_id": str(uuid.uuid4())})
        assert resp.status_code == 404


class TestAiGaps:
    def test_a_missing_macro_is_named_and_not_sent_to_the_model(self, client, saved):
        saved["macros"] = []
        resp = client.post("/api/ai/gaps", data={"project_id": PID, "workflow_id": WID})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        macro_gaps = [g for g in body["gaps"] if g.get("tool_type") == "Macro"]
        assert len(macro_gaps) == 1
        assert "standard cleanse.yxmc wasn't available" in macro_gaps[0]["summary"]
        assert body["completable"] == []

    def test_a_batch_macro_gap_says_why_and_is_not_sent_to_the_model(self, client, saved):
        saved["macros"] = [(MACRO[0], formula_macro(runtime=BATCH).encode())]
        body = client.post("/api/ai/gaps", data={"project_id": PID, "workflow_id": WID}).json()
        (gap,) = [g for g in body["gaps"] if g.get("tool_type") == "Macro"]
        assert "batch macro" in gap["summary"]
        assert body["completable"] == []

    def test_with_the_macro_there_is_no_macro_gap(self, client, saved):
        body = client.post("/api/ai/gaps", data={"project_id": PID, "workflow_id": WID}).json()
        assert not [g for g in body["gaps"] if g.get("tool_type") == "Macro"]


class TestBatch:
    @pytest.fixture()
    def started(self, monkeypatch):
        seen = {}

        async def fake_create(file_data, **kwargs):
            seen["names"] = [name for name, _ in file_data]
            seen["macros"] = [name for name, _ in kwargs.get("macros") or []]
            return "job-1"

        monkeypatch.setattr(batch_service, "create_batch_job", fake_create)
        return seen

    def test_a_selection_still_gets_the_projects_macros(self, client, saved, started):
        resp = client.post("/api/convert/batch", data={"project_id": PID, "workflow_names": json.dumps([MAIN[0]])})
        assert resp.status_code == 200, resp.text
        assert started == {"names": ["main.yxmd"], "macros": ["Standard Cleanse.yxmc"]}

    def test_an_upload_can_send_macros_it_doesnt_convert(self, client, started):
        resp = client.post("/api/convert/batch", files=[("files", MAIN), ("macros", MACRO)])
        assert resp.status_code == 200, resp.text
        assert started == {"names": ["main.yxmd"], "macros": ["Standard Cleanse.yxmc"]}

    def test_converting_a_whole_project_skips_its_macros(self, client, saved, started):
        """A macro is what workflows call, not a workflow to convert on its own."""
        resp = client.post("/api/convert/batch", data={"project_id": PID})
        assert resp.status_code == 200, resp.text
        assert started == {"names": ["main.yxmd"], "macros": ["Standard Cleanse.yxmc"]}
        assert resp.json()["total_files"] == 1

    def test_an_upload_of_only_macros_has_nothing_to_convert(self, client, started):
        resp = client.post("/api/convert/batch", files=[("files", MACRO)])
        assert resp.status_code == 422
        assert "only macros" in resp.json()["detail"]

    def test_the_run_expands_against_the_library(self, tmp_path):
        import asyncio

        job = batch_service.get_store().create(total=1)
        asyncio.run(batch_service._run_batch(job, [MAIN], macros=[MACRO]))
        (result,) = job.file_results
        assert result["success"], result
        types = [n["tool_type"] for n in result["dag_data"]["nodes"]]
        assert "Formula" in types and "Unknown" not in types


class TestEstate:
    def test_analysis_counts_the_macro_interior_not_an_unknown_tool(self, client):
        resp = client.post("/api/analyze", files=[("files", MAIN), ("files", MACRO)])
        assert resp.status_code == 200, resp.text
        main = next(w for w in resp.json()["workflows"] if w["file_name"].startswith("main"))
        assert main["coverage_percentage"] == 100.0
        assert "Unknown" not in resp.json()["unsupported_tools"]

    def test_from_a_project(self, client, saved):
        resp = client.post("/api/analyze", data={"project_id": PID})
        assert resp.status_code == 200, resp.text
        assert "Unknown" not in resp.json()["unsupported_tools"]

    @pytest.mark.parametrize("route", ["/api/analyze", "/api/assess", "/api/savings", "/api/portfolio"])
    def test_macros_are_not_counted_as_workflows(self, client, saved, route):
        resp = client.post(route, data={"project_id": PID})
        assert resp.status_code == 200, resp.text
        body = json.dumps(resp.json())
        assert "Standard Cleanse" not in body.replace("standard cleanse", "")  # not a workflow row
        counts = {
            "/api/analyze": lambda b: b["total_workflows"],
            "/api/assess": lambda b: b["totals"]["workflows"],
            "/api/savings": lambda b: b["estate"]["workflow_count"],
            "/api/portfolio": lambda b: b["summary"]["workflow_count"],
        }
        assert counts[route](resp.json()) == 1

    def test_a_missing_macro_is_named_not_a_macro_tool_type(self, client, saved):
        saved["macros"] = []
        resp = client.post("/api/analyze", data={"project_id": PID})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "Macro" not in body["unsupported_tools"]
        assert [m["name"] for m in body["unresolved_macros"]] == ["standard cleanse.yxmc"]
        assert body["workflows"][0]["coverage_percentage"] < 100


class TestLibraryNames:
    def test_keeps_the_name_workflows_refer_to(self):
        assert _library_name("Standard Cleanse (v2).yxmc") == "Standard Cleanse (v2).yxmc"

    def test_drops_any_path(self):
        assert _library_name("../../etc/evil.yxmc") == "evil.yxmc"
        assert _library_name(r"C:\Macros\Cleanse.yxmc") == "Cleanse.yxmc"

    @pytest.mark.parametrize("bad", ["", "..", "a\x00b.yxmc", "x" * 300 + ".yxmc"])
    def test_refuses_unusable_names(self, bad):
        assert _library_name(bad) is None

    def test_writes_into_one_folder(self, tmp_path):
        (library,) = write_macro_library([MACRO, ("../up.yxmc", b"<x/>")], tmp_path)
        assert sorted(p.name for p in library.iterdir()) == ["Standard Cleanse.yxmc", "up.yxmc"]
        assert library.parent == tmp_path

    def test_no_macros_no_folder(self, tmp_path):
        assert write_macro_library([], tmp_path) == []
        assert list(tmp_path.iterdir()) == []

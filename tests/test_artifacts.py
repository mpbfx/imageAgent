"""Tests for artifact-first run directories and JSONL tracing (plan task 3)."""

import json

from genclaw.artifacts import RunArtifacts
from genclaw.tracing import TraceWriter

TS = "20260618-120000"


def test_run_directory_is_created(tmp_run_dir):
    arts = RunArtifacts.create(tmp_run_dir, "req-1", TS)
    assert arts.run_dir.is_dir()
    assert arts.run_dir.name == f"{TS}-req-1"


def test_request_id_is_sanitized(tmp_run_dir):
    arts = RunArtifacts.create(tmp_run_dir, "bad/id:weird", TS)
    # No path separators or illegal Windows chars leak into the dir name.
    assert "/" not in arts.run_dir.name
    assert ":" not in arts.run_dir.name
    assert arts.run_dir.is_dir()


def test_artifact_paths_are_stable_within_a_run(tmp_run_dir):
    arts = RunArtifacts.create(tmp_run_dir, "req-1", TS)
    assert arts.plan_path == arts.plan_path
    assert arts.sketch_path == arts.run_dir / "sketch.png"
    assert arts.final_path == arts.run_dir / "final.png"


def test_canvas_path_by_backend(tmp_run_dir):
    arts = RunArtifacts.create(tmp_run_dir, "req-1", TS)
    assert arts.canvas_path("svg").name == "canvas.svg"
    assert arts.canvas_path("html").name == "canvas.html"
    # Three.js compiles to an HTML host page.
    assert arts.canvas_path("three").name == "canvas.html"


def test_write_json_preserves_non_ascii(tmp_run_dir):
    arts = RunArtifacts.create(tmp_run_dir, "req-1", TS)
    arts.write_json(arts.plan_path, {"prompt": "代码即画笔"})
    loaded = json.loads(arts.plan_path.read_text(encoding="utf-8"))
    assert loaded["prompt"] == "代码即画笔"


def test_write_error_artifact(tmp_run_dir):
    arts = RunArtifacts.create(tmp_run_dir, "req-1", TS)
    path = arts.write_error("render", "playwright missing", detail={"code": 1})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {
        "stage": "render",
        "error": "playwright missing",
        "detail": {"code": 1},
    }


def test_trace_appends_valid_jsonl(tmp_run_dir):
    arts = RunArtifacts.create(tmp_run_dir, "req-1", TS)
    writer = TraceWriter(arts.trace_path)
    writer.append("conceptualize", {"prompt": "代码即画笔"}, timestamp=TS)
    writer.append("render", {"backend": "svg"}, timestamp=TS)

    lines = arts.trace_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[0]["stage"] == "conceptualize"
    assert records[0]["prompt"] == "代码即画笔"
    assert [r["seq"] for r in records] == [0, 1]


def test_trace_contains_node_name(tmp_run_dir):
    arts = RunArtifacts.create(tmp_run_dir, "req-1", TS)
    writer = TraceWriter(arts.trace_path)
    writer.append_node(
        "render_node",
        input_summary="svg plan",
        artifacts={"canvas": arts.canvas_path("svg"), "sketch": arts.sketch_path},
    )
    events = writer.read_events()
    assert events[0]["node"] == "render_node"
    assert events[0]["artifacts"]["canvas"].endswith("canvas.svg")
    assert events[0]["error"] is None


def test_trace_creates_parent_dir(tmp_path):
    # Writer constructed before its directory exists must still work.
    target = tmp_path / "nope" / "trace.jsonl"
    writer = TraceWriter(target)
    writer.append("boot")
    assert target.exists()


def test_read_events_empty_when_missing(tmp_path):
    writer = TraceWriter(tmp_path / "absent.jsonl")
    assert writer.read_events() == []

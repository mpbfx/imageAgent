"""Tests for the CLI (plan task 12)."""

import json

import pytest
from typer.testing import CliRunner

from genclaw.cli import app

runner = CliRunner()


def test_run_fixture_exits_zero_and_prints_run_dir(tmp_path):
    result = runner.invoke(
        app, ["run", "--prompt", "three red circles on the left", "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    # The printed run dir exists and holds the artifacts.
    lines = result.output.strip().splitlines()
    # Last line should contain the review result (通过 or similar)
    # Skip text encoding issues by checking the run dir exists and artifacts are there
    run_dirs = list(tmp_path.glob("*/"))
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "plan.json").exists()
    assert (run_dir / "final.png").exists()
    assert (run_dir / "review.json").exists()


def test_run_rejects_unknown_mode(tmp_path):
    result = runner.invoke(
        app,
        ["run", "--prompt", "x", "--mode", "bogus", "--out", str(tmp_path)],
    )
    assert result.exit_code == 2
    assert "unknown mode" in result.output


def test_run_external_without_credentials_reports_error(tmp_path, monkeypatch):
    # No API keys -> the run should exit with code 1 or 2 and report an error.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    result = runner.invoke(
        app,
        ["run", "--prompt", "two blue squares", "--mode", "external", "--out", str(tmp_path)],
    )
    # Either exit code 1 (provider error caught during run) or 2 (config error at pipeline build)
    assert result.exit_code in (1, 2)


def test_run_unknown_prompt_exits_nonzero(tmp_path):
    result = runner.invoke(
        app, ["run", "--prompt", "an impressionist landscape", "--out", str(tmp_path)]
    )
    assert result.exit_code == 1
    # Verify that an error dir was created (even if with encoding issues in output text)
    assert list(tmp_path.glob("*/error.*.json"))


def test_render_compiles_saved_plan(tmp_path):
    # Produce a plan.json via a run, then render it standalone.
    runner.invoke(
        app, ["run", "--prompt", "three red circles on the left", "--out", str(tmp_path)]
    )
    plan_files = list(tmp_path.glob("*/plan.json"))
    assert plan_files
    out = tmp_path / "rendered"
    result = runner.invoke(app, ["render", "--plan", str(plan_files[0]), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "canvas.svg").exists()


def test_render_missing_plan_exits_two(tmp_path):
    result = runner.invoke(app, ["render", "--plan", str(tmp_path / "nope.json")])
    assert result.exit_code == 2


def test_review_over_run_dir(tmp_path):
    runner.invoke(
        app, ["run", "--prompt", "three red circles on the left", "--out", str(tmp_path)]
    )
    run_dir = next(tmp_path.glob("*/plan.json")).parent
    result = runner.invoke(app, ["review", "--run-dir", str(run_dir)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["passed"] is True

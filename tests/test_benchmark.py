"""Tests for the mini-benchmark harness (plan task 13)."""

import json

import pytest
from typer.testing import CliRunner

from genclaw.benchmarks.fixtures import get_suite
from genclaw.benchmarks.runner import run_benchmark
from genclaw.cli import app

runner = CliRunner()


def test_get_suite_unknown_raises():
    with pytest.raises(ValueError, match="unknown suite"):
        get_suite("nope")


def test_mini_suite_all_pass_in_fixture_mode(tmp_path):
    summary = run_benchmark(
        "mini",
        base_dir=tmp_path / "bench",
        runs_dir=tmp_path / "runs",
        mode="fixture",
    )
    assert summary["total"] == 3
    assert summary["passed"] == 3
    assert summary["pass_rate"] == 1.0
    # Disclaimer must mark this as non-official.
    assert "NOT comparable" in summary["disclaimer"]


def test_benchmark_writes_results_and_summary(tmp_path):
    run_benchmark("mini", base_dir=tmp_path / "bench", runs_dir=tmp_path / "runs")
    results = list((tmp_path / "bench").glob("*/results.json"))
    summaries = list((tmp_path / "bench").glob("*/summary.md"))
    assert results and summaries

    data = json.loads(results[0].read_text(encoding="utf-8"))
    assert {c["family"] for c in data["cases"]} == {
        "composition",
        "long_text",
        "physical_reasoning",
    }
    md = summaries[0].read_text(encoding="utf-8")
    assert "Pass rate" in md
    assert "NOT comparable" in md


def test_cli_bench_exit_zero(tmp_path):
    result = runner.invoke(app, ["bench", "--suite", "mini", "--out", str(tmp_path / "b")])
    assert result.exit_code == 0, result.output
    assert "3/3 passed" in result.output


def test_cli_bench_unknown_suite_exits_two(tmp_path):
    result = runner.invoke(app, ["bench", "--suite", "bogus", "--out", str(tmp_path / "b")])
    assert result.exit_code == 2

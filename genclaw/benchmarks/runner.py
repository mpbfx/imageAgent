"""Mini-benchmark runner (plan task 13).

Runs each fixture case through the pipeline, scores it against the case's
deterministic expectations (backend, object counts, required text in the canvas
source), and writes ``results.json`` + ``summary.md`` under
``outputs/benchmarks/<timestamp>/``.

This is a regression smoke harness, not a paper-comparable benchmark: scores are
pass/fail against our own fixtures, and the summary says so explicitly so no one
mistakes them for GenEval++/LongText numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from genclaw.benchmarks.fixtures import BenchCase, get_suite
from genclaw.graph.state import GenClawState
from genclaw.pipeline import Pipeline


@dataclass
class CaseResult:
    case_id: str
    family: str
    passed: bool
    checks: list = field(default_factory=list)  # (name, ok, detail)
    run_dir: Optional[str] = None
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "family": self.family,
            "passed": self.passed,
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in self.checks],
            "run_dir": self.run_dir,
            "errors": self.errors,
        }


def _score_case(case: BenchCase, state: GenClawState) -> CaseResult:
    checks: list[tuple[str, bool, str]] = []

    if state.plan is None:
        return CaseResult(
            case_id=case.case_id,
            family=case.family,
            passed=False,
            checks=[("plan_created", False, "no plan produced")],
            run_dir=str(state.run_dir) if state.run_dir else None,
            errors=list(state.errors),
        )

    # backend
    actual_backend = state.plan.backend.value
    checks.append(
        ("backend", actual_backend == case.expect_backend,
         f"expected {case.expect_backend}, got {actual_backend}")
    )

    # object counts by kind
    for kind, expected in case.expect_object_kinds.items():
        actual = sum(1 for o in state.plan.objects if o.kind == kind)
        checks.append(
            (f"count[{kind}]", actual == expected, f"expected {expected}, got {actual}")
        )

    # required text in the compiled canvas source
    if case.expect_texts:
        source = ""
        if state.rendered_canvas is not None and state.rendered_canvas.source_path.exists():
            source = state.rendered_canvas.source_path.read_text(encoding="utf-8")
        for needle in case.expect_texts:
            checks.append((f"text[{needle}]", needle in source, "in canvas source"))

    # canvas + final artifacts exist
    if state.rendered_canvas is not None:
        checks.append(
            ("canvas_artifact", state.rendered_canvas.source_path.exists(), "canvas source written")
        )
    if state.generation_result is not None:
        checks.append(
            ("final_artifact", state.generation_result.final_path.exists(), "final image written")
        )

    passed = all(ok for _, ok, _ in checks)
    return CaseResult(
        case_id=case.case_id,
        family=case.family,
        passed=passed,
        checks=checks,
        run_dir=str(state.run_dir) if state.run_dir else None,
        errors=list(state.errors),
    )


def run_benchmark(
    suite: str = "mini",
    *,
    base_dir: str | Path = "outputs/benchmarks",
    runs_dir: str | Path = "outputs/runs",
    timestamp: str = "00000000-000000",
    mode: str = "fixture",
) -> dict:
    """Run a suite and write results.json + summary.md. Returns the summary dict."""
    cases = get_suite(suite)
    pipeline = Pipeline.for_mode(mode, base_dir=runs_dir)

    results: list[CaseResult] = []
    for case in cases:
        state = pipeline.run(case.prompt, request_id=case.case_id, timestamp=timestamp)
        results.append(_score_case(case, state))

    passed = sum(1 for r in results if r.passed)
    summary = {
        "suite": suite,
        "mode": mode,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_rate": passed / len(results) if results else 0.0,
        "cases": [r.to_dict() for r in results],
        "disclaimer": (
            "Local regression smoke against project fixtures. NOT comparable to "
            "GenEval++/LongText-Bench/ImgEdit/Mind-Bench official metrics."
        ),
    }

    out_dir = Path(base_dir) / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_results(out_dir, summary)
    _write_summary_md(out_dir, summary)
    return summary


def _write_results(out_dir: Path, summary: dict) -> Path:
    import json

    path = out_dir / "results.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_summary_md(out_dir: Path, summary: dict) -> Path:
    lines = [
        f"# GenClaw mini-benchmark — suite `{summary['suite']}` (mode `{summary['mode']}`)",
        "",
        f"> {summary['disclaimer']}",
        "",
        f"**Pass rate:** {summary['passed']}/{summary['total']} "
        f"({summary['pass_rate'] * 100:.0f}%)",
        "",
        "| Case | Family | Result | Failing checks |",
        "| --- | --- | --- | --- |",
    ]
    for case in summary["cases"]:
        result = "✅ pass" if case["passed"] else "❌ fail"
        failing = [c["name"] for c in case["checks"] if not c["ok"]]
        lines.append(
            f"| {case['case_id']} | {case['family']} | {result} | "
            f"{', '.join(failing) or '—'} |"
        )
    path = out_dir / "summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

"""mini-benchmark runner(plan task 13)。

把每个 fixture case 跑过 pipeline,按 case 自带的确定性期望(backend、
object count、canvas 源码里必须出现的文本)打分,产物 ``results.json`` +
``summary.md`` 落在 ``outputs/benchmarks/<timestamp>/`` 下。

这是回归 smoke,不是论文可比对 benchmark:分数是"通过/不通过"我们
自己的 fixture,summary 里会写明,免得有人当成 GenEval++ / LongText
数字用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
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
            checks=[("plan_created", False, "没产出 plan")],
            run_dir=str(state.run_dir) if state.run_dir else None,
            errors=list(state.errors),
        )

    # backend
    actual_backend = state.plan.backend.value
    checks.append(
        ("backend", actual_backend == case.expect_backend,
         f"期望 {case.expect_backend},实际 {actual_backend}")
    )

    # 按 kind 统计 object 数量
    for kind, expected in case.expect_object_kinds.items():
        actual = sum(1 for o in state.plan.objects if o.kind == kind)
        checks.append(
            (f"count[{kind}]", actual == expected, f"期望 {expected},实际 {actual}")
        )

    # 编译出来的 canvas 源码里必须出现的文本
    if case.expect_texts:
        source = ""
        if state.rendered_canvas is not None and state.rendered_canvas.source_path.exists():
            source = state.rendered_canvas.source_path.read_text(encoding="utf-8")
        for needle in case.expect_texts:
            checks.append((f"text[{needle}]", needle in source, "在 canvas 源码里"))

    # canvas + final artifact 都已落盘
    if state.rendered_canvas is not None:
        checks.append(
            ("canvas_artifact", state.rendered_canvas.source_path.exists(), "canvas 源码已写")
        )
    if state.generation_result is not None:
        checks.append(
            ("final_artifact", state.generation_result.final_path.exists(), "最终图已写")
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
    timestamp: Optional[str] = None,
    mode: str = "fixture",
) -> dict:
    """跑一个 suite,写 results.json + summary.md,返回 summary dict。

    如果 timestamp 未指定,自动生成 YYYYMMDD_HHmmss 格式的时间戳。
    """
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

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
            "本地项目 fixture 回归 smoke,**不**和官方 GenEval++ / "
            "LongText-Bench / ImgEdit / Mind-Bench 指标可比。"
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
        f"**通过率:** {summary['passed']}/{summary['total']} "
        f"({summary['pass_rate'] * 100:.0f}%)",
        "",
        "| Case | Family | 结果 | 未通过的检查 |",
        "| --- | --- | --- | --- |",
    ]
    for case in summary["cases"]:
        result = "✅ 通过" if case["passed"] else "❌ 未通过"
        failing = [c["name"] for c in case["checks"] if not c["ok"]]
        lines.append(
            f"| {case['case_id']} | {case['family']} | {result} | "
            f"{', '.join(failing) or '—'} |"
        )
    path = out_dir / "summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path

"""GenClaw command-line interface (plan task 12).

Commands:

    genclaw run --prompt "three red circles on the left" --mode fixture
    genclaw render --plan path/to/plan.json
    genclaw review --run-dir path/to/run

Built on Typer + Rich. The CLI is a thin shell over :class:`genclaw.pipeline.
Pipeline`; it adds no domain logic. Errors exit non-zero with a concise message
rather than a traceback.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from genclaw.schemas import CanvasBackend, CanvasPlan


def _load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE lines from a local .env into os.environ (no override).

    Minimal, dependency-free, and only fills vars that aren't already set, so
    the real environment always wins. Credentials live here (gitignored), never
    in code. Lines starting with '#' and blank lines are ignored.
    """
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


# Pick up local credentials before any command runs.
_load_dotenv()

app = typer.Typer(
    add_completion=False,
    help="GenClaw reproduction: code-driven agentic image generation (fixture mode).",
)
console = Console()
err_console = Console(stderr=True)


@app.command()
def run(
    prompt: str = typer.Option(..., "--prompt", "-p", help="Natural-language request."),
    mode: str = typer.Option("fixture", "--mode", help="Provider mode: 'fixture', 'external', or 'external-code' (code-as-brush)."),
    out: Path = typer.Option(Path("outputs/runs"), "--out", help="Run output base dir."),
    max_revisions: int = typer.Option(1, "--max-revisions", help="Review retry budget."),
    use_langgraph: bool = typer.Option(False, "--langgraph", help="Drive via LangGraph."),
):
    """Run the pipeline for a prompt and write a complete run directory.

    'fixture' is deterministic and needs no credentials. 'external' uses the
    paper-aligned stack (Claude-Opus agent, Gemini generator, VLM reviewer) and
    requires ANTHROPIC_API_KEY / GOOGLE_API_KEY.
    """
    from genclaw.config import ProviderNotConfiguredError
    from genclaw.pipeline import Pipeline

    try:
        pipeline = Pipeline.for_mode(mode, base_dir=out, use_langgraph=use_langgraph)
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)

    try:
        state = pipeline.run(prompt, max_revisions=max_revisions)
    except ProviderNotConfiguredError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)
    except Exception as exc:  # pragma: no cover - defensive; nodes catch their own
        err_console.print(f"[red]run failed: {type(exc).__name__}: {exc}[/red]")
        raise typer.Exit(code=1)

    if state.plan is None or state.errors:
        err_console.print(f"[red]run completed with errors: {state.errors}[/red]")
        # Still print the dir so the error artifacts can be inspected.
        console.print(str(state.run_dir))
        raise typer.Exit(code=1)

    passed = state.review_result.passed if state.review_result else False
    console.print(str(state.run_dir))
    console.print(f"review: {'[green]PASS[/green]' if passed else '[yellow]FAIL[/yellow]'}")


@app.command()
def render(
    plan: Path = typer.Option(..., "--plan", help="Path to a plan.json file."),
    out: Optional[Path] = typer.Option(None, "--out", help="Output dir (default: plan's dir)."),
):
    """Compile a saved CanvasPlan to canvas source (and PNG if a browser is present)."""
    if not plan.exists():
        err_console.print(f"[red]plan file not found: {plan}[/red]")
        raise typer.Exit(code=2)
    try:
        data = json.loads(plan.read_text(encoding="utf-8"))
        canvas_plan = CanvasPlan.model_validate(data)
    except Exception as exc:
        err_console.print(f"[red]invalid plan: {type(exc).__name__}: {exc}[/red]")
        raise typer.Exit(code=2)

    out_dir = out or plan.parent
    renderer = _renderer_for(canvas_plan.backend)
    result = renderer.render(canvas_plan, out_dir)
    console.print(str(result.source_path))


@app.command()
def review(
    run_dir: Path = typer.Option(..., "--run-dir", help="A completed run directory."),
):
    """Re-run rule-based review over a completed run directory."""
    plan_path = run_dir / "plan.json"
    if not plan_path.exists():
        err_console.print(f"[red]no plan.json in {run_dir}[/red]")
        raise typer.Exit(code=2)

    from genclaw.review.rules import RuleReviewer

    canvas_plan = CanvasPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    source_path = run_dir / f"canvas.{_ext(canvas_plan.backend)}"
    final_path = run_dir / "final.png"
    result = RuleReviewer().review(
        canvas_plan,
        canvas_source_path=source_path if source_path.exists() else None,
        image_path=final_path if final_path.exists() else None,
    )
    console.print_json(result.model_dump_json())
    if not result.passed:
        raise typer.Exit(code=1)


@app.command()
def bench(
    suite: str = typer.Option("mini", "--suite", help="Benchmark suite name."),
    out: Path = typer.Option(Path("outputs/benchmarks"), "--out", help="Benchmark output base dir."),
    mode: str = typer.Option("fixture", "--mode", help="Provider mode."),
):
    """Run a local mini-benchmark suite and write results.json + summary.md.

    This is a regression smoke against project fixtures, NOT comparable to the
    official GenEval++/LongText/ImgEdit/Mind-Bench metrics.
    """
    from genclaw.benchmarks.runner import run_benchmark

    try:
        summary = run_benchmark(suite, base_dir=out, mode=mode)
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)

    console.print(
        f"{suite}: {summary['passed']}/{summary['total']} passed "
        f"({summary['pass_rate'] * 100:.0f}%)"
    )
    if summary["failed"]:
        raise typer.Exit(code=1)


def _ext(backend: CanvasBackend) -> str:
    return {
        "svg": "svg",
        "html": "html",
        "three": "html",
        "python": "py",
        "canvas": "html",
    }[backend.value]


def _renderer_for(backend: CanvasBackend):
    # Reuse the canonical renderer dispatch so the CLI never drifts from the
    # graph's backend support.
    from genclaw.graph.nodes import _renderer_for as dispatch

    return dispatch(backend)


if __name__ == "__main__":  # pragma: no cover
    app()

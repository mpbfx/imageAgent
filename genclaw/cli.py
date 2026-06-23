"""GenClaw 命令行入口(plan task 12)。

命令:

    genclaw run --prompt "three red circles on the left" --mode fixture
    genclaw render --plan path/to/plan.json
    genclaw review --run-dir path/to/run

基于 Typer + Rich。CLI 是 :class:`genclaw.pipeline.Pipeline` 的薄壳,
不引入领域逻辑。错误以非零退出 + 简短信息返回,不打 traceback。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
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


# 在任何命令运行前先拾起本地凭据。
_load_dotenv()

app = typer.Typer(
    add_completion=False,
    help="GenClaw 复现:code-driven 智能体图像生成(默认 fixture 模式)。",
)
console = Console()
err_console = Console(stderr=True)


@app.command()
def run(
    prompt: str = typer.Option(..., "--prompt", "-p", help="自然语言请求。"),
    mode: str = typer.Option("fixture", "--mode", help="fixture | external(code-as-brush,真实模型默认) | external-template(结构化) | external-code(别名)。"),
    out: Path = typer.Option(Path("outputs/runs"), "--out", help="run 输出根目录。"),
    max_revisions: int = typer.Option(1, "--max-revisions", help="审查重试预算。"),
    use_langgraph: bool = typer.Option(False, "--langgraph", help="改用 LangGraph 驱动。"),
    search_provider: Optional[str] = typer.Option(None, "--search-provider", help="搜索后端:tavily(默认) | serper。"),
):
    """为 prompt 跑一次 pipeline,产出完整 run 目录。

    'fixture' 确定性、不需要凭据。'external' 用论文对齐的栈
    (Claude-Opus agent、图像生成器、VLM 审查者),默认 *code-as-brush*:
    LLM 直接写 SVG / HTML / Three.js 源码。'external-template' 是结构化
    模板兜底(不跑模型代码)。需要 ANTHROPIC_API_KEY / GOOGLE_API_KEY。

    搜索 provider 默认为 Tavily;指定 --search-provider serper 切换到 Serper。
    """
    from genclaw.config import ProviderNotConfiguredError
    from genclaw.pipeline import Pipeline

    # 安全提示:code-as-brush 会执行模型写的代码(HTML / Three.js 在
    # 无沙箱的头部 Chromium 里跑 JS;ADR 0005)。显式警告一下,让用户
    # 知道真实模型 run 在做什么。external-template 不会。
    if mode in ("external", "external-code"):
        err_console.print(
            "[yellow]⚠ code-as-brush:接下来会渲染模型写的代码。HTML / "
            "Three.js 会在无沙箱的头部 Chromium 里跑 JS(ADR 0005)。"
            "仅在信任输入时使用;想避免跑模型代码请用 --mode external-template。"
            "[/yellow]"
        )

    def on_progress(stage: str, status: str, details: dict | None):
        """进度回调:显示当前阶段和状态。"""
        stage_names = {
            "conceptualize": "理解需求",
            "render": "渲染画布",
            "generate": "生成图像",
            "review": "审查",
            "revise": "修订",
            "search": "搜索",
        }
        display_stage = stage_names.get(stage, stage)
        if status == "starting":
            print(f"{display_stage}...", end="", flush=True, file=sys.stdout)
        elif status == "done":
            detail_str = ""
            if details:
                if stage == "conceptualize" and "objects" in details:
                    detail_str = f" ({details['objects']} 个对象, backend={details['backend']})"
                elif stage == "render" and "backend" in details:
                    detail_str = f" (backend={details['backend']})"
                elif stage == "generate" and "provider" in details:
                    detail_str = f" (provider={details['provider']})"
                elif stage == "review" and "passed" in details:
                    passed = details["passed"]
                    score = details.get("score", 0)
                    status_mark = "通过" if passed else "未通过"
                    detail_str = f" ({status_mark}, 分数={score:.2f})"
                elif stage == "revise" and "revision" in details:
                    detail_str = f" (轮次 {details['revision']}/{details['max_revisions']})"
            print(f" [OK]{detail_str}", file=sys.stdout)

    try:
        pipeline = Pipeline.for_mode(
            mode, base_dir=out, use_langgraph=use_langgraph, on_progress=on_progress, search_provider=search_provider
        )
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)

    # 生成 YYYYMMDD_HHmmss 格式的时间戳
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        state = pipeline.run(prompt, max_revisions=max_revisions, timestamp=timestamp)
    except ProviderNotConfiguredError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)
    except Exception as exc:  # pragma: no cover —— 防御性;节点自己接异常
        err_console.print(f"[red]run 失败:{type(exc).__name__}:{exc}[/red]")
        raise typer.Exit(code=1)

    if state.plan is None or state.errors:
        err_console.print(f"[red]run 完成但有错误:{state.errors}[/red]")
        # 仍然把目录打出来,这样 error artifact 还能被查到。
        console.print(str(state.run_dir))
        raise typer.Exit(code=1)

    passed = state.review_result.passed if state.review_result else False
    print(f"\n输出目录: {state.run_dir}", file=sys.stdout)
    print(f"审查: {'通过' if passed else '未通过'}", file=sys.stdout)


@app.command()
def render(
    plan: Path = typer.Option(..., "--plan", help="plan.json 路径。"),
    out: Optional[Path] = typer.Option(None, "--out", help="输出目录(默认:plan 所在目录)。"),
):
    """把保存的 CanvasPlan 编译成画布源码(有浏览器时还会光栅化 PNG)。"""
    if not plan.exists():
        err_console.print(f"[red]找不到 plan 文件:{plan}[/red]")
        raise typer.Exit(code=2)
    try:
        data = json.loads(plan.read_text(encoding="utf-8"))
        canvas_plan = CanvasPlan.model_validate(data)
    except Exception as exc:
        err_console.print(f"[red]plan 不合法:{type(exc).__name__}:{exc}[/red]")
        raise typer.Exit(code=2)

    out_dir = out or plan.parent
    renderer = _renderer_for(canvas_plan.backend)
    result = renderer.render(canvas_plan, out_dir)
    console.print(str(result.source_path))


@app.command()
def review(
    run_dir: Path = typer.Option(..., "--run-dir", help="一个已完成的 run 目录。"),
):
    """对一个已完成的 run 目录重跑基于规则的审查。"""
    plan_path = run_dir / "plan.json"
    if not plan_path.exists():
        err_console.print(f"[red]{run_dir} 里没有 plan.json[/red]")
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
    suite: str = typer.Option("mini", "--suite", help="benchmark 套件名。"),
    out: Path = typer.Option(Path("outputs/benchmarks"), "--out", help="benchmark 输出根目录。"),
    mode: str = typer.Option("fixture", "--mode", help="provider mode。"),
):
    """跑本地 mini-benchmark 套件,产出 results.json + summary.md。

    这是项目 fixture 的回归 smoke,**不**和官方 GenEval++ / LongText /
    ImgEdit / Mind-Bench 指标可比。
    """
    from genclaw.benchmarks.runner import run_benchmark

    try:
        summary = run_benchmark(suite, base_dir=out, mode=mode)
    except ValueError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2)

    console.print(
        f"{suite}:{summary['passed']}/{summary['total']} 通过 "
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
    # 复用 graph 节点的 renderer 派发,这样 CLI 永远不会和图里的
    # backend 支持表脱节。
    from genclaw.graph.nodes import _renderer_for as dispatch

    return dispatch(backend)


if __name__ == "__main__":  # pragma: no cover —— CLI 入口,不走单测
    app()

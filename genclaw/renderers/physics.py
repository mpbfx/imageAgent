"""物理/几何 renderer:Python plotting 和 2D Canvas(论文 §3.2)。

论文对受物理规律约束的任务(弹簧、压强、浮力、几何关系)用「Python
plotting、Canvas、或者简单 3D 脚本」——重点是「关系对」,不是画面好不好
看,代码在这里扮演「物理草稿 / 符号化世界模型」的角色。Three.js 是全 3D
场景,对「弹簧形变曲线」这种数值草图来说完全错误,所以拆成两个独立
backend。

本模块容纳两个 backend:

* ``python`` -- 吐出一个 matplotlib 脚本,有 matplotlib 时直接光栅化(无
  需浏览器)。源码编译总是纯函数。
* ``canvas`` -- 吐出一个 2D ``<canvas>`` 脚本的 HTML 页,用 Playwright 辅助
  函数光栅化(和 HTML / Three 后端一个路径)。

objects 画在它们的 ``attributes`` 上(位置、大小),cognitive 层算出的
``ReasoningStep.values`` 也会出现在 plan 里以驱动坐标——renderer 只读
结构化 plan,绝**不**执行 model 写的代码(phase-1 的 structured source
策略)。
"""

# 中文补充说明：
# 设计要点:
#   1) 两个 backend 共享一个 renderer 类,backend 由 __init__ 决定
#   2) python backend 用 matplotlib 截屏(不需浏览器);canvas backend 用
#      浏览器截屏(同 HTML / Three 路径)
#   3) draw calls 完全由 plan 字段生成,LLM 写的「代码」绝对不会在这里
#      被直接执行——这是 phase-1 的安全策略:
#        LLM 只能「选结构化字段」,不能「注入任意代码」
#   4) reasoning 步骤里的 values 会原样落到脚本注释里,既可读又可复现

from __future__ import annotations

import json
from pathlib import Path

from genclaw.renderers.base import RenderedCanvas, Renderer
from genclaw.schemas import CanvasBackend, CanvasPlan, ObjectSpec


class PhysicsRenderer(Renderer):
    """把物理/几何 plan 编译成 Python 或 Canvas 草稿。"""

    def __init__(self, backend: CanvasBackend = CanvasBackend.python):
        if backend not in (CanvasBackend.python, CanvasBackend.canvas):
            raise ValueError(f"PhysicsRenderer does not support backend {backend!r}")
        self.backend = backend

    def compile_source(self, plan: CanvasPlan) -> str:
        """把 ``plan`` 编译成对应 backend 的源码。纯函数,无执行、无 IO。"""
        if self.backend is CanvasBackend.python:
            return _python_source(plan)
        return _canvas_source(plan)

    def render(self, plan: CanvasPlan, output_dir: Path) -> RenderedCanvas:
        """写 source + 有可能光栅化 PNG(matplotlib 或 Playwright)。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        source = self.compile_source(plan)

        if self.backend is CanvasBackend.python:
            source_path = output_dir / "canvas.py"
            source_path.write_text(source, encoding="utf-8")
            png_path = output_dir / "sketch.png"
            rasterized = _try_matplotlib(plan, png_path)
        else:
            source_path = output_dir / "canvas.html"
            source_path.write_text(source, encoding="utf-8")
            png_path = output_dir / "sketch.png"
            rasterized = _try_rasterize_html(source, png_path, plan.size.width, plan.size.height)

        return RenderedCanvas(
            backend=self.backend,
            source_path=source_path,
            png_path=png_path if rasterized else None,
            width=plan.size.width,
            height=plan.size.height,
        )


def _draw_calls_py(plan: CanvasPlan) -> str:
    """把 plan.objects 翻译成 matplotlib 绘制调用。"""
    lines = []
    for obj in plan.objects:
        a = obj.attributes
        color = json.dumps(obj.fill or a.get("color", "#1f77b4"))
        if obj.kind in ("circle", "sphere"):
            # radius 优先 attributes.radius,否则用 width/height 的最大一半,
            # 全 0 兜底 1.0 防止除 0
            r = a.get("radius", max(obj.width, obj.height) / 2.0 or 1.0)
            lines.append(
                f"ax.add_patch(plt.Circle(({obj.x}, {obj.y}), {r}, color={color}))"
            )
        elif obj.kind in ("rectangle", "rect"):
            lines.append(
                f"ax.add_patch(plt.Rectangle(({obj.x}, {obj.y}), "
                f"{obj.width}, {obj.height}, color={color}))"
            )
        elif obj.kind == "line":
            pts = a.get("points", [])
            if pts:
                xs = json.dumps([p[0] for p in pts])
                ys = json.dumps([p[1] for p in pts])
                lines.append(f"ax.plot({xs}, {ys}, color={color})")
    return "\n".join("    " + ln for ln in lines) or "    pass"


def _python_source(plan: CanvasPlan) -> str:
    """生成 matplotlib 脚本。reasoning 步骤以注释形式落进去,方便人读。"""
    w, h = plan.size.width, plan.size.height
    dpi = 100
    reasoning = json.dumps(
        [{"q": r.question, "c": r.conclusion, "v": r.values} for r in plan.reasoning],
        ensure_ascii=False,
    )
    return f'''"""Auto-generated physical-draft plot for: {plan.prompt!r}.

Reasoning steps (derived constraints): {reasoning}
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def render(out_path="sketch.png"):
    fig, ax = plt.subplots(figsize=({w / dpi}, {h / dpi}), dpi={dpi})
    ax.set_xlim(0, {w})
    ax.set_ylim(0, {h})
    ax.set_aspect("equal")
{_draw_calls_py(plan)}
    fig.savefig(out_path)
    plt.close(fig)


if __name__ == "__main__":
    render()
'''


def _draw_calls_canvas(plan: CanvasPlan) -> str:
    """把 plan.objects 翻译成 2D canvas 绘制调用。"""
    lines = []
    for obj in plan.objects:
        a = obj.attributes
        color = json.dumps(obj.fill or a.get("color", "#1f77b4"))
        if obj.kind in ("circle", "sphere"):
            r = a.get("radius", max(obj.width, obj.height) / 2.0 or 1.0)
            lines.append(f"ctx.fillStyle = {color};")
            lines.append("ctx.beginPath();")
            lines.append(f"ctx.arc({obj.x}, {obj.y}, {r}, 0, 2 * Math.PI);")
            lines.append("ctx.fill();")
        elif obj.kind in ("rectangle", "rect"):
            lines.append(f"ctx.fillStyle = {color};")
            lines.append(f"ctx.fillRect({obj.x}, {obj.y}, {obj.width}, {obj.height});")
    return "\n      ".join(lines) or "// no drawable objects"


def _canvas_source(plan: CanvasPlan) -> str:
    """生成 HTML+canvas2D 脚本页。__gcRendered 是给 Playwright 的「渲染完成」旗标。"""
    w, h = plan.size.width, plan.size.height
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8" /><style>*{{margin:0;padding:0}}</style></head>
<body>
  <canvas id="c" width="{w}" height="{h}"></canvas>
  <script>
    const ctx = document.getElementById("c").getContext("2d");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, {w}, {h});
    {_draw_calls_canvas(plan)}
    window.__gcRendered = true;
  </script>
</body>
</html>
"""


def _try_matplotlib(plan: CanvasPlan, png_path: Path) -> bool:
    """有 matplotlib 就直接光栅化,失败/没装就返回 False(只留 source)。"""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return False
    try:
        dpi = 100
        fig, ax = plt.subplots(
            figsize=(plan.size.width / dpi, plan.size.height / dpi), dpi=dpi
        )
        ax.set_xlim(0, plan.size.width)
        ax.set_ylim(0, plan.size.height)
        ax.set_aspect("equal")
        for obj in plan.objects:
            _draw_obj_mpl(ax, obj, plt)
        fig.savefig(png_path)
        plt.close(fig)
    except Exception:
        return False
    return True


def _draw_obj_mpl(ax, obj: ObjectSpec, plt) -> None:
    """_try_matplotlib 用到的对象绘制器。和 _draw_calls_py 平行但走 live API。"""
    a = obj.attributes
    color = obj.fill or a.get("color", "#1f77b4")
    if obj.kind in ("circle", "sphere"):
        r = a.get("radius", max(obj.width, obj.height) / 2.0 or 1.0)
        ax.add_patch(plt.Circle((obj.x, obj.y), r, color=color))
    elif obj.kind in ("rectangle", "rect"):
        ax.add_patch(plt.Rectangle((obj.x, obj.y), obj.width, obj.height, color=color))


def _try_rasterize_html(html: str, png_path: Path, width: int, height: int) -> bool:
    """Playwright 可用就截屏 canvas 页,否则跳过。"""
    try:
        from genclaw.renderers.playwright_render import render_html_to_png
    except Exception:
        return False
    try:
        render_html_to_png(html, png_path, width=width, height=height)
    except Exception:
        return False
    return True

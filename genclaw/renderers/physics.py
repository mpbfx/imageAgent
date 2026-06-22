"""Physics/geometry renderers: Python plotting and 2D Canvas (paper §3.2).

The paper uses "Python plotting, Canvas, or a simple 3D script" for tasks
governed by physical laws (springs, pressure, buoyancy, geometry), where the
point is *correct relations*, not visual style -- code acts as a "physical
draft" or "symbolic world model". Three.js (a full 3D scene) is the wrong tool
for a numeric draft like a spring deflection plot, so these are distinct
backends.

Two backends share this module:

* ``python`` -- emits a matplotlib script and rasterizes via matplotlib if
  available (no browser needed). Source compilation is always pure.
* ``canvas`` -- emits an HTML page with a 2D ``<canvas>`` script and rasterizes
  via the Playwright helper (like the HTML/Three backends).

Objects are drawn from their ``attributes`` (positions, sizes), and any
``ReasoningStep.values`` the cognitive layer derived are available on the plan
to drive coordinates -- the renderer reads the structured plan, never executes
model-authored code (phase-1 structured source policy).
"""

from __future__ import annotations

import json
from pathlib import Path

from genclaw.renderers.base import RenderedCanvas, Renderer
from genclaw.schemas import CanvasBackend, CanvasPlan, ObjectSpec


class PhysicsRenderer(Renderer):
    """Compiles a physical/geometric plan to a Python or Canvas draft."""

    def __init__(self, backend: CanvasBackend = CanvasBackend.python):
        if backend not in (CanvasBackend.python, CanvasBackend.canvas):
            raise ValueError(f"PhysicsRenderer does not support backend {backend!r}")
        self.backend = backend

    def compile_source(self, plan: CanvasPlan) -> str:
        """Compile ``plan`` to backend source. Pure; no execution, no IO."""
        if self.backend is CanvasBackend.python:
            return _python_source(plan)
        return _canvas_source(plan)

    def render(self, plan: CanvasPlan, output_dir: Path) -> RenderedCanvas:
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
    lines = []
    for obj in plan.objects:
        a = obj.attributes
        color = json.dumps(obj.fill or a.get("color", "#1f77b4"))
        if obj.kind in ("circle", "sphere"):
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
    a = obj.attributes
    color = obj.fill or a.get("color", "#1f77b4")
    if obj.kind in ("circle", "sphere"):
        r = a.get("radius", max(obj.width, obj.height) / 2.0 or 1.0)
        ax.add_patch(plt.Circle((obj.x, obj.y), r, color=color))
    elif obj.kind in ("rectangle", "rect"):
        ax.add_patch(plt.Rectangle((obj.x, obj.y), obj.width, obj.height, color=color))


def _try_rasterize_html(html: str, png_path: Path, width: int, height: int) -> bool:
    try:
        from genclaw.renderers.playwright_render import render_html_to_png
    except Exception:
        return False
    try:
        render_html_to_png(html, png_path, width=width, height=height)
    except Exception:
        return False
    return True

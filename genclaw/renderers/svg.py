"""SVG renderer(plan task 6)。

把 ``structured`` :class:`~genclaw.schemas.CanvasPlan` 编译成 SVG 源码。
SVG 是 object count / layout / spatial relations / local edit 任务
(GenEval++ / ImgEdit) 的后端。源码编译是纯函数、且不依赖浏览器;PNG
光栅化由 Playwright 辅助函数负责,且只在浏览器可用时尝试——所以本模块
import 不需要装 Playwright。

支持 shape: circle / rectangle / ellipse / polygon(显式 ``points``)。
元素按 layer 顺序、再按 object 顺序绘制,后画的盖在前面(对齐
``CanvasPlan.ordered_layers`` 的语义)。
"""

# 中文补充说明：
# 整个 renderer 几乎没有复杂度,核心就两个步骤:
#   1) compile_source:把 plan 里所有 objects / text 排好序,塞进 <svg>
#   2) _try_rasterize:用 Playwright 把 SVG 套进一个最小 HTML 容器截屏
# 浏览器不可用就退回「只有 source 没有 png」,phase-1 也能跑 CI。
# _SHAPES 用 kind 字符串分派具体形状的 renderer,新增 shape 只需加一个
# 函数 + 字典里加一行。

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from genclaw.renderers.base import RenderedCanvas, Renderer
from genclaw.schemas import CanvasBackend, CanvasPlan, ObjectSpec, TextSpec


def _attr(value: object) -> str:
    """转义一个值,让它能放进双引号包裹的 XML 属性。"""
    return escape(str(value), {'"': "&quot;"})


def _circle(obj: ObjectSpec) -> str:
    # radius 优先取 attributes.radius,否则用 width 的一半
    r = obj.attributes.get("radius", obj.width / 2.0 if obj.width else 0.0)
    cx = obj.x + r
    cy = obj.y + r
    fill = obj.fill or "none"
    stroke = f' stroke="{_attr(obj.stroke)}"' if obj.stroke else ""
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{_attr(fill)}"{stroke} />'


def _rectangle(obj: ObjectSpec) -> str:
    fill = obj.fill or "none"
    stroke = f' stroke="{_attr(obj.stroke)}"' if obj.stroke else ""
    return (
        f'<rect x="{obj.x}" y="{obj.y}" width="{obj.width}" height="{obj.height}" '
        f'fill="{_attr(fill)}"{stroke} />'
    )


def _ellipse(obj: ObjectSpec) -> str:
    rx = obj.width / 2.0
    ry = obj.height / 2.0
    cx = obj.x + rx
    cy = obj.y + ry
    fill = obj.fill or "none"
    stroke = f' stroke="{_attr(obj.stroke)}"' if obj.stroke else ""
    return f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{_attr(fill)}"{stroke} />'


def _polygon(obj: ObjectSpec) -> str:
    pts = obj.attributes.get("points", [])
    # 接受 [[x,y],...] 或 [x,y,x,y,...] 两种写法
    if pts and isinstance(pts[0], (list, tuple)):
        flat = [coord for pair in pts for coord in pair]
    else:
        flat = list(pts)
    points = " ".join(
        f"{flat[i]},{flat[i + 1]}" for i in range(0, len(flat) - 1, 2)
    )
    fill = obj.fill or "none"
    stroke = f' stroke="{_attr(obj.stroke)}"' if obj.stroke else ""
    return f'<polygon points="{_attr(points)}" fill="{_attr(fill)}"{stroke} />'


# kind -> 形状渲染函数。新增形状只需加函数 + 字典加一行
_SHAPES = {
    "circle": _circle,
    "rectangle": _rectangle,
    "rect": _rectangle,
    "ellipse": _ellipse,
    "polygon": _polygon,
}


def _text(txt: TextSpec) -> str:
    anchor = {"left": "start", "center": "middle", "right": "end"}[txt.align]
    # y 在 plan 里是「文字框的 top」,而 SVG text 元素的 y 是「baseline」;
    # 这里把 font_size 加回去当作近似 baseline 偏移(够用,不做精细 baseline 对齐)
    y = txt.y + txt.font_size
    return (
        f'<text x="{txt.x}" y="{y}" font-size="{txt.font_size}" '
        f'fill="{_attr(txt.color)}" text-anchor="{anchor}">'
        f"{escape(txt.text)}</text>"
    )


class SVGRenderer(Renderer):
    """把 CanvasPlan 编译成 SVG,可选地光栅化为 PNG。"""

    backend = CanvasBackend.svg

    def compile_source(self, plan: CanvasPlan) -> str:
        """把 ``plan`` 编译成 SVG 源码。纯函数,无浏览器、无 IO。"""
        w, h = plan.size.width, plan.size.height
        # layer_id -> order 的查找表,后面排序要用
        layer_order = {layer.id: layer.order for layer in plan.layers}
        # 稳定排序:先按 layer.order,再按原顺序(index 决定并列时的相对位置)
        ordered_objs = sorted(
            enumerate(plan.objects),
            key=lambda io: (layer_order.get(io[1].layer_id, 0), io[0]),
        )
        ordered_texts = sorted(
            enumerate(plan.text),
            key=lambda it: (layer_order.get(it[1].layer_id, 0), it[0]),
        )

        body: list[str] = []
        for _, obj in ordered_objs:
            shape = _SHAPES.get(obj.kind)
            if shape is not None:
                body.append("  " + shape(obj))
        for _, txt in ordered_texts:
            body.append("  " + _text(txt))

        children = "\n".join(body)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}">\n{children}\n</svg>\n'
        )

    def render(self, plan: CanvasPlan, output_dir: Path) -> RenderedCanvas:
        """写 source 到 ``output_dir/canvas.svg``,有 Playwright 就再截 PNG。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        source = self.compile_source(plan)
        source_path = output_dir / "canvas.svg"
        source_path.write_text(source, encoding="utf-8")

        png_path = output_dir / "sketch.png"
        rasterized = _try_rasterize(source, png_path, plan.size.width, plan.size.height)

        return RenderedCanvas(
            backend=CanvasBackend.svg,
            source_path=source_path,
            png_path=png_path if rasterized else None,
            width=plan.size.width,
            height=plan.size.height,
        )


def _try_rasterize(svg_source: str, png_path: Path, width: int, height: int) -> bool:
    """如果 Playwright 可用,把 SVG 光栅化成 PNG;否则返回 False 跳过。

    返回值表示「是否生成了 PNG」。import 是懒的,所以本模块在没有浏览器
    的环境里也能 import(phase-1 策略)。
    """
    try:
        from genclaw.renderers.playwright_render import render_html_to_png
    except Exception:
        return False
    # SVG 套进最小 HTML 容器,Playwright 直接截
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>*{margin:0;padding:0}</style></head>"
        f"<body>{svg_source}</body></html>"
    )
    try:
        render_html_to_png(html, png_path, width=width, height=height)
    except Exception:
        return False
    return True

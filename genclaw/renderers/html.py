"""HTML/CSS renderer(plan task 7)。

把 long-text ``structured`` :class:`~genclaw.schemas.CanvasPlan` 编译成
HTML/CSS。HTML 是长文本 / 海报 / 卡片(LongText-Bench)类任务的后端。文字
块用绝对定位以获得确定性布局,user 文本做 HTML escape(绝不会当 markup 执
行),文本原文完整保留——这样 reviewer 的 ``contains_text`` 检查能精确
核对。

源码编译纯函数、无浏览器;PNG 光栅化交给 Playwright 辅助函数,只在浏览
器可用时尝试。
"""

# 中文补充说明：
# 关键点:escape(txt.text) 是必须的——LLM 写出来的 prompt 内容里如果
# 出现 < > & 之类,不能让它变成 markup;既要忠实显示,也要安全。
# 绝对定位 (position: absolute) 是为了「像素级确定」——reviewer
# 才能精确框位置,而不是被自动布局打乱。
# 中文字体优先 Microsoft YaHei(Win) / Segoe UI(Mac/默认 fallback),
# 长文本任务里西文/中文混排不出现「口口」。

from __future__ import annotations

from html import escape
from pathlib import Path

from genclaw.renderers.base import RenderedCanvas, Renderer
from genclaw.schemas import CanvasBackend, CanvasPlan, TextSpec

CJK_FONT_STACK = (
    "'Noto Serif CJK SC','Source Han Serif SC','Source Han Serif CN',"
    "'SimSun','Songti SC','Microsoft YaHei',serif"
)


def _text_block(txt: TextSpec) -> str:
    """把一个 TextSpec 编成一个 ``<div>``。position:absolute 保确定性。"""
    style = (
        f"position:absolute; left:{txt.x}px; top:{txt.y}px; "
        f"width:{txt.width or 'auto'}{'px' if txt.width else ''}; "
        f"height:{txt.height or 'auto'}{'px' if txt.height else ''}; "
        f"font-size:{txt.font_size}px; color:{escape(txt.color, quote=True)}; "
        f"text-align:{txt.align}; "
        f"font-family:{CJK_FONT_STACK}; "
        "white-space:pre-wrap; word-wrap:break-word;"
    )
    return (
        f'<div class="text-block" id="{escape(txt.id, quote=True)}" '
        f'style="{style}">{escape(txt.text)}</div>'
    )


class HTMLRenderer(Renderer):
    """把 long-text CanvasPlan 编译成 HTML/CSS,可选地光栅化 PNG。"""

    backend = CanvasBackend.html

    def compile_source(self, plan: CanvasPlan) -> str:
        """把 ``plan`` 编译成 HTML 文档。纯函数,无浏览器、无 IO。"""
        w, h = plan.size.width, plan.size.height
        bg = plan.style.get("background", "#ffffff")
        layer_order = {layer.id: layer.order for layer in plan.layers}
        ordered = sorted(
            enumerate(plan.text),
            key=lambda it: (layer_order.get(it[1].layer_id, 0), it[0]),
        )
        blocks = "\n    ".join(_text_block(t) for _, t in ordered)
        return (
            "<!doctype html>\n"
            '<html lang="en">\n<head>\n  <meta charset="utf-8" />\n'
            "  <style>\n"
            "    * { margin: 0; padding: 0; box-sizing: border-box; }\n"
            f"    #canvas {{ position: relative; width: {w}px; height: {h}px; "
            f"background: {escape(str(bg), quote=True)}; overflow: hidden; }}\n"
            "  </style>\n</head>\n<body>\n"
            f'  <div id="canvas">\n    {blocks}\n  </div>\n'
            "</body>\n</html>\n"
        )

    def render(self, plan: CanvasPlan, output_dir: Path) -> RenderedCanvas:
        """写 source 到 ``output_dir/canvas.html``,有 Playwright 就再截 PNG。"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        source = self.compile_source(plan)
        source_path = output_dir / "canvas.html"
        source_path.write_text(source, encoding="utf-8")

        png_path = output_dir / "sketch.png"
        rasterized = _try_rasterize(source, png_path, plan.size.width, plan.size.height)

        return RenderedCanvas(
            backend=CanvasBackend.html,
            source_path=source_path,
            png_path=png_path if rasterized else None,
            width=plan.size.width,
            height=plan.size.height,
        )


def _try_rasterize(html: str, png_path: Path, width: int, height: int) -> bool:
    """Playwright 可用就截屏,不可用或失败就跳过并返回 False。"""
    try:
        from genclaw.renderers.playwright_render import render_html_to_png
    except Exception:
        return False
    try:
        render_html_to_png(html, png_path, width=width, height=height)
    except Exception:
        return False
    return True

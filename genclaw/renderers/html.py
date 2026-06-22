"""HTML/CSS renderer (plan task 7).

Compiles a long-text ``structured`` :class:`~genclaw.schemas.CanvasPlan` into
HTML/CSS. HTML is the backend for long text, posters, and cards (LongText-Bench
family). Text blocks are absolutely positioned for deterministic layout, user
text is HTML-escaped (never executed as markup), and the exact text is preserved
in the source so the reviewer's ``contains_text`` check can verify it.

Source compilation is pure and browser-free; PNG rasterization is delegated to
the Playwright helper and only attempted when a browser is available.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from genclaw.renderers.base import RenderedCanvas, Renderer
from genclaw.schemas import CanvasBackend, CanvasPlan, TextSpec


def _text_block(txt: TextSpec) -> str:
    style = (
        f"position:absolute; left:{txt.x}px; top:{txt.y}px; "
        f"width:{txt.width or 'auto'}{'px' if txt.width else ''}; "
        f"height:{txt.height or 'auto'}{'px' if txt.height else ''}; "
        f"font-size:{txt.font_size}px; color:{escape(txt.color, quote=True)}; "
        f"text-align:{txt.align}; "
        "font-family:'Segoe UI',Arial,'Microsoft YaHei',sans-serif; "
        "white-space:pre-wrap; word-wrap:break-word;"
    )
    return (
        f'<div class="text-block" id="{escape(txt.id, quote=True)}" '
        f'style="{style}">{escape(txt.text)}</div>'
    )


class HTMLRenderer(Renderer):
    """Compiles a long-text CanvasPlan to HTML/CSS and (optionally) PNG."""

    backend = CanvasBackend.html

    def compile_source(self, plan: CanvasPlan) -> str:
        """Compile ``plan`` to an HTML document. Pure; no browser, no IO."""
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
    try:
        from genclaw.renderers.playwright_render import render_html_to_png
    except Exception:
        return False
    try:
        render_html_to_png(html, png_path, width=width, height=height)
    except Exception:
        return False
    return True

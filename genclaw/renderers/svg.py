"""SVG renderer (plan task 6).

Compiles a ``structured`` :class:`~genclaw.schemas.CanvasPlan` into SVG source.
SVG is the backend for object count / layout / spatial relations / local edits
(GenEval++ / ImgEdit families). Source compilation is pure and browser-free;
PNG rasterization is delegated to the Playwright helper and only attempted when
a browser is available, so this module imports without Playwright.

Supported shapes: circle, rectangle, ellipse, polygon (explicit ``points``).
Elements render in layer order, then object order, so later layers paint on top
(matching ``CanvasPlan.ordered_layers``).
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from genclaw.renderers.base import RenderedCanvas, Renderer
from genclaw.schemas import CanvasBackend, CanvasPlan, ObjectSpec, TextSpec


def _attr(value: object) -> str:
    """Escape a value for use inside a double-quoted XML attribute."""
    return escape(str(value), {'"': "&quot;"})


def _circle(obj: ObjectSpec) -> str:
    # radius from attributes, else half of width.
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
    # Accept [[x,y],...] or [x,y,x,y,...].
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


_SHAPES = {
    "circle": _circle,
    "rectangle": _rectangle,
    "rect": _rectangle,
    "ellipse": _ellipse,
    "polygon": _polygon,
}


def _text(txt: TextSpec) -> str:
    anchor = {"left": "start", "center": "middle", "right": "end"}[txt.align]
    # y is treated as the text baseline offset by font size for a top-anchored box.
    y = txt.y + txt.font_size
    return (
        f'<text x="{txt.x}" y="{y}" font-size="{txt.font_size}" '
        f'fill="{_attr(txt.color)}" text-anchor="{anchor}">'
        f"{escape(txt.text)}</text>"
    )


class SVGRenderer(Renderer):
    """Compiles a CanvasPlan to SVG and (optionally) rasterizes to PNG."""

    backend = CanvasBackend.svg

    def compile_source(self, plan: CanvasPlan) -> str:
        """Compile ``plan`` to SVG source. Pure; no browser, no IO."""
        w, h = plan.size.width, plan.size.height
        layer_order = {layer.id: layer.order for layer in plan.layers}
        # Stable order: by layer order, then original object order.
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
    """Rasterize SVG to PNG via Playwright if available; else skip.

    Returns True if a PNG was written. Import is lazy so the module loads
    without a browser (phase-1 strategy).
    """
    try:
        from genclaw.renderers.playwright_render import render_html_to_png
    except Exception:
        return False
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

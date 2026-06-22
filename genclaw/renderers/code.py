"""Free-form code renderer: code-as-brush (ADR 0005).

This is the heart of GenClaw's paper mechanism: the LLM writes the canvas
*source code* directly (``source="code"`` with ``code_source``/``code_lang``),
instead of filling fields that a template compiles. The renderer takes that
code, (lightly) validates it, and rasterizes it -- the code IS the brush.

Supported langs:
- ``svg``  -- pure markup; static allow-list validation (``svg_validate``).
- ``html`` -- full HTML/CSS (may contain JS); rendered via Playwright.
- ``three`` / ``javascript`` -- a Three.js (or other JS) scene; the LLM writes a
  complete HTML document (loading three from a CDN) and we wait for WebGL frames
  before screenshotting.

SECURITY DEBT (ADR 0005, deliberately deferred): HTML/Three.js execute arbitrary
model-authored JavaScript in headless Chromium with **NO sandbox** (no network
isolation, no CSP, no resource caps beyond Playwright's timeout). This is
acceptable ONLY because this is a LOCAL, single-machine reproduction whose input
comes from a trusted LLM provider. Do NOT expose this to untrusted input or
deploy publicly before the execution-sandbox ADR is implemented. SVG remains
statically validated; HTML/JS are run essentially as-is.
"""

from __future__ import annotations

from pathlib import Path

from genclaw.renderers.base import RenderedCanvas, Renderer
from genclaw.renderers.svg_validate import validate_svg
from genclaw.schemas import CanvasBackend, CanvasPlan, CanvasSource

# Langs that execute JS in the browser. Rendered with NO sandbox (see module
# docstring). Three.js scenes additionally need a few animation frames before
# the WebGL canvas has painted.
_HTML_LANGS = {"html"}
_JS_SCENE_LANGS = {"three", "javascript"}


class CodeRenderError(ValueError):
    """Raised when a code-source plan cannot be rendered."""


class CodeRenderer(Renderer):
    """Renders a ``source="code"`` plan by validating and rasterizing its code."""

    backend = CanvasBackend.svg  # nominal; actual backend resolved per plan

    def _resolve_lang(self, plan: CanvasPlan) -> str:
        """Determine the effective code language (explicit, else inferred)."""
        lang = (plan.code_lang or "").lower()
        if lang:
            return lang
        src = (plan.code_source or "").lower()
        if "<svg" in src:
            return "svg"
        # A full HTML doc that pulls in three.js is a three scene; else plain html.
        if "three" in src and ("<html" in src or "<script" in src):
            return "three"
        if "<html" in src or "<!doctype html" in src:
            return "html"
        return "svg"

    def compile_source(self, plan: CanvasPlan) -> str:
        """Return the code source to render. Pure; no IO, no execution.

        SVG is statically validated; HTML/Three.js are returned as-is (executed
        without a sandbox at render time -- see module docstring / ADR 0005).
        """
        if plan.source is not CanvasSource.code or not plan.code_source:
            raise CodeRenderError(
                "CodeRenderer requires source='code' with non-empty code_source"
            )
        lang = self._resolve_lang(plan)
        if lang == "svg":
            return validate_svg(plan.code_source)
        if lang in _HTML_LANGS or lang in _JS_SCENE_LANGS:
            return plan.code_source  # executed as-is; NO sandbox (ADR 0005)
        raise CodeRenderError(
            f"unsupported code_lang {lang!r}; expected 'svg', 'html', 'three', "
            "or 'javascript'"
        )

    def _ext_and_backend(self, lang: str) -> tuple[str, CanvasBackend]:
        if lang == "svg":
            return "svg", CanvasBackend.svg
        if lang in _HTML_LANGS:
            return "html", CanvasBackend.html
        return "html", CanvasBackend.three  # three/javascript host page

    def render(self, plan: CanvasPlan, output_dir: Path) -> RenderedCanvas:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        source = self.compile_source(plan)  # validates SVG; raises on bad input
        lang = self._resolve_lang(plan)
        ext, backend = self._ext_and_backend(lang)

        source_path = output_dir / f"canvas.{ext}"
        source_path.write_text(source, encoding="utf-8")

        png_path = output_dir / "sketch.png"
        rasterized = _try_rasterize(
            source, lang, png_path, plan.size.width, plan.size.height
        )

        return RenderedCanvas(
            backend=backend,
            source_path=source_path,
            png_path=png_path if rasterized else None,
            width=plan.size.width,
            height=plan.size.height,
        )


def _try_rasterize(
    source: str, lang: str, png_path: Path, width: int, height: int
) -> bool:
    """Rasterize the code to PNG via Playwright if available; else skip.

    SVG is wrapped in a minimal HTML host. HTML is rendered as-is. Three.js/JS
    scenes are rendered as-is but with a frame wait so WebGL has painted.
    """
    try:
        from genclaw.renderers.playwright_render import render_html_to_png
    except Exception:
        return False

    if lang == "svg":
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>*{margin:0;padding:0}</style></head>"
            f"<body>{source}</body></html>"
        )
        wait_frames = 0
    else:
        html = source  # full HTML/Three.js document authored by the LLM
        wait_frames = 5 if lang in _JS_SCENE_LANGS else 0

    try:
        render_html_to_png(
            html, png_path, width=width, height=height, wait_for_frames=wait_frames
        )
    except Exception:
        return False
    return True

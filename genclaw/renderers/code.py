"""自由形式代码 renderer:code-as-brush(ADR 0005)。

这是 GenClaw 论文机制的核心:LLM 直接写画布*源码*(``source="code"``
配 ``code_source`` / ``code_lang``),而不是填字段让模板去编译。renderer
拿到这段代码,做(轻量)校验,然后光栅化——代码本身就是"画笔"。

支持的语言:
- ``svg`` —— 纯标记语言;走静态白名单校验(``svg_validate``)。
- ``html`` —— 完整 HTML / CSS(可以含 JS);用 Playwright 渲染。
- ``three`` / ``javascript`` —— Three.js(或别的 JS)场景;LLM 写一
  整份 HTML 文档(从 CDN 拉 three),我们等 WebGL 画几帧再截屏。

安全债(ADR 0005,故意延后):HTML / Three.js 会在头部 Chromium 里执行
**任意**模型写的 JS,**没有沙箱**(无网络隔离、无 CSP、没有除
Playwright timeout 之外的资源限制)。这只在"本地、单机的复现项目,
输入来自可信 LLM provider"的前提下能接受。在执行沙箱 ADR 落地
之前,*不要*把它暴露给不可信输入或对外部署。SVG 保持静态校验;
HTML / JS 基本按原样执行。
"""

from __future__ import annotations

from pathlib import Path

from genclaw.renderers.base import RenderedCanvas, Renderer
from genclaw.renderers.svg_validate import validate_svg
from genclaw.schemas import CanvasBackend, CanvasPlan, CanvasSource

# 会在浏览器里跑 JS 的语言。无沙箱渲染(见模块 docstring)。
# Three.js 场景另外需要等几帧,WebGL canvas 才真正画完。
_HTML_LANGS = {"html"}
_JS_SCENE_LANGS = {"three", "javascript"}


class CodeRenderError(ValueError):
    """code-source plan 渲染失败时抛出。"""


class CodeRenderer(Renderer):
    """对 ``source="code"`` plan 做校验 + 光栅化。"""

    backend = CanvasBackend.svg  # 名义上的;实际 backend 由 plan 决定

    def _resolve_lang(self, plan: CanvasPlan) -> str:
        """决定 plan 实际用的代码语言(显式指定,否则启发式推断)。"""
        lang = (plan.code_lang or "").lower()
        if lang:
            return lang
        src = (plan.code_source or "").lower()
        if "<svg" in src:
            return "svg"
        # 包含 three.js 的完整 HTML 文档 = three 场景;否则就是普通 html。
        if "three" in src and ("<html" in src or "<script" in src):
            return "three"
        if "<html" in src or "<!doctype html" in src:
            return "html"
        return "svg"

    def compile_source(self, plan: CanvasPlan) -> str:
        """返回要渲染的源码。纯函数:无 IO、无执行。

        SVG 做静态校验;HTML / Three.js 原样返回(渲染时无沙箱执行,
        见模块 docstring / ADR 0005)。
        """
        if plan.source is not CanvasSource.code or not plan.code_source:
            raise CodeRenderError(
                "CodeRenderer requires source='code' and non-empty code_source"
            )
        lang = self._resolve_lang(plan)
        if lang == "svg":
            return validate_svg(plan.code_source)
        if lang in _HTML_LANGS or lang in _JS_SCENE_LANGS:
            return plan.code_source  # 原样执行;无沙箱(ADR 0005)
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
    """Playwright 可用就光栅化成 PNG,否则跳过。

    SVG 包一层最小 HTML 宿主;HTML 原样渲染;Three.js / JS 场景也原样
    渲染,但会等几帧,让 WebGL 真正画完。
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
        html = source  # LLM 写的完整 HTML / Three.js 文档
        wait_frames = 5 if lang in _JS_SCENE_LANGS else 0

    try:
        render_html_to_png(
            html, png_path, width=width, height=height, wait_for_frames=wait_frames
        )
    except Exception:
        return False
    return True

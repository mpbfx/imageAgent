"""Tests for free-form SVG validation + CodeRenderer (code-as-brush, ADR 0005)."""

import pytest

from genclaw.renderers.code import CodeRenderer, CodeRenderError
from genclaw.renderers.svg_validate import SVGValidationError, validate_svg
from genclaw.schemas import (
    CanvasBackend,
    CanvasPlan,
    CanvasSize,
    CanvasSource,
    TaskType,
)

_GOOD_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
    '<circle cx="50" cy="50" r="40" fill="#d62828"/>'
    '<text x="10" y="90">hi</text></svg>'
)


# --- validator ----------------------------------------------------------------


def test_valid_svg_passes():
    assert validate_svg(_GOOD_SVG) == _GOOD_SVG


def test_empty_rejected():
    with pytest.raises(SVGValidationError, match="empty"):
        validate_svg("   ")


def test_non_svg_rejected():
    with pytest.raises(SVGValidationError, match="root element"):
        validate_svg("<html><body>nope</body></html>")


def test_script_rejected():
    with pytest.raises(SVGValidationError, match="forbidden"):
        validate_svg('<svg><script>alert(1)</script></svg>')


def test_event_handler_rejected():
    with pytest.raises(SVGValidationError, match="forbidden"):
        validate_svg('<svg><rect onload="x()" /></svg>')


def test_foreignobject_rejected():
    with pytest.raises(SVGValidationError, match="forbidden"):
        validate_svg('<svg><foreignObject><body/></foreignObject></svg>')


def test_external_href_rejected():
    # <use> with an external href exercises the external-reference check
    # (not the <image> forbidden-pattern path).
    with pytest.raises(SVGValidationError, match="external reference"):
        validate_svg('<svg xmlns="http://www.w3.org/2000/svg">'
                     '<use href="http://evil.com/x.svg#a"/></svg>')


def test_external_image_tag_rejected():
    # <image with a network ref is caught by the forbidden-pattern first.
    with pytest.raises(SVGValidationError):
        validate_svg('<svg><image href="https://x/y.png" width="10" height="10"/></svg>')


def test_in_document_ref_allowed():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg"><defs>'
           '<linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient>'
           '</defs><rect fill="url(#g)" width="10" height="10"/></svg>')
    assert validate_svg(svg) == svg


def test_disallowed_tag_rejected():
    with pytest.raises(SVGValidationError, match="disallowed tag"):
        validate_svg('<svg><blink>x</blink></svg>')


def test_entity_doctype_rejected():
    with pytest.raises(SVGValidationError, match="forbidden"):
        validate_svg('<!DOCTYPE svg [<!ENTITY x "y">]><svg/>')


# --- CodeRenderer -------------------------------------------------------------


def _code_plan(code=_GOOD_SVG, lang="svg"):
    return CanvasPlan(
        request_id="c1",
        prompt="a red circle",
        task_type=TaskType.composition,
        backend=CanvasBackend.svg,
        source=CanvasSource.code,
        code_source=code,
        code_lang=lang,
        size=CanvasSize(width=100, height=100),
    )


def test_code_renderer_compiles_validated_svg():
    out = CodeRenderer().compile_source(_code_plan())
    assert "<circle" in out


def test_code_renderer_rejects_structured_plan():
    plan = CanvasPlan(
        request_id="s1", prompt="p", task_type=TaskType.composition,
        backend=CanvasBackend.svg, size=CanvasSize(width=10, height=10),
    )
    with pytest.raises(CodeRenderError, match="requires source='code'"):
        CodeRenderer().compile_source(plan)


def test_code_renderer_rejects_unsupported_lang():
    with pytest.raises(CodeRenderError, match="unsupported code_lang"):
        CodeRenderer().compile_source(_code_plan(code="print('x')", lang="python"))


def test_code_renderer_accepts_html():
    html = "<!doctype html><html><body><h1>Hello</h1></body></html>"
    plan = _code_plan(code=html, lang="html")
    out = CodeRenderer().compile_source(plan)
    assert "<h1>Hello</h1>" in out


def test_code_renderer_accepts_three():
    doc = ('<!doctype html><html><body><canvas></canvas>'
           '<script type="module">import * as THREE from "https://unpkg.com/three";'
           'window.__gcRendered = true;</script></body></html>')
    plan = _code_plan(code=doc, lang="three")
    out = CodeRenderer().compile_source(plan)
    assert "THREE" in out


def test_html_render_writes_html_source(tmp_path):
    html = "<!doctype html><html><body><h1>Hi</h1></body></html>"
    result = CodeRenderer().render(_code_plan(code=html, lang="html"), tmp_path)
    assert result.backend is CanvasBackend.html
    assert result.source_path.name == "canvas.html"
    assert "<h1>Hi</h1>" in result.source_path.read_text(encoding="utf-8")


def test_three_render_reports_three_backend(tmp_path):
    doc = ('<!doctype html><html><body><canvas></canvas>'
           '<script type="module">import * as THREE from "https://unpkg.com/three";'
           'window.__gcRendered = true;</script></body></html>')
    result = CodeRenderer().render(_code_plan(code=doc, lang="three"), tmp_path)
    assert result.backend is CanvasBackend.three
    assert result.source_path.name == "canvas.html"


def test_code_renderer_propagates_validation_error():
    with pytest.raises(SVGValidationError):
        CodeRenderer().compile_source(_code_plan(code="<svg><script>x</script></svg>"))


def test_code_renderer_writes_source(tmp_path):
    result = CodeRenderer().render(_code_plan(), tmp_path)
    assert result.backend is CanvasBackend.svg
    assert result.source_path.exists()
    assert "<circle" in result.source_path.read_text(encoding="utf-8")


def test_lang_inferred_when_none():
    # code_lang omitted (None) but content is SVG -> still compiles.
    out = CodeRenderer().compile_source(_code_plan(lang=None))
    assert "<circle" in out


@pytest.mark.render
def test_code_renderer_png_nonempty(tmp_path):
    result = CodeRenderer().render(_code_plan(), tmp_path)
    assert result.png_path is not None
    assert result.png_path.stat().st_size > 0


@pytest.mark.render
def test_html_code_png_nonempty(tmp_path):
    html = ("<!doctype html><html><body style='background:#fff'>"
            "<h1 style='color:#1d3557'>Hello GenClaw</h1></body></html>")
    result = CodeRenderer().render(_code_plan(code=html, lang="html"), tmp_path)
    assert result.png_path is not None
    assert result.png_path.stat().st_size > 0


@pytest.mark.render
def test_three_code_png_nonempty(tmp_path):
    # A minimal Three.js scene authored as free-form code; must paint a frame.
    doc = """<!doctype html><html><head><meta charset="utf-8"><style>*{margin:0}</style></head>
<body><canvas id="c" width="200" height="200"></canvas>
<script type="module">
import * as THREE from "https://unpkg.com/three@0.160.0/build/three.module.js";
const canvas=document.getElementById("c");
const r=new THREE.WebGLRenderer({canvas,preserveDrawingBuffer:true});
r.setSize(200,200,false);
const s=new THREE.Scene(); s.background=new THREE.Color("#202030");
const cam=new THREE.PerspectiveCamera(50,1,0.1,100); cam.position.z=3;
s.add(new THREE.Mesh(new THREE.BoxGeometry(1,1,1),new THREE.MeshBasicMaterial({color:"#e63946"})));
let n=0;(function loop(){r.render(s,cam);if(++n>=3)window.__gcRendered=true;requestAnimationFrame(loop);})();
</script></body></html>"""
    plan = _code_plan(code=doc, lang="three")
    plan.size.width = 200
    plan.size.height = 200
    result = CodeRenderer().render(plan, tmp_path)
    assert result.png_path is not None
    assert result.png_path.stat().st_size > 0

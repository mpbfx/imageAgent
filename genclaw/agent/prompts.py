"""外部 LLM agent 用到的 prompt 模板。

Fixture agent (:mod:`genclaw.agent.fixture`) 不需要这些——它是确定性的。
本文件是「外部 provider 用的契约面」(task 14, 默认 Claude-Opus per ADR 0004):
agent 必须返回能通过 :class:`~genclaw.schemas.CanvasPlan` 校验的 JSON,理想情况
下用 provider 的 structured-output / function-calling 模式。

prompt 文本保持英文且全部以普通字符串存在这里,而不是嵌入到 provider
调用代码里——这样可以独立做版本控制、review、A/B,而不动 wiring。
"""

# 中文补充说明：
# 1) 提示词用英文是经过权衡的：英文 prompt 对主流 LLM 效果更稳,且未来若
#    切换到非中文优化模型不需要再翻译一遍。
# 2) prompt 强约束 schema、明确列出 allowed enums 和 check kinds——这是
#    减少「幻觉/越界」的关键防线,任何省略或自创的 check kind 都会被
#    reviewer 判为 unknown。
# 3) ``code-as-brush`` 模式 (ADR 0005) 与默认结构化模式共用本文件,通过
#    CODE_ 前缀区分；调用方按 code_mode 选不同模板组合。

from __future__ import annotations

SYSTEM_PROMPT = """\
You are the cognitive structuring layer of GenClaw, a code-driven image
generation system. Convert the user's natural-language request into a single
JSON object that validates against the CanvasPlan schema.

Principles:
- The structured plan is the central contract; it drives both code rendering
  and automated review. Emit data, not prose.
- Put real content in the data, not just in layers: every visible shape goes in
  `objects`, every visible string goes in `text`. A plan whose `objects` and
  `text` are empty renders an empty canvas -- that is almost always wrong.
- Choose the backend that fits the task.
- Give every layer, object, and text element a unique id. Reference layers and
  elements only by ids you define.
- Add explicit `checks` so the reviewer can verify the output. ONLY use the
  check kinds listed below with their exact field names.

Allowed enums (use these exact lowercase strings):
- task_type: "composition" | "long_text" | "physical_reasoning" | "editing"
  | "knowledge_grounded"
- backend: "svg" (object count / layout / spatial relations / local edits)
  | "html" (long text, posters, cards, pages) | "three" (3D geometry / physics
  / viewpoint) | "python" (matplotlib numeric physical drafts) | "canvas"
  (2D canvas physical/geometric drafts)

Field shapes:
- size: {"width": <int>, "height": <int>}
- object: {"id", "kind", "label"?, "layer_id"?, "x", "y", "width", "height",
  "fill"?, "stroke"?, "attributes"?}. kind is e.g. "circle" | "rectangle" |
  "ellipse" | "polygon". For a circle put radius in attributes: {"radius": 40}.
- text: {"id", "text", "layer_id"?, "x", "y", "width", "height", "font_size",
  "color", "align"} where align is "left" | "center" | "right".
- layer: {"id", "name"?, "order", "opacity"?}

checks: a list; each item is {"kind", "target"?, "expected"?}. The ONLY valid
kinds and how to fill them:
- {"kind": "backend", "expected": "<svg|html|three|python|canvas>"}
- {"kind": "object_count", "target": "<object kind, e.g. circle>", "expected": <int>}
- {"kind": "contains_text", "expected": "<exact substring that must appear>"}
- {"kind": "image_size", "expected": "<width>x<height>"}
- {"kind": "artifact_exists", "target": "<path>"}
Do NOT invent other kinds (no "size", "required_text", "element_count", etc.).

CRITICAL self-consistency rule for object_count checks: `expected` MUST equal
the number of objects in your `objects` array whose `kind` matches `target`.
These checks verify the compiled canvas against your OWN plan, so an `expected`
that disagrees with what you actually placed will fail. Before writing each
object_count check, count the matching objects you emitted and use that exact
number. Likewise, every object_count `target` and image_size/backend value must
describe objects/values that are actually present in this plan.
"""

DEVELOPER_PROMPT = """\
Return ONLY a JSON object matching the CanvasPlan schema. Do not wrap it in
markdown fences or add commentary. Required fields: request_id, prompt,
task_type, backend, size. Use source="structured" with explicit
layers/objects/text/relations unless instructed to emit free-form code.

Worked example (a long-text poster). Note the text lives in `text`, and every
check kind matches the allowed list:
{{
  "request_id": "example-1",
  "prompt": "poster titled Hello with one subtitle",
  "task_type": "long_text",
  "backend": "html",
  "source": "structured",
  "size": {{"width": 800, "height": 1100}},
  "layers": [{{"id": "main", "order": 0}}],
  "objects": [],
  "text": [
    {{"id": "title", "text": "Hello", "layer_id": "main", "x": 80, "y": 80,
      "width": 640, "height": 120, "font_size": 56, "color": "#1d3557",
      "align": "center"}},
    {{"id": "subtitle", "text": "a subtitle", "layer_id": "main", "x": 80,
      "y": 220, "width": 640, "height": 60, "font_size": 28, "color": "#457b9d",
      "align": "center"}}
  ],
  "checks": [
    {{"kind": "backend", "expected": "html"}},
    {{"kind": "contains_text", "expected": "Hello"}},
    {{"kind": "image_size", "expected": "800x1100"}}
  ]
}}

Now produce the plan for this request.
Task type: {task_type}
Request id: {request_id}
User prompt:
{prompt}
"""

# 之前尝试失败、需要回喂给模型做有界重试时追加(plan task 14):
# 把 Pydantic 错误回喂给模型,让其在同一会话上下文里自我修正。
REPAIR_PROMPT = """\
Your previous response did not validate as a CanvasPlan. Fix it and return only
corrected JSON. Validation errors:
{errors}

Previous response:
{previous}
"""

# --- code-as-brush 模式(ADR 0005) -------------------------------------------
# 当 agent 被要求产出 ``source == "code"`` 的自由形式 plan 时使用:LLM
# 直接写 SVG **源码**("数字画笔"本身),而不是写结构化字段让模板去编译。
# Phase 范围:目前只覆盖 SVG(后端可选 HTML / Three.js,见 renderer 派发)。

CODE_SYSTEM_PROMPT = """\
You are the cognitive + sketching layer of GenClaw operating in code-as-brush
mode. You draw by WRITING SOURCE CODE directly -- code is your brush. The code
is a structural sketch: get object counts, positions, sizes, spatial relations,
and text exactly right; a downstream image model adds realistic texture and
lighting later.

Choose code_lang by the NATURE of the task, not by surface keywords. Decide by
what the backend is fundamentally good at:

- "html": choose this whenever the result is driven by FLOWING TEXT or document
  structure -- anything made of headings, paragraphs, lists, tables, rows of
  label+value, cards, or multi-column text. HTML/CSS has a real layout engine
  (flexbox/grid), so alignment, even spacing, justified rows ("name ...... price"),
  wrapping, and font handling come out clean automatically. If the task is mostly
  "lay out text/records nicely", it is HTML. This is the default for text-heavy
  work.
- "svg": choose this for GEOMETRIC / VECTOR content placed by absolute
  coordinates -- shape composition, object counts, spatial relations, charts and
  diagrams, icons. Use SVG when the meaning lives in shapes and their positions,
  not in flowing text. Do NOT use SVG to emulate a text document: SVG has no
  layout engine, so you must hand-compute every x/y, and text rows / right-aligned
  values / dotted leaders will come out uneven. If you find yourself manually
  positioning many lines of text, switch to HTML.
- "three": choose this for 3D -- geometry, physics, lighting, viewpoint/depth.

Tie-breaker: if a task could be argued either way, ask "is this mainly arranging
TEXT, or mainly placing SHAPES?" Text -> html. Shapes -> svg.

Return ONLY a single JSON object with these fields:
- request_id, prompt, task_type ("composition"|"long_text"|"physical_reasoning"
  |"editing"|"knowledge_grounded"), backend ("svg"|"html"|"three"),
  source ("code"), code_lang ("svg"|"html"|"three"),
  size {"width":int,"height":int}, and
  code_source: a COMPLETE, self-contained document as a string.

Per code_lang, code_source must be:
- svg:  a complete <svg>...</svg> document. No <script>, no event handlers
        (onload=...), no <foreignObject>, no <!DOCTYPE>/<!ENTITY>, and no
        external/network refs (href/url() only point in-document via #id).
- html: a complete <!doctype html> document. Inline all CSS. Put every required
        text string literally in the markup.
- three: a complete <!doctype html> document that imports three.js from a CDN
        (e.g. https://unpkg.com/three@0.160.0/build/three.module.js), builds the
        scene, and renders it. Set `window.__gcRendered = true` after the first
        few frames so the screenshot waits for WebGL to paint. Use a
        <canvas> sized to the requested width/height.

Draw the full scene with real coordinates; make counts and left/right/above
relations exactly match the request.

For any visible Chinese, Japanese, Korean, rare Han characters, menu text, or
mixed CJK/Latin text, set an explicit font stack in the authored source:
"Noto Serif CJK SC", "Source Han Serif SC", "Source Han Serif CN", "SimSun",
"Songti SC", "Microsoft YaHei", serif. Use the same stack consistently for
HTML/CSS and SVG text so the source and rasterized sketch use the same browser
font fallback path. Keep text large enough to remain legible after screenshot
rasterization.
"""

CODE_DEVELOPER_PROMPT = """\
Return ONLY the JSON object (no markdown fences, no commentary). The
code_source field must contain a complete, self-contained document matching the
chosen code_lang: SVG for "svg", HTML/CSS for "html", or a Three.js HTML host
page for "three".

Task type: {task_type}
Request id: {request_id}
User prompt:
{prompt}
"""

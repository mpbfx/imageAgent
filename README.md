# GenClaw Reproduction

[中文](README.zh-CN.md)

Independent reproduction of **GenClaw: Code-Driven Agentic Image Generation** (`arXiv:2605.30248`).

GenClaw turns an image request into a structured plan, renders a code-based sketch, then asks an image model to fill in appearance. The point is to make hard constraints such as count, position, text, charts, and occlusion explicit in code instead of hoping a text-to-image prompt preserves them.

> This is an independent implementation from the paper description. It does not run official GenClaw code and does not claim to reproduce the paper's numeric results exactly.

Last reviewed: 2026-07-02

## Quick Start

Use fixture mode first. It needs no API keys and exercises the local pipeline: planning, rendering, mock generation, artifacts, and traces.

```bash
pip install -e ".[dev]"
python -m playwright install chromium

genclaw run --prompt "three red circles on the left" --mode fixture --enable-review
genclaw run --prompt "poster for GenClaw with title Code as Brush" --mode fixture
genclaw run --prompt "mirror reflection of a small ball" --mode fixture

genclaw bench --suite mini
pytest -q
```

Each run writes a directory under `outputs/runs/` with:

```text
request.json
plan.json
canvas.svg | canvas.html | canvas.py
sketch.png
final.png
review.json     # when review is enabled
trace.jsonl
```

## What This Implements

The project follows the paper's three-layer shape:

```text
conceptualize -> search -> render -> generate -> review -> route_after_review
                  |                                      |
                  |                                      v
                  +------------------------------ revise -> render
```

| Layer | What happens here | Current implementation |
| --- | --- | --- |
| Think | Prompt becomes a schema-valid `CanvasPlan`; optional knowledge refs and reasoning slots attach to it. | Fixture agent and external LLM agent. Search node is wired; Tavily needs credentials. |
| Sketch | The plan becomes executable canvas code, then a PNG sketch. | SVG, HTML/CSS, Three.js, Python/matplotlib, and Canvas renderers. |
| Color + Review | The sketch is passed to a generator; structural and visual checks produce a review result. | Mock generator in fixture mode; external generator and VLM reviewer adapters exist. |

The central contract is `CanvasPlan`, not a long natural-language prompt. Code is used as the "brush" for layout and structure; image models are used mainly for texture, light, style, and realism.

## Usage

### Fixture Mode

Fixture mode is deterministic and suitable for local smoke tests, CI-style checks, and debugging artifact flow. It does not produce photorealistic images.

```bash
genclaw run --prompt "three red circles on the left" --mode fixture
genclaw render --plan path/to/plan.json
genclaw review --run-dir path/to/run
genclaw bench --suite mini
```

By default, `genclaw run` skips review. Add `--enable-review` when you want the review step in the run:

```bash
genclaw run --prompt "three red circles on the left" --mode fixture --enable-review
```

### External Models

Copy `.env.example` to `.env` and fill in the provider credentials. The CLI loads `.env` automatically.

```bash
pip install -e ".[providers]"
```

```bash
# .env
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...

# Optional proxy or gateway URLs.
ANTHROPIC_BASE_URL=https://...
GOOGLE_BASE_URL=https://...

# Optional model overrides.
GENCLAW_AGENT_MODEL=...
GENCLAW_REVIEWER_MODEL=...
GENCLAW_GENERATOR_MODEL=...

# Optional knowledge grounding.
TAVILY_API_KEY=...
```

Run modes:

| Mode | Use when | Notes |
| --- | --- | --- |
| `fixture` | You want a no-credential local run. | Deterministic agent and mock generator. |
| `external` | You want the default real-model path. | Uses code-as-brush by default. |
| `external-code` | You want to be explicit about code-as-brush. | LLM writes SVG/HTML/Three.js canvas source. |
| `external-template` | You want a safer structured baseline. | Uses validated fields and templates; avoids model-written canvas code. |
| `external-tele` | You want the TeleImage SSH generator path. | Keeps code-as-brush agent/reviewer/search behavior but uses the TeleImage generator. |

Example:

```bash
genclaw run --prompt "a sales bar chart with exact labels" --mode external
genclaw run --prompt "a sales bar chart with exact labels" --mode external-template
```

The image generation step needs an image-to-image capable model when you want it to respect the sketch. A pure text-to-image model cannot see the rendered canvas and should only be treated as a baseline.

## Current Status

| Area | Status | Notes |
| --- | --- | --- |
| `CanvasPlan` schema | Done | Covers structured and code canvas sources. |
| Artifact-first run output | Done | Request, plan, canvas source, images, review, and trace are preserved. |
| LangGraph orchestration | Done | Main graph and conditional review route are implemented. |
| Renderers | Done | SVG, HTML, Three.js, Python, and Canvas. |
| Fixture pipeline | Done | Main no-credential development path. |
| External LLM/provider adapters | Done | Claude/Gemini-style stack with configurable base URLs. |
| Code-as-brush | Done for SVG/HTML/Three.js | Useful but carries sandbox risk for HTML/Three.js. |
| Search grounding | Partial | Node and Tavily adapter exist; real multi-round search still needs validation. |
| Revision loop | Partial | Routing exists; useful feedback-driven regeneration is still limited. |
| Layered editing | Not done | SAM3 + mask/inpainting path is still the largest paper-mechanism gap. |
| Official benchmarks | Not done | Mini benchmark is local smoke coverage, not GenEval++/LongText/ImgEdit/Mind-Bench. |

The project is most useful for hard-constraint image tasks: exact counts, spatial relationships, long or unusual text, charts, diagrams, and controlled layouts. For ordinary photorealistic scenes, frontier text-to-image models are often already strong enough, so this pipeline's advantage is smaller.

## Safety Notes

`external`, `external-code`, and `external-tele` can render model-written code.

SVG is checked with a static allowlist. HTML and Three.js are rendered in headless Chromium and can execute JavaScript without a complete sandbox: no strong network isolation, CSP boundary, or resource limits are guaranteed yet.

Use these modes only for local, trusted inputs. For a safer baseline, use `external-template`. Do not expose code-as-brush rendering to untrusted users or a public service before the execution sandbox work lands.

## Project Layout

```text
genclaw/
  agent/          prompt-to-plan providers
  benchmarks/     mini benchmark fixtures and runner
  generators/     mock, external, and TeleImage generators
  graph/          LangGraph nodes, state, and routes
  renderers/      SVG, HTML, Three.js, Python, Canvas rendering
  review/         rule and VLM review

docs/
  specs/          reproduction scope and paper-mechanism coverage
  plans/          implementation plans
  adr/            architecture decisions
```

Important docs:

- `docs/reproduction-roadmap.md` - one-page implementation status
- `docs/TODO.md` - prioritized next work
- `docs/specs/2026-06-18-genclaw-reproduction-spec.md` - scope and coverage notes
- `docs/adr/` - architecture decisions
- `SEARCH_INTEGRATION.md` - search provider notes

## Development Notes

If PyPI or Playwright downloads fail because of local network restrictions, use a mirror:

```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn

PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright \
  python -m playwright install chromium
```

Recommended checks before changing behavior:

```bash
pytest -q
genclaw bench --suite mini
```

Known high-value next steps:

- Generate object-count review checks from actual code/plan structure instead of trusting the LLM's self-reported count.
- Add execution sandboxing for HTML/Three.js code-as-brush.
- Implement layered editing with segmentation, masks, inpainting, and non-edited-region metrics.
- Validate real Tavily-backed search and official benchmark adapters.

## License

Apache-2.0.

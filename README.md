# imageAgent — GenClaw reproduction

An independent, from-scratch reproduction of **GenClaw: Code-Driven Agentic Image
Generation** (arXiv `2605.30248`). The agent generates images the way a human
artist works — **first conceptualize, then sketch in code, then color** — instead
of firing a single prompt at a black-box text-to-image model.

> ⚠️ **Independent reproduction.** Built from the paper as a spec. The official
> code/demo was unreleased at the time of writing; this project does not run the
> authors' code and does not claim to reproduce their exact numbers.

---

## Why code-as-brush?

Natural language is ambiguous about **counts, coordinates, text, and occlusion**
("three red circles on the left", "A behind B"). Code is not:
`<circle cx="100" cy="50" r="40"/>` is exact. GenClaw lets the LLM **write the
canvas source code** (SVG / HTML / Three.js) to lock the structure, then hands
that sketch to an image model purely as a **colorist** for texture and lighting.

Result: counts, layout, and text come out right (the code guarantees them) while
the image model supplies realism. This is decisively better than pure
text-to-image on **counting, spatial relations, data charts, and rare glyphs** —
and roughly even on ordinary scenes, where frontier image models already cope.

## Architecture — three layers (LangGraph)

```
conceptualize → search → render → generate → review → route_after_review
   (Think)      (facts)  (Sketch) (Color)   (verify)   └─(fail & under budget)→ revise → render
```

1. **Think** — prompt → schema-validated `CanvasPlan` (Pydantic). Intent
   understanding + optional **search** (knowledge grounding) + **reasoning**
   slots. The plan, not free-text, is the central contract.
2. **Sketch** — compile/emit executable canvas code and rasterize to a PNG:
   - **SVG** — composition, counts, spatial relations, diagrams
   - **HTML/CSS** — long text, posters, cards (real layout engine)
   - **Three.js** — 3D geometry / physics / viewpoint (headless WebGL)
   - **Python (matplotlib) / Canvas** — numeric physical drafts
3. **Color + Review** — feed the sketch as a **visual condition** to an image
   model (image-to-image), then review (deterministic rules + optional VLM) and
   iterate up to a budget.

Two ways the canvas is produced:
- **structured** (templates fill validated fields) — the deterministic scaffold.
- **code** (the LLM writes the source directly) — **code-as-brush**, the paper's
  core mechanism. Enable with `--mode external-code`.

## Install

Requires Python 3.10+.

```bash
pip install -e ".[dev]"
python -m playwright install chromium     # for SVG/HTML/Three.js → PNG
```

If PyPI is unreachable (TLS resets on `pypi.org`), use a mirror:

```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn
# Playwright browser binary via mirror:
PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright \
  python -m playwright install chromium
```

## Quickstart — fixture mode (no credentials)

Deterministic agent + mock generator. Exercises the whole pipeline
(orchestration / render / review / artifacts) with no API keys; does not produce
photorealism.

```bash
genclaw run --prompt "three red circles on the left" --mode fixture
genclaw run --prompt "poster for GenClaw with title Code as Brush" --mode fixture
genclaw run --prompt "mirror reflection of a small ball" --mode fixture

genclaw render --plan path/to/plan.json     # compile a saved plan standalone
genclaw review --run-dir path/to/run        # re-run rule review on a finished run
genclaw bench  --suite mini                  # local regression smoke
pytest -q                                    # tests
```

Every run writes a complete, inspectable directory
`outputs/runs/<timestamp>-<request_id>/`:
`request.json`, `plan.json`, `canvas.{svg,html,py}`, `sketch.png`, `final.png`,
`review.json`, `trace.jsonl`.

## External mode — real models

Configure credentials in a local `.env` (copy `.env.example`; `.env` is
gitignored). The CLI auto-loads it.

```bash
# .env
ANTHROPIC_API_KEY=sk-...          # Claude agent + VLM reviewer
GOOGLE_API_KEY=...                # image generator
# Optional: route through an Anthropic/OpenAI-compatible proxy/gateway
ANTHROPIC_BASE_URL=https://...
GOOGLE_BASE_URL=https://...
GENCLAW_GENERATOR_MODEL=...       # override image model id if your proxy differs
TAVILY_API_KEY=...                # multi-round search (knowledge grounding)
```

```bash
pip install -e ".[providers]"

# external: structured templates + real models
genclaw run --prompt "your prompt" --mode external

# external-code: CODE-AS-BRUSH — the LLM writes SVG/HTML/Three.js source itself
genclaw run --prompt "a poster titled Quantum 101 with three bullet points" \
  --mode external-code
```

Default stack aligns with the paper (ADR 0004): Claude-Opus agent + VLM reviewer,
Gemini-3.1-Flash-Image generator, Tavily search. Providers are **pluggable** —
the image model is selected from config, so swapping it is a one-line `.env`
change (e.g. `gpt-image-2` instead of Gemini). Missing credentials raise
`ProviderNotConfiguredError` with setup hints, and a failed step writes a
structured error artifact instead of failing silently.

**Note on image models:** code-as-brush's Color step needs an **image-to-image**
model (it conditions on the sketch). A pure **text-to-image** model ignores the
sketch and collapses the pipeline back to black-box generation — use one only as
a baseline, not as the colorist.

## Paper mechanism ↔ coverage (honest status)

- ✅ **Working**: intent understanding (fixture + LLM agent); search node
  (wired); SVG/HTML/Three.js/Python/Canvas rendering; **code-as-brush**
  (`external-code`, SVG/HTML/Three.js verified end-to-end); rule review;
  composite (structural + VLM) review; artifact/trace.
- ◑ **Scaffolded**: real multi-round search (needs Tavily key); reasoning
  (`ReasoningStep` schema present, auto-fill pending); image coloring + VLM
  review (run end-to-end via proxy; quality varies).
- ✗ **Not yet (phase 2 / deferred)**: **layered editing + SAM3 + inpainting**
  (the paper's hardest quantitative claim, ImgEdit PSNR/SSIM — biggest gap);
  **execution sandbox** for HTML/Three.js code-as-brush (see Security); official
  benchmarks (GenEval++/LongText/ImgEdit/Mind-Bench).

See `docs/reproduction-roadmap.md` and `docs/TODO.md` for the live status.

## ⚠️ Security

`--mode external-code` runs **model-authored code**:
- SVG goes through a static allow-list validator (no scripts/external refs).
- **HTML/Three.js execute arbitrary JS in headless Chromium with NO sandbox**
  (no network isolation, CSP, or resource caps). This is acceptable only for a
  **local, single-machine** run with trusted-LLM input. **Do not expose to
  untrusted input or deploy publicly** until the execution-sandbox work (ADR
  0005, deferred) lands.

## Docs

- `docs/specs/` — requirements, scope, paper-coverage table
- `docs/plans/` — ordered implementation tasks
- `docs/adr/` — architecture decisions (0001 artifact-first/pluggable, 0002
  LangGraph, 0003 template vs free-form, 0004 provider/benchmark, 0005
  code-as-brush + deferred sandbox)
- `docs/reproduction-notes.md`, `docs/reproduction-roadmap.md`, `docs/TODO.md`

## License

Apache-2.0.

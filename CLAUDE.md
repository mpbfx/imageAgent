# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目性质

本仓库是论文 **GenClaw: Code-Driven Agentic Image Generation**（arXiv 2605.30248）的**独立复现项目**，目前处于**规划阶段，尚无实现代码**。官方代码未发布，因此复现以论文为规格来源，不复跑作者代码，也不声称精确复现论文数值。

仓库当前只包含：论文材料（PDF、LaTeX 源 `tmp_genclaw_src/`、中文翻译、`tmp/pdfs/` 抽取文本）和 `docs/` 下的规划文档。`tmp/` 与 `tmp_genclaw_src/` 是只读参考材料，不是要构建的代码。

## 权威文档（动手前必读）

实现尚未开始，所有设计决策都在 `docs/` 中，是真正的 single source of truth：

- `docs/specs/2026-06-18-genclaw-reproduction-spec.md` — 功能/非功能需求、范围、验收标准
- `docs/plans/2026-06-18-genclaw-reproduction-plan.md` — 15 个有序实现任务、目标目录结构、每任务的文件与测试
- `docs/adr/0001-*.md` — artifact-first、provider-pluggable 架构决策及被否决的备选方案
- `docs/adr/0002-*.md` — 选用 LangGraph 作编排框架的理由
- `docs/adr/0003-*.md` — 模板 vs free-form 代码生成的分阶段路线；明确 phase-1 是脚手架、phase-2 才落地 code-as-brush 核心机制
- `docs/adr/0004-*.md` — provider/benchmark 选型:默认实现对齐论文栈(Opus + Gemini-Flash-Image + SAM3 + 官方 benchmark),开源替代为退路

开始编码时，按 plan 的任务顺序（任务 1 → 15）推进；目标目录结构与每个任务的测试清单都在 plan 中明确给出。

## 核心架构（论文三层 → 复现 pipeline）

GenClaw 把图像生成从黑盒拆成三层，复现据此设计：

1. **认知结构化层** — 自然语言 prompt → schema 校验的 `CanvasPlan`（Pydantic）。结构化记录服务于控制和渲染，而非堆叠自然语言 prompt。
2. **可执行画布层** — 将 `CanvasPlan` 按 `backend` 编译成可执行代码并渲染为 PNG：SVG（对象计数/布局/空间关系/局部编辑）、HTML/CSS（长文本/海报/卡片）、Three.js（几何/物理/视角）。
3. **视觉生成与审查层** — 以代码 sketch 作视觉条件调用图像生成/编辑 provider 补全材质纹理光照，再审查并有上限地迭代。

关键约束（来自 ADR）：

- **结构化计划是中心契约**：renderer 和 reviewer 都消费同一个 `CanvasPlan`。schema 须对齐四个 benchmark 任务族(GenEval++/LongText/ImgEdit/Mind-Bench)并以 `source` 字段区分 `structured`(模板,phase 1)与 `code`(free-form 源码,phase 2),见 ADR 0003。
- **phase-1 是脚手架,不是机制复现**:phase-1 用模板化画布验证编排/产物/审查/渲染管道;论文核心 code-as-brush(LLM 直接写代码)属 phase-2 的受约束 free-form 代码生成 + 沙箱渲染。文档与表述不得把 phase-1 称为"复现了 GenClaw 机制"。
- **模板控制的画布**：代码从校验后的字段生成，模型输出当作数据，**不直接执行模型生成的任意代码**。
- **provider 全部可插拔**：LLM/VLM、search、image generation/editing、segmentation 都是 adapter。**默认实现对齐论文栈**(Opus backbone、Gemini-Flash-Image generator、SAM3 分割、官方 benchmark;见 ADR 0004);开源替代(FLUX.1-Kontext/Qwen-Image/SDXL+ControlNet/SAM2/SearXNG)为凭据不可得时的退路;fixture/mock 仅作无凭据 CI 冒烟。
- **LangGraph 只负责编排**，不承担 domain logic；route function 须为纯函数；每个 node 执行后必须写 trace。schema 校验、renderer、generator、reviewer 保持独立模块。

LangGraph 主图：`conceptualize → render → generate → review → route_after_review`，review 失败且未超 `max_revisions` 时经 conditional edge 回到 `revise → render`。

## Artifact-first 输出

每次 run 写出完整目录 `outputs/runs/<timestamp>-<request_id>/`：`request.json`、`plan.json`、`canvas.{svg,html}`、`sketch.png`、`final.png`、`review.json`、`trace.jsonl`。审查者无需重跑 pipeline 即可检查全过程。单个 provider/backend 失败须产出结构化 error artifact，不能吞掉上下文。

## 技术栈与命令

技术栈：Python 3.11+、LangGraph、Pydantic、Typer、Rich、Playwright（SVG/HTML/Three.js → PNG）、Pillow、NumPy、pytest。外部 provider 包放 optional extras，非 core 必需。

环境为 Windows（工作区 `D:\genclaw`），所有代码须支持 Windows。实现落地后的常用命令（见 plan 验证清单）：

```powershell
python -m pip install -e ".[dev]"
python -m playwright install chromium
python -m pytest -q
genclaw run --prompt "three red circles on the left" --mode fixture
genclaw bench --suite mini
```

fixture mode 不依赖私有模型凭据，也不复现 photorealism；结构控制与最终审美质量分开评测。

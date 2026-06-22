# imageAgent — GenClaw 复现

论文 **GenClaw: Code-Driven Agentic Image Generation**（arXiv `2605.30248`）的独立复现。
让智能体像人类画家一样作画——**先构思、再用代码起稿、后上色**，而不是把一句 prompt 丢给黑盒文生图模型。

> ⚠️ **独立复现。** 以论文为规格从零实现。官方代码/demo 在撰写时尚未发布；本项目不复跑作者代码，也不声称精确复现论文数值。

---

## 为什么是 code-as-brush（代码即画笔）

自然语言在**数量、坐标、文字、遮挡**上有歧义（"左边三个红圆"、"A 在 B 后面"），而代码没有：
`<circle cx="100" cy="50" r="40"/>` 就是精确的。GenClaw 让 LLM **直接写画布源码**（SVG / HTML / Three.js）
来锁定结构，再把这张草图作为**视觉条件**交给图像模型，让它只当"上色师"补材质和光照。

效果：数量、布局、文字都正确（由代码保证），真实感由图像模型补。在**计数、空间关系、数据图表、生僻字**
这类任务上明显强于纯文生图；在普通场景上与之持平（前沿图像模型本身已够强）。

## 架构 — 三层（LangGraph 编排）

```
conceptualize → search → render → generate → review → route_after_review
   (构思)       (检索)   (起稿)   (上色)    (审查)    └─(失败且未超限)→ revise → render
```

1. **构思（Think）** — prompt → schema 校验的 `CanvasPlan`（Pydantic）。意图理解 +
   可选**搜索**（知识接地）+ **推理**槽位。中心契约是结构化 plan，不是自然语言。
2. **起稿（Sketch）** — 编译/生成可执行画布代码并渲染成 PNG：
   - **SVG** — 组合、计数、空间关系、图表
   - **HTML/CSS** — 长文本、海报、卡片（有真正的排版引擎）
   - **Three.js** — 3D 几何 / 物理 / 视角（headless WebGL）
   - **Python（matplotlib）/ Canvas** — 数值型物理草图
3. **上色 + 审查（Color + Review）** — 把草图作**视觉条件**喂给图像模型（图生图），
   再审查（确定性规则 + 可选 VLM）并有上限地迭代。

画布有两种产生方式：
- **structured（结构化）** — 模板填入校验过的字段，确定性脚手架。
- **code（代码）** — LLM 直接写源码，即 **code-as-brush**，论文的核心机制。用 `--mode external-code` 启用。

## 安装

需要 Python 3.10+。

```bash
pip install -e ".[dev]"
python -m playwright install chromium     # SVG/HTML/Three.js → PNG 所需
```

若 PyPI 直连不通（`pypi.org` 被 TLS 重置），改用国内镜像：

```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn
# Playwright 浏览器二进制走镜像：
PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright \
  python -m playwright install chromium
```

## 快速开始 — fixture 模式（无需凭据）

确定性 agent + mock 生成器。跑通整条管道（编排 / 渲染 / 审查 / 产物），无需任何 API key；不产出真实感图像。

```bash
genclaw run --prompt "three red circles on the left" --mode fixture
genclaw run --prompt "poster for GenClaw with title Code as Brush" --mode fixture
genclaw run --prompt "mirror reflection of a small ball" --mode fixture

genclaw render --plan path/to/plan.json     # 单独编译一个已保存的 plan
genclaw review --run-dir path/to/run        # 对已完成的 run 重跑规则审查
genclaw bench  --suite mini                  # 本地回归冒烟
pytest -q                                    # 测试
```

每次 run 写出完整、可检查的目录 `outputs/runs/<时间戳>-<request_id>/`：
`request.json`、`plan.json`、`canvas.{svg,html,py}`、`sketch.png`、`final.png`、`review.json`、`trace.jsonl`。

## external 模式 — 接入真实模型

在本地 `.env` 配置凭据（复制 `.env.example`；`.env` 已 gitignore）。CLI 会自动加载。

```bash
# .env
ANTHROPIC_API_KEY=sk-...          # Claude agent + VLM 审查
GOOGLE_API_KEY=...                # 图像生成
# 可选：走 Anthropic/OpenAI 兼容的代理/网关
ANTHROPIC_BASE_URL=https://...
GOOGLE_BASE_URL=https://...
GENCLAW_GENERATOR_MODEL=...       # 代理的图像模型 id 不同时覆盖
TAVILY_API_KEY=...                # 多轮搜索（知识接地）
```

```bash
pip install -e ".[providers]"

# external：默认即 CODE-AS-BRUSH —— LLM 自己写 SVG/HTML/Three.js 源码（论文核心机制）
genclaw run --prompt "你的 prompt" --mode external

# external-code：external 的显式别名（同样是 code-as-brush）
genclaw run --prompt "..." --mode external-code

# external-template：结构化模板回退（不执行模型代码，确定性，可作对照基线）
genclaw run --prompt "你的 prompt" --mode external-template
```

默认栈对齐论文（见 ADR 0004）：Claude-Opus agent + VLM 审查、Gemini-3.1-Flash-Image
生成器、Tavily 搜索。**接真实模型时默认走 code-as-brush**——论文是 *Code-Driven*，所以
`external` 即代码即画笔；`external-template` 才退回模板路径。Provider **可插拔**——图像模型
从配置选取，换一个只需改一行 `.env`（如用 `gpt-image-2` 替代 Gemini）。缺凭据时抛
`ProviderNotConfiguredError` 并给配置指引；某步失败会写结构化 error artifact，而非静默失败。

**关于图像模型：** code-as-brush 的上色步需要**图生图（image-to-image）**模型（它要以草图为条件）。
**纯文生图（text-to-image）**模型看不到草图，会让管道退回黑盒生成——这类模型只能当对照基线，不能当上色师。

## 论文机制 ↔ 覆盖度（诚实声明）

- ✅ **已实现可跑**：意图理解（fixture + LLM agent）；search 节点（已接线）；
  SVG/HTML/Three.js/Python/Canvas 渲染；**code-as-brush**（`external-code`，
  SVG/HTML/Three.js 已端到端验证）；规则审查；复合审查（结构 + VLM）；artifact/trace。
- ◑ **已搭结构 / stub**：真实多轮搜索（需 Tavily key）；推理（`ReasoningStep` schema
  已建，自动填充待接）；图像上色 + VLM 审查（经代理已端到端跑通，质量有波动）。
- ✗ **尚未实现（phase 2 / 暂缓）**：**分层编辑 + SAM3 + inpainting**（论文最硬的定量
  主张 ImgEdit PSNR/SSIM，当前最大缺口）；HTML/Three.js code-as-brush 的**执行沙箱**（见安全）；
  官方 benchmark（GenEval++/LongText/ImgEdit/Mind-Bench）。

实时状态见 `docs/reproduction-roadmap.md` 和 `docs/TODO.md`。

## ⚠️ 安全

`--mode external-code` 会运行**模型生成的代码**：
- SVG 经过静态白名单校验（禁脚本/外链）。
- **HTML/Three.js 在 headless Chromium 中直接执行任意 JS，无沙箱**（无网络隔离、CSP、
  资源上限）。这仅在**本地单机、可信 LLM 输入**下可接受。**在执行沙箱（ADR 0005，已推迟）
  落地前，切勿暴露给不可信输入或公开部署。**

## 文档

- `docs/specs/` — 需求、范围、论文覆盖度表
- `docs/plans/` — 有序实现任务
- `docs/adr/` — 架构决策（0001 artifact-first/可插拔、0002 LangGraph、0003 模板 vs
  free-form、0004 provider/benchmark、0005 code-as-brush + 推迟沙箱）
- `docs/reproduction-notes.md`、`docs/reproduction-roadmap.md`、`docs/TODO.md`

## 许可

Apache-2.0。

# GenClaw 复现

[English](README.md)

论文 **GenClaw: Code-Driven Agentic Image Generation**（`arXiv:2605.30248`）的独立复现。

GenClaw 会把一次图像生成请求先转成结构化计划，再渲染成代码草图，最后交给图像模型补全外观。这样做的重点是：把数量、位置、文字、图表、遮挡关系这类硬约束写进代码，而不是期待纯文生图 prompt 自动保真。

> 本项目根据论文描述独立实现，不运行官方 GenClaw 代码，也不声称能精确复现论文里的数值结果。

最后复查：2026-07-02

## 快速开始

建议先跑 fixture 模式。它不需要 API key，可以验证本地管道：计划生成、渲染、mock 生成、产物落盘和 trace。

```bash
pip install -e ".[dev]"
python -m playwright install chromium

genclaw run --prompt "three red circles on the left" --mode fixture --enable-review
genclaw run --prompt "poster for GenClaw with title Code as Brush" --mode fixture
genclaw run --prompt "mirror reflection of a small ball" --mode fixture

genclaw bench --suite mini
pytest -q
```

每次运行会在 `outputs/runs/` 下写出一个目录：

```text
request.json
plan.json
canvas.svg | canvas.html | canvas.py
sketch.png
final.png
review.json     # 启用 review 时生成
trace.jsonl
```

## 实现内容

项目按论文的三层流程组织：

```text
conceptualize -> search -> render -> generate -> review -> route_after_review
                  |                                      |
                  |                                      v
                  +------------------------------ revise -> render
```

| 层级 | 作用 | 当前实现 |
| --- | --- | --- |
| Think | 把 prompt 转成 schema 校验通过的 `CanvasPlan`，并可挂载知识引用和推理记录。 | Fixture agent 与外部 LLM agent；search 节点已接线，Tavily 需要凭据。 |
| Sketch | 把计划转成可执行画布代码，再渲染成 PNG 草图。 | SVG、HTML/CSS、Three.js、Python/matplotlib、Canvas 渲染器。 |
| Color + Review | 把草图交给生成器，并用结构/视觉检查产出审查结果。 | fixture 模式使用 mock generator；外部图像生成器和 VLM reviewer adapter 已存在。 |

核心契约是 `CanvasPlan`，不是一段很长的自然语言 prompt。代码负责锁定布局和结构；图像模型主要负责纹理、光照、风格和真实感。

## 使用方式

### Fixture 模式

Fixture 模式是确定性的，适合本地冒烟、CI 风格检查和调试 artifact 流程。它不会生成真实感图片。

```bash
genclaw run --prompt "three red circles on the left" --mode fixture
genclaw render --plan path/to/plan.json
genclaw review --run-dir path/to/run
genclaw bench --suite mini
```

`genclaw run` 默认跳过 review。需要在一次 run 内执行审查时，加 `--enable-review`：

```bash
genclaw run --prompt "three red circles on the left" --mode fixture --enable-review
```

### 外部模型

复制 `.env.example` 为 `.env`，填入 provider 凭据。CLI 会自动加载 `.env`。

```bash
pip install -e ".[providers]"
```

```bash
# .env
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...

# 可选：代理或网关地址
ANTHROPIC_BASE_URL=https://...
GOOGLE_BASE_URL=https://...

# 可选：覆盖默认模型
GENCLAW_AGENT_MODEL=...
GENCLAW_REVIEWER_MODEL=...
GENCLAW_GENERATOR_MODEL=...

# 可选：知识接地搜索
TAVILY_API_KEY=...
```

运行模式：

| 模式 | 适用场景 | 说明 |
| --- | --- | --- |
| `fixture` | 想要无凭据本地运行。 | 确定性 agent 和 mock generator。 |
| `external` | 想走默认真实模型路径。 | 默认使用 code-as-brush。 |
| `external-code` | 想显式启用 code-as-brush。 | LLM 直接写 SVG/HTML/Three.js 画布源码。 |
| `external-template` | 想要更安全的结构化基线。 | 使用校验字段和模板，不执行模型写的画布代码。 |
| `external-tele` | 想使用 TeleImage SSH 生成器。 | 保持 code-as-brush 的 agent/reviewer/search 行为，但换用 TeleImage 生成器。 |

示例：

```bash
genclaw run --prompt "a sales bar chart with exact labels" --mode external
genclaw run --prompt "a sales bar chart with exact labels" --mode external-template
```

如果希望最终图像尊重草图，图像生成步骤需要支持 image-to-image 的模型。纯 text-to-image 模型看不到渲染后的画布，只适合作为对照基线。

## 当前状态

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| `CanvasPlan` schema | 已完成 | 覆盖 structured 和 code 两类画布来源。 |
| Artifact-first 输出 | 已完成 | request、plan、画布源码、图像、review、trace 都会保留。 |
| LangGraph 编排 | 已完成 | 主图和 review 后的条件路由已实现。 |
| 渲染器 | 已完成 | SVG、HTML、Three.js、Python、Canvas。 |
| Fixture pipeline | 已完成 | 无凭据开发主路径。 |
| 外部 LLM/provider adapter | 已完成 | Claude/Gemini 风格栈，支持配置 base URL。 |
| Code-as-brush | SVG/HTML/Three.js 已完成 | 有用，但 HTML/Three.js 仍有沙箱风险。 |
| Search grounding | 部分完成 | 节点和 Tavily adapter 已有；真实多轮搜索仍需验证。 |
| Revision loop | 部分完成 | 路由存在，但基于反馈的有效重生成仍有限。 |
| 分层编辑 | 未完成 | SAM3 + mask/inpainting 是当前最大的论文机制缺口。 |
| 官方 benchmark | 未完成 | mini benchmark 只是本地冒烟，不等价于 GenEval++/LongText/ImgEdit/Mind-Bench。 |

这个项目最适合验证硬约束图像任务：精确计数、空间关系、长文本或生僻字、图表、示意图和受控布局。对于普通写实场景，前沿 text-to-image 模型通常已经足够强，GenClaw 管道的边际优势会小一些。

## 安全说明

`external`、`external-code` 和 `external-tele` 可能会渲染模型写出的代码。

SVG 会经过静态白名单检查。HTML 和 Three.js 会在 headless Chromium 中渲染，并且可能执行 JavaScript；目前还没有完整沙箱，不能保证强网络隔离、CSP 边界或资源限制。

这些模式只适合本地、可信输入。需要更安全的基线时，用 `external-template`。在执行沙箱完成前，不要把 code-as-brush 渲染暴露给不可信用户或公开服务。

## 项目结构

```text
genclaw/
  agent/          prompt-to-plan provider
  benchmarks/     mini benchmark fixture 与 runner
  generators/     mock、external、TeleImage 生成器
  graph/          LangGraph 节点、状态和路由
  renderers/      SVG、HTML、Three.js、Python、Canvas 渲染
  review/         规则审查和 VLM 审查

docs/
  specs/          复现范围和论文机制覆盖度
  plans/          实现计划
  adr/            架构决策记录
```

重要文档：

- `docs/reproduction-roadmap.md` - 一页纸实现状态
- `docs/TODO.md` - 按优先级排列的后续工作
- `docs/specs/2026-06-18-genclaw-reproduction-spec.md` - 范围与覆盖度说明
- `docs/adr/` - 架构决策
- `SEARCH_INTEGRATION.md` - 搜索 provider 说明

## 开发说明

如果 PyPI 或 Playwright 下载因为本地网络受限失败，可以使用镜像：

```bash
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn

PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright \
  python -m playwright install chromium
```

修改行为前建议跑：

```bash
pytest -q
genclaw bench --suite mini
```

高价值下一步：

- 从实际代码/plan 结构生成对象数量检查，不再信任 LLM 自报数量。
- 为 HTML/Three.js code-as-brush 增加执行沙箱。
- 实现基于分割、mask、inpainting 和非编辑区域指标的分层编辑。
- 验证真实 Tavily 搜索和官方 benchmark adapter。

## 许可证

Apache-2.0。

# GenClaw 复现实现计划

**目标:** 构建一个本地可测试的 GenClaw-style pipeline：用 LangGraph 编排 prompt 结构化、可执行代码草图渲染、可选图像生成 provider 调用和审查迭代。

**架构:** 采用 artifact-first、provider-pluggable 和 LangGraph state graph 设计。核心 schema、renderer、review 和 graph nodes 在本地确定性运行；LLM、VLM、搜索、图像生成、图像编辑、分割都通过 adapter 接入。

**技术栈:** Python 3.10+（开发机为 64-bit 3.10.11）、LangGraph、Pydantic、Typer、Rich、Playwright、Pillow、NumPy、pytest。

**修订说明（依据 ADR 0003 与 spec 评审）：** 本计划在原 15 任务基础上前置两项:任务 2 的 schema 必须对齐四个 benchmark 任务族(GenEval++/LongText/ImgEdit/Mind-Bench)并区分 `structured`/`code` 两类画布来源,而非围绕 3 个 fixture;任务 8(Three.js)前新增**任务 7.5 headless WebGL 渲染 spike**。任务 14 补充 prompt→`CanvasPlan` 的可靠性机制。任务 1 须锁定 langgraph/langchain 依赖版本。

---

## 目录结构

创建如下结构：

```text
D:\genclaw
  pyproject.toml
  README.md
  genclaw
    __init__.py
    cli.py
    config.py
    pipeline.py
    schemas.py
    artifacts.py
    tracing.py
    graph
      __init__.py
      state.py
      nodes.py
      routes.py
      builder.py
    agent
      __init__.py
      base.py
      fixture.py
      prompts.py
    renderers
      __init__.py
      base.py
      svg.py
      html.py
      three.py
      playwright_render.py
    generators
      __init__.py
      base.py
      mock.py
    review
      __init__.py
      base.py
      rules.py
    benchmarks
      __init__.py
      fixtures.py
      runner.py
  tests
    test_schemas.py
    test_svg_renderer.py
    test_html_renderer.py
    test_three_renderer.py
    test_review_rules.py
    test_pipeline_fixture.py
    test_cli.py
  examples
    prompts
      composition.txt
      poster.txt
      physics.txt
  outputs
    .gitkeep
```

## 任务 1：项目骨架

**文件：**

- 新建：`pyproject.toml`
- 新建：`README.md`
- 新建：`genclaw` 包目录
- 新建：`tests/conftest.py`

**步骤：**

1. 创建 Python package skeleton。
2. 添加依赖：
   - runtime：`langgraph`、`pydantic`、`typer`、`rich`、`pillow`、`numpy`、`playwright`
   - dev：`pytest`、`pytest-cov`
   - **锁定 `langgraph` 与传递依赖 `langchain-core` 的版本范围**（API churn 大），记录已验证版本。
3. 添加 CLI entry point：`genclaw = "genclaw.cli:app"`。
4. README 写清：
   - 当前是独立复现；
   - 官方代码尚未发布；
   - fixture mode quickstart。
5. 运行 `python -m pip install -e ".[dev]"`。
6. 运行 `python -m playwright install chromium`。
7. 运行 `pytest`，预期为无测试或初始 import 测试通过。

## 任务 2：核心 Schema

**文件：**

- 新建：`genclaw/schemas.py`
- 新建：`tests/test_schemas.py`

**实现要求：**

定义 Pydantic models。**设计前提（ADR 0003）：** 字段需求从四个 benchmark 任务族推导(组合控制/长文本/局部编辑/知识推理),不得只为 3 个 fixture 设计。`CanvasPlan` 必须含 `source` 判别字段区分 `structured`(模板编译,第一阶段)与 `code`(free-form 源码 + 校验,第二阶段),后者预留 `code_source`/`code_lang` 字段但第一阶段可不实现编译。

- `TaskType`：`composition`、`long_text`、`physical_reasoning`、`editing`、`knowledge_grounded`
- `CanvasBackend`：`svg`、`html`、`three`
- `CanvasSize`：width、height
- `LayerSpec`：id、name、order、opacity
- `ObjectSpec`：id、kind、label、layer_id、x、y、width、height、fill、stroke、attributes
- `TextSpec`：id、text、layer_id、x、y、width、height、font_size、color、align
- `RelationSpec`：subject_id、relation、object_id、strength
- `ReviewCheck`：kind、target、expected
- `CanvasPlan`：request_id、prompt、task_type、backend、size、layers、objects、text、relations、style、checks
- `ReviewResult`：passed、score、failures、warnings

**测试：**

- 合法 plan 能 parse。
- 引用不存在的 layer 必须失败。
- 负数尺寸必须失败。
- 重复 id 必须失败。

## 任务 3：Artifact 与 Trace 管理

**文件：**

- 新建：`genclaw/artifacts.py`
- 新建：`genclaw/tracing.py`
- 修改：`tests/test_pipeline_fixture.py`

**实现要求：**

- `RunArtifacts.create(base_dir, request_id)` 创建：
  - `request.json`
  - `plan.json`
  - `canvas.*`
  - `sketch.png`
  - `final.png`
  - `review.json`
  - `trace.jsonl`
- `TraceWriter.append(stage, data)` 每次写入一行 JSON。
- LangGraph node 每次执行后必须追加 trace，至少记录 node 名称、输入摘要、输出 artifact paths、错误摘要。
- 输出目录放在 `outputs/runs/<timestamp>-<request_id>`。

**测试：**

- run directory 会被创建。
- trace file 追加合法 JSONL。
- trace file 包含 LangGraph node 名称。
- 同一次 run 内 artifact paths 稳定。

## 任务 3.5：LangGraph State 定义

**文件：**

- 新建：`genclaw/graph/__init__.py`
- 新建：`genclaw/graph/state.py`
- 新建：`tests/test_graph_state.py`

**实现要求：**

定义 `GenClawState`，包含：

- `request_id`
- `prompt`
- `task_type`
- `plan`
- `artifacts`
- `rendered_canvas`
- `generation_result`
- `review_result`
- `revision_count`
- `max_revisions`
- `errors`
- `trace_events`

**测试：**

- 初始 state 能从 prompt 构造。
- state 能保存 `CanvasPlan`。
- `revision_count` 递增后仍可序列化。
- `errors` 为空时默认为空列表。

## 任务 4：Fixture Agent

**文件：**

- 新建：`genclaw/agent/base.py`
- 新建：`genclaw/agent/fixture.py`
- 新建：`genclaw/agent/prompts.py`

**实现要求：**

- `AgentProvider.conceptualize(prompt, task_type=None) -> CanvasPlan`
- Fixture provider 返回确定性 plans：
  - prompt 包含 `three red circles`：返回含 3 个 circle 的 SVG composition plan。
  - prompt 包含 `poster`：返回 HTML long-text poster plan。
  - prompt 包含 `mirror`：返回 Three.js physical reasoning plan。
- `prompts.py` 保存后续外部 LLM provider 用的 system/developer prompt 模板。

**测试：**

- composition fixture 返回 3 个 object specs。
- poster fixture 返回精确保留文本的 text specs。
- mirror fixture 选择 `three` backend。

## 任务 5：Renderer 基类与 Playwright 渲染

**文件：**

- 新建：`genclaw/renderers/base.py`
- 新建：`genclaw/renderers/playwright_render.py`

**实现要求：**

- `Renderer.render(plan, output_dir) -> RenderedCanvas`
- `RenderedCanvas` 包含 backend、source_path、png_path、width、height。
- Playwright helper 将 HTML string 渲染为 PNG，并支持：
  - 固定 viewport；
  - 本地文件加载；
  - timeout；
  - console error 捕获。

**测试：**

- 最小 HTML 能渲染为 PNG。
- 缺失输出目录时自动创建。
- renderer timeout 返回结构化异常。

## 任务 6：SVG Renderer

**文件：**

- 新建：`genclaw/renderers/svg.py`
- 新建：`tests/test_svg_renderer.py`

**实现要求：**

- 将 `CanvasPlan` 编译为 SVG。
- 支持 shapes：
  - circle；
  - rectangle；
  - ellipse；
  - polygon，输入为显式 points 列表。
- 渲染顺序按 layer order，再按 object order。
- SVG 内支持 text nodes。
- 通过 Playwright 将 inline SVG 包装成 HTML 后渲染 PNG。

**测试：**

- three-circle plan 输出恰好 3 个 `<circle` 节点。
- layer order 反映在 SVG 源码顺序中。
- PNG 被创建且非空。

## 任务 7：HTML Renderer

**文件：**

- 新建：`genclaw/renderers/html.py`
- 新建：`tests/test_html_renderer.py`

**实现要求：**

- 将长文本 plan 编译为 HTML/CSS。
- 使用 absolute-positioned text blocks 保持确定性布局。
- 转义用户文本。
- HTML 源码中保留全部精确文本。
- 使用 Playwright 渲染 PNG。

**测试：**

- HTML 源码包含要求的英文和中文文本。
- 输入 HTML 片段会被转义，不作为 markup 执行。
- PNG 被创建且非空。

## 任务 7.5：Three.js Headless 渲染 Spike（前置风险验证）

**目的：** 在投入任务 8 前，先验证 headless Chromium 能在 Windows 上稳定渲染 WebGL 并截到非空帧。这是全计划最大的渲染风险点。

**文件：**

- 新建：`tmp/spikes/three_headless_spike.py`（一次性验证脚本，不进 package）

**步骤：**

1. 用 Playwright 启动 Chromium，加入 `--use-gl=swiftshader`、`--enable-unsafe-swiftshader`、`--ignore-gpu-blocklist` 等 flag。
2. 加载一个最小 Three.js 场景（单个有色 cube + 光源）。
3. 等 WebGL 真正出帧后截图：监听 `requestAnimationFrame` 渲染若干帧、或注入渲染完成信号后再 `screenshot`，不要立刻截图。
4. 校验 PNG 非空且非纯背景色（采样像素方差）。

**通过标准：** 连续 5 次运行都产出非空、含可见几何体的 PNG。若不稳定，记录所需 flag/等待策略，并据此调整任务 8；若 Windows headless WebGL 始终不稳定，触发后续 ADR 决定降级方案（如 Three.js 离屏渲染服务或几何任务暂以 2D Canvas 替代）。

## 任务 8：Three.js Renderer

**前置：** 任务 7.5 spike 通过后再开始，复用其验证过的浏览器 flag 与出帧等待策略。

**文件：**

- 新建：`genclaw/renderers/three.py`
- 新建：`tests/test_three_renderer.py`

**实现要求：**

- 将 physical/geometric plan 编译为包含 Three.js scene 的 HTML 文件。
- 第一版 mirror fixture 创建：
  - ground plane；
  - mirror plane；
  - sphere；
  - directional light；
  - camera。
- 使用确定性 camera 和 object coordinates。
- 渲染稳定第一帧为 PNG（复用任务 7.5 验证过的 swiftshader flag 与出帧等待策略，不要在场景未出帧时截图）。

**测试：**

- HTML 源码包含必要 scene objects。
- PNG 被创建且非空。
- renderer 报告 backend 为 `three`。

## 任务 9：Generator Provider 接口

**文件：**

- 新建：`genclaw/generators/base.py`
- 新建：`genclaw/generators/mock.py`

**实现要求：**

- `ImageGenerator.generate(prompt, sketch_path, output_path, constraints) -> GenerationResult`
- Mock generator 将 `sketch.png` 复制到 `final.png`，并写 metadata，说明 fixture mode 不提供 photorealism。
- 外部 provider 配置不写入 core implementation。

**测试：**

- mock provider 创建 final image。
- metadata 记录 provider name 和 sketch path。

## 任务 10：规则审查

**文件：**

- 新建：`genclaw/review/base.py`
- 新建：`genclaw/review/rules.py`
- 新建：`tests/test_review_rules.py`

**实现要求：**

实现检查项：

- 按 kind 检查对象数量；
- 检查 source canvas 中是否包含 required text；
- 检查 required backend；
- 检查 artifact 是否存在；
- 检查 image size 是否匹配 canvas size。

返回 `ReviewResult`，必须包含明确 failure reason。

**测试：**

- three-circle fixture 通过数量检查。
- 缺少 required text 时失败，且原因清晰。
- backend 错误时失败。

## 任务 11：Pipeline 编排

**文件：**

- 新建：`genclaw/pipeline.py`
- 新建：`genclaw/graph/nodes.py`
- 新建：`genclaw/graph/routes.py`
- 新建：`genclaw/graph/builder.py`
- 新建：`tests/test_langgraph_workflow.py`
- 修改：`tests/test_pipeline_fixture.py`

**实现要求：**

- 使用 LangGraph `StateGraph` 定义主流程：
  1. `conceptualize_node`
  2. `render_node`
  3. `generate_node`
  4. `review_node`
  5. `revise_node`
- `route_after_review(state)`：
  - `review_result.passed == True` 时结束；
  - `passed == False` 且 `revision_count < max_revisions` 时进入 `revise_node`；
  - 达到上限时结束，并保留失败 review。
- `revise_node` 在 fixture mode 下先返回明确 unsupported 信息，并递增 `revision_count`。
- `Pipeline.run(prompt, task_type=None, max_revisions=1)` 构造初始 state，调用 compiled graph，返回最终 state 和 run artifacts。
- 写出所有 artifacts 和 trace。
- 不允许吞掉 provider error。

**测试：**

- LangGraph workflow 节点顺序为 conceptualize、render、generate、review。
- review 失败且未超过上限时 route 到 revise。
- review 通过时 route 到结束。
- composition fixture 端到端创建 plan、canvas、sketch、final、review、trace。
- review result 被序列化为 JSON。
- provider failure 生成 error artifact。

## 任务 12：CLI

**文件：**

- 新建：`genclaw/cli.py`
- 新建：`tests/test_cli.py`

**命令：**

```text
genclaw run --prompt "three red circles on the left" --mode fixture
genclaw render --plan path\to\plan.json
genclaw review --run-dir path\to\run
genclaw bench --suite mini
```

**测试：**

- `genclaw run` 在 fixture mode 下 exit code 为 0。
- 输出 run directory 路径。
- 非法 backend exit code 非 0，错误信息简洁。

## 任务 13：Mini Benchmark Harness

**文件：**

- 新建：`genclaw/benchmarks/fixtures.py`
- 新建：`genclaw/benchmarks/runner.py`

**Fixture Families：**

- Composition：
  - 固定对象数量；
  - left/right relation；
  - occlusion/layering。
- Long text：
  - poster title/subtitle/body；
  - 中英文混合文本。
- Physical reasoning：
  - mirror reflection scene；
  - simple geometry layout。
- Editing：
  - source plan plus edit instruction；
  - object move/change color fixture。

**输出：**

- `outputs/benchmarks/<timestamp>/results.json`
- `outputs/benchmarks/<timestamp>/summary.md`

## 任务 13.5：官方 Benchmark 接入（一致性目标，phase 2）

**目的：** mini fixture 仅作回归冒烟;真正的一致性来自官方 benchmark 与 official metric(ADR 0004)。

**文件：**

- 新建：`genclaw/benchmarks/official/__init__.py`
- 新建：`genclaw/benchmarks/official/<bench>.py`（每个 benchmark 一个 adapter）

**实现要求：**

- 优先接入 **GenEval++** 或 **LongText-Bench**(组合控制 / 文本渲染,phase-1 渲染能力已覆盖,最易先跑通)。
- 复用各 benchmark 的官方数据集与 official metric 实现,不自造指标。
- ImgEdit 一致性走 CoCoEdit 的非编辑区 mask PSNR/SSIM 方案;指标用 torchmetrics/piq 等标准实现,不手写。
- 输出区分"官方 benchmark 结果"与"本地 fixture 结果",并记录所用模型版本与数据集版本,便于说明数值不可保证精确复现。
- Mind-Bench(依赖 search node + 多轮检索)与完整 ImgEdit(依赖 SAM3 分层 + inpainting)在对应机制就绪后再接。

## 任务 14：外部 Provider Stubs

**文件：**

- 新建可选模块：
  - `genclaw/agent/external.py`
  - `genclaw/generators/external.py`
  - `genclaw/review/vlm.py`

**实现要求：**

- 定义接口和环境变量配置名。
- **默认实现对齐论文栈(ADR 0004)**:LLM agent / VLM reviewer 默认 Claude-Opus-4.6;image generator 默认 Gemini-3.1-Flash-Image;分割默认 SAM3(`facebookresearch/sam3`,已确认发布可用;代码中记录所用版本与许可)。
- 接口保持可插拔,开源替代(FLUX.1-Kontext、Qwen-Image、SDXL+ControlNet、SAM2、SearXNG)为可选 provider,非默认。
- 未配置凭据时 external adapters 抛出 `ProviderNotConfiguredError`,并给出配置指引。

**Provider Contract：**

- LLM agent 返回能校验为 `CanvasPlan` 的 JSON。
- Image generator 接收 prompt、sketch image 和 constraints。
- VLM reviewer 返回结构化 pass/fail 和 evidence。

**prompt→`CanvasPlan` 可靠性机制（关键，架构 pivot 在此契约上）：**

- 优先用 provider 的 structured output / function calling 约束输出为 `CanvasPlan` schema。
- 校验失败时带 Pydantic 错误信息回灌、有上限重试(如 2 次);仍失败则产出结构化 error artifact,不得静默吞掉或返回半成品。
- 在 fixture/mock 之外补一个针对该机制的测试:注入一次非法 JSON,验证重试与最终 error artifact 行为。

## 任务 15：文档与复现说明

**文件：**

- 修改：`README.md`
- 新建：`docs/reproduction-notes.md`

**内容：**

- 说明本项目和官方 GenClaw 的区别。
- 说明 fixture mode。
- 说明如何接入外部 LLM/image providers。
- 说明 benchmark 限制。
- 链接论文、官方 GitHub、本地 spec 和 ADR。

## 验证清单

完成实现前运行：

```powershell
python -m pytest -q
genclaw run --prompt "three red circles on the left" --mode fixture
genclaw run --prompt "poster for GenClaw with title Code as Brush" --mode fixture
genclaw run --prompt "mirror reflection of a small ball" --mode fixture
genclaw bench --suite mini
```

预期结果：

- 所有测试通过；
- 每次 run 都创建完整 artifact directory；
- 每个 sketch 和 final image 文件非空；
- benchmark summary 存在；
- README quickstart 在 Windows 上可运行。

# GenClaw 复现规格说明

**日期:** 2026-06-18

**论文来源:** `GenClaw: Code-Driven Agentic Image Generation`，arXiv `2605.30248v2`。

**官方代码状态:** 已在 2026-06-18 核对。官方 GitHub 仓库当前说明技术报告已发布，代码和 demo 仍在准备中。因此本复现目标是按论文描述独立实现一套 GenClaw-style pipeline，而不是复跑作者尚未发布的代码。

## 目标

实现一个可复现的 GenClaw 风格系统，使用 LangGraph 编排 agent workflow，将用户的图像生成请求转换为：

1. 结构化视觉计划；
2. 可执行代码草图；
3. 渲染后的中间画布；
4. 可选的图像模型最终渲染；
5. 审查报告和有限迭代修正。

第一阶段目标是完成本地可运行的确定性 proof of concept，使用确定性渲染器和 mock generator。第二阶段再接入外部 LLM、VLM 和图像生成模型，并补充 benchmark 风格评测。

**定位澄清（见 ADR 0003）：** 第一阶段交付的是**脚手架**——验证 LangGraph 编排、artifact/trace、review 规则与 Playwright 渲染管道是否成立。论文核心机制 code-as-brush（让 LLM 直接编写 SVG/HTML/Three.js 代码）依赖受约束的 free-form 代码生成，属第二阶段。本规格不主张第一阶段“复现了 GenClaw 机制”；第一阶段的模板化画布是过渡手段，可能在第二阶段被 free-form 代码后端替换。

## 从论文提取的核心要求

GenClaw 将图像生成拆成三层：

1. **认知结构化层**
   - 解析用户意图。
   - 在需要时检索事实或执行推理。
   - 将结果转换为 JSONL 风格的结构化记录。
   - 记录应服务于控制和渲染，而不是堆叠自然语言 prompt。

2. **可执行画布层**
   - 根据任务类型选择后端：
     - SVG：适合对象计数、布局、空间关系、图层和局部编辑。
     - HTML/CSS：适合长文本、海报、菜单、课程表、卡片、网页式任务。
     - Python/Canvas/Three.js：适合几何、物理、视角和简单模拟任务。
   - 将结构化计划编译成可执行代码，并渲染成可检查的中间图像。
   - 保存代码和中间产物，便于后续直接修改对象、文本、坐标和图层。

3. **视觉生成与审查层**
   - 将代码草图作为视觉条件，调用图像生成或编辑模型。
   - 让图像模型主要负责材质、纹理、光照、真实感和风格补全。
   - 审查最终图像是否满足用户目标和结构化约束。
   - 迭代时优先修改结构化记录或代码，而不是只重写自然语言 prompt。

## 论文机制 ↔ 本复现覆盖度（诚实声明）

下表把论文声明的机制逐项对照当前实现状态，避免“声称覆盖却未实现”的失真。状态分：✅ 已实现可跑 / ◑ 已建结构化记录或 stub（机制未真正落地）/ ✗ 未实现。

| 论文机制（出处） | 本复现状态 | 说明 |
| --- | --- | --- |
| 认知层 - 意图理解（§3.1-3.2） | ✅ | fixture（关键字）+ external LLM agent（Claude-Opus，structured-output + 重试）。 |
| 认知层 - 搜索 / 知识接地（§3.2, Mind-Bench） | ◑→✅ 结构 | `search_node` 已在主图中、gated 运行、合并 `KnowledgeRef`（带可溯源 source）；默认 NullSearchProvider 为 no-op，真实多轮检索需配 Tavily 凭据。 |
| 认知层 - 推理（§3.2 几何/物理先算后画） | ◑ 结构 | schema 有 `ReasoningStep`（question/conclusion/values）承载中间结论；尚无自动推理 provider 填充，需 agent/外部模型产出。 |
| 可执行画布 - SVG（组合/计数/空间） | ✅ | 源码编译 + Playwright PNG。 |
| 可执行画布 - HTML/CSS（长文本/海报） | ✅ | 源码编译 + Playwright PNG，精确文本保留 + 转义。 |
| 可执行画布 - Three.js（3D 物理/视角） | ✅ | swiftshader headless WebGL 出帧截图已验证。 |
| 可执行画布 - Python/Canvas（数值物理草图） | ✅ | Python(matplotlib 直接出图)/Canvas(2D, Playwright)；论文 §3.2 与 Three.js 并列。 |
| code-as-brush（LLM 直接写 free-form 代码） | ✗（phase 2） | 当前为模板编译的 `structured` 来源；`code` 来源字段已在 schema 预留，编译/沙箱未实现（ADR 0003）。 |
| 视觉生成（Gemini-Flash-Image 上色） | ◑ | 接口 + 默认 Gemini adapter 已写，未配凭据实跑；fixture 用 mock（复制 sketch，无 photorealism）。 |
| 审查层（VLM 审查 + 可追踪诊断） | ✅ 规则 / ◑ VLM | 规则审查可跑；VLM reviewer（Claude-Opus）接口+解析已写，未配凭据实跑。 |
| 分层编辑 + SAM3 分割 + inpainting（§3.2, ImgEdit，论文最硬定量主张 PSNR/SSIM） | ✗（phase 2） | schema 有 `EditOp` 占位；分割 provider、editing pipeline、非编辑区一致性指标均未实现。**本复现尚不能支撑该定量主张。** |
| 官方 benchmark + official metric（GenEval++/LongText/ImgEdit/Mind-Bench） | ✗（暂缓） | 用户决定先复刻核心 pipeline，benchmark 暂缓（ADR 0004 接入方案在案）。 |

## 复现范围

### 范围内

- CLI 驱动的 pipeline：
  - `conceptualize`：从 prompt/reference 生成结构化记录。
  - `sketch`：从结构化记录生成 SVG/HTML/Three.js 代码。
  - `render`：将可执行画布渲染为 PNG。
  - `generate`：通过 provider 接口可选调用图像生成模型。
  - `review`：执行规则审查和可选 VLM 审查。
  - `run`：端到端编排。
- LangGraph 编排：
  - 使用 `StateGraph` 表达 `conceptualize -> render -> generate -> review`。
  - review 失败且未超过上限时，通过 conditional edge 回到 revision 节点。
  - 图状态必须包含 request、plan、artifact paths、review result、revision count、errors。
- artifact-first 输出：
  - `request.json`
  - `plan.json`
  - `canvas.svg` 或 `canvas.html`
  - `sketch.png`
  - `final.png`
  - `review.json`
  - `trace.jsonl`
- 小型评测 harness，覆盖论文对应任务族：
  - 类 GenEval++ 的复杂组合控制（第一阶段）；
  - 类 LongText-Bench 的长文本渲染（第一阶段）；
  - 类 ImgEdit 的局部编辑（**仅占位/简化**，完整机制见下）；
  - 类 Mind-Bench 的知识和推理型图像生成（**第二阶段**，依赖 search node 与外部 VLM）。

  说明：论文中 ImgEdit 的核心机制是 VLM 分层 + SAM 分割 + 遮挡区域 inpainting，Mind-Bench 依赖 multi-round search。这两者第一阶段**不实现真实机制**，仅在 schema 与图中预留接口；harness 对应任务族标记为占位，不得据此声称覆盖。
- provider 抽象：
  - LLM/VLM agent；
  - 搜索和检索；
  - 图像生成；
  - 图像编辑；
  - 分割和 mask。
- 无私有凭据的确定性 fixture mode。

### 第一阶段不做

- 训练任何模型。
- 声称精确复现论文表格中的数值（即便接入官方 benchmark，闭源模型版本差异仍使精确数值不可保证）。
- 依赖尚未发布的官方代码。
- 强制依赖 Claude-Opus-4.6 或 Gemini-3.1-Flash-Image。
- 在核心 pipeline 稳定前完整接入 GenEval++、LongText-Bench、ImgEdit、Mind-Bench。
- 保证本地纯 mock/open 模型能达到论文展示的 photorealism。论文自身也指出当前真实感强依赖 frontier image generator。

## 功能需求

### FR1：结构化视觉计划

给定用户 prompt，系统必须生成 schema 校验通过的计划，包含：

- 任务类型；
- 画布尺寸；
- 对象；
- 文本块；
- 空间关系；
- 图层；
- 风格提示；
- 生成约束；
- 审查项。

该 schema 必须足够稳定，能做确定性测试；同时要能表达 SVG、HTML 和 Three.js 三类后端需要的信息。

该 schema 必须围绕四个 benchmark 任务族（GenEval++ 组合控制、LongText-Bench 长文本、ImgEdit 局部编辑、Mind-Bench 知识/推理）做需求推导，而非仅围绕第一阶段的 3 个 fixture。schema 必须显式区分两类画布来源（见 ADR 0003）：`structured`（字段经模板编译，第一阶段）与 `code`（free-form 源码经校验后渲染，第二阶段），使同一中心契约能容纳两条路线。

### FR2：可执行画布渲染

系统必须将合法计划编译为一种可执行画布：

- SVG：用于场景组合；
- HTML/CSS：用于长文本、海报、卡片、页面；
- Three.js：用于 3D 物理/几何/视角演示；
- Python（matplotlib）/ Canvas（2D）：用于数值型物理草图（弹簧、压力、浮力、几何关系），论文 §3.2 明确将其与 Three.js 并列——这类任务重点是“关系正确”而非视觉风格，code 充当“物理草稿/符号世界模型”。

每种后端都必须能以固定尺寸渲染为 PNG（Python 后端经 matplotlib 直接出图，无需浏览器；其余经 Playwright）。

### FR3：产物可追踪

每次运行必须创建完整输出目录。无需重新运行 pipeline，审查者也能检查 request、plan、代码画布、sketch、final image、review report 和 trace log。

### FR4：图像生成 provider 接口

图像生成必须通过 provider 接口调用。第一阶段 provider 是 mock generator，用于复制或轻量处理 sketch。外部 provider 后续接入时不能改变 pipeline 主契约。

### FR5：审查与修正

review 模块必须支持：

- 对象数量、必需文本、画布尺寸、产物存在性等确定性检查；
- 可选 VLM 语义审查；
- 结构化失败原因；
- 有上限的 revision loop，由 LangGraph conditional edge 控制，可修改计划或代码后重新渲染。

### FR6：LangGraph 工作流编排

系统必须用 LangGraph 实现主编排图：

- `conceptualize_node`：调用 agent provider 生成 `CanvasPlan`，含意图理解；论文认知层（§3.1-3.2）的另两支柱——搜索与推理——分别由下述 search_node 与计划中的 `reasoning`（`ReasoningStep`）结构化记录承载。
- `search_node`（**已实现，gated**）：当 `task_type == knowledge_grounded` 时调用 search provider 检索事实，并入 `CanvasPlan.knowledge`（每条带可溯源 `source`），对应 Mind-Bench 的 multi-round search。默认 `NullSearchProvider`（no-op，无凭据可跑，真实存在于图中而非仅占位）；外部默认 Tavily（ADR 0004），SearXNG 为开源退路。检索失败为非致命，记录 error artifact 后继续。
- `render_node`：根据 `CanvasPlan.backend` 选择 SVG/HTML/Three.js/Python/Canvas renderer。
- `generate_node`：调用 image generator provider，fixture mode 使用 mock generator。
- `review_node`：调用规则审查和可选 VLM reviewer。
- `revise_node`：根据 review failures 修改 plan 或返回 fixture mode unsupported 信息。
- `route_after_review`：根据 `ReviewResult.passed` 和 `revision_count` 决定结束或修正。

主图节点顺序：`conceptualize → search → render → generate → review → route_after_review`，review 失败且未超上限时经 conditional edge 回到 `revise → render`。

### FR7：评测 harness

benchmark harness 必须能运行本地小型 fixture 集，并报告：

- task success/failure；
- review pass rate；
- render success rate；
- 文本 exact-match 或 OCR-compatible 检查；
- 编辑任务在有源图和目标图时的简单图像相似度指标。

## 非功能需求

- **可复现性:** fixture mode 必须不依赖私有模型凭据。
- **模块化:** providers 和 renderers 必须可替换。
- **可观测性:** trace 必须记录每个 LangGraph node 的输入摘要、输出路径、provider 调用元数据和 route 决策。
- **失败隔离:** 单个后端或 provider 失败时必须生成结构化错误产物，不能只抛异常后丢上下文。
- **安全性:** 模型生成内容应视作数据。渲染必须走受控本地 renderer、带超时，不允许直接执行模型输出的任意 shell 命令。
- **可移植性:** 当前工作区为 `D:\genclaw`，必须支持 Windows。

## 建议技术栈

- Python 3.10+（开发机为 64-bit 3.10.11；最初 spec 写 3.11+，因本机仅有 3.10.11 64-bit 与 3.14 32-bit，为获得 numpy/Pillow/Playwright 的稳定 wheel，下调为 3.10+）。
- `langgraph`：agent workflow 编排、状态图和 revision loop。
- `pydantic`：schema。
- `typer`：CLI。
- `rich`：终端输出。
- Playwright：将 SVG/HTML/Three.js 渲染为 PNG。
- `Pillow` 和 `numpy`：轻量图像检查。
- 外部 provider 包放在 optional extras，不作为 core 必需依赖。
- `pytest`：测试。

**默认 provider 栈（对齐论文，见 ADR 0004）：** 接口可插拔，但默认实现指向论文同款——agent backbone / review VLM = Claude-Opus-4.6，默认 generator = Gemini-3.1-Flash-Image，分割 = SAM3（`facebookresearch/sam3`，已确认发布可用）。开源替代（FLUX.1-Kontext、Qwen-Image、SDXL+ControlNet、SAM2、SearXNG 等）为可选退路，仅在凭据/权重不可得时启用。

## 验收标准

第一阶段完成条件：

- `genclaw run --prompt "..." --mode fixture` 能创建完整 artifact 目录。
- 至少一个 SVG composition fixture 能渲染为 PNG。
- 至少一个 HTML long-text fixture 能渲染为 PNG，且源码保留精确文本。
- 至少一个 Three.js physical/geometric fixture 能渲染为 PNG。
- review report 能输出 pass/fail 和结构化原因。
- 单元测试覆盖 schema 校验、renderer 输出、review 检查、CLI artifact 创建。

第二阶段完成条件：

- 默认 LLM adapter（Claude-Opus-4.6）能从自然语言 prompt 生成 schema-valid 的 `CanvasPlan`。
- 默认 image-generation adapter（Gemini-3.1-Flash-Image）能消费 sketch 并生成 final image。
- benchmark harness 能接入并运行至少一个**官方** benchmark（优先 GenEval++ 或 LongText-Bench），用其 official metric 报告，而非仅本地 mini fixture。
- 本地 mini fixture 套件保留为快速回归（覆盖四类任务族），但不作为对外数值依据。
- 结果导出为 JSON 和 Markdown summary，并区分"官方 benchmark 结果"与"本地 fixture 结果"。

## 风险与缓解

- **官方实现尚未发布。**
  - 缓解：以论文为规格来源，不声称精确复现作者实现和数值。

- **闭源 frontier model API 可能不可用或发生变化。**
  - 缓解：使用 provider interface 和 fixture mode，将 provider 配置单独文档化。

- **模型生成代码可能不安全或不可渲染。**
  - 缓解：第一阶段从 schema-owned templates 编译代码，只允许模型填入经过校验的字段。

- **本地/open generator 的真实感可能不足。**
  - 缓解：结构控制和最终审美质量分开评测。

- **官方 benchmark 数据可能不易获取。**
  - 缓解：先做 paper-aligned mini fixtures，再接官方 benchmark adapter。

## 参考

- 官方 GitHub: https://github.com/yejy53/GenClaw
- arXiv: https://arxiv.org/abs/2605.30248
- 本地论文: `D:\genclaw\GenClaw_Code-Driven_Agentic_Image_Generation.pdf`
- 本地抽取材料：
  - `D:\genclaw\tmp\pdfs\genclaw_full_text.txt`
  - `D:\genclaw\tmp_genclaw_src\sections\3_method.tex`
  - `D:\genclaw\tmp_genclaw_src\sections\4_experiments.tex`

# 复现说明（Reproduction Notes）

本文件说明本项目与官方 GenClaw 的关系、fixture 模式的定位、如何接入外部 provider，以及 benchmark 与机制层面的限制。面向想理解"这个复现到底复现了什么、没复现什么"的读者。

## 与官方 GenClaw 的关系

- **独立复现，非官方实现。** 以论文 arXiv `2605.30248` 为唯一规格来源，从零实现。官方代码与 demo 截至 2026-06-18 尚未发布。
- **不复跑作者代码，不声称精确复现数值。** 即便后续接入官方 benchmark，闭源 backbone（Claude-Opus、Gemini-Flash-Image）的版本漂移也使论文表格数值不可逐位复现。
- **分阶段。** 第一阶段交付的是脚手架——LangGraph 编排 + artifact/trace + 规则审查 + 多后端确定性渲染 + 认知层结构（含 search 节点）。论文的两个核心差异化机制——**code-as-brush**（LLM 直接写 SVG/HTML/Three.js 代码）与**分层编辑**（VLM 分层 + SAM3 分割 + inpainting）——属第二阶段，当前未实现（见下"机制限制"）。

## fixture 模式

fixture 模式是无凭据的确定性冒烟路径：

- agent = `FixtureAgent`：对三个关键字（`three red circles` / `poster` / `mirror`）返回写死的 schema-valid `CanvasPlan`；未知 prompt 抛 `FixtureAgentError`。它是**关键字匹配，不是意图理解**——真正的意图识别在 external 模式的 LLM agent。
- generator = `MockImageGenerator`：把 sketch 复制为 final，并在 metadata 标注"fixture 模式不提供 photorealism"。
- reviewer = `RuleReviewer`：确定性规则检查（对象数量、必需文本、backend、产物存在、图像尺寸）。
- search = `NullSearchProvider`：no-op，search 节点真实存在并运行、记 trace，但不检索。

用途：验证编排/产物/审查/渲染管道在无任何外部依赖时端到端成立，便于 CI 与回归。它**不复现论文机制**，也不产出真实感图像。

## 接入外部 provider

external 模式把各层换成对齐论文的真实 provider（默认栈见 ADR 0004）：

- **Agent（意图识别）**：`ExternalLLMAgent`，默认 Claude-Opus-4.6。关键是 prompt→`CanvasPlan` 的可靠性机制：用 structured-output 约束输出，JSON/schema 校验失败时把 Pydantic 错误回灌重试（上限 `max_parse_retries`，默认 2），仍失败抛 `PlanParseError` 带尝试历史，由调用方写结构化 error artifact——不静默吞、不返回半成品。
- **图像生成**：`GeminiImageGenerator`，默认 Gemini-3.1-Flash-Image，以 sketch 作结构条件。
- **VLM 审查**：`VLMReviewer`，默认 Claude-Opus，返回结构化 pass/fail + evidence；verdict 非法时 fail closed。
- **搜索**：`TavilySearchProvider`（多轮），开源退路 SearXNG。

所有 external adapter：SDK 懒加载、凭据缺失时抛 `ProviderNotConfiguredError`（带环境变量名与配置指引）。配置见 README "接入外部 provider"。

环境变量：`ANTHROPIC_API_KEY`、`GOOGLE_API_KEY`、`TAVILY_API_KEY`；可选模型覆盖 `GENCLAW_AGENT_MODEL` / `GENCLAW_REVIEWER_MODEL` / `GENCLAW_GENERATOR_MODEL`。

## 机制限制（重要，诚实声明）

下列论文机制当前**未真正实现**，不得据本项目声称已复现：

1. **分层编辑 + SAM3 + inpainting（ImgEdit）。** 论文最硬的定量主张是编辑任务在非编辑区的 PSNR/SSIM 优势，机制为"VLM 理解 → 分层 → SAM3 分割 → inpainting 补遮挡 → JSONL 管理 layer/z-order"。当前仅 schema 有 `EditOp` 占位；分割 provider、editing pipeline、非编辑区一致性指标均缺失。**本复现尚不能支撑该主张。**
2. **code-as-brush（free-form 代码生成）。** 论文核心是让 LLM 直接编写可执行代码。当前所有画布是模板从校验字段编译（`source="structured"`），不执行模型生成的任意代码；`source="code"` 字段已在 schema 预留，但编译/沙箱未实现（ADR 0003）。
3. **推理自动填充。** `ReasoningStep` 结构已建（承载"先算数值/物理量再转视觉约束"），但没有自动推理 provider 去填充它，需 agent/外部模型产出。
4. **真实搜索实跑。** search 节点与 Tavily adapter 已写，但默认 NullSearchProvider 不检索；多轮检索 + 候选过滤的真实行为需配凭据验证。
5. **external 真实凭据实跑。** external 模式只做了契约与可靠性机制的单测，未用真实 API key 端到端跑过。

## Benchmark 限制

- 第一阶段不接官方 benchmark。用户已决定先复刻核心 pipeline，benchmark（mini fixture 与官方 GenEval++/LongText/ImgEdit/Mind-Bench）暂缓。
- 官方 benchmark 接入方案在 ADR 0004 与 plan 任务 13.5 在案：复用各 benchmark 官方数据集与 official metric，ImgEdit 一致性走 CoCoEdit 非编辑区 mask PSNR/SSIM，不自造指标。
- mini fixture（plan 任务 13）仅作开发期回归冒烟，不充当复现主体。

## 链接

- 论文：arXiv `2605.30248`
- 官方 GitHub：见论文（代码/demo 准备中）
- 本地 spec：`docs/specs/2026-06-18-genclaw-reproduction-spec.md`
- 本地 plan：`docs/plans/2026-06-18-genclaw-reproduction-plan.md`
- ADR：`docs/adr/0001`–`0004`

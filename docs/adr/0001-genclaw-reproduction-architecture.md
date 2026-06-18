# ADR 0001：将 GenClaw 复现为 Artifact-First、Provider-Pluggable Pipeline

**日期:** 2026-06-18

**状态:** 已接受，作为初始复现架构决策。

> **修订注记（2026-06-18，见 ADR 0004）：** 本 ADR 的 "provider-pluggable / vendor-neutral" 仍然成立，但默认取向已调整为**默认实现对齐论文同款栈**(Claude-Opus-4.6 backbone、Gemini-3.1-Flash-Image generator、SAM3 分割、官方 benchmark)，开源替代与 fixture/mock 降级为退路与无凭据冒烟。可插拔接口不变，变的是默认指向。

## 背景

GenClaw 论文提出了一种 code-driven agentic image generation 工作流：

1. 使用 LLM/VLM、搜索和推理完成 conceptualize；
2. 使用 SVG、HTML/CSS、Python、Canvas、Three.js 等可执行视觉代码完成 sketch；
3. 使用图像生成或编辑模型完成 color/refine；
4. 使用 review 模块审查并迭代。

当前官方仓库没有可运行代码。论文中的强结果还依赖 frontier proprietary models。一个有价值的复现需要把论文的核心机制和具体模型厂商解耦。

## 决策

将 GenClaw 复现为 artifact-first 的本地 pipeline，使用 LangGraph 作为 agent workflow 编排层，并使用严格接口：

- **结构化计划作为中心契约。**
  - 自然语言先转换为 schema-validated `CanvasPlan`。
  - renderer 和 reviewer 都消费同一个 plan。

- **模板控制的可执行画布。**
  - SVG、HTML/CSS、Three.js 从校验后的字段生成。
  - 模型输出被当作数据，不直接当作任意可执行代码。

- **模型 provider 可插拔。**
  - LLM/VLM agent、search、image generation、image editing、segmentation、VLM review 都是 adapters。
  - fixture provider 和 mock provider 是一等公民，保证无凭据也能跑通。

- **LangGraph 编排主流程。**
  - 使用 `StateGraph` 表达 conceptualize、render、generate、review、revise 节点。
  - 使用 conditional edge 表达 review 后的结束或修正分支。
  - `Pipeline.run` 只负责构造初始 state、调用 compiled graph、保存最终 artifacts。

- **产物可追踪。**
  - 每次 run 都写出 request、plan、canvas code、sketch image、final image、review report、trace log。
  - 调试和评测依赖这些显式产物，而不是隐藏状态。

- **审查分层。**
  - 确定性规则检查数量、文本、backend、图像尺寸、产物存在性。
  - VLM review 后续用于语义一致性和审美质量判断。

## 备选方案

### 方案 1：直接做 Prompt-Rewriting Agent

系统可以实现一个反复改写自然语言 prompt、调用图像模型的 agent。

**不采用原因:** 这会偏离论文核心贡献。GenClaw 的关键不是更长 prompt 或更多 agent turns，而是把 code 作为可控中间画布。

### 方案 2：让 LLM 直接写任意 SVG/HTML/Three.js

系统可以让 LLM 输出完整代码，然后直接执行或渲染。

**不采用原因:** 第一阶段这样做会让测试脆弱，并引入不必要的安全风险。复现应先用 schema-owned templates 证明架构可行，后续再考虑受约束的 free-form code generation backend。

### 方案 3：硬绑定单一闭源模型栈

系统可以假设论文中提到的具体模型栈。

**不采用原因:** API 可用性、模型名称和访问权限都可能变化；同时没有私有凭据时无法本地测试。Provider interface 能保持复现代码 vendor-neutral。

### 方案 4：一开始完整复现所有 Benchmark

系统可以从 GenEval++、LongText-Bench、ImgEdit、Mind-Bench 的完整接入开始。

**不采用原因:** 核心 pipeline 稳定前，benchmark 规模不是瓶颈。mini fixture suite 更适合快速发现架构回归，也不依赖外部数据集可用性。

## 影响

### 正向影响

- 无模型凭据也能本地测试 pipeline。
- LangGraph 明确表达状态、节点和 revision loop，贴合论文的 agentic workflow。
- 外部模型接入时不需要重写 renderer 或 review 逻辑。
- 中间产物让失败可检查、可定位。
- 实现直接覆盖论文的 code-as-canvas 机制。
- 模板生成代码比直接执行模型代码更安全。

### 负向影响

- fixture mode 不会复现 photorealistic quality。
- 在 provider 和 benchmark 数据未对齐论文前，不能声称精确复现论文数值。
- 模板控制的画布灵活性弱于无约束的模型写代码。
- 需要额外维护 provider interface、artifact schema 和 LangGraph state schema。

## 后续 ADR

后续需要单独决策：

- 首先支持哪些外部 LLM/VLM providers；
- 非 fixture 运行使用哪个 image-generation/editing provider；
- 是否允许受约束的 free-form model-generated code；
- 如果启用不可信代码生成，如何 sandbox browser rendering；
- 如何把官方 benchmark 映射到本地 evaluation harness。

## 参考

- GenClaw 论文: https://arxiv.org/abs/2605.30248
- 官方仓库: https://github.com/yejy53/GenClaw
- 本地 Spec: `D:\genclaw\docs\specs\2026-06-18-genclaw-reproduction-spec.md`
- 本地 Plan: `D:\genclaw\docs\plans\2026-06-18-genclaw-reproduction-plan.md`

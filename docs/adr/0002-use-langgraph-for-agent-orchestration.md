# ADR 0002：使用 LangGraph 作为 GenClaw 复现的 Agent 编排框架

**日期:** 2026-06-18

**状态:** 已接受。

## 背景

GenClaw 不是单次文生图调用，而是一个 agentic workflow：

1. 理解和结构化用户意图；
2. 生成可执行视觉代码；
3. 渲染中间 sketch；
4. 调用图像生成或编辑模型；
5. 审查结果；
6. 必要时回到计划或画布修正。

这个流程天然需要状态、分支、循环、工具调用和 trace。直接用顺序函数可以跑通第一版，但后续接入外部 LLM/VLM、VLM review、revision loop 和 benchmark 时会变得难维护。

## 决策

使用 LangGraph 作为主编排框架。

主图为：

```text
START
  -> conceptualize_node
  -> render_node
  -> generate_node
  -> review_node
  -> route_after_review
       -> END                 if passed
       -> revise_node          if failed and revision_count < max_revisions
       -> END                 if failed and max_revisions reached
  -> render_node               after revise
```

核心 state 为 `GenClawState`，至少包含：

- request metadata；
- prompt 和 task_type；
- `CanvasPlan`；
- artifact paths；
- rendered canvas metadata；
- generation result；
- review result；
- revision count；
- errors；
- trace events。

## 采用原因

- **状态图比顺序脚本更贴合论文。** GenClaw 的 review/revise 是图结构，不是一次性线性 pipeline。
- **可测试性更好。** 每个 node 和 route function 都可以单测。
- **便于接入外部模型。** LLM agent、image generator、VLM reviewer 都可以封装为 node 内部 provider。
- **便于观测。** 每个 node 执行后写 trace，问题定位更直接。
- **便于扩展。** 后续可以加入 search node、segmentation node、human review node、benchmark batch graph。

## 备选方案

### 方案 1：纯 Python 顺序 Pipeline

**不采用原因:** 第一版简单，但 revision loop、条件分支、错误恢复和 trace 会逐渐散落在 `pipeline.py` 中。

### 方案 2：CrewAI

**不采用原因:** CrewAI 更偏角色型多 agent 协作。GenClaw 复现更需要可控状态机和确定性 artifacts，而不是多个角色对话。

### 方案 3：OpenAI Agents SDK

**不采用原因:** 如果后续强绑定 OpenAI 模型，它很合适。但当前复现需要 vendor-neutral，且核心是状态图和 artifact pipeline。

### 方案 4：AutoGen / Microsoft Agent Framework

**不采用原因:** 适合更复杂的多 agent 对话与企业集成，但对当前目标来说引入面更大。LangGraph 的 graph-first 模型更直接。

## 影响

### 正向影响

- 主流程、状态和 revision loop 显式化。
- 后续接入 search、VLM review、human-in-the-loop 更自然。
- 测试可以覆盖 node、route 和端到端 graph。
- 与 GenClaw 论文的 agentic generation 叙述更一致。

### 负向影响

- 增加 `langgraph` 依赖。
- 初始实现需要多维护一层 `graph/state.py`、`graph/nodes.py`、`graph/routes.py`、`graph/builder.py`。
- 执行者需要理解 LangGraph 的 state update 语义。

## 实现约束

- LangGraph 只负责编排，不承担 domain logic。
- schema 校验、renderer、generator、reviewer 仍保持独立模块。
- node 内不能直接写复杂业务逻辑；复杂逻辑下沉到 provider/renderer/reviewer。
- route function 必须纯函数化，便于单测。
- 所有 node 执行结果必须写 trace。

## 参考

- LangGraph 文档: https://docs.langchain.com/oss/python/langgraph/overview
- 本地 Spec: `D:\genclaw\docs\specs\2026-06-18-genclaw-reproduction-spec.md`
- 本地 Plan: `D:\genclaw\docs\plans\2026-06-18-genclaw-reproduction-plan.md`
- ADR 0001: `D:\genclaw\docs\adr\0001-genclaw-reproduction-architecture.md`

# Agent 问题清单与改进计划

> 日期：2026-07-03  
> 基于代码审查：`genclaw/agent/external.py`、`genclaw/agent/fixture.py`、`genclaw/agent/prompts.py`、`genclaw/pipeline.py`、`genclaw/graph/nodes.py`

---

## 问题 1：intent_classify 是一次多余的 LLM 调用（根因：意图识别慢）

**位置**：[agent/external.py:170-257](../genclaw/agent/external.py#L170-L257)，[graph/nodes.py:202-255](../genclaw/graph/nodes.py#L202-L255)

**现状**：每次 `pipeline.run()` 先触发 `intent_node`（LLM 调用）→ 再触发 `conceptualize`（LLM 调用），两次完整网络往返。intent 的返回只有3个字段（`task_type`、`needs_search`、`reason`），大约50 token，但 `_complete` 硬编码 `max_tokens=4096`（Anthropic）/ `8192`（GLM），整条 Opus 级模型都被拉起来。

**问题**：
- 两次 LLM 调用 = 两倍延迟，其中第一次只产出 50 token 的 JSON
- `conceptualize` 里已经推断 `task_type`；intent 信息在逻辑上可以内联
- `_complete` 没有 `max_tokens` 参数，intent 调用无法缩减 token 预算

**改法（推荐：合并）**：把 `needs_search` 加到 `CanvasPlan` schema，在 SYSTEM_PROMPT 加一句让模型顺带输出它，删掉 `intent_node` 和 `intent_classify`。一次调用，零额外延迟。

**改法（备选：保留但提速）**：给 `_complete` 加 `max_tokens` 参数，intent 调用传 `max_tokens=128`；并为 intent 单独配一个轻量模型（如 `claude-haiku-4-5-20251001`）而不跟着 `agent_model` 走。

---

## 问题 2：conceptualize 里残留旧启发式，与 intent_node 逻辑重叠

**位置**：[agent/external.py:309-313](../genclaw/agent/external.py#L309-L313)

**现状**：
```python
if _should_knowledge_ground(prompt):
    data.setdefault("task_type", TaskType.knowledge_grounded.value)
```
这行在 `conceptualize()` 里仍然存在。但 `intent_node` 已经通过 LLM 判断 `task_type`，并把它写进 `state.task_type`；`conceptualize` 调用时 `task_type` 参数已经是 intent 判断的结果，这里的关键词启发式是旧逻辑的残留，两套路径并存。

**问题**：
- 若 intent LLM 判断为 `composition`，但 prompt 里含有 `"2026"` 等关键词，这里会把 task_type 静默改成 `knowledge_grounded`，与 intent 判断冲突
- `_should_knowledge_ground` 是降级 fallback，不应在主路径里运行

**改法**：删掉 conceptualize 里的 `if _should_knowledge_ground(...)` 分支（第309-313行）。intent 已经负责这件事了。

---

## 问题 3：repair loop 回喂方式不是真正的对话轮次

**位置**：[agent/external.py:283-295](../genclaw/agent/external.py#L283-L295)

**现状**：
```python
repair = REPAIR_PROMPT.format(errors=last_error, previous=attempts[-1])
raw = self._complete(system, user + "\n\n" + repair)
```
把修复指令追加到 user 消息末尾，把上一次的原始输出也塞进去，作为单条超长 user 消息发给模型。注释写的是"同一会话上下文里自我修正"，但实际上模型看不到自己作为 assistant 的上一次输出——它只是在一条很长的 user 消息里看到了自己上次说的话的文本拷贝。

**问题**：
- 对话模型的 assistant 角色感知缺失，修复效果比真正的多轮对话差
- 如果 `attempts[-1]` 很长（模型产出大量 token），user 消息会变得非常大
- 与注释的描述不符，造成误解

**改法**：把 `_complete` 改成支持可选 `history: list[dict]` 参数，repair 轮时传入 `[{"role": "user", "content": user}, {"role": "assistant", "content": attempts[-1]}, {"role": "user", "content": repair_msg}]` 的真实多轮对话。Anthropic 和 OpenAI SDK 都直接支持。

---

## 问题 4：SDK client 每次调用重新构造

**位置**：[agent/external.py:397-418](../genclaw/agent/external.py#L397-L418)

**现状**：`_complete_anthropic` 每次调用都执行 `anthropic.Anthropic(**kwargs)` 新建 client；`_complete_openai_compatible` 同理每次都 `OpenAI(**kwargs)` 新建。一次带 repair retry 的 conceptualize（最多3次调用）加上 intent（1次），会建4个 client 实例，每个都要初始化 HTTP 连接池。

**问题**：在 bench 批量跑多个 prompt 时，连接池无法复用，每次 run 都冷启动

**改法**：把 client 缓存在 `ExternalLLMAgent` 实例上，懒初始化一次：
```python
@property
def _anthropic_client(self):
    if not hasattr(self, "_ac"):
        self._ac = anthropic.Anthropic(**self.config.anthropic_kwargs(...))
    return self._ac
```

---

## 问题 5：`responses.create()` 的 AttributeError 被 silent fallback 吞掉

**位置**：[agent/external.py:356-367](../genclaw/agent/external.py#L356-L367)

**现状**：
```python
try:
    response = client.responses.create(...)
    return response.output_text or ""
except AttributeError:
    pass  # 回退到标准接口
```
`AttributeError` 被静默吞掉，没有任何日志或 warning。

**问题**：SDK 版本升级、接口变更、或者 `output_text` 为 None 的边界情况，全部无声失败，排查极困难。

**改法**：加一行 warning log 或 trace，或者直接废弃这个路径——先检查 `hasattr(client, "responses")` 再决定走哪条路，失败时至少打一条 debug 信息。

---

## 问题 6：`_complete_openai_compatible` 的异常处理过于宽泛

**位置**：[agent/external.py:387-395](../genclaw/agent/external.py#L387-L395)

**现状**：
```python
try:
    message = client.chat.completions.create(..., response_format={"type": "json_object"})
except (TypeError, Exception):
    message = client.chat.completions.create(**request_kwargs)
```
`except (TypeError, Exception)` 实际上等于 `except Exception`，会把网络错误、认证错误、速率限制都吞掉，然后不带 `response_format` 重试。认证失败重试还是会失败，但错误信息已经被消费掉了。

**改法**：只捕获 `TypeError`（这是唯一预期的"provider 不支持该参数"场景），让其他异常直接向上传播。

---

## 问题 7：`agent_model` 是单一配置，intent 和 conceptualize 无法分别配置

**位置**：[config.py:48](../genclaw/config.py#L48)，[agent/external.py:325-338](../genclaw/agent/external.py#L325-L338)

**现状**：`ProviderConfig.agent_model` 是一个字段，intent classify 和 conceptualize 都走它。论文对齐栈用 Opus，但 intent 是3字段分类任务，Haiku 够了。

**问题**：没法在不改代码的情况下把 intent 跑在轻量模型上

**改法（仅在保留 intent 独立调用时需要）**：在 `ProviderConfig` 加 `intent_model: str = DEFAULT_INTENT_MODEL`（默认 Haiku），在 `intent_classify` 里用 `self.config.intent_model` 而不是 `self.config.agent_model`。

---

## 问题 8：`needs_search` 不在 CanvasPlan，intent 是游离的 artifact

**位置**：[schemas.py:174-185](../genclaw/schemas.py#L174-L185)，[graph/nodes.py:229-244](../genclaw/graph/nodes.py#L229-L244)

**现状**：`intent.json` 和 `plan.json` 是两份独立 artifact，`needs_search` 只存在 `state.intent` 和 `intent.json` 里，不在 plan 里。审查者要追溯"为什么搜了/没搜"需要跨两份文件。

**问题**：如果合并 intent 到 conceptualize（问题1的推荐改法），intent.json 就消失了，但 plan.json 里没有 `needs_search` 字段，搜索决策无法从 plan 追溯。

**改法**：在 `CanvasPlan` 加 `needs_search: bool = False` 字段（可选，默认 False），让 conceptualize 产出时顺带输出它。这样 plan artifact 自包含，intent_node 可以省去。

---

## 优先级排序

| # | 问题 | 影响 | 改动量 | 优先 |
|---|------|------|--------|------|
| 1 | intent_classify 独立调用（慢） | 每次 run +1 LLM 往返 | 中（合并路径） | P0 |
| 2 | conceptualize 里旧启发式残留 | 逻辑冲突 | 小（删3行） | P0 |
| 6 | except Exception 过宽 | 掩盖真实错误 | 小（改捕获类型） | P1 |
| 3 | repair loop 非真对话轮次 | 修复质量差 | 中（改接口） | P1 |
| 4 | SDK client 每次新建 | batch 场景连接浪费 | 小（加缓存） | P2 |
| 5 | AttributeError silent fallback | 排查困难 | 小（加日志） | P2 |
| 7 | agent_model 无法分 intent/conceptualize | 成本/速度 | 小（加配置字段） | P2，仅保留 intent 时 |
| 8 | needs_search 不在 plan | artifact 追溯不完整 | 小（加字段） | P2，随 P0 一起做 |

---

## 最小可行改动（P0，一次提交）

1. 删除 [agent/external.py:309-313](../genclaw/agent/external.py#L309-L313) 的旧启发式（问题2）
2. 在 `CanvasPlan` 加 `needs_search: bool = False`（问题8 前置）
3. 把 `needs_search` 加进 SYSTEM_PROMPT / CODE_SYSTEM_PROMPT 的输出要求
4. 在 `conceptualize` 里从返回的 JSON 读取 `needs_search`，写进 plan 和 state
5. 删掉 `intent_node`、`intent_classify` 抽象方法、fixture 的关键词实现（问题1）
6. 从 `_run_direct` 和 `_run_langgraph` 里移除 `intent_node` 调用

这六步使每次 run 减少一次 LLM 调用，消除逻辑冲突，保留完整的搜索决策可追溯性。

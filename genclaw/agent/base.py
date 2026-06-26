"""Agent provider contract.

The cognitive structuring layer (paper §3.1) turns a natural-language prompt
into a schema-validated :class:`~genclaw.schemas.CanvasPlan`. ``AgentProvider``
is the pluggable boundary: the fixture provider (task 4) is deterministic and
credential-free; external LLM providers (task 14, default Claude-Opus per
ADR 0004) implement the same contract behind structured-output validation.
"""

from __future__ import annotations

import abc
from typing import Optional

from genclaw.schemas import CanvasPlan, Intent, TaskType


# 中文说明:
# 这是「agent(认知结构化层)」的统一接口(抽象基类)。所有把自然语言 prompt
# 变成结构化 CanvasPlan 的实现都继承它——fixture(确定性、无需凭据)和
# external(真正调用 LLM)共用同一个契约。
# 想新增一种 agent(比如换别的模型/别的解析策略),只要新建一个类继承
# AgentProvider 并实现 conceptualize 即可,pipeline 其余部分无需改动。
class AgentProvider(abc.ABC):
    """把 prompt 转成校验过的 CanvasPlan。"""

    @abc.abstractmethod
    def conceptualize(
        self,
        prompt: str,
        task_type: Optional[TaskType] = None,
        request_id: Optional[str] = None,
        knowledge: Optional[list] = None,
    ) -> CanvasPlan:
        """把 ``prompt`` 结构化成 :class:`CanvasPlan`。

        ``knowledge`` 是 pre-search 阶段已检索到的 :class:`~genclaw.schemas.KnowledgeRef`
        列表,实现应把这些事实注入 prompt 让 LLM 写代码时能参考。
        """
        raise NotImplementedError

    @abc.abstractmethod
    def intent_classify(
        self,
        prompt: str,
        requested_task_type: Optional[TaskType] = None,
    ) -> Intent:
        """在 search 之前用 LLM 语义判断:这个 prompt 要不要搜索?任务族是什么?

        论文 §3.2:智能体"首先执行意图理解",遇到长尾实体/实时事件/
        地理/文化符号等"模型内部知识不足以支持准确生成"的任务时,
        才调用搜索工具——这是 *LLM 主动决策*,不是正则启发式。

        实现方式:
          * external (LLM agent):走一次轻量 LLM 调用,schema 是 Intent
            (task_type + needs_search + reason),token 预算极小。
          * fixture:用关键词查表,无凭据也能跑(降级到原 _should_knowledge_ground 启发式)。
        """
        raise NotImplementedError

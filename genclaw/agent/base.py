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

from genclaw.schemas import CanvasPlan, TaskType


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
    ) -> CanvasPlan:
        """把 ``prompt`` 结构化成 :class:`CanvasPlan`。

        输入:prompt(用户自然语言需求)、task_type(可选,任务族;为 None
        时由实现自行推断)、request_id(可选,run 标识,写进 artifact)。
        输出:必须是一个通过 schema 校验的 CanvasPlan。
        """
        raise NotImplementedError

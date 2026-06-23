"""``GenClawState`` -- 贯穿 LangGraph workflow 的状态对象。

这是一个普通 Pydantic 模型,不带 langgraph 依赖,这样 graph 契约在没装
编排栈的环境下也能被测试(懒加载策略)。主图::

    conceptualize -> render -> generate -> review -> route_after_review
                                                       |-> revise -> render (loop)

每个领域的载荷(plan / rendered canvas / generation result / review result)
都是带类型的 Pydantic 模型,方便 state 序列化进 trace / inspection。
``artifacts`` 句柄是 IO 工具(拥有路径的 dataclass),从序列化里排除;
``run_dir`` 单独保留到 dump 里以供审计。
"""

# 中文补充说明：
# state 字段分组:
#   - request:request_id / prompt / task_type(任务族,agent 可覆盖)
#   - pipeline payloads:四个 Optional,每个节点负责填一项
#   - control:revision_count(已修订次数) + max_revisions(预算)
#   - bookkeeping:errors + trace_events + run_dir + artifacts
# ``artifacts`` 用 Field(exclude=True)不让它进 model_dump,但作为
# arbitrary_types_allowed 还是允许这个 dataclass 存在,方便节点直接调
# 它的 write_json / write_error 方法。

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from genclaw.artifacts import RunArtifacts
from genclaw.generators.base import GenerationResult
from genclaw.renderers.base import RenderedCanvas
from genclaw.schemas import CanvasPlan, KnowledgeRef, ReviewResult, TaskType


class GenClawState(BaseModel):
    """单次 run 跨节点传递的可变状态。"""

    # ``artifacts`` 是 dataclass 不是 Pydantic 模型:放行它,但从 dump 里
    # 排除(因为它由 run_dir 重建,不应当冗余存两份)。
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # --- request ---------------------------------------------------------------
    request_id: str
    prompt: str
    task_type: Optional[TaskType] = None

    # --- pipeline payloads -----------------------------------------------------
    # 每个节点只负责填自己的那一项;其它节点只读
    plan: Optional[CanvasPlan] = None
    rendered_canvas: Optional[RenderedCanvas] = None
    generation_result: Optional[GenerationResult] = None
    review_result: Optional[ReviewResult] = None

    # pre-conceptualize 搜索结果;conceptualize 节点会把它合进 plan.knowledge
    knowledge: list[KnowledgeRef] = Field(default_factory=list)

    # --- control ---------------------------------------------------------------
    # revision_count:已经触发过几次 revise;max_revisions:路由函数看这个预算
    revision_count: int = 0
    max_revisions: int = 1

    # --- bookkeeping -----------------------------------------------------------
    errors: list[str] = Field(default_factory=list)
    trace_events: list[dict] = Field(default_factory=list)

    run_dir: Optional[Path] = None
    artifacts: Optional[RunArtifacts] = Field(default=None, exclude=True)

    @classmethod
    def from_prompt(
        cls,
        request_id: str,
        prompt: str,
        task_type: Optional[TaskType] = None,
        max_revisions: int = 1,
    ) -> "GenClawState":
        """从一次请求构造初始 state。"""
        return cls(
            request_id=request_id,
            prompt=prompt,
            task_type=task_type,
            max_revisions=max_revisions,
        )

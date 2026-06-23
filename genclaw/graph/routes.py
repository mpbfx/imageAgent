"""图的路由函数(plan task 11)。

路由函数都是纯函数(无 IO、不调 provider),遵循「LangGraph routing 不
带业务逻辑」的约束。``route_after_review`` 决定 review 之后是 finish
还是回 ``revise`` -> ``render`` 循环。
"""

# 中文补充说明：
# 规则就三条:
#   - review 没结果(上游挂) -> finish,不拿空 review 去空转
#   - review 通过 -> finish
#   - 没通过但还有预算 -> revise
#   - 没通过又没预算 -> finish(留下失败的 review,让上层决定)

from __future__ import annotations

from genclaw.graph.state import GenClawState

# 边标签:直接路径和 LangGraph builder 共用同一组字符串
REVISE = "revise"
FINISH = "finish"


def route_after_review(state: GenClawState) -> str:
    """review 之后决定下一条边。

    * review 通过                          -> finish
    * 没 review 结果(上游挂了)             -> finish(不要在空 review 上死循环)
    * 没通过且还在 revision 预算内         -> revise
    * 没通过且预算用完                     -> finish(保留 failed review 给上层看)
    """
    result = state.review_result
    if result is None:
        return FINISH
    if result.passed:
        return FINISH
    if state.revision_count < state.max_revisions:
        return REVISE
    return FINISH

"""LangGraph ``StateGraph`` 构造器(plan task 11)。

把节点函数(:mod:`nodes`)和纯路由函数(:mod:`routes`)拼成一个编译好的
LangGraph workflow::

    conceptualize -> search -> render -> generate -> review -> route_after_review
                                                                |-> revise -> render (loop)

注:实际边顺序是 ``search -> conceptualize -> render ...``(search 前置,
先检索知识再让 agent 带着事实写代码,见 :func:`build_graph`)。

``search`` 节点给知识类任务先做检索(paper §3.1-3.2),内部 gate 起来,
对非知识类任务是 no-op。

``langgraph`` 在 :func:`build_graph` 里懒加载——这样本模块、还有 fallback
到「直接顺序执行」的 pipeline 都能在没装 langgraph 的环境下 import
(phase-1 策略)。LangGraph 在这里只负责编排,所有节点函数和直接路径
用的是同一份可调用对象。
"""

# 中文补充说明:
# Builder 本身几乎全是声明式:声明节点、声明入口、声明边、声明条件边。
# 关键设计点:
#   1) 入口是 conceptualize(把自然语言变结构化 plan)
#   2) review 之后走 route_after_review 二选一:finish 或 revise -> render
#      形成「自我修订」循环(在 fixture 模式下 revise 是显式 no-op,见 nodes.py)
#   3) 编译返回的是可调用对象,跟普通函数一样被 Pipeline 调用——pipeline
#      本身不在意底下是 LangGraph 还是直接顺序。

from __future__ import annotations

from typing import Any

from genclaw.graph.nodes import GraphNodes
from genclaw.graph.routes import FINISH, REVISE, route_after_review


def build_graph(nodes: GraphNodes) -> Any:
    """用 ``nodes`` 构造并编译 LangGraph workflow。

    若未安装 langgraph 则抛 ImportError,并提示用户安装或使用
    ``Pipeline(use_langgraph=False)``。
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:  # pragma: no cover - 仅在无 langgraph 时执行
        raise ImportError(
            "langgraph is not installed; install it or use Pipeline(use_langgraph=False)"
        ) from exc

    from genclaw.graph.state import GenClawState

    graph = StateGraph(GenClawState)
    graph.add_node("intent", nodes.intent_node)
    graph.add_node("conceptualize", nodes.conceptualize)
    graph.add_node("search", nodes.search_node)
    graph.add_node("render", nodes.render)
    graph.add_node("generate", nodes.generate)
    graph.add_node("review", nodes.review)
    graph.add_node("revise", nodes.revise)

    # 入口改成 intent:论文 §3.2 "智能体首先执行意图理解",由 LLM 决定
    # 任务族 + 要不要搜,再决定后续走向(intent -> search -> conceptualize)。
    graph.set_entry_point("intent")
    # 主干: intent -> search -> conceptualize -> render -> generate -> review
    graph.add_edge("intent", "search")
    # search 前置:先检索知识,conceptualize 带着事实写代码(论文 §3.1-3.2)
    graph.add_edge("search", "conceptualize")
    graph.add_edge("conceptualize", "render")
    graph.add_edge("render", "generate")
    graph.add_edge("generate", "review")
    # 条件边: review 之后由 route_after_review 决定下一步
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {REVISE: "revise", FINISH: END},
    )
    # revise 完成后回到 render,实现「修订后重画」循环
    graph.add_edge("revise", "render")
    return graph.compile()

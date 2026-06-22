"""LangGraph ``StateGraph`` builder (plan task 11).

Wires the node functions (``nodes.py``) and the pure route function
(``routes.py``) into a compiled LangGraph workflow::

    conceptualize -> search -> render -> generate -> review -> route_after_review
                                                                |-> revise -> render (loop)

The ``search`` node grounds knowledge-bench tasks before sketching (paper
§3.1-3.2); it is gated internally and is a no-op for non-knowledge tasks.

``langgraph`` is imported lazily inside :func:`build_graph` so this module --
and the pipeline that falls back to direct sequencing -- imports without the
orchestration stack installed (phase-1 strategy). LangGraph owns *only*
orchestration here; every node is the same callable the direct path uses.
"""

from __future__ import annotations

from typing import Any

from genclaw.graph.nodes import GraphNodes
from genclaw.graph.routes import FINISH, REVISE, route_after_review


def build_graph(nodes: GraphNodes) -> Any:
    """Build and compile the LangGraph workflow from ``nodes``.

    Raises ``ImportError`` (with guidance) if langgraph is not installed.
    """
    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:  # pragma: no cover - exercised only without langgraph
        raise ImportError(
            "langgraph is not installed; install it or use Pipeline(use_langgraph=False)"
        ) from exc

    from genclaw.graph.state import GenClawState

    graph = StateGraph(GenClawState)
    graph.add_node("conceptualize", nodes.conceptualize)
    graph.add_node("search", nodes.search_node)
    graph.add_node("render", nodes.render)
    graph.add_node("generate", nodes.generate)
    graph.add_node("review", nodes.review)
    graph.add_node("revise", nodes.revise)

    graph.set_entry_point("conceptualize")
    graph.add_edge("conceptualize", "search")
    graph.add_edge("search", "render")
    graph.add_edge("render", "generate")
    graph.add_edge("generate", "review")
    graph.add_conditional_edges(
        "review",
        route_after_review,
        {REVISE: "revise", FINISH: END},
    )
    graph.add_edge("revise", "render")
    return graph.compile()

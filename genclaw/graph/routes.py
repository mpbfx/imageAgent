"""Routing functions for the graph (plan task 11).

Route functions are pure (no IO, no provider calls) per the project constraint
that LangGraph routing carries no domain logic. ``route_after_review`` decides
whether to finish or loop back through ``revise`` -> ``render``.
"""

from __future__ import annotations

from genclaw.graph.state import GenClawState

# Edge labels, shared by the direct pipeline and the LangGraph builder.
REVISE = "revise"
FINISH = "finish"


def route_after_review(state: GenClawState) -> str:
    """Return the next edge after review.

    * Review passed                          -> finish.
    * No review result (an upstream error)   -> finish (don't loop on failure).
    * Failed but under the revision budget    -> revise.
    * Failed and at the budget                -> finish, keeping the failed review.
    """
    result = state.review_result
    if result is None:
        return FINISH
    if result.passed:
        return FINISH
    if state.revision_count < state.max_revisions:
        return REVISE
    return FINISH

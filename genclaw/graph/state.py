"""``GenClawState`` -- the state threaded through the LangGraph workflow.

This is a plain Pydantic model with no langgraph dependency, so the graph
contract is testable without the orchestration stack (lazy-import strategy).
The main graph is::

    conceptualize -> render -> generate -> review -> route_after_review
                                                       |-> revise -> render (loop)

Each domain payload (plan, rendered canvas, generation result, review result)
is a typed Pydantic model so the state serializes for trace/inspection. The
``artifacts`` handle is IO machinery (a dataclass owning paths), so it is
excluded from serialization; ``run_dir`` is recorded separately for the record.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from genclaw.artifacts import RunArtifacts
from genclaw.generators.base import GenerationResult
from genclaw.renderers.base import RenderedCanvas
from genclaw.schemas import CanvasPlan, ReviewResult, TaskType


class GenClawState(BaseModel):
    """Mutable state carried across graph nodes for one run."""

    # ``artifacts`` is a dataclass, not a Pydantic model; allow it but exclude
    # it from dumps (it is reconstructible from ``run_dir``).
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # --- request ---------------------------------------------------------------
    request_id: str
    prompt: str
    task_type: Optional[TaskType] = None

    # --- pipeline payloads -----------------------------------------------------
    plan: Optional[CanvasPlan] = None
    rendered_canvas: Optional[RenderedCanvas] = None
    generation_result: Optional[GenerationResult] = None
    review_result: Optional[ReviewResult] = None

    # --- control ---------------------------------------------------------------
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
        """Construct the initial state from a request."""
        return cls(
            request_id=request_id,
            prompt=prompt,
            task_type=task_type,
            max_revisions=max_revisions,
        )
